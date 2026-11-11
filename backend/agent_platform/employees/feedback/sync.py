"""差评同步：从智易飞拉当月 1–3 星反馈，过滤后按 sid + 站点 + 订单去重入库。"""
import asyncio
import time

from ...tools.effiseller import build_client
from .cases import inspect_row

PAGE_SIZE = 100
QUERY = "/api/open/erp/system/cs/feedback/low-rating/query"


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
            ctx.log("feedback_sync_failed", {"reason": str(exc), "page": page,
                                             "seconds": time.time() - started})
            raise

        now = time.time()
        added = kept = 0
        skipped = []
        with manager.store.transaction():
            for row in rows:
                record, reason = inspect_row(row)
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
