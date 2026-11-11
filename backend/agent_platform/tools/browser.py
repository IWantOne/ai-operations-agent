"""页面操作工具：通过紫鸟 WebDriver 的调试端口操作已打开的店铺窗口。

- 工具：browser.read / browser.goto / browser.evaluate / browser.click / browser.fill / browser.screenshot。
- 失败保留可读原因（连不上端口、页面没加载完、选择器没找到），截图落在 data/evidence。
- 页面操作不决定业务结果；业务脚本负责判断页面内容是否满足条件。
- 超时取 settings/timing.py 的 browser_timeout_seconds。
"""
import asyncio
import re
import time
from pathlib import Path

from ..connectors.cdp import CDP, page_target

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "data" / "evidence"


async def _connect(manager, shop):
    timeout = manager.timing_settings.read()["browser_timeout_seconds"]
    browser = getattr(manager.pool, "browser", None)
    if browser is None:
        raise RuntimeError("当前没有可用的浏览器连接")
    port = await browser.debug_port(str(shop))
    if port is None:
        raise RuntimeError("当前连接方式不提供页面调试端口；请使用紫鸟 WebDriver，并先打开店铺窗口")
    target = await asyncio.to_thread(page_target, port, timeout=min(timeout, 10))
    return await asyncio.to_thread(CDP, port, target, timeout)


async def _run(manager, shop, action):
    cdp = await _connect(manager, shop)
    try:
        return await asyncio.to_thread(action, cdp)
    finally:
        await asyncio.to_thread(cdp.close)


def register_browser(manager):
    async def read(shop):
        def action(cdp):
            return {"url": cdp.url(), "title": cdp.title(), "text": cdp.text()}
        return await _run(manager, shop, action)

    async def goto(shop, url):
        def action(cdp):
            cdp.navigate(url)
            return {"url": cdp.url(), "title": cdp.title()}
        return await _run(manager, shop, action)

    async def evaluate(shop, expression, await_promise=False):
        return await _run(manager, shop, lambda cdp: cdp.evaluate(expression, await_promise))

    async def click(shop, selector):
        return await _run(manager, shop, lambda cdp: cdp.click(selector))

    async def fill(shop, selector, text):
        return await _run(manager, shop, lambda cdp: cdp.fill(selector, text))

    async def screenshot(shop, label="page"):
        def action(cdp):
            EVIDENCE.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^\w\-]+", "_", str(label))[:40] or "page"
            path = EVIDENCE / f"{int(time.time() * 1000)}-{safe}.png"
            return cdp.screenshot(path)
        return await _run(manager, shop, action)

    manager.tools.register("browser.read", read, restart_safe=True)
    manager.tools.register("browser.goto", goto)
    manager.tools.register("browser.evaluate", evaluate)
    manager.tools.register("browser.click", click)
    manager.tools.register("browser.fill", fill)
    manager.tools.register("browser.screenshot", screenshot)
