"""差评员工：同步智易飞 1–3 星卖家反馈，处理阶段在店铺窗口内核验并申请移除。

- ``feedback.sync``：拉当月低分反馈，过滤无效记录，按 sid + 站点 + 订单去重入库。
- 每条记录保存具体原因（日期不对、店铺未知、订单号格式不对、已移除等），页面和日志直接显示。
- 状态只在流程分流时使用：NEW / SUBMITTED / REMOVED / HANDLED / MANUAL。
"""
import asyncio
import re
import time
from datetime import datetime, timedelta, timezone

from ...tools.effiseller import build_client
from .process import register as register_process

SHANGHAI = timezone(timedelta(hours=8))
ORDER_ID = re.compile(r"^\d{3}-\d{7}-\d{7}$")
PAGE_SIZE = 100
QUERY = "/api/open/erp/system/cs/feedback/low-rating/query"


def _date(value):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _inspect(row):
    """返回 (可入库的记录, 跳过原因)。跳过原因用于同步日志。"""
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


def register(manager):
    async def sync(ctx):
        settings = manager.integration_settings.read("effiseller")
        if not settings["app_id"] or not settings["app_secret"]:
            ctx.log("feedback_sync_skipped", {"reason": "智易飞 App ID／Secret 未配置，跳过同步"})
            return
        client = build_client(manager)
        started = time.time()
        rows, total, page = [], None, 1
        try:
            while True:
                result = await asyncio.to_thread(client.api, "POST", QUERY,
                                                 {"pageNum": page, "pageSize": PAGE_SIZE})
                body = result.get("body")
                if not isinstance(body, dict) or body.get("code") != 0:
                    raise RuntimeError(f"智易飞差评接口返回异常：{str(body)[:300]}")
                data = body.get("data") or {}
                count, items = data.get("total"), data.get("list")
                if not isinstance(count, int) or not isinstance(items, list):
                    raise RuntimeError(f"智易飞差评接口结构异常：{str(data)[:300]}")
                if total is not None and count != total:
                    raise RuntimeError("拉取过程中总数发生变化，本轮中止，下轮重新拉取")
                total = count
                rows.extend(items)
                if len(rows) >= total or not items:
                    break
                page += 1
        except Exception as exc:
            ctx.log("feedback_sync_failed", {"reason": str(exc), "page": page, "seconds": time.time() - started})
            raise

        now = time.time()
        added = kept = 0
        skipped = []
        with manager.store.transaction():
            for row in rows:
                record, reason = _inspect(row)
                if record is None:
                    skipped.append(reason)
                    continue
                existing = manager.store.one(
                    "SELECT id FROM feedback_case WHERE sid=? AND marketplace_id=? AND order_id=?",
                    (record["sid"], record["marketplace_id"], record["order_id"]))
                if existing:
                    manager.store.update("feedback_case", existing["id"], updated_at=now,
                                         external_id=record["external_id"])
                    kept += 1
                else:
                    manager.store.insert("feedback_case", {**record, "status": "NEW", "reason": "",
                                                           "created_at": now, "updated_at": now})
                    added += 1
        ctx.log("feedback_synced", {"total": total, "added": added, "kept": kept,
                                    "skipped": len(skipped), "reasons": skipped[:10],
                                    "seconds": time.time() - started})

    manager.register("feedback.sync", sync)
    register_process(manager)
