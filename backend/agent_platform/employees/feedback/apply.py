"""提交移除申请：点菜单里的“请求审核”，按商品反馈理由提交，回读 Case 编号。

页面结构在不同站点可能不同，所以每一步都返回页面文本作为证据；
识别不到下一步就停下并记录，不盲目继续点击。
"""
import json
import re

CASE_ID = re.compile(r"(?:case|caseId|case_id)[^0-9A-Za-z]{0,3}([0-9]{6,})", re.IGNORECASE)
REQUEST_LABELS = ("request review", "request removal", "请求审核", "要求审核", "申请审核", "申請審査")
REASON_LABELS = ("商品反馈", "与商品有关", "product review", "product feedback", "商品に関する")
CONTINUE_LABELS = ("continue", "next", "继续", "下一步", "次の")
SUBMIT_LABELS = ("submit", "提交", "送信")

CLICK_BY_TEXT = r"""(()=>{const labels=__LABELS__;
const walk=root=>{const out=[];const visit=r=>{for(const e of r.querySelectorAll('*')){
 const text=(e.innerText||'').trim().toLowerCase();
 const role=e.getAttribute&&e.getAttribute('role');
 const tag=e.tagName;
 const clickable=/^(BUTTON|A|KAT-BUTTON|KAT-DROPDOWN-MENU-ITEM|KAT-ACTION-MENU-ITEM)$/.test(tag)||role==='button'||role==='menuitem'||role==='link';
 if(clickable&&labels.some(l=>text===l||text.startsWith(l))) out.push(e);
 if(e.shadowRoot)visit(e.shadowRoot);
}};visit(root);return out;};
const found=walk(document).filter(e=>!(e.disabled||e.hasAttribute('disabled')));
if(!found.length)return JSON.stringify({clicked:false});
const button=found[0];
for(const type of ['pointerover','pointerdown','mousedown','pointerup','mouseup','click']){
 button.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,composed:true,view:window}));
}
return JSON.stringify({clicked:true,text:(button.innerText||'').trim().slice(0,80)});})()"""


async def _click(ctx, shop, labels):
    expression = CLICK_BY_TEXT.replace("__LABELS__", json.dumps([label.lower() for label in labels],
                                                               ensure_ascii=False))
    value = await ctx.tool("browser.evaluate", shop=shop, expression=expression)
    try:
        return json.loads(value) if isinstance(value, str) else {"clicked": False}
    except ValueError:
        return {"clicked": False}


async def _page(ctx, shop):
    return await ctx.tool("browser.read", shop=shop)


def _case_id(page):
    text = f"{page.get('url') or ''}\n{page.get('title') or ''}\n{page.get('text') or ''}"
    match = CASE_ID.search(text)
    return match.group(1) if match else ""


async def run(ctx, shop, order_id):
    """返回 (状态, 原因, 证据)。状态 SUBMITTED / MANUAL / NEW。"""
    evidence = {"steps": []}
    page = await _page(ctx, shop)
    for step, labels in (("请求审核", REQUEST_LABELS), ("商品反馈", REASON_LABELS),
                         ("继续", CONTINUE_LABELS), ("提交", SUBMIT_LABELS)):
        clicked = await _click(ctx, shop, labels)
        evidence["steps"].append({"step": step, "clicked": clicked.get("clicked", False),
                                  "text": clicked.get("text", "")})
        if not clicked.get("clicked"):
            evidence["page_text"] = (page.get("text") or "")[:3000]
            evidence["url"] = page.get("url")
            return "MANUAL", f"申请流程停在“{step}”：页面上没有找到可点的按钮", evidence
        await ctx.sleep(2)
        page = await _page(ctx, shop)
        evidence["url"] = page.get("url")
        evidence["title"] = page.get("title")
        case_id = _case_id(page)
        if case_id:
            evidence["case_id"] = case_id
            return "SUBMITTED", f"已提交，Case {case_id}", evidence
        evidence["page_text"] = (page.get("text") or "")[:3000]
    return "MANUAL", "点完申请流程后没有识别到 Case 编号，请人工核对页面", evidence
