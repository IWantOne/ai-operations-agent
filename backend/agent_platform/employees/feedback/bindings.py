"""差评的店铺映射：ERP 的 sid → 紫鸟账号（店铺池里的 browserId）。"""
import json
from pathlib import Path

from ...resources.market import host_for

ROOT = Path(__file__).resolve().parents[4]
BINDINGS = ROOT / "deploy" / "store-bindings.json"


def load_bindings():
    if not BINDINGS.is_file():
        return {}
    return {str(row["sid"]): row for row in json.loads(BINDINGS.read_text(encoding="utf-8"))}


def url_for(marketplace_id):
    host = host_for(marketplace_id)
    return f"https://{host}/feedback-manager/index.html#/" if host else None
