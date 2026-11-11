# 一期验收记录：统一排队与生命周期

日期：2026-11-09。结论：一期代码完成，复查发现的缺口已修复，本地验收通过。首次 84 项测试没有覆盖下述故障组合，不能据此认定没有遗漏。未操作真实紫鸟店铺，未重启当前用户服务。

## 交付结果

任务页面、定时触发、人工续跑、紫鸟页面、上下文脚本和工具均进入 QueueService。旧 TaskManager、ResourcePool.pump、资源独立等待队列、task_run_request、resume_waiting 和旧动作 HTTP 别名已删除。代码边界有自动检查。

唯一派发器按任务、紫鸟、脚本/工具、清理/核验、取消五类名额控制执行；窗口占用另有上限。同店铺获取按顺序，打开/关闭/核验互斥。窗口交接必须确认使用者停止及窗口关闭。

请求、尝试、执行投影、预算和完成事件原子提交。根请求预算在父子操作之间共享；清理/核验有独立控制预算；安全性未声明时默认不自动重放。任务需核验时保留原异常，不能以诊断状态替代原因。

暂停与继续在检查点确认，取消等待实际停止；收尾允许必要控制。重启不恢复丢失的 Python 栈，不启动已经失去父尝试的子操作。数据库实例锁独立于 state-dir。

## 已执行的验证

| 验证 | 结果 |
| --- | --- |
| `python -m unittest discover -s verification -v`（PYTHONPATH=backend;verification） | 最新复查 98 项通过，约 44.1 秒（复查累计新增 14 项） |
| `node --test verification/test_log_presentation.mjs` | 上一轮 5 项通过；本轮未修改前端，未重复运行 |
| `npm run build`（frontend） | 上一轮构建成功，42 个模块；本轮未修改前端，未重复构建 |

核心全局场景及证据：

| 行为 | 自动验证 |
| --- | --- |
| 提交键相同不重复执行，不同输入拒绝 | `test_queueing.test_idempotency_checks_input_and_kind`；HTTP 测试验证提交 ID |
| 窗口、工具、父任务共同消耗根预算 2 | `test_window_tool_and_parent_share_two_retries_total`：开窗调用 2 次、工具 2 次、父任务 1 次，合计自动重试 2 次 |
| 父子重试不能乘法放大，重启不补预算 | `test_root_and_child_retry_budget_is_not_multiplied`、`test_parent_and_child_can_each_consume_same_budget`、`test_platform.test_finite_retry_budget_is_kept_on_original_request` |
| 未知外部结果不自动重放，原对象/异常链保留 | `test_unsafe_tool_is_never_replayed_and_original_error_survives`、`test_error_evidence` |
| 完成提交中途写库失败 | `test_final_commit_failure_rolls_back_all_projections_and_budget`：请求和尝试仍 RUNNING，预算未扣减、完成事件未写入，后续完整提交成功；重复完成/取消不覆盖已确认结果 |
| 任务名额 2、窗口 1、三个任务依次推进 | `test_full_task_capacity_does_not_block_child_or_cleanup` |
| 同店铺 FIFO，其他店铺独立推进 | `test_same_shop_fifo_does_not_block_other_shop` |
| 开窗中取消、关窗中取消与并发核验 | `test_cancel_during_open_settles_open_before_release`、`test_cancel_during_cleanup_waits_and_inspection_is_serialized` |
| 停止失败不关窗、不释放；关窗失败不成功 | `test_stop_failure_cannot_close_or_free_window`、`test_error_evidence` |
| 人工核验只有确认关闭才解除占用 | `test_manual_inspection_only_frees_confirmed_closed_window` |
| 单项输入/返回值/调度配置错误不停止其他工作 | `test_one_bad_request_does_not_stop_other_work`、`test_invalid_executor_result_does_not_disable_dispatch`、`test_invalid_schedule_does_not_stop_other_tasks` |
| 运行、暂停、窗口等待、排队混合收尾，可人工结束 | `test_mixed_pause_window_wait_and_queued_root_drain`、`test_timing_settings`、`test_queue_api` |
| 中断后不重放未知工作及孤儿子操作 | `test_restart_does_not_replay_unconfirmed_work`、`test_restart_discards_queued_children_of_lost_parent` |
| 相同数据库不能被另一个实例接管 | `test_database_lock_is_independent_of_state_directory`、`test_web_config` 中实例锁测试 |
| 脚本输出运行中入库、取消后证据保留 | `test_script_output_is_persisted_through_child_request_while_running`、`test_stream_output` |
| 超时、非零退出保留实际信息 | `test_script_timeout_and_exit_failure_keep_actual_evidence`；异常附退出码、输出预览与调用 ID |
| Windows 强杀后脚本及子孙进程停止 | `test_runtime_crash`：隔离进程实际终止及此前输出落库 |
| 外部操作先返回 ID，停止期间仍可查询与取消 | `test_queue_api.test_connection_operation_http_identity_and_cancel_during_drain` |
| 连接验证输入不明文持久化，页面不返回密文 | `test_credentials_are_sealed_and_idempotency_uses_actual_input` |
| 启动/重启脚本、端口冲突和失败诊断 | `test_startup`：隔离前后端实例 |
| 无旧调度路径，API / scheduler 不写执行终态 | `test_code_has_one_dispatcher_and_no_old_control_path` |

## 二次复查与修复

本次沿提交、子操作、取消、超时、清理、结果提交和重启恢复检查公共控制路径。以下六个遗漏先用新增测试复现失败，再修改实现使测试通过：

| 原问题及全局影响 | 修复与验证（`verification/test_queue_review.py`） |
| --- | --- |
| 到期检查直接等待停止；一次停止失败可抛出主循环，慢停止阻塞其他工作派发 | 到期提交统一取消请求，保存所属尝试 ID；失败记在该控制请求。验证停止异常不逃出 tick，旧尝试的超时命令不会取消新尝试 |
| 完成落库失败关闭整个派发器，连必要清理也不能执行，父任务可能一直等待 | 停止普通接单及派发，保留清理/人工控制；保存原始业务失败、提交失败及观察到的结果。能写库时登记需核验；不能写库时保留原意图并输出诊断。验证清理继续、未知结果不重放、不误报收尾完成 |
| 没有运行协程时，停止流程忽略已排队控制请求 | 收尾同时等待排队控制请求及运行工作；验证没有初始运行任务时也处理控制队列 |
| 任务捕获开窗失败后继续工作，执行计时仍冻结 | 统一等待接口处理结果，在窗口等待结束后恢复计时；验证后续工作继续累计运行时间 |
| 从持久化记录恢复异常，再记录时增加 PersistedFailure 类型和新堆栈，遮盖原始证据 | 内部传递已保存证据时原样还原；显式添加上下文时保留原始异常链和堆栈。验证直接还原及新增上下文两种路径 |
| 已结束请求的取消标记和原因留在内存，随历史累计 | 请求终结后释放临时控制记录；验证连续取消 30 个请求后不留标记 |

复查另补了公共边界验证：工具取消必须等实际调用返回后才交还窗口；提交参数不能伪造控制权限或跨执行关联子操作；WebDriver 的日志脱敏不能改变真实响应、数字字段或破坏错误记录；落库故障后重新恢复仍保留此前业务异常和提交异常。Windows 凭据保护失败直接保留系统异常码及具体消息。

上述行为共新增 12 项自动验证。页面增加完成落库故障提示，展示实际错误，说明已停止新接单及仍可用的控制入口。

## 再次核查：代码与实际停止证据

再次核查确认上一轮修改确实位于运行代码中，原 12 项复查测试重新通过；同时发现以下两处遗漏，先新增测试复现失败，再修正实现：

- 紫鸟账户查询、连接验证及连接保存取消时，等待协程被取消，但底层线程仍可访问外部服务和数据库。现在 `queueing/models.py` 的执行器默认必须等待实际调用结束；仅任务和受管脚本声明可在子操作/进程停止后中断。`queueing/service.py` 使用这一声明，删除按操作名称维护的取消例外列表。验证用实际线程分别覆盖三类操作，确认取消请求保持 RUNNING、停止服务等待线程完成，线程最后的日志仍可入库，然后才确认取消。
- API 原始操作失败后，如果错误日志也写入失败，HTTP 处理器直接断开连接。现在 `api/server.py` 保留原始错误响应，另外返回日志写入失败证据，并将两份异常及堆栈输出到服务诊断流。真实本地 HTTP 测试注入日志写入异常，确认仍收到原始错误及写库错误，不再只有连接断开。

这两项测试位于 `verification/test_queue_review.py`；现有 `test_queue_api.py` 同步验证取消等待真实完成的 HTTP 行为。测试不调用真实紫鸟。本轮完整 Python 回归原始输出保存到 `data/acceptance/framework-recheck-20261109.txt`。

## 生效方式与数据

重启 `deploy/start.bat` 后加载新后端；构建产物已更新。默认数据库改为 `database/sqlite/unified.sqlite3`，启动时创建新结构。旧 `local.sqlite3` 原样保留，不双写、不迁移。旧库的运行记录、时间/预算设置和连接配置不自动进入新库；配置页面以新库的实际设置为准。

旧数据库结构若通过 --db 指定，会明确拒绝启动并说明原因，避免新旧结构半兼容。没有删除项目外文件，也没有运行真实店铺业务。

## 验证边界

- 本次平台为 Windows + SQLite，紫鸟使用模拟适配器；真实连接协议、真实窗口故障和 PostgreSQL 需对应环境验证，不列为已验证结果。
- 普通异步处理器仍需非阻塞，任意同步死循环不具备进程隔离能力；受管脚本具备 Windows 进程树控制。普通工具不具备通用强制终止能力，取消会等待实际调用结束，期间保留窗口占用；不能把取消等待协程当作外部操作已停止。
- 全量历史状态读取、日志归档/保留期限、任意工具大返回值容量、文件与数据库配置权威性属于改造前审查的其他框架缺口，本期未承诺解决。
- 共享数据库失效属于服务级故障：最终事务回滚，保存可写入的原始失败证据并停止普通接单/派发；控制入口保留，但实际执行仍依赖数据库可用。数据库持续不可写时，异常输出到服务诊断流，不能承诺日志已入库。不会把无法提交的结果当作成功，中断后的不确定结果仍需核验。

本记录证明本期统一控制机制及上述场景，不代表系统所有框架问题都已经消除。
