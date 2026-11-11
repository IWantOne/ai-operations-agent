# Agent 工作台

Python 后端负责业务、任务调度和资源管理。Vue 前端按设计包的 `Demo/员工工作台-demo.html` 展示员工、进度看板、紫鸟资源和配置。

## 启动

双击 `deploy/start.bat`，或在项目根目录执行 `.\deploy\start.ps1`。默认启动 Vite 热更新前端和 Python 后端，仅在缺少前端依赖时安装，不执行前端构建。打开 http://127.0.0.1:5173 ，修改 Vue 文件会自动更新页面。后端默认使用 8765 端口，可用启动参数 `--port` 指定。5173 被占用时会报错，不会切换到其他端口。涉及店铺的操作使用真实紫鸟；店铺池来自紫鸟账户的店铺列表，不需要在部署文件里写死店铺。

`start.bat` / `start.ps1` 是整个工作台的启动／重启入口：未运行时启动前后端；已运行时，再次双击会请求当前配置端口上的后端正常停止，等待后端进程完成清理及旧前端退出，然后重新启动前后端。不会强杀占用端口的其他程序；停止失败或等待超时会报错并终止本次重启。

保留启动窗口查看输出；通过页面“停止服务”或窗口内 Ctrl+C 停止，后端退出时脚本也会停止其启动的 Vite。启动失败时 bat 会保留窗口供查看错误。前端文件保存后热更新；Python 后端代码修改后再次双击脚本重启整个工作台。

需要构建产物模式时，执行 `.\deploy\start.ps1 -Production`（也可 `deploy\start.bat -Production`），脚本构建 Vue 页面后启动服务，打开 http://127.0.0.1:8765 。两种模式均可追加后端参数，例如 `.\deploy\start.ps1 --port 8766`。

前端端口可通过 `-FrontendPort 5174` 指定。重启时沿用上次的前后端端口参数；默认双击使用前端 5173 和配置中的后端端口。

开发 Vue 页面时，在 `frontend/` 执行 `npm ci` 和 `npm run dev`。在 `backend/` 执行 `python -m agent_platform serve` 启动 API。开发服务器将 `/api` 转发至后端 8765 端口。

## 一期：统一执行控制

任务页面和紫鸟页面保留各自入口，后台统一由 `queueing.QueueService` 接单、派发、控制、收尾和恢复。旧 `tasks/manager.py`、资源池的等待派发循环和 `task_run_request` 已删除。

```text
backend/agent_platform/
  queueing/      # 唯一控制器、仓库、派发器、生命周期、重试预算、恢复
  tasks/         # 任务定义、处理器注册
  scheduler/     # 只提交定时请求，不执行任务
  executions/    # 受限任务上下文、进度与累计计时
  resources/     # 窗口归属、占用事实、单次开关窗与核验
  runtime/       # 受管脚本进程、停止、流式输出
  tools/         # 工具登记和单次调用
  connectors/    # 紫鸟协议及原始返回
  settings/      # 配置校验和持久化
  database/      # SQLite / PostgreSQL 连接与事务
  logs/          # 原始证据、事件词典、数据库分页查询
  api/           # 提交操作与控制命令，读取实际结果
```

统一请求包括 `task.run`、`ziniao.acquire/release/inspect`、紫鸟账户查询、连接验证/保存、端口检测、`script.run`、`tool.call` 和取消操作。只有 `queueing/dispatcher.py` 创建业务执行协程。运行器内部的进程监控、管道读取不属于业务调度。

- `work_request` 保存工作身份、输入、父尝试、根请求、策略快照和结果；同提交键同输入返回原请求，不同输入拒绝。
- `work_attempt` 保存每次实际执行及原始异常。请求、尝试、任务执行投影、预算和完成事件在同一事务提交；外部操作不占数据库事务。
- `retry_budget` 是根请求总预算。任务、窗口、工具的自动重试共同消耗；首次尝试不扣减，重启不重置。人工重跑创建关联历史的新根请求。
- `control_command` 区分已提交、实际确认和失败。暂停/继续到达检查点后确认，取消等待实际使用者停止。
- 请求终态为成功、失败、取消、超时或需核验，不再使用 `DONE`。需核验表示暂停自动处理，具体原因始终来自原异常。

## 容量、停止与恢复

“配置 → 统一执行控制”可以设置任务、紫鸟、脚本/工具、窗口容量，以及独立保留的清理/核验和取消名额。降低容量不强停现有工作，在后续派发时生效。任务等待子操作时保留任务名额，子操作不占任务名额。

同店铺有序互斥，其他可用店铺可以推进；同一店铺的打开、关闭、核验也不能交叉执行。窗口交接要求使用者停止、关闭完成、核验关闭。停止失败不能关窗或释放容量；关窗失败保留占用与具体原因，紫鸟资源页提供“核验是否已关闭”和“尝试关闭并核验”。

停止服务先拒绝新根工作、停止新根请求派发；已有执行的子操作和收尾继续推进。状态、日志、取消、继续及窗口核验仍可用。等待时长及到期动作在“配置 → 时间与停止策略”设置，默认到期后继续等待；可选择取消。未派发的根请求保留到下次启动。

到期停止通过统一控制队列执行，单项停止失败保留具体异常，不阻塞主循环派发其他工作。收尾包含已排队的控制请求。普通工具取消须等待实际调用结束后才交还窗口；受管脚本可停止进程树，普通工具没有通用强制终止能力。

执行器统一声明是否允许中断，默认等待实际调用结束。紫鸟账户查询、验证/保存连接也遵守同一规则，底层线程未结束时不能确认取消或完成服务收尾。

完成结果落库失败时停止普通接单及派发，保留清理和人工控制，页面显示具体原因。原始业务异常、提交异常及已观察到的结果分别保留；数据库持续不可写时输出服务诊断，不能承诺已入库或已完成。恢复时保留已写入的故障证据，不自动重放未知结果。

重启前取得数据库排他锁：SQLite 锁随数据库路径，PostgreSQL 使用数据库 advisory lock，均不由 state-dir 决定。恢复先把没有收到结果的运行尝试登记为需核验，取消失去父执行的未启动子操作，再核验窗口。未确认关闭的窗口继续占用容量；不会自动重做未知外部动作，也不会假装恢复 Python 内存栈。

## 配置和新开发库

当前默认数据库为 `database/sqlite/unified.sqlite3`，首次启动创建。旧 `database/sqlite/local.sqlite3` 未删除、不迁移；新代码会拒绝混用旧调度结构。当前系统尚未投用，采用新结构直接开发，原开发库中的运行记录和数据库配置不会自动带入新库。

没有部署配置文件：数据库默认 `database/sqlite/unified.sqlite3`、端口默认 8765、状态目录默认 `data/`，都可用启动参数覆盖（`--db`、`--port`）。使用 PostgreSQL 需安装 `python -m pip install -e ".[postgres]"`，用 `--db` 传连接串并设置 `AGENT_PLATFORM_DATABASE_URL`；该适配器尚未实连验证。

统一重试设置保存在 `queue.retry`，字段为 `enabled`、`total_retries`。默认关闭。任务从头重跑必须明确声明 `restart_safe=True`，工具重试也须声明安全；未声明默认不重放。开窗重试必须有明确未产生副作用的声明，并核验窗口确实未打开。关闭或检查结果不明时保留原始错误供核验。

清理/核验使用关联原执行的独立有限控制预算，不重跑业务。根预算、重试间隔和任务时限在提交时冻结；子操作继承根策略。窗口占用时长在获得窗口时冻结。连接超时用于下一次调用，停止策略在收尾开始时读取。所有运营时间配置集中在 `settings/timing.py`，包括本机端口检测与探测超时。

## 任务接入

任务为非阻塞异步函数，通过 `service.register("name", handler, restart_safe=False)` 注册。工具通过 `service.tools.register("name", handler, restart_safe=False)` 登记。处理器返回可 JSON 序列化的结果，异常直接抛出，不替换成状态码。

```python
async def work(ctx):
    lease = await ctx.window(ctx.input["shop_id"])
    result = await ctx.tool("registered_tool", window=lease["window_ref"])
    await ctx.release(lease["id"])
    return {"completed": True, "result": result}
```

`ctx.window/release/script/tool` 都生成关联当前尝试的队列子请求。上下文提供 `input`、`skill`、`data/save`、`progress/save_progress`、`log`、`sleep`、`checkpoint`、`human`；不公开 manager/store。`resume_enabled` 允许人工使用已保存进度创建新执行，旧记录不覆盖。

脚本非零退出会保留退出码、stdout/stderr 预览和输出调用 ID，并报告实际 `CalledProcessError`。超时和取消保留各自结果，清理异常另行记录。脚本的 Windows Job Object 管理和进程树终止能力继续保留。

## 日志与页面

“日志”使用普通列表，支持时间、模块、级别、类别、执行 ID 和原文查询，数据库分页。展开查看原始内容、异常类型、异常链和完整堆栈。UNKNOWN 仅为资源诊断筛选元数据和内部保护状态，不能替换或再包装异常。

任务详情和紫鸟资源页显示统一请求、每次尝试、父尝试关联、重试已用/剩余数以及实际错误；控制命令显示提交与确认情况。外部操作先返回操作 ID，页面查询 `/api/operations/{id}` 取得实际结果，不把等待响应当成执行结果。

脚本输出边读取边写入 `runtime_log`：每段最多 16 KiB，stdout/stderr 各最多保留 64 KiB 返回预览，携带截断标志、总字节数和调用 ID。日志可以还原原始字节，取消或强杀前已提交的记录仍保留。参见 [日志规范](docs/logging-spec.md)。

## 验证与范围

```powershell
# 在 frontend 目录
npm run build
```

本项目不维护自动化测试套件。`verification/live_acceptance.py` 是可选的真实冒烟入口：`python verification/live_acceptance.py --confirm-store 27156808109149` 会打开和关闭授权店铺的空白窗口，使用独立验收库；只有明确需要真实验收时才运行。`python verification/workbench.py --manual` 可启动独立 A/B 手动验收页面。

本期交付单机统一执行控制，不承诺隔离任意 Python 同步阻塞代码；此类处理器仍须改成非阻塞接口或受管脚本。历史状态接口仍有全量读取，日志归档/保留期限、任意工具大结果容量、文件与数据库配置一致性不在本期交付范围。不能把本地验收通过等同于所有框架问题已解决。

[一期执行文档](docs/unified-execution-plan.md)记录实际任务单；[验收记录](docs/phase-one-acceptance.md)记录验证结果；[改造前审查](docs/framework-review.md)保留问题基线。
