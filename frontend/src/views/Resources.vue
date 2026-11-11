<script setup>
import { computed, inject } from "vue";
import WorkRequests from "../components/WorkRequests.vue";
import AccountOverview from "../components/AccountOverview.vue";
import ShopDetail from "../components/ShopDetail.vue";
import ShopLink from "../components/ShopLink.vue";
import { stamp } from "../api/platform";
const { state, openTask, route, action, busy } = inject("workbench");
const activeLease = (resource) =>
  state.value.leases.find(
    (l) =>
      l.resource_id === resource.id &&
      ["ACTIVE", "OPENING", "CLOSING", "UNKNOWN"].includes(l.status),
  );
const taskFor = (row) => {
  const taskId =
    row?.task_id ??
    state.value.executions.find((e) => e.id === row?.execution_id)?.task_id;
  return state.value.tasks.find((t) => t.id === taskId);
};
const employeeName = (key) => state.value.employees?.find((employee) => employee.key === key)?.name || key;
const leases = {ACTIVE:"使用中", RELEASED:"已归还", FAILED:"失败", CANCELLED:"已取消"};
const names = {
  CLOSED: "已关闭",
  OPEN: "使用中",
  OPENING: "打开中",
  CLOSING: "回收中",
  UNKNOWN: "操作未完成，见失败原因",
};
const queues = computed(() => ({
  窗口申请队列: state.value.requests.filter(r=>r.kind==="ziniao.acquire" && ["QUEUED","RETRY_WAIT"].includes(r.status)).map(r=>({...r,shop_id:JSON.parse(r.run_input).shop_id})),
  任务派发队列: state.value.requests.filter((r) => r.kind === "task.run" && ["QUEUED","RETRY_WAIT"].includes(r.status)),
}));
</script>
<template>
  <ShopDetail v-if="route.shop" />
  <div v-show="!route.shop" class="ap-heading">
    <h1>紫鸟资源</h1>
    <span class="ap-muted"
      >工作台窗口占用
      {{ state.resources.filter((r) => r.status !== "CLOSED").length }}/{{state.settings.queue.windows}}</span
    >
  </div>
  <AccountOverview v-show="!route.shop" />
  <template v-if="!route.shop">
  <WorkRequests />
  <h2 class="resource-section-title">任务资源与队列</h2>
  <section v-if="!state.resources.length" class="ap-panel">
    <h2>暂无工作台任务占用窗口</h2>
    <p class="ap-muted">任务申请店铺窗口后，可在这里查看占用员工和关联任务。</p>
  </section>
  <section v-for="r in state.resources" :key="r.id" class="ap-panel">
    <div class="ap-panelhead">
      <div>
        <h2><ShopLink :id="String(r.shop_id)" /></h2>
        <p v-if="activeLease(r)">
          {{ employeeName(taskFor(activeLease(r))?.employee_key) }} ·
          {{ taskFor(activeLease(r))?.name }} · 执行 #{{
            activeLease(r).execution_id
          }}
        </p>
        <p v-else>当前无借用</p>
      </div>
      <span
        :class="[
          'ap-badge',
          r.blocked ? 'failed' : r.status === 'CLOSED' ? 'idle' : 'running',
        ]"
        >{{ r.blocked ? "资源已停用，见失败原因" : names[r.status] || r.status }}</span
      >
    </div>
    <div v-if="activeLease(r) && r.blocked" class="ap-actions">
      <button class="ap-btn" :disabled="busy" @click="action('inspect_window',activeLease(r).id)">核验是否已关闭</button>
      <button class="ap-btn" :disabled="busy" @click="action('release_window',activeLease(r).id)">尝试关闭并核验</button>
    </div>
    <p v-if="r.error_message" class="ap-issue" role="alert"><strong>失败原因：</strong>{{ r.error_message }}</p>
    <p v-if="activeLease(r)" class="ap-muted">
      申请 #{{ activeLease(r).id }} · 到期
      {{ stamp(activeLease(r).expires_at) }}
    </p>
    <button
      v-if="taskFor(activeLease(r)) && activeLease(r)"
      class="ap-btn"
      @click="openTask(taskFor(activeLease(r)))"
    >
      查看关联任务
    </button>
  </section>
  <section v-for="(queue, title) in queues" :key="title" class="ap-panel">
    <div class="ap-panelhead">
      <h2>{{ title }}</h2>
      <span class="ap-muted">{{ queue.length }} 项</span>
    </div>
    <p v-if="!queue.length" class="ap-muted">暂无排队</p>
    <div v-for="(r, i) in queue" :key="r.id" class="ap-panelhead">
      <p>
        {{ i + 1 }}.
        {{
          r.execution_id
            ? r.shop_id + " · 执行 #" + r.execution_id
            : "请求 #" + r.id
        }}
      </p>
      <button v-if="taskFor(r)" class="ap-link" @click="openTask(taskFor(r))">
        {{ taskFor(r).name }}
      </button>
    </div>
  </section>
  <section class="ap-panel">
    <details>
      <summary>最近借还记录</summary>
      <p
        v-for="l in [...state.leases].sort((a, b) => b.id - a.id).slice(0, 30)"
        :key="l.id"
      >
        申请 #{{ l.id }} · {{ l.shop_id }} · 执行 #{{ l.execution_id }} ·
        {{ leases[l.status] || names[l.status] || l.status }}
      </p>
      <p v-if="!state.leases.length" class="ap-muted">暂无记录</p>
    </details>
  </section>
  </template>
</template>

<style scoped>
.resource-section-title {margin:28px 0 16px !important}
</style>
