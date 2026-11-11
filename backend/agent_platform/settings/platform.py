"""Read deployment settings independently of the caller's working directory."""
import os
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[3]


def read_settings():
    with (ROOT / "deploy" / "platform.toml").open("rb") as stream:
        return tomllib.load(stream)


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
