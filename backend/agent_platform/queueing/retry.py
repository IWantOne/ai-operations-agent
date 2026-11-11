"""The only automatic replay decision and shared budget debit."""
import json


def reserve_retry(store, request, status, *, safe, now):
    if status != "FAILED" or not safe:
        return None
    budget_id = request["budget_id"]
    changed = store.execute("UPDATE retry_budget SET used=used+1 WHERE id=? AND used<retry_limit", (budget_id,))
    if not changed:
        return None
    return now + json.loads(request["policy"])["retry_delay_seconds"]
