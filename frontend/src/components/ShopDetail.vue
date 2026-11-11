<script setup>
import { computed, inject, ref, watch } from "vue";
import { taskShopId, taskStage, taskLabel, stages, stamp, attempts, taskRoute, routeHref } from "../api/platform";
const { state, route, navigate, accountOverview, accountLoading, accountError, loadAccounts } = inject("workbench");
const id = computed(() => String(route.value.shop || ""));
const shop = computed(() => accountOverview.value?.shops.find(s => String(s.id) === id.value));
const tasks = computed(() => state.value.tasks.filter(t => taskShopId(t) === id.value)
  .sort((a,b) => b.created_at - a.created_at || b.id - a.id));
const status = ref("all"), employee = ref("all");
const owners = computed(() => [...new Set(tasks.value.map(t => t.employee_key))]);
const employeeName = key => state.value.employees.find(e => e.key === key)?.name || key;
const visible = computed(() => tasks.value.filter(t => (status.value === "all" || taskStage(t) === status.value)
  && (employee.value === "all" || t.employee_key === employee.value)));
watch(id, () => {status.value = "all"; employee.value = "all";}, {immediate: true});
</script>
<template>
  <div class="ap-back"><a href="?menu=resources" @click.exact.prevent="navigate({menu:'resources'})">← 店铺列表</a></div>
  <section class="ap-panel shop-details">
    <div class="ap-panelhead">
      <div><h1>{{ shop?.name || '店铺 ' + id }}</h1><p class="ap-muted">店铺 ID {{ id }}</p></div>
      <button class="ap-btn" :disabled="accountLoading" @click="loadAccounts(true)">{{ accountLoading ? '读取中…' : '刷新店铺信息' }}</button>
    </div>
    <p v-if="accountError" class="ap-issue" role="alert">{{ accountError }}{{ accountOverview ? ' 当前显示上次读取的店铺信息。' : '' }}</p>
    <p v-else-if="accountLoading && !shop" class="ap-muted" role="status">正在读取店铺信息…</p>
    <p v-else-if="!shop" class="ap-muted">当前账户未返回此店铺，以下任务仍按店铺 ID 展示。可刷新店铺信息或检查连接账户。</p>
    <dl v-if="shop" class="shop-meta">
      <div><dt>店铺来源</dt><dd>{{ shop.provider === 'ziniao' ? '紫鸟' : '未标注' }}</dd></div>
      <div><dt>平台</dt><dd>{{ shop.platform }}</dd></div>
      <div><dt>店铺账号</dt><dd>{{ shop.account || '未提供' }}</dd></div>
      <div><dt>有效状态</dt><dd>{{ shop.expired === true ? '已过期' : shop.expired === false ? '未过期' : '待核验' }}</dd></div>
      <div><dt>窗口状态</dt><dd>{{ shop.running === true ? '已打开' : shop.running === false ? '已关闭' : '待核验' }}</dd></div>
    </dl>
    <p v-if="accountOverview?.window_error" class="ap-issue" role="status">{{ accountOverview.window_error }}</p>
  </section>
  <section class="ap-panel">
    <div class="ap-panelhead"><div><h2>关联任务</h2><p>共 {{ tasks.length }} 项 · 汇总所有员工当前关联此店铺的任务</p></div></div>
    <div v-if="tasks.length" class="shop-task-filters">
      <label>任务状态<select v-model="status"><option value="all">全部状态</option><option v-for="(label,key) in stages" :key="key" :value="key">{{ label }}</option></select></label>
      <label>所属员工<select v-model="employee"><option value="all">全部员工</option><option v-for="key in owners" :key="key" :value="key">{{ employeeName(key) }}</option></select></label>
      <span class="ap-muted">{{ visible.length }} 项任务</span>
    </div>
    <div v-if="visible.length" class="shop-task-table">
      <table><thead><tr><th>任务</th><th>所属员工</th><th>状态</th><th>执行次数</th><th>最近执行</th></tr></thead>
        <tbody><tr v-for="task in visible" :key="task.id">
          <td><a :href="routeHref(taskRoute(task))" @click.exact.prevent="navigate(taskRoute(task))">{{ task.name }}</a><small>任务 #{{ task.id }}</small></td>
          <td>{{ employeeName(task.employee_key) }}</td>
          <td><span :class="['ap-badge',taskStage(task)]">{{ taskLabel(task) }}</span></td>
          <td>{{ attempts(state,task).length }} 次</td><td>{{ stamp(attempts(state,task)[0]?.started_at) }}</td>
        </tr></tbody>
      </table>
    </div>
    <div v-else class="ap-empty">
      <template v-if="tasks.length">没有符合筛选条件的任务。<button class="ap-link" @click="status='all';employee='all'">清除筛选</button></template>
      <template v-else>此店铺尚未关联任务。在员工任务的新增或编辑页面，选择「关联店铺」即可建立关联。
        <button class="ap-link" @click="navigate({menu:'employees'})">前往员工任务</button>
      </template>
    </div>
  </section>
</template>
<style scoped>
.shop-meta {display:flex;gap:24px 40px;flex-wrap:wrap;border-top:1px solid var(--ap-line);padding-top:18px;margin:18px 0 0}
.shop-meta dt {color:var(--ap-muted);font-size:12px;margin-bottom:6px}
.shop-meta dd {margin:0;overflow-wrap:anywhere}
.shop-task-filters {display:flex;gap:16px;align-items:end;flex-wrap:wrap;margin-bottom:18px}
.shop-task-table {overflow-x:auto}
.shop-task-table table {min-width:600px}
.shop-task-table small {display:block;color:var(--ap-muted);margin-top:5px;font-size:12px}
.ap-empty .ap-link {display:block;margin:12px auto 0}
</style>
