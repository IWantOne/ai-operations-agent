"""Register single connection operations with the common execution controller."""
import base64
import hashlib
import json
from .models import Executor
from .repository import encode
from ..connectors.connections import protect
from ..connectors.discovery import detect_webdriver


def seal_input(values):
    clean = {key: values[key] for key in ("mode", "company", "username", "password", "port") if key in values}
    payload = encode(clean).encode()
    return {"_sealed": base64.b64encode(protect(payload)).decode(),
            "_fingerprint": hashlib.sha256(payload).hexdigest(), "mode": clean.get("mode")}


def register_connections(service, connections):
    async def overview(row, *args):
        if connections is None:
            raise ValueError("当前服务没有配置连接")
        return await connections.account_overview()

    async def configure(row, *args):
        if connections is None:
            raise ValueError("当前服务没有配置连接")
        payload = json.loads(row["run_input"])
        values = json.loads(protect(base64.b64decode(payload["_sealed"]), True))
        return await connections.configure(service, values, save=row["kind"] == "ziniao.configure")

    async def detect(row, *args):
        return await detect_webdriver(service.store, json.loads(row["policy"]))

    service.executors.update({
        "ziniao.accounts": Executor(overview, "ziniao", True),
        "ziniao.verify": Executor(configure, "ziniao", True),
        "ziniao.configure": Executor(configure, "ziniao"),
        "ziniao.detect": Executor(detect, "ziniao", True),
    })
