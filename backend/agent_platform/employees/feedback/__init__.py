"""差评员工：同步、处理、回传三个任务，各自在 sync.py / process.py / report.py 里实现。"""
from .detail import detail
from .process import register as register_process
from .report import register as register_report
from .sync import register as register_sync


def register(manager):
    register_sync(manager)
    register_process(manager)
    register_report(manager)
    manager.register_detail("feedback", detail)
