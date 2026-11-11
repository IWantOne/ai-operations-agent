<script setup>
import { computed, inject, onUnmounted, ref, watch } from "vue";
import { request, stamp } from "../api/platform";
import { payload, summary, operationLabel } from "../api/logPresentation";

const { route } = inject("workbench");
const definitions = ref({modules:{}, event_types:{}, providers:{}, levels:{}});
const emptyFilters = () => ({ module: "", event_type: "", provider: "", level: "", category: "", execution_id: "", call_id: "", q: "", since: "", end: "" });
const filters = ref(emptyFilters());
const applied = ref({});
const items = ref([]), total = ref(0), page = ref(1), loading = ref(false), error = ref("");
const snapshotUntil = ref(null), updated = ref(""), expanded = ref("");
const pageSize = 50;
const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
let controller;
const identity = (row) => row.source + ":" + row.id;
function formatted(row) {
  const data = payload(row);
  return data === null ? row.content : JSON.stringify(data, null, 2);
}
async function load(target = 1, fresh = false) {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = "";
  const query = new URLSearchParams({ ...applied.value, page: target, page_size: pageSize });
  if (!fresh && snapshotUntil.value !== null) query.set("until", snapshotUntil.value);
  try {
    const data = await request("logs/query?" + query, { signal: current.signal });
    if (controller !== current) return;
    items.value = data.items;
    if (data.definitions) definitions.value = data.definitions;
    total.value = data.total;
    page.value = data.page;
    snapshotUntil.value = data.until;
    updated.value = new Date().toLocaleTimeString("zh-CN");
    expanded.value = "";
  } catch (e) {
    if (controller === current && e.name !== "AbortError") error.value = e.message;
  } finally {
    if (controller === current) loading.value = false;
  }
}
function search() {
  const values = Object.fromEntries(Object.entries(filters.value).filter(([, value]) => value !== ""));
  if (values.since) values.since = new Date(values.since).getTime() / 1000;
  if (values.end) {
    values.until = new Date(values.end).getTime() / 1000;
    delete values.end;
  }
  applied.value = values;
  load(1, true);
}
function reset() {
  filters.value = emptyFilters();
  search();
}
watch(() => route.value.execution_id, (id) => {
  filters.value.execution_id = id || "";
  search();
}, { immediate: true });
onUnmounted(() => controller?.abort());
</script>

<template>
  <section class="log-page">
    <div class="ap-heading">
      <h1>日志</h1>
      <button class="ap-btn" :disabled="loading" @click="load(1, true)">刷新日志</button>
    </div>
    <p class="log-guide">记录模块说明谁记录，事件类型说明发生了什么。紫鸟是外部数据来源；接口响应不等于任务成功。</p>
    <form class="log-filters" @submit.prevent="search">
      <label>记录模块<select v-model="filters.module"><option value="">全部模块</option><option v-for="(label,key) in definitions.modules" :key="key" :value="key">{{ label }}</option></select></label>
      <label>事件类型<select v-model="filters.event_type"><option value="">全部类型</option><option v-for="(label,key) in definitions.event_types" :key="key" :value="key">{{ label }}</option></select></label>
      <label>数据来源<select v-model="filters.provider"><option value="">全部来源</option><option v-for="(label,key) in definitions.providers" :key="key" :value="key">{{ label }}</option></select></label>
      <label>级别<select v-model="filters.level"><option value="">全部级别</option><option v-for="(label,key) in definitions.levels" :key="key" :value="key">{{ label }}</option></select></label>
      <label>诊断标记<select v-model="filters.category"><option value="">不限标记</option><option value="UNKNOWN">资源结果未确认</option></select></label>
      <label>执行 ID<input v-model="filters.execution_id" type="number" min="1" step="1" placeholder="全部执行" /></label>
      <label>调用 ID<input v-model="filters.call_id" type="text" maxlength="128" placeholder="全部调用" /></label>
      <label>开始时间<input v-model="filters.since" type="datetime-local" step="1" /></label>
      <label>结束时间<input v-model="filters.end" type="datetime-local" step="1" /></label>
      <label class="log-search">搜索原文<input v-model="filters.q" type="search" maxlength="500" placeholder="错误原因、返回码、操作或关键词" /></label>
      <div class="log-filter-actions"><button class="ap-btn" type="submit" :disabled="loading">查询</button><button class="ap-link" type="button" @click="reset">重置</button></div>
    </form>
    <p v-if="error" class="ap-issue" role="alert">读取日志失败：{{ error }}。当前列表未更新。<button class="ap-link" @click="load(page)">重试</button></p>
    <div class="log-count" aria-live="polite"><span>{{ loading ? '正在读取…' : `共 ${total} 条` }}</span><span v-if="updated">最近读取 {{ updated }} · 按时间从新到旧</span></div>
    <div class="log-table-wrap" :aria-busy="loading">
      <table class="log-table">
        <thead><tr><th scope="col">时间</th><th scope="col">事件</th><th scope="col">记录模块 / 类型</th><th scope="col">数据来源 / 级别</th><th scope="col">关联</th><th scope="col">结果与内容</th><th scope="col">详情</th></tr></thead>
        <tbody>
          <template v-for="row in items" :key="identity(row)">
            <tr>
              <td class="log-time">{{ stamp(row.occurred_at) }}</td>
              <td class="log-operation">{{ row.event_label || row.action }}<small v-if="operationLabel(row)">{{ operationLabel(row) }}</small><small v-if="row.category === 'UNKNOWN'" class="log-error">资源结果未确认</small></td>
              <td>{{ definitions.modules[row.module] || row.source }}<small>{{ definitions.event_types[row.event_type] || '未登记事件' }}</small></td>
              <td>{{ definitions.providers[row.provider] || '未标注' }}<small :class="{ 'log-error': ['ERROR', 'CRITICAL'].includes(row.level) }">{{ definitions.levels[row.level] || row.level }}</small></td>
              <td class="log-relations"><span v-if="row.execution_id">执行 #{{ row.execution_id }}</span><span v-if="row.task_id">任务 #{{ row.task_id }}</span><span v-if="row.borrow_id">申请 #{{ row.borrow_id }}</span><span v-if="!row.execution_id && !row.task_id && !row.borrow_id">—</span></td>
              <td><div class="log-preview">{{ summary(row) }}</div></td>
              <td><button class="ap-link" :aria-expanded="expanded === identity(row)" :aria-controls="'log-' + identity(row)" @click="expanded = expanded === identity(row) ? '' : identity(row)">{{ expanded === identity(row) ? '收起' : '展开' }}</button></td>
            </tr>
            <tr v-if="expanded === identity(row)" :id="'log-' + identity(row)" class="log-details"><td colspan="7">
              <p>存储记录 {{ row.source }} #{{ row.id }} · 事件代码 {{ row.action }} · 原级别 {{ row.level }}<span v-if="row.call_id"> · 调用 {{ row.call_id }}</span></p>
              <p v-if="row.category === 'UNKNOWN'">资源结果未确认是事件发生时的诊断标记，不代表当前状态。具体原因见下方原始内容。</p>
              <template v-if="payload(row)?.traceback"><strong>异常堆栈</strong><pre>{{ payload(row).traceback }}</pre></template>
              <strong>完整内容</strong><pre>{{ formatted(row) }}</pre>
              <details><summary>存储原文</summary><pre>{{ row.content }}</pre></details>
            </td></tr>
          </template>
          <tr v-if="!items.length && !loading"><td colspan="7" class="log-empty">{{ error ? '日志读取失败，请重试。' : '没有符合条件的日志。' }}</td></tr>
        </tbody>
      </table>
    </div>
    <div class="log-pagination"><span>每页 {{ pageSize }} 条 · 第 {{ page }} / {{ pages }} 页</span><button class="ap-btn" :disabled="loading || page <= 1" @click="load(page - 1)">上一页</button><button class="ap-btn" :disabled="loading || page >= pages" @click="load(page + 1)">下一页</button></div>
  </section>
</template>

<style scoped>
.log-guide {font-size:13px;color:var(--ap-muted);line-height:1.7}
.log-filters {display:flex;flex-wrap:wrap;align-items:end;gap:12px;padding:16px 0;border-bottom:1px solid var(--ap-border,#dce3e0)}
.log-filters label {display:flex;flex-direction:column;gap:6px;font-size:13px}
.log-filters input,.log-filters select {font:inherit;color:inherit;background:var(--ap-surface,#fff);border:1px solid var(--ap-border,#ccd6d0);border-radius:6px;padding:8px;min-height:36px}
.log-filters input[type=number] {width:110px}.log-search {flex:1;min-width:240px}.log-filter-actions {display:flex;gap:12px;align-items:center;min-height:36px}
.log-count,.log-pagination {display:flex;align-items:center;gap:12px;padding:16px 0;font-size:13px}.log-count {justify-content:space-between}.log-pagination>span {margin-right:auto}
.log-table-wrap {overflow:auto;border:1px solid var(--ap-border,#dce3e0);border-radius:8px}.log-table {width:100%;min-width:960px;border-collapse:collapse;text-align:left;font-size:13px}
.log-table th {background:var(--ap-soft,#f4f7f5);font-weight:600;white-space:nowrap}.log-table th,.log-table td {padding:12px;border-bottom:1px solid var(--ap-border,#e2e8e4);vertical-align:top}
.log-table small,.log-relations span {display:block;margin-top:4px}.log-time {white-space:nowrap;width:150px}.log-operation {max-width:180px;overflow-wrap:anywhere}.log-relations {white-space:nowrap}
.log-preview {white-space:pre-wrap;overflow-wrap:anywhere;min-width:240px;max-height:100px;overflow:hidden}.log-error {color:#b42318;font-weight:600}
.log-details td {background:var(--ap-soft,#f8faf9)}.log-details pre {white-space:pre-wrap;overflow-wrap:anywhere;max-height:520px;overflow:auto;font-size:12px;padding:12px;background:var(--ap-surface,#fff);border:1px solid var(--ap-border,#dce3e0);user-select:text}.log-details p {margin:0 0 12px}.log-empty {text-align:center;padding:40px!important}
/* The employee template has global nth-column and mobile table rules. Keep logs independent. */
#agent-console-demo .log-table {display:table;background:var(--ap-panel)}
#agent-console-demo .log-table thead {display:table-header-group}
#agent-console-demo .log-table tbody {display:table-row-group}
#agent-console-demo .log-table tr {display:table-row}
#agent-console-demo .log-table td {display:table-cell;padding:12px;border-bottom:1px solid var(--ap-line)}
#agent-console-demo .log-table td::before {content:none}
#agent-console-demo .log-table th:nth-child(1) {width:16%}
#agent-console-demo .log-table th:nth-child(2) {width:16%}
#agent-console-demo .log-table th:nth-child(3) {width:13%}
#agent-console-demo .log-table th:nth-child(4) {width:12%}
#agent-console-demo .log-table th:nth-child(5) {width:10%}
#agent-console-demo .log-table th:nth-child(6) {width:27%}
#agent-console-demo .log-table th:nth-child(7) {width:6%}
#agent-console-demo .log-table .log-error {color:var(--ap-red)}
.log-preview {min-width:0}
</style>
