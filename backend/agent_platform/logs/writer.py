"""模块内的日志写入口：每个模块持有自己的 writer，动作必须已登记。

约定：

- 一张日志表一个 writer，由拥有该事实的模块持有（窗口管理写 resource_log，
  任务执行写 execution_log，脚本运行写 runtime_log……）。模块内所有日志都从
  这里写，任务和业务代码不再各自调用 store.log。
- 写入前按 catalog 校验动作：没登记的动作立即报错，避免写出无法查询的事件。
- 本层不改内容、不改级别含义，只负责把事实写进对应的表。
"""
from .catalog import EVENTS

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
LOG_TABLES = tuple(sorted({table for table, _ in EVENTS}))


class LogWriter:
    """绑定一张日志表的写入器。表与动作的对应关系以 catalog 为准。"""

    def __init__(self, store, table):
        if table not in LOG_TABLES:
            raise ValueError(f"未知日志仓库：{table}")
        self.store, self.table = store, table

    def write(self, action, content=None, *, level="INFO", task_id=None,
              execution_id=None, borrow_id=None, call_id=None):
        if (self.table, action) not in EVENTS:
            raise ValueError(f"日志事件未登记：{self.table}/{action}")
        if level not in LEVELS:
            raise ValueError(f"日志级别无效：{level}")
        return self.store.log(self.table, action, {} if content is None else content,
                              task_id=task_id, execution_id=execution_id,
                              borrow_id=borrow_id, level=level, call_id=call_id)
