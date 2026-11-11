"""差评业务规则：ERP 记录过滤、页面证据判定、状态与原因。纯函数，不碰浏览器和数据库。"""
import re
from datetime import datetime, timedelta, timezone

SHANGHAI = timezone(timedelta(hours=8))
ORDER_ID = re.compile(r"^\d{3}-\d{7}-\d{7}$")


def _date(value):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def inspect_row(row):
    """ERP 一条记录 → (可入库的记录, 跳过原因)。"""
    if not isinstance(row, dict):
        return None, "记录不是对象"
    date = _date(row.get("feedbackDate"))
    if date is None:
        return None, "反馈日期无法解析"
    if date.strftime("%Y-%m") != datetime.now(SHANGHAI).strftime("%Y-%m"):
        return None, "不是当月反馈"
    try:
        rating = int(row.get("rating"))
    except (TypeError, ValueError):
        return None, "星级无法解析"
    if rating < 1 or rating > 3:
        return None, "星级不在 1–3 星"
    if row.get("removed") == 1 or row.get("deleted") == 1:
        return None, "平台已移除或删除"
    order = str(row.get("amazonOrderId") or "")
    if not ORDER_ID.match(order):
        return None, f"订单号格式不对：{order or '空'}"
    comment = str(row.get("comments") or "").strip()
    if not comment:
        return None, "反馈内容为空"
    sid = str(row.get("sid") or "")
    if not sid:
        return None, "缺少店铺 sid"
    return {"sid": sid,
            "store_name": str(row.get("storeName") or ""),
            "marketplace_id": str(row.get("marketplaceId") or ""),
            "order_id": order,
            "feedback_date": date.isoformat(),
            "rating": rating,
            "comment": comment,
            "external_id": str(row.get("id") or "")}, ""


def judge(state, order_id):
    """页面证据 → (状态, 人话原因, 证据补充)。"""
    rows = state.get("rows") or []
    if not rows:
        return "MANUAL", (f"反馈列表里没有订单 {order_id} 的行"
                          f"（当前页 {state.get('rowCount', 0)} 行，{state.get('url')}）"), {}
    row = rows[0]
    struck = any(item.get("struck") for item in row.get("comments") or [])
    links = [link for link in row.get("caseLinks") or []
             if isinstance(link.get("href"), str) and "case" in link["href"].lower()]
    if struck:
        return "REMOVED", "页面显示反馈已划线", {"links": row.get("caseLinks")}
    if links:
        return "SUBMITTED", f"页面已有 Case：{links[0].get('href')}", {"links": links}
    return "NEW", "未划线、没有 Case，可以申请", {"actions": row.get("actions")}
