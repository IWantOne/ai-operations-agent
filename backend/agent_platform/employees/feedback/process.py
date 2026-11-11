"""差评处理：打开窗口、进 Feedback Manager、按订单核验、记录证据。

流程（每个 case）：
1. 按 sid 从 deploy/store-bindings.json 找到紫鸟账号（browserId），窗口不够就排队。
2. 打开站点对应的 Feedback Manager，按订单号找行。
3. 判定：已划线 → REMOVED；已有 Case → SUBMITTED；否则进入申请入口，读取菜单和审核页文本。
4. 证据（URL、标题、行文本、菜单项、审核页文本、截图路径）写进 feedback_case.evidence。
5. 登录页、验证码、找不到行、站点不匹配 → MANUAL，原因写清楚。

提交按钮这一步先只走到“申请入口 + 审核页读取”，确认真实 DOM 后再接提交与 Case 回读。
"""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BINDINGS = ROOT / "deploy" / "store-bindings.json"

# 站点 → Seller Central 地址；ERP 只给 marketplaceId。
MARKETS = {
    "ATVPDKIKX0DER": "sellercentral.amazon.com",
    "A2EUQ1WTGCTBG2": "sellercentral.amazon.ca",
    "A1AM78C64UM0Y8": "sellercentral.amazon.com.mx",
    "A1F83G8C2ARO7P": "sellercentral.amazon.co.uk",
    "A1PA6795UKMFR9": "sellercentral.amazon.de",
    "A13V1IB3VIYZZH": "sellercentral.amazon.fr",
    "APJ6JRA9NG5V4": "sellercentral.amazon.it",
    "A1RKKUPIHCS9HS": "sellercentral.amazon.es",
    "A1805IZSGTT6HS": "sellercentral.amazon.nl",
    "A2NODRKZP88ZB9": "sellercentral.amazon.se",
    "A1C3SOZRARQ6R3": "sellercentral.amazon.pl",
    "AMEN7PMS3EDWL": "sellercentral.amazon.com.be",
    "A33AVAJ2PDY3EV": "sellercentral.amazon.com.tr",
    "A2Q3Y263D00KWC": "sellercentral.amazon.com",
    "A1VC38T7YXB528": "sellercentral.amazon.co.jp",
    "A28R8C7NBKEWEA": "sellercentral.amazon.ie",
    "A17E79C6D8DWNP": "sellercentral.amazon.sa",
    "A2VIGQ35RCS4UG": "sellercentral.amazon.ae",
}

REQUEST_LABELS = ("request review", "request removal", "请求审核", "要求审核",
                  "申请审核", "申請審査", "レビューの削除をリクエスト")

ROW_SCRIPT = r"""(()=>{
const order=__ORDER__;
const rows=Array.from(document.querySelectorAll('kat-table-row')).filter(r=>
 Array.from(r.querySelectorAll('kat-link')).some(a=>a.getAttribute('label')===order));
const deep=root=>{const out=[];const walk=r=>{for(const e of r.querySelectorAll('*')){out.push(e);if(e.shadowRoot)walk(e.shadowRoot);}};walk(root);return out;};
return {url:location.href,title:document.title,ready:document.readyState,
 rowCount:document.querySelectorAll('kat-table-row').length,
 rows:rows.map(r=>({text:(r.innerText||'').slice(0,3000),
  ratings:Array.from(r.querySelectorAll('kat-star-rating')).map(e=>e.getAttribute('value')),
  comments:Array.from(r.querySelectorAll('p')).filter(e=>(e.innerText||'').trim()).map(e=>({
   text:(e.innerText||'').slice(0,1000),
   struck:!!e.closest('s,del')||getComputedStyle(e).textDecorationLine.includes('line-through')})),
  caseLinks:Array.from(r.querySelectorAll('a[href],kat-link[href]')).map(e=>({
   text:(e.innerText||e.getAttribute('label')||'').slice(0,200),href:e.getAttribute('href')})),
  actions:deep(r).filter(e=>/BUTTON|DROPDOWN|MENU|OPTION/.test(e.tagName)||['button','menuitem','combobox','option'].includes(e.getAttribute('role'))).map(e=>({
   tag:e.tagName,text:(e.innerText||'').slice(0,200),label:e.getAttribute('label'),
   disabled:!!(e.disabled||e.hasAttribute('disabled'))}))}))};
})()"""

MENU_READ = r"""(()=>{const out=[];const walk=root=>{
for(const e of root.querySelectorAll('*')){
 const text=(e.innerText||'').trim();
 const role=e.getAttribute&&e.getAttribute('role');
 const tag=e.tagName;
 if((tag==='KAT-DROPDOWN-MENU-ITEM'||tag==='KAT-ACTION-MENU-ITEM'||role==='menuitem'||tag==='KAT-OPTION')&&text&&text.length<80){
   out.push({tag,text,role:role||'',disabled:!!(e.disabled||e.hasAttribute('disabled'))});
 }
 if(e.shadowRoot)walk(e.shadowRoot);
}};walk(document);return {url:location.href,title:document.title,text:(document.body?document.body.innerText:'').slice(0,4000),items:out.slice(0,20)};})()"""


def load_bindings():
    if not BINDINGS.is_file():
        return {}
    return {str(row["sid"]): row for row in json.loads(BINDINGS.read_text(encoding="utf-8"))}


def url_for(marketplace_id):
    host = MARKETS.get(str(marketplace_id))
    return f"https://{host}/feedback-manager/index.html#/" if host else None


def judge(state, order_id):
    """根据页面证据判定状态；返回 (状态, 人话原因, 证据补充)。"""
    rows = state.get("rows") or []
    if not rows:
        return "MANUAL", (f"反馈列表里没有订单 {order_id} 的行"
                          f"（页面共 {state.get('rowCount', 0)} 行，{state.get('url')}）"), {}
    row = rows[0]
    struck = any(c.get("struck") for c in row.get("comments") or [])
    links = [link for link in row.get("caseLinks") or []
             if isinstance(link.get("href"), str) and "case" in link["href"].lower()]
    if struck:
        return "REMOVED", "页面显示反馈已划线", {"links": row.get("caseLinks")}
    if links:
        return "SUBMITTED", f"页面已有 Case：{links[0].get('href')}", {"links": links}
    return "NEW", "未划线、没有 Case，可以申请", {"actions": row.get("actions")}


def register(manager):
    def mark(case, status, reason, evidence):
        manager.store.update("feedback_case", case["id"], status=status, reason=reason,
                             evidence=json.dumps(evidence, ensure_ascii=False), updated_at=time.time())

    async def process(ctx):
        limit = int(ctx.input.get("limit", 3))
        cases = manager.store.all(
            "SELECT * FROM feedback_case WHERE status='NEW' ORDER BY id LIMIT ?", (limit,))
        if not cases:
            ctx.log("feedback_processed", {"checked": 0, "reason": "没有待处理的差评"})
            return
        bindings = load_bindings()
        counts = {"checked": 0, "removed": 0, "submitted": 0, "manual": 0, "kept": 0}
        for case in cases:
            binding = bindings.get(str(case["sid"]))
            url = url_for(case["marketplace_id"])
            if not binding or not binding.get("browser_id"):
                mark(case, "MANUAL", f"店铺 sid={case['sid']} 没有映射到紫鸟账号", {})
                counts["manual"] += 1
                continue
            if not url:
                mark(case, "MANUAL", f"站点 {case['marketplace_id']} 没有对应的 Seller Central 地址", {})
                counts["manual"] += 1
                continue
            shop = binding["browser_id"]
            try:
                running = await manager.pool.browser.find_windows(shop)
            except Exception as exc:
                mark(case, "MANUAL", f"检查店铺窗口失败：{exc}", {})
                counts["manual"] += 1
                continue
            if running:
                mark(case, "MANUAL",
                     f"{binding.get('account_name') or shop} 的窗口已在运行（不是工作台开的），"
                     "请先在紫鸟里关闭它再处理", {"running": running})
                counts["manual"] += 1
                continue
            lease = await ctx.window(shop)
            try:
                try:
                    await ctx.tool("browser.goto", shop=shop, url=url)
                    state = await ctx.tool("browser.evaluate", shop=shop,
                                           expression=ROW_SCRIPT.replace("__ORDER__", json.dumps(case["order_id"])))
                except Exception as exc:
                    shot = await ctx.tool("browser.screenshot", shop=shop, label=f"feedback-{case['order_id']}")
                    mark(case, "MANUAL", f"打开反馈页失败：{exc}", {"screenshot": shot.get("path")})
                    counts["manual"] += 1
                    continue
                status, reason, extra = judge(state, case["order_id"])
                evidence = {"url": state.get("url"), "title": state.get("title"), **extra}
                if status == "NEW":
                    selector = f"kat-table-row:has(kat-link[label='{case['order_id']}']) kat-dropdown-button"
                    try:
                        await ctx.tool("browser.click", shop=shop, selector=selector)
                        await ctx.sleep(1)
                        menu = await ctx.tool("browser.evaluate", shop=shop, expression=MENU_READ)
                        evidence["menu"] = menu.get("items", [])
                        evidence["page_text"] = (menu.get("text") or "")[:2000]
                        labels = [item["text"].lower() for item in evidence["menu"]]
                        if any(any(label in text for label in REQUEST_LABELS) for text in labels):
                            reason = "已打开申请菜单，下一步提交（待确认审核页）"
                        else:
                            reason = "菜单里没有识别到“请求审核”，页面文本已记录"
                    except Exception as exc:
                        shot = await ctx.tool("browser.screenshot", shop=shop, label=f"feedback-menu-{case['order_id']}")
                        evidence["menu_error"] = str(exc)
                        evidence["screenshot"] = shot.get("path")
                        reason = f"打开申请菜单失败：{exc}"
                    mark(case, "NEW", reason, evidence)
                    counts["kept"] += 1
                else:
                    mark(case, status, reason, evidence)
                    counts["removed" if status == "REMOVED" else "submitted" if status == "SUBMITTED" else "manual"] += 1
                counts["checked"] += 1
            finally:
                await ctx.release(lease["id"])
        ctx.log("feedback_processed", counts)

    manager.register("feedback.process", process)
