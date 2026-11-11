"""Employee directories contain their own Python handlers and task manifest."""
from importlib import import_module
from pathlib import Path

from ..settings import load_tasks
from .catalog import list_employees, manage, visible_tasks

ROOT = Path(__file__).resolve().parent


def register_handlers(manager):
    for entry in sorted(ROOT.glob("*/__init__.py")):
        module = import_module(f"{__name__}.{entry.parent.name}")
        if hasattr(module, "register"):
            module.register(manager)


def load_employee_tasks(manager):
    root = Path(getattr(manager, "employee_root", ROOT)).resolve()
    for manifest in sorted(root.glob("*/manifest.json")):
        if manifest.resolve().parent.parent != root:
            raise ValueError("员工清单路径超出目录")
        load_tasks(manager, manifest)
