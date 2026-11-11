"""A failed commit stops ordinary admissions, but must not disable cleanup controls."""
import sys
import traceback
from .lifecycle import finish
from ..logs.errors import exception_details, PersistedFailure


def record_commit_failure(service, rid, aid, exc, *, status, result, evidence):
    commit = exception_details(exc)
    details = {**(evidence or commit), "commit_error": commit,
               "error": ((evidence["error"] + "; ") if evidence else "") + "完成持久化失败：" + commit["error"],
               "request_id": rid, "attempt_id": aid, "observed_status": status}
    service.accepting = False
    service.fault = details
    service.commit_errors[rid] = PersistedFailure(details)
    try:
        service.system.write("work_commit_error", {**details, "observed_result": result},
                             call_id=f"attempt:{aid}", level="ERROR")
        # This records uncertainty, not a second execution or an automatic business retry.
        # If storage is still unavailable the original RUNNING intent remains for recovery.
        finish(service, rid, "NEEDS_REVIEW", result=result, error=details)
    except Exception as storage_error:
        # The database cannot serve as its own fallback sink. Preserve both traces on the
        # service diagnostic stream instead of losing them as an unobserved asyncio error.
        print(details["error"], file=sys.stderr, flush=True)
        traceback.print_exception(exc)
        traceback.print_exception(storage_error)
