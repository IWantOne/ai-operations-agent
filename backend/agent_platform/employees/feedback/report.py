"""差评结果回传：把已提交、已移除的结果写回智易飞 ERP。

只回传有明确结果的状态；需人工处理（MANUAL）留在本地等处理，不往 ERP 发。
回传失败的记录保留 reported_at 为空，下一轮自动重试，原因写入 report_error。
"""
import asyncio
import json
import time

from ...tools.effiseller import build_client

PATH = "/api/open/erp/system/cs/feedback/low-rating/removal/results"


def _case_id(evidence):
    try:
        return json.loads(evidence or "{}").get("case_id") or ""
    except ValueError:
        return ""


def register(manager):
    async def report(ctx):
        rows = manager.store.all(
            "SELECT * FROM feedback_case WHERE status IN ('SUBMITTED','REMOVED') "
            "AND reported_at IS NULL ORDER BY id LIMIT 20")
        if not rows:
            ctx.log("feedback_reported", {"sent": 0, "reason": "没有待回传的结果"})
            return
        client = build_client(manager)
        results = [{"externalId": row["external_id"], "orderId": row["order_id"],
                    "marketplaceId": row["marketplace_id"], "sid": row["sid"],
                    "status": row["status"], "caseId": _case_id(row["evidence"]),
                    "reason": row["reason"], "updatedAt": row["updated_at"]} for row in rows]
        try:
            response = await asyncio.to_thread(client.api, "POST", PATH, {"results": results})
        except Exception as exc:
            ctx.log("feedback_report_failed", {"reason": str(exc), "count": len(rows)})
            raise
        body = response.get("body")
        ok = isinstance(body, dict) and (str(body.get("code")) == "0" or body.get("success") is True)
        now = time.time()
        with manager.store.transaction():
            for row in rows:
                manager.store.update("feedback_case", row["id"],
                                     reported_at=now if ok else None,
                                     report_error="" if ok else str(body)[:500])
        ctx.log("feedback_reported", {"sent": len(rows), "ok": ok,
                                      "response": str(body)[:300]})
        if not ok:
            raise RuntimeError(f"智易飞回传未成功：{str(body)[:300]}")
        return {"sent": len(rows), "ok": True}

    manager.register("feedback.report", report)
