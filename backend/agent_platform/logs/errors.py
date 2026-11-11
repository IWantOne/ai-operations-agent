"""Exception evidence shared by boundaries; no state transitions or retry policy here."""
import traceback
from copy import deepcopy


class PersistedFailure(RuntimeError):
    """Transport saved evidence when the original exception object no longer exists.

    This carrier is never an additional diagnostic exception layer.
    """
    def __init__(self, evidence):
        self.evidence = deepcopy(evidence)
        super().__init__(evidence.get("error", "服务中断，未收到执行结果；需核对外部实际结果"))


def exception_details(exc):
    """Keep original types, messages, chained causes and stack locations."""
    if isinstance(exc, PersistedFailure):
        return deepcopy(exc.evidence)
    chain = []
    seen = set()
    current = exc
    saved_trace = ""
    saved_evidence = None
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, PersistedFailure):
            saved_evidence = deepcopy(current.evidence)
            chain.extend(deepcopy(current.evidence.get("exception_chain", [])))
            saved_trace = current.evidence.get("traceback", "")
            break
        chain.append({"type": type(current).__name__, "message": str(current)})
        current = current.__cause__ or current.__context__
    details = {
        "error": " <- ".join(f"{item['type']}: {item['message']}" for item in chain),
        "exception_chain": chain,
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, chain=saved_evidence is None)) + saved_trace,
    }
    if saved_evidence is not None:
        details["cause_evidence"] = saved_evidence
        if not saved_evidence.get("exception_chain"):
            details["error"] += " <- " + saved_evidence.get("error", "未收到执行结果")
    for field in ("returncode", "stdout", "stderr", "output_call_id", "timeout_seconds"):
        value = getattr(exc, field, None)
        if value is not None:
            details[field] = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    return details
