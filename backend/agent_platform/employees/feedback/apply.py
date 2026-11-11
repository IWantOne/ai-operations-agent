"""提交移除申请：点“请求审核”入口，按商品反馈理由提交，回读 Case 编号。

入口点击会请求 /fbmapi/v1/feedbacks/<id>/removal；亚马逊拒绝该请求（HTTP 401/403）时
表单不会打开，此时如实记录授权受阻，不重试、不换账号绕过。表单打开后每一步都先看页面
像不像这一步，不像就停下并记录，不盲目继续点击。
"""
import re

from . import pages

CASE_ID = re.compile(r"(?:case|caseId|case_id)[^0-9A-Za-z]{0,3}([0-9]{6,})", re.IGNORECASE)
# 入口请求被接受后，亚马逊会直接给出审核结论：保留（不删除）或已删除。
KEPT_MARKERS = ("已审核此反馈", "审核此反馈", "已保留", "没有违反", "未违反",
                "not violate", "has been retained")
REMOVED_MARKERS = ("已删除此反馈", "已移除此反馈", "反馈已被删除", "已被移除")
REASON_LABELS = ("商品回饋", "商品反馈", "與商品有關", "与商品有关", "商品相關", "商品相关",
                 "product review", "product feedback", "商品に関する")
CONTINUE_LABELS = ("繼續", "继续", "continue", "next", "下一步", "次の")
SUBMIT_LABELS = ("提交", "送出", "submit", "送信")

# 每步点之前先看页面像不像这一步；不像就停，避免在错误页面上乱点。
GUARDS = {
    "商品反馈": ("原因", "reason", "feedback", "商品", "review"),
    "提交": ("移除", "删除", "removal", "submit", "审核", "review"),
}


async def _page(ctx, shop):
    return await ctx.tool("browser.read", shop=shop)


def _case_id(page):
    text = f"{page.get('url') or ''}\n{page.get('title') or ''}\n{page.get('text') or ''}"
    match = CASE_ID.search(text)
    return match.group(1) if match else ""


async def run(ctx, shop, order_id):
    """返回 (状态, 原因, 证据)。状态 SUBMITTED / MANUAL / NEW。"""
    evidence = {"steps": []}
    started = await ctx.tool("browser.evaluate", shop=shop, expression="performance.now()")
    point = await pages.menu_action_point(ctx, shop, order_id, "request_removal")
    if point.get("error") in {"OPTION_NOT_FOUND", "OPTION_NOT_VISIBLE", "DROPDOWN_NOT_FOUND"}:
        # 菜单可能在两次工具调用之间收起了，重新展开一次。
        await pages.open_menu(ctx, shop, order_id)
        point = await pages.menu_action_point(ctx, shop, order_id, "request_removal")
    if not point.get("x"):
        return "MANUAL", (f"操作菜单里没有可点的“请求审核”："
                          f"{point.get('error', '未知原因')}"), evidence
    await ctx.tool("browser.click_point", shop=shop, x=point["x"], y=point["y"])
    entry = await pages.removal_entry(ctx, shop, started)
    evidence["reviewEntry"] = entry
    status = (entry or {}).get("status")
    if status in (401, 403):
        return "MANUAL", (f"亚马逊拒绝打开请求审核表单（HTTP {status}），未提交申请；"
                          f"该账号的亚马逊审核入口授权需要处理"), evidence
    if not status:
        return "MANUAL", "点了“请求审核”，但没有观察到亚马逊的审核入口请求，未提交申请", evidence

    # 入口被接受后，页面会直接给出审核结论；也可能继续进入理由页。轮询等它落定。
    page = await _page(ctx, shop)
    for _ in range(15):
        case_id = _case_id(page)
        if case_id:
            evidence["case_id"] = case_id
            return "SUBMITTED", f"已提交，Case {case_id}", evidence
        text = str(page.get("text") or "")
        if any(marker in text for marker in KEPT_MARKERS):
            evidence["page_text"] = text[:3000]
            evidence["url"] = page.get("url")
            return "REJECTED", "亚马逊审核后保留反馈（未移除）", evidence
        if any(marker in text for marker in REMOVED_MARKERS):
            evidence["page_text"] = text[:3000]
            evidence["url"] = page.get("url")
            return "REMOVED", "亚马逊已移除该反馈", evidence
        await ctx.sleep(1)
        page = await _page(ctx, shop)

    for step, labels in (("商品反馈", REASON_LABELS), ("继续", CONTINUE_LABELS),
                         ("提交", SUBMIT_LABELS)):
        guard = GUARDS.get(step)
        if guard:
            text = str(page.get("text") or "").lower()
            if not any(marker.lower() in text for marker in guard):
                evidence["page_text"] = (page.get("text") or "")[:3000]
                evidence["url"] = page.get("url")
                return "MANUAL", f"申请流程停在“{step}”：当前页面不像这一步，页面文本已记录", evidence
        clicked = await pages.click_text(ctx, shop, labels)
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
