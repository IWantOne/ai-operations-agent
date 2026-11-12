<script setup>
import { computed, inject, reactive, ref } from "vue";
import WorkRequests from "./WorkRequests.vue";
import { attempts, request, states, stamp, when } from "../api/platform";
const props = defineProps({ task: { type: Object, required: true } });
const { state, action, busy, navigate } = inject("workbench");

const rows = computed(() => attempts(state.value, props.task));
const latest = computed(() => rows.value[0]);
const pending = computed(() =>
  state.value.requests.filter(
    (r) => r.task_id === props.task.id && ["QUEUED", "RETRY_WAIT"].includes(r.status),
  ),
);
const active = (row) => ["STARTING", "RUNNING", "PAUSED"].includes(row.status);

const open = ref(new Set());
const logs = reactive({});
const logErrors = reactive({});
const selected = ref("");

async function toggle(id) {
  const next = new Set(open.value);
  if (next.has(id)) {
    next.delete(id);
    open.value = next;
    return;
  }
  next.add(id);
  open.value = next;
  if (logs[id]) return;
  try {
    logs[id] = await request("logs?execution_id=" + id);
  } catch (e) {
    logErrors[id] = e.message;
  }
}

const LABELS = {
  checked: "检查", added: "新增", kept: "保持", skipped: "跳过",
  submitted: "已提交", removed: "已移除", manual: "需人工",
  sent: "回传", ok: "成功", total: "共",
};
function parse(value) {
  try {
    const data = typeof value === "string" ? JSON.parse(value || "{}") : value;
    return data && typeof data === "object" ? data : null;
  } catch {
    return null;
  }
}
function describe(data) {
  return Object.entries(data)
    .filter(([key, value]) => key !== "completed" && value !== null && value !== "" && typeof value !== "object")
    .slice(0, 5)
    .map(([key, value]) => `${LABELS[key] || key} ${value}`)
    .join(" · ");
}
const ERROR_NAMES = {
  CancelledError: "已取消",
  TimeoutError: "超时",
  ConnectionRefusedError: "紫鸟客户端未连接",
  ConnectorError: "紫鸟调用失败",
};
function human(error) {
  const text = String(error || "").split("\n")[0].trim();
  if (!text) return "";
  const name = text.split(":")[0].trim();
  const detail = text.slice(name.length + 1).trim();
  return ERROR_NAMES[name] ? `${ERROR_NAMES[name]}${detail ? "：" + detail : ""}` : text;
}
function summary(row) {
  if (row.pause_reason) return "暂停：" + row.pause_reason;
  const data = parse(row.result_data);
  if (data && Object.keys(data).length) {
    const text = describe(data);
    if (text) return text;
  }
  if (row.error_message) return human(row.error_message).slice(0, 90);
  if (row.wait_reason === "WINDOW") return "等待紫鸟窗口";
  if (row.status === "SUCCEEDED" && Number(row.elapsed_seconds || 0) < 0.5) return "无待处理";
  return row.wait_reason || "";
}
const tone = (row) =>
  row.status === "SUCCEEDED" ? "done"
    : ["FAILED", "TIMEOUT", "NEEDS_REVIEW", "CANCELLED"].includes(row.status) ? "failed"
      : active(row) ? "running" : "queued";
const time = (seconds) => when(seconds);

const CASE_LABELS = { NEW: "待处理", MANUAL: "需人工", SUBMITTED: "已提交", REMOVED: "已移除", REJECTED: "审核后保留" };
const caseTone = (status) =>
  status === "NEW" ? "queued" : status === "REMOVED" || status === "SUBMITTED" ? "done"
    : status === "REJECTED" ? "running" : "failed";
const cases = computed(() => props.task.employee_key === "feedback" ? (state.value.cases || []) : []);
const caseCounts = computed(() => {
  const counts = {};
  for (const item of cases.value) counts[item.status] = (counts[item.status] || 0) + 1;
  return Object.entries(counts).map(([status, n]) => `${CASE_LABELS[status] || status} ${n}`).join(" · ");
});
const pendingCases = computed(() => cases.value.filter((item) => item.status === "NEW").length);
async function focusExecution(id) {
  if (!open.value.has(id)) await toggle(id);
  document.getElementById("exec-" + id)?.scrollIntoView({ behavior: "smooth", block: "center" });
}
</script>
<template>
  <div class="ap-inlineexecution">
    <div v-if="cases.length" class="ap-cases">
      <div class="ap-caseshead">
        <h2>差评明细</h2>
        <span class="ap-muted">{{ caseCounts }}</span>
        <button v-if="pendingCases" class="ap-btn" :disabled="busy"
                @click="action('run', task.id, {input_data: {limit: pendingCases}})">
          处理 {{ pendingCases }} 条待处理
        </button>
      </div>
      <table class="ap-case-table">
        <thead>
          <tr><th>订单</th><th>店铺</th><th>星级</th><th>状态</th><th>原因</th><th>更新时间</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="c in cases" :key="c.id">
            <td>{{ c.order_id }}</td>
            <td>{{ c.store_name || c.sid }}</td>
            <td>{{ c.rating }}★</td>
            <td><span :class="['ap-badge', caseTone(c.status)]">{{ CASE_LABELS[c.status] || c.status }}</span></td>
            <td class="ap-case-reason">{{ c.reason || "—" }}</td>
            <td class="ap-case-time">{{ time(c.updated_at) }}</td>
            <td class="ap-case-actions">
              <button v-if="c.status === 'MANUAL'" class="ap-btn" :disabled="busy"
                      @click="action('retry_case', c.id, {task_id: task.id})">重试</button>
              <button v-if="c.execution_id" class="ap-link" @click="focusExecution(c.execution_id)">
                执行 #{{ c.execution_id }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="ap-timelinehead">
      <h2>执行记录</h2>
      <div class="ap-actions">
        <button v-if="task.enabled && task.handler" class="ap-btn" :disabled="busy"
                @click="action('run', task.id)">运行一次</button>
        <button v-if="task.handler" class="ap-btn" :disabled="busy"
                @click="action(task.enabled ? 'disable' : 'enable', task.id)">
          {{ task.enabled ? "停用" : "启用" }}
        </button>
        <template v-if="latest && active(latest)">
          <button class="ap-btn" :disabled="busy"
                  @click="action(latest.status === 'PAUSED' ? 'resume' : 'pause', latest.id)">
            {{ latest.status === "PAUSED" ? "继续" : "暂停" }}
          </button>
          <button class="ap-btn" :disabled="busy"
                  @click="action('cancel', latest.request_id)">结束</button>
        </template>
        <button v-else-if="latest?.resume_enabled" class="ap-btn" :disabled="busy"
                @click="action('continue', latest.id)">从业务进度续跑</button>
      </div>
    </div>

    <div v-for="r in pending" :key="r.id" class="ap-issue">
      请求 #{{ r.id }} · 等待派发
      <button class="ap-btn" :disabled="busy" @click="action('cancel', r.id)">取消排队</button>
    </div>

    <div v-if="!rows.length" class="ap-empty">暂无执行记录</div>
    <div v-else class="ap-executions">
      <article v-for="r in rows" :key="r.id" :id="'exec-' + r.id" class="ap-execrow">
        <button class="ap-exechead" :aria-expanded="open.has(r.id)" @click="toggle(r.id)">
          <time>{{ time(r.started_at) }}</time>
          <span :class="['ap-badge', tone(r)]">{{ states[r.status] || r.status }}</span>
          <span class="ap-execsum">{{ summary(r) || "—" }}</span>
          <span class="ap-execsecs">{{ Number(r.elapsed_seconds || 0).toFixed(1) }}s</span>
          <span class="ap-execid">#{{ r.id }}</span>
          <span class="ap-cue">{{ open.has(r.id) ? "收起" : "详情" }}</span>
        </button>

        <div v-if="open.has(r.id)" class="ap-execbody">
          <p v-if="r.error_message" class="ap-issue">{{ r.error_message }}</p>
          <p v-if="r.pause_reason" class="ap-issue">暂停原因：{{ r.pause_reason }}</p>
          <p v-if="logErrors[r.id]" role="alert">{{ logErrors[r.id] }}</p>

          <div v-if="logs[r.id]?.length" class="ap-timeline" role="region" aria-label="执行步骤">
            <div class="ap-timeline-track">
              <button v-for="l in logs[r.id]" :key="l.table + ':' + l.id"
                      :class="['ap-node', l.level === 'ERROR' ? 'failed'
                        : l.action === 'window_wait' ? 'wait' : 'step']"
                      :aria-pressed="selected === l.table + ':' + l.id"
                      @click="selected = selected === l.table + ':' + l.id ? '' : l.table + ':' + l.id">
                <time>{{ time(l.occurred_at) }}</time>
                <span class="ap-node-symbol">{{ l.level === "ERROR" ? "!" : l.action === "window_wait" ? "◷" : "✓" }}</span>
                <strong>{{ l.action }}</strong>
                <small>{{ l.table }}</small>
              </button>
            </div>
          </div>
          <p v-else class="ap-muted">本次执行暂无步骤记录</p>
          <div v-if="selected && logs[r.id]?.find(l => l.table + ':' + l.id === selected)"
               class="ap-node-info">
            <span>{{ logs[r.id].find(l => l.table + ':' + l.id === selected).content }}</span>
            <small>{{ stamp(logs[r.id].find(l => l.table + ':' + l.id === selected).occurred_at) }}</small>
            <button class="ap-link" @click="selected = ''">关闭</button>
          </div>

          <details class="ap-tech">
            <summary>技术细节（工作请求与重试）</summary>
            <WorkRequests :execution-id="r.id" />
          </details>

          <p class="ap-muted">
            执行 #{{ r.id }} · {{ states[r.status] || r.status }} ·
            累计 {{ Number(r.elapsed_seconds || 0).toFixed(2) }} 秒
            <button class="ap-link" @click="navigate({ menu: 'logs', execution_id: r.id })">查看日志列表</button>
          </p>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.ap-executions {display:flex;flex-direction:column;gap:8px;margin-top:10px}
.ap-execrow {border:1px solid var(--ap-line);border-radius:8px;background:var(--ap-panel)}
.ap-exechead {display:grid;grid-template-columns:64px 82px 1fr auto auto 56px;align-items:center;gap:12px;
  width:100%;padding:10px 14px;background:none;border:none;font:inherit;color:inherit;text-align:left;cursor:pointer}
.ap-exechead:hover {background:var(--ap-soft)}
.ap-exechead time {font-variant-numeric:tabular-nums;color:var(--ap-muted);font-size:13px}
.ap-execsum {overflow-wrap:anywhere;font-size:13px}
.ap-execsecs,.ap-execid {color:var(--ap-muted);font-size:12px;font-variant-numeric:tabular-nums}
.ap-cue {color:var(--ap-muted);font-size:12px;text-align:right}
.ap-execbody {padding:4px 14px 14px;border-top:1px solid var(--ap-line)}
.ap-tech {margin-top:12px}
.ap-tech summary {cursor:pointer;color:var(--ap-muted);font-size:13px}
.ap-cases {margin-top:18px}
.ap-caseshead {display:flex;align-items:baseline;gap:12px}
.ap-caseshead h2 {margin:0}
.ap-case-table {width:100%;border-collapse:collapse;font-size:13px;margin-top:8px;table-layout:fixed}
.ap-case-table th:nth-child(1) {width:190px}
.ap-case-table th:nth-child(2) {width:130px}
.ap-case-table th:nth-child(3) {width:60px}
.ap-case-table th:nth-child(4) {width:90px}
.ap-case-table th:nth-child(6) {width:100px}
.ap-case-table th:nth-child(7) {width:120px}
.ap-case-actions {white-space:nowrap}
.ap-case-actions .ap-btn {margin-right:8px}
.ap-case-table th {text-align:left;color:var(--ap-muted);font-weight:500;padding:6px 8px;border-bottom:1px solid var(--ap-line)}
.ap-case-table td {padding:6px 8px;border-bottom:1px solid var(--ap-line);vertical-align:top}
.ap-case-reason {max-width:520px;overflow-wrap:anywhere}
.ap-case-time {color:var(--ap-muted);font-variant-numeric:tabular-nums;white-space:nowrap}
@media (max-width: 720px) {
  .ap-exechead {grid-template-columns:56px 74px 1fr auto}
  .ap-execsecs,.ap-execid {display:none}
}
</style>
