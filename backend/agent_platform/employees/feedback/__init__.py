"""差评员工：同步与处理两个任务，各自在 sync.py / process.py 里实现。"""
from .process import register as register_process
from .sync import register as register_sync


def register(manager):
    register_sync(manager)
    register_process(manager)
