"""Chrome DevTools Protocol 客户端：不依赖 playwright／websocket 库。

紫鸟 WebDriver 打开窗口后返回 ``debuggingPort``，本模块用最小 RFC 6455 实现连上该端口，
完成跳转、读取页面文本、执行表达式、点击、填写和截图。失败一律抛出带可读原因的
``CDPError``（选择器没找到、页面没加载完、端口连不上），不返回“已处理”之类的模糊结果。
"""
import base64
import hashlib
import json
import os
import socket
import struct
import time
import urllib.request

# 紫鸟后台大量使用 Shadow DOM，查询要逐层穿透，否则选择器在 document 上找不到。
LOOKUP = """function zq(selector){
 const roots=[document],seen=[];
 while(roots.length){
  const root=roots.shift();
  const hit=root.querySelector(selector);
  if(hit)return hit;
  for(const el of root.querySelectorAll('*')){
   if(el.shadowRoot&&!seen.includes(el.shadowRoot)){seen.push(el.shadowRoot);roots.push(el.shadowRoot);}
  }
 }
 return null;
}"""


def click_script(selector):
    """后台按钮响应指针序列，直接 element.click() 常常没有反应。"""
    message = json.dumps(f"找不到元素：{selector}")
    return f"""(()=>{{
{LOOKUP}
 const el=zq({json.dumps(selector)});
 if(!el)return JSON.stringify({{errorCode:{message}}});
 for(const type of ['pointerover','pointerenter','pointerdown','mousedown','pointerup','mouseup','click']){{
  el.dispatchEvent(new MouseEvent(type,{{bubbles:true,cancelable:true,composed:true,view:window}}));
 }}
 return JSON.stringify({{clicked:true,tag:el.tagName}});
}})()"""


def fill_script(selector, text):
    """通过原型 setter 写入，框架才会感知到值变化。"""
    message = json.dumps(f"找不到元素：{selector}")
    return f"""(()=>{{
{LOOKUP}
 const el=zq({json.dumps(selector)});
 if(!el)return JSON.stringify({{errorCode:{message}}});
 const proto=Object.getPrototypeOf(el);
 const setter=Object.getOwnPropertyDescriptor(proto,'value');
 if(setter&&setter.set){{setter.set.call(el,{json.dumps(text)});}}else{{el.value={json.dumps(text)};}}
 for(const type of ['input','change','blur']){{
  el.dispatchEvent(new Event(type,{{bubbles:true,composed:true}}));
 }}
 return JSON.stringify({{filled:true,tag:el.tagName}});
}})()"""


def mask_frame(payload, opcode=0x1):
    """构造客户端帧（FIN + 掩码，RFC 6455）。"""
    header = bytearray([0x80 | opcode])
    mask = os.urandom(4)
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < (1 << 16):
        header.append(0x80 | 126)
        header += struct.pack(">H", length)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", length)
    header += mask
    return bytes(header) + bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))


def parse_frame(buffer, unmask=True):
    """返回 (opcode, payload, 剩余字节)；帧还不完整时返回 None。"""
    if len(buffer) < 2:
        return None
    first, second = buffer[0], buffer[1]
    masked = bool(second & 0x80)
    length = second & 0x7F
    offset = 2
    if length == 126:
        if len(buffer) < 4:
            return None
        length = struct.unpack(">H", buffer[2:4])[0]
        offset = 4
    elif length == 127:
        if len(buffer) < 10:
            return None
        length = struct.unpack(">Q", buffer[2:10])[0]
        offset = 10
    if masked:
        offset += 4
    if len(buffer) < offset + length:
        return None
    payload = buffer[offset:offset + length]
    if masked and unmask:
        mask = buffer[offset - 4:offset]
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return first & 0x0F, payload, buffer[offset + length:]


def page_target(port, host="127.0.0.1", timeout=10):
    """读取 /json 列表，返回第一个 page 目标的 id；没有页面时给出可读原因。"""
    url = f"http://{host}:{port}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            targets = json.loads(response.read().decode("utf-8", "replace"))
    except Exception as exc:
        raise CDPError(f"读取 {url} 失败：{exc}") from exc
    pages = [t for t in targets if isinstance(t, dict) and t.get("type") == "page"]
    if not pages:
        raise CDPError(f"调试端口 {port} 上没有页面标签：{json.dumps(targets)[:300]}")
    return pages[0].get("id")


class CDPError(RuntimeError):
    """页面操作失败。保留可读原因。"""


class CDP:
    def __init__(self, port, target_id=None, timeout=20.0, host="127.0.0.1"):
        self.timeout = timeout
        self.socket = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {self._path(target_id)} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.socket.sendall(request.encode())
        self._buffer = b""
        while b"\r\n\r\n" not in self._buffer:
            self._recv_more()
        head, self._buffer = self._buffer.split(b"\r\n\r\n", 1)
        if b"101" not in head.split(b"\r\n")[0]:
            raise CDPError(f"调试端口握手失败：{head[:120]!r}")
        self._next = 0

    @staticmethod
    def _path(target_id):
        return f"/devtools/page/{target_id}" if target_id else "/devtools/browser"

    def _recv_more(self):
        chunk = self.socket.recv(65536)
        if not chunk:
            raise CDPError("调试端口连接已断开")
        self._buffer += chunk

    def _read_frame(self):
        while True:
            parsed = parse_frame(self._buffer)
            if parsed:
                opcode, payload, self._buffer = parsed
                return opcode, payload
            self._recv_more()

    def call(self, method, **params):
        self._next += 1
        message_id = self._next
        payload = json.dumps({"id": message_id, "method": method, "params": params}).encode()
        self.socket.sendall(mask_frame(payload))
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            opcode, body = self._read_frame()
            if opcode not in (0x1, 0x2):
                continue
            data = json.loads(body.decode("utf-8", "replace"))
            if data.get("id") != message_id:
                continue
            if "error" in data:
                raise CDPError(f"{method} 失败：{data['error'].get('message')}")
            return data.get("result", {})
        raise CDPError(f"{method} 超过 {self.timeout} 秒未返回")

    def evaluate(self, expression, await_promise=False):
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True,
                           awaitPromise=await_promise)
        if result.get("exceptionDetails"):
            detail = result["exceptionDetails"].get("exception", {}).get("description")
            raise CDPError(f"页面脚本出错：{detail or result['exceptionDetails'].get('text')}")
        return result.get("result", {}).get("value")

    def evaluate_json(self, expression, await_promise=False):
        value = self.evaluate(expression, await_promise=await_promise)
        if not isinstance(value, str):
            raise CDPError(f"页面脚本没有返回 JSON 文本，而是 {type(value).__name__}")
        return json.loads(value)

    def navigate(self, url, timeout=None):
        result = self.call("Page.navigate", url=url)
        if result.get("errorText"):
            raise CDPError(f"打开 {url} 失败：{result['errorText']}")
        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            if self.evaluate("document.readyState") == "complete":
                return result.get("frameId")
            time.sleep(0.2)
        raise CDPError(f"打开 {url} 后 {timeout or self.timeout} 秒仍未加载完成")

    def url(self):
        return self.evaluate("location.href")

    def title(self):
        return self.evaluate("document.title")

    def text(self, limit=20000):
        value = self.evaluate("document.body ? document.body.innerText : ''")
        return (value or "")[:limit]

    def click(self, selector):
        value = self.evaluate_json(click_script(selector))
        if value.get("errorCode"):
            raise CDPError(value["errorCode"])
        return value

    def fill(self, selector, text):
        value = self.evaluate_json(fill_script(selector, text))
        if value.get("errorCode"):
            raise CDPError(value["errorCode"])
        return value

    def screenshot(self, path):
        result = self.call("Page.captureScreenshot", format="png")
        data = base64.b64decode(result["data"])
        with open(path, "wb") as handle:
            handle.write(data)
        return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def close(self):
        try:
            self.socket.close()
        except OSError:
            pass
