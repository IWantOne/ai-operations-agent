"""Read ordinary Skill files; the caller retains the loaded string per execution."""
from pathlib import Path


def load(path) -> str:
    return Path(path).read_text(encoding="utf-8-sig")
