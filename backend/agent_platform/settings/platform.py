"""Deployment defaults. 店铺池以数据库为准，不再读配置文件。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

DEFAULTS = {
    "database": {"type": "sqlite", "path": "database/sqlite/unified.sqlite3"},
    "service": {"port": 8765, "state_dir": "data"},
}


def read_settings():
    """没有配置文件时用内置默认值；命令行参数仍然优先。"""
    return {"database": dict(DEFAULTS["database"]), "service": dict(DEFAULTS["service"])}


def database_target(config):
    kind = config["type"]
    if kind == "sqlite":
        path = ROOT / config["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)
    if kind == "postgresql":
        value = os.environ.get(config["dsn_env"], "")
        if not value.startswith(("postgres://", "postgresql://")):
            raise ValueError(f"Set {config['dsn_env']} to a PostgreSQL connection URL")
        return value
    raise ValueError(f"Unsupported database type: {kind}")
