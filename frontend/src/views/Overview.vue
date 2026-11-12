<script setup>
import { computed, inject, ref } from "vue";
import { shop, taskLabel, taskStage } from "../api/platform";
const { state, openTask, navigate } = inject("workbench");
const term = ref("");
const selected = ref("attention");
const owners = computed(() => new Map(state.value.employees.map(e => [e.key, e.name])));
const tabs = {attention:"需要处理", running:"执行中", all:"全部任务"};
const priority = {failed:0, inactive:1, running:2, queued:3, done:4};
function matches(task, filter) {
  const stage = taskStage(task);
  return filter === "all" || (filter === "attention" ? (stage === "failed" || (stage === "inactive" && !task.handler)) : stage === filter);
}
const rows = computed(() => {
  const keyword = term.value.trim().toLocaleLowerCase();
  return state.value.tasks.filter(t => matches(t, selected.value) &&
    [t.name, owners.value.get(t.employee_key), shop(t), "#" + t.id].some(value =>
      String(value || "").toLocaleLowerCase().includes(keyword)))
    .sort((a,b) => priority[taskStage(a)] - priority[taskStage(b)] || b.id - a.id);
});
const reclaiming = computed(() => state.value.resources.filter(r => r.status === "CLOSING").length);
const waiting = computed(() => state.value.requests.filter(r => r.kind === "ziniao.acquire" && ["QUEUED","RETRY_WAIT"].includes(r.status)).length);
function reset() { term.value = ""; selected.value = "all"; }
</script>
<template>
  <div class="ap-heading"><div><h1>工作总览</h1>
    <p>{{ owners.size }} 位员工，共 {{ state.tasks.length }} 项任务</p></div>
    <button class="ap-btn" @click="navigate({menu:'employees'})">查看员工</button>
  </div>
  <div class="overview-layout">
    <section class="work-list">
      <div class="list-title"><h2>任务清单</h2><input type="search" class="work-search" v-model="term" placeholder="搜索任务、员工或店铺" aria-label="搜索任务、员工或店铺" /></div>
      <div class="ap-tabs inbox-tabs" aria-label="任务范围">
        <button v-for="(label,key) in tabs" :key="key" :aria-pressed="selected === key" @click="selected = key">{{ label }} <b>{{ state.tasks.filter(t => matches(t,key)).length }}</b></button>
      </div>
      <button v-for="t in rows" :key="t.id" class="inbox-row" @click="openTask(t)">
        <span class="inbox-name"><strong>{{ t.name }}</strong><small>任务 #{{ t.id }} · {{ owners.get(t.employee_key) || t.employee_key }}<template v-if="shop(t) !== '无店铺'"> · {{ shop(t) }}</template></small></span>
        <span :class="['ap-badge',taskStage(t)]">{{ taskLabel(t) }}</span><span aria-hidden="true">›</span>
      </button>
      <div v-if="!rows.length" class="ap-empty">
        <p>{{ term ? '没有匹配的任务' : !state.tasks.length ? '工作台还没有任务' : selected === 'attention' ? '当前没有需要处理的任务' : '当前没有执行中的任务' }}</p>
        <button v-if="state.tasks.length" class="ap-link" @click="reset">查看全部任务</button>
        <button v-else class="ap-link" @click="navigate({menu:'employees'})">前往员工目录</button>
      </div>
    </section>
    <aside class="resource-brief">
      <h2>紫鸟窗口</h2>
      <div class="window-count"><b>{{ state.resources.filter(r => r.status !== 'CLOSED').length }}</b> 个窗口占用中</div>
      <dl><div><dt>等待窗口</dt><dd>{{ waiting }} 项</dd></div>
          <div><dt>回收中</dt><dd>{{ reclaiming }} 个</dd></div></dl>
      <button class="ap-link" @click="navigate({menu:'resources'})">查看资源与队列</button>
    </aside>
  </div>
</template>
