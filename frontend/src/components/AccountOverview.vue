<script setup>
import { computed, inject, onMounted, ref, watch } from "vue";
import { stamp, taskShopId, shopRoute, routeHref } from "../api/platform";
const { state, navigate, accountOverview: overview, accountLoading: loading,
  accountError: error, loadAccounts } = inject("workbench");
const taskCounts = computed(() => {
  const counts = new Map();
  for (const task of state.value.tasks) {
    const id = taskShopId(task);
    if (id) counts.set(id, (counts.get(id) || 0) + 1);
  }
  return counts;
});
const query = ref(""), filter = ref("all"), platform = ref("all"), page = ref(1);
const shops = computed(() => overview.value?.shops || []);
const platforms = computed(() => [...new Set(shops.value.map(s => s.platform))].sort());
const filtered = computed(() => {
  const text = query.value.trim().toLocaleLowerCase();
  return shops.value.filter(shop =>
    (platform.value === "all" || shop.platform === platform.value) &&
    (filter.value === "all" || (filter.value === "running" ? shop.running === true : shop.expired === true)) &&
    [shop.name, shop.account, shop.id].some(value => String(value).toLocaleLowerCase().includes(text)))
    .sort((a, b) => Number(b.running === true) - Number(a.running === true));
});
function selectSummary(status) {
  query.value = "";
  platform.value = "all";
  filter.value = status;
  page.value = 1;
}
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / 20)));
watch([query, filter, platform], () => { page.value = 1; });
watch(pages, value => { page.value = Math.min(value, page.value); });
onMounted(() => loadAccounts());
</script>
<template>
  <section class="ap-panel account-overview">
    <div class="ap-panelhead">
      <div><h2>我的紫鸟账户</h2><p class="ap-muted">店铺来源：紫鸟</p>
        <p v-if="overview">{{ overview.account.company }} · {{ overview.account.username }}</p>
      </div>
      <div class="account-actions">
        <button class="ap-link" @click="navigate({menu:'config'})">连接设置</button>
        <button class="ap-btn" :disabled="loading" @click="loadAccounts(true)">{{ loading ? '读取中…' : '刷新账户' }}</button>
      </div>
    </div>
    <p v-if="error" role="alert" class="account-error">{{ error }}<template v-if="overview"> 当前显示上次读取的数据。</template></p>
    <p v-if="loading && !overview" role="status" class="ap-muted">正在从紫鸟读取可访问店铺和运行窗口…</p>
    <template v-if="overview">
      <div class="account-stats" role="group" aria-label="按账户汇总筛选">
        <button type="button" :aria-pressed="filter === 'all'" @click="selectSummary('all')"><strong>{{ shops.length }}</strong><span>可访问店铺</span></button>
        <button type="button" :aria-pressed="filter === 'running'" @click="selectSummary('running')"><strong>{{ shops.filter(s => s.running === true).length }}{{ overview.window_error ? '（已确认）' : '' }}</strong><span>窗口已打开</span></button>
        <button type="button" :aria-pressed="filter === 'expired'" @click="selectSummary('expired')"><strong>{{ shops.filter(s => s.expired === true).length }}</strong><span>已过期店铺</span></button>
      </div>
      <p v-if="overview.window_error" role="status" class="account-error">{{ overview.window_error }}</p>
      <div class="account-filters">
        <input class="work-search" type="search" v-model="query" placeholder="搜索店铺、店铺账号或 ID" aria-label="搜索店铺" />
        <label>平台<select v-model="platform"><option value="all">全部平台</option><option v-for="name in platforms" :key="name">{{ name }}</option></select></label>
        <label>状态<select v-model="filter"><option value="all">全部店铺</option><option value="running">窗口已打开</option><option value="expired">已过期</option></select></label>
      </div>
      <div v-if="filtered.length" class="account-table-wrap">
        <table class="account-table">
          <thead><tr><th>店铺</th><th>平台 / 店铺账号</th><th>有效状态</th><th>窗口状态</th><th>关联任务</th></tr></thead>
          <tbody><tr v-for="shop in filtered.slice((page-1)*20,page*20)" :key="shop.id">
            <td><a :href="routeHref(shopRoute(shop.id))" @click.exact.prevent="navigate(shopRoute(shop.id))"><strong>{{ shop.name }}</strong></a><small v-if="shop.task_authorized">已授权工作台任务</small><small v-if="shop.id">ID {{ shop.id }}</small></td>
            <td>{{ shop.platform }}<small>{{ shop.account || '未提供店铺账号' }}</small></td>
            <td><span :class="['ap-badge', shop.expired === true ? 'failed' : '']">{{ shop.expired === true ? '已过期' : shop.expired === false ? '未过期' : '待核验' }}</span></td>
            <td><span :class="['ap-badge', shop.running === true ? 'running' : '']">{{ shop.running === true ? '已打开' : shop.running === false ? '已关闭' : '待核验' }}</span></td>
            <td><a :href="routeHref(shopRoute(shop.id))" @click.exact.prevent="navigate(shopRoute(shop.id))">{{ taskCounts.get(String(shop.id)) || 0 }} 项任务</a></td>
          </tr></tbody>
        </table>
      </div>
      <div v-else class="ap-empty">{{ shops.length ? '没有符合条件的店铺' : '当前账号未返回可访问店铺' }}
        <button v-if="shops.length" class="ap-link" @click="query='';platform='all';filter='all'">清除筛选</button>
      </div>
      <div class="account-pages">
        <span class="ap-muted">{{ filtered.length }} 家店铺 · 已打开优先 · 更新于 {{ stamp(overview.fetched_at) }}</span>
        <div v-if="pages > 1" class="account-actions">
          <button class="ap-btn" :disabled="page === 1" @click="page--">上一页</button>
          <span>{{ page }} / {{ pages }}</span>
          <button class="ap-btn" :disabled="page === pages" @click="page++">下一页</button>
        </div>
      </div>
    </template>
  </section>
</template>
<style scoped>
.account-actions,.account-filters,.account-pages {display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.account-filters {margin:18px 0;align-items:end}
.account-stats {display:flex;gap:12px;padding:16px 0;border-top:1px solid var(--ap-line);border-bottom:1px solid var(--ap-line);flex-wrap:wrap}
.account-stats button {display:grid;gap:5px;min-width:110px;padding:12px 16px;text-align:left;border:1px solid transparent;border-radius:7px;background:transparent}
.account-stats button:hover {background:var(--ap-bg);border-color:var(--ap-line)}
.account-stats button[aria-pressed=true] {background:var(--ap-soft);border-color:var(--ap-accent)}
.account-stats strong {font-size:25px;line-height:1.2;font-weight:600}
.account-stats span {font-size:12px;color:var(--ap-muted)}
.account-error {color:var(--ap-red);padding:10px 0}
.account-pages {justify-content:space-between;margin-top:16px;font-size:12px}
.account-table-wrap {overflow-x:auto}
#agent-console-demo .account-table {min-width:680px}
#agent-console-demo .account-table th:nth-child(1) {width:35%}
#agent-console-demo .account-table th:nth-child(2) {width:30%}
#agent-console-demo .account-table small {display:block;color:var(--ap-muted);font-size:11px;overflow-wrap:anywhere;margin-top:4px}
</style>
