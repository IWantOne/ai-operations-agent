"""Log vocabulary v1. See docs/logging-spec.md; query metadata never replaces evidence."""
MODULES = {"system": "工作台系统", "execution": "任务执行", "runtime": "脚本运行",
           "tools": "工具调用", "resources": "窗口管理", "ziniao": "紫鸟连接"}
EVENT_TYPES = {"system": "系统运行", "settings": "配置变更", "task": "任务执行与控制",
               "schedule": "任务调度", "window": "窗口借还", "connection": "接口通信",
               "script": "脚本运行", "tool": "工具调用", "custom": "未登记事件"}
PROVIDERS = {"ziniao": "紫鸟"}
LEVELS = {"DEBUG": "调试", "INFO": "信息", "WARNING": "警告", "ERROR": "错误", "CRITICAL": "严重错误"}
SOURCE_MODULES = {"system_log": "system", "execution_log": "execution", "runtime_log": "runtime",
                  "tool_call_log": "tools", "resource_log": "resources"}
UNKNOWN_ACTIONS = ("INSPECT_FAILED", "OPEN_FAILED", "CLOSE_FAILED", "OWNERSHIP_CONFLICT")

# Each group: storage table, recording module, event type, external data provider, exact event labels.
GROUPS = [
    ("system_log", "system", "system", "", {
        "control_submitted": "控制命令已提交", "control_confirmed": "控制命令已确认", "control_failed": "控制命令未完成", "work_dispatch_error": "工作派发登记失败", "work_commit_error": "工作完成提交失败", "API_ERROR": "工作台接口异常", "shutdown_started": "开始停止服务",
        "shutdown_wait_elapsed": "服务收尾等待时长已到"}),
    ("system_log", "system", "settings", "", {
        "queue_settings_saved": "保存统一队列容量", "timing_settings_saved": "保存时间与停止策略",
        "retry_settings_saved": "保存任务重试策略", "tool_settings_saved": "保存工具配置"}),
    ("execution_log", "execution", "schedule", "", {
        "schedule_error": "定时计划错误并停用", "work_queued": "工作请求入队", "work_finished": "工作尝试结束", "schedule_skip": "跳过重叠调度",
        "schedule_missed_during_restart": "记录重启期间错过的调度"}),
    ("execution_log", "execution", "task", "", {
        "started": "开始执行", "execution_error": "执行异常", "cleanup_incomplete": "执行后的资源清理未完成",
        "task_enabled": "启用任务", "task_disabled": "停用任务", "window_wait": "执行申请店铺窗口"}),
    ("resource_log", "resources", "window", "", {
        "RECONCILED": "窗口核验完成", "INSPECT_FAILED": "窗口核验失败", "ACQUIRED": "获得窗口",
        "OPEN_REJECTED": "开窗被拒且核验未打开", "OPEN_FAILED": "打开窗口失败", "OWNERSHIP_CONFLICT": "窗口归属冲突",
        "CLOSED": "归还并关闭窗口", "CLOSE_FAILED": "关闭窗口失败"}),
    # 连接器事件：日志与异常共用 ConnectorCode，CLI 与 WebDriver 写同一组码。
    ("resource_log", "ziniao", "connection", "ziniao", {
        "CONNECTOR_RAW": "收到连接器原始返回", "CONNECTOR_ERROR": "连接器调用异常",
        "CONNECTOR_INTERRUPTED": "连接器调用中断", "WEBDRIVER_DISCOVERY_PROBE": "探测本机紫鸟接口"}),
    ("resource_log", "ziniao", "window", "ziniao", {
        "CONNECTOR_OPENED": "窗口已打开", "CONNECTOR_CLOSED": "窗口已关闭",
        "CONNECTOR_FOREIGN": "发现非工作台持有的窗口"}),
    ("runtime_log", "runtime", "script", "", {
        "script_output": "脚本输出", "script_start": "启动脚本", "script_managed": "脚本已纳入进程管理", "script_result": "脚本返回",
        "script_timeout": "脚本超时", "script_cancelled": "脚本取消", "script_error": "脚本异常", "script_stopped": "脚本已停止"}),
    ("tool_call_log", "tools", "tool", "", {
        "tool_start": "开始调用工具", "tool_error": "工具调用异常", "tool_result": "工具返回"}),
]
EVENTS = {}
for table, module, event_type, provider, labels in GROUPS:
    for action, label in labels.items():
        key = (table, action)
        if key in EVENTS:
            raise ValueError(f"Duplicate log event: {key}")
        EVENTS[key] = dict(module=module, event_type=event_type, provider=provider, event_label=label)


def sql_metadata(table, field):
    """Only static catalog values enter SQL; all user filters remain parameters."""
    quote = lambda value: "'" + value.replace("'", "''") + "'"
    default = {"module": quote(SOURCE_MODULES[table]), "event_type": "'custom'", "provider": "''", "event_label": "action"}[field]
    cases = " ".join(f"WHEN {quote(action)} THEN {quote(values[field])}"
                     for (source, action), values in EVENTS.items() if source == table)
    return f"CASE action {cases} ELSE {default} END"


def definitions():
    return dict(version=1, modules=MODULES, event_types=EVENT_TYPES, providers=PROVIDERS, levels=LEVELS)
