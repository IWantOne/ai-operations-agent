<script setup>
import { computed, onMounted, onUnmounted, provide, ref, watch } from "vue";
import Overview from "./views/Overview.vue";
import Employees from "./views/Employees.vue";
import ProgressBoard from "./views/ProgressBoard.vue";
import Resources from "./views/Resources.vue";
import Settings from "./views/Settings.vue";
import Logs from "./views/Logs.vue";
import { request, runAction } from "./api/platform";

const menus = {
  overview: ["工作总览", Overview],
  employees: ["员工", Employees],
  board: ["进度看板", ProgressBoard],
  resources: ["紫鸟资源", Resources],
  logs: ["日志", Logs],
  config: ["配置", Settings],
};
const navIcons = {
  overview: "M3 3h8v8H3z M15 3h6v5h-6z M3 15h8v6H3z M15 12h6v9h-6z",
  employees: "M16 20H2v-2c0-6 14-6 14 0z M13 7a4 4 0 1 1-8 0 4 4 0 1 1 8 0 M17 4a4 4 0 0 1 0 7 M18 14q4 0 4 5",
  board: "M3 4h18v16H3z M9 4v16 M15 4v16 M5 8h2 M11 12h2 M17 9h2",
  resources: "M2 4h20v14H2z M8 22h8 M12 18v4 M2 8h20",
  logs: "M5 3h14v18H5z M8 7h8 M8 12h8 M8 17h5",
  config: "M3 5h8m4 0h6 M3 12h2m4 0h12 M3 19h11m4 0h3 M11 2v6 M5 9v6 M14 16v6",
};
const readRoute = () =>
  Object.fromEntries(new URLSearchParams(location.search));
const route = ref(readRoute());
const menu = computed(() =>
  Object.hasOwn(menus, route.value.menu) ? route.value.menu : (route.value.owner ? "employees" : "overview"),
);
const state = ref(null),
  error = ref(""),
  notice = ref(""),
  busy = ref(false),
  updated = ref("");
const accountOverview = ref(null), accountLoading = ref(false), accountError = ref("");
let accountRequest, accountVersion = 0;
watch(() => JSON.stringify(state.value?.connection), () => {
  accountVersion++;
  accountOverview.value = null;
  accountError.value = "";
  accountLoading.value = false;
  accountRequest = null;
});
function loadAccounts(force = false) {
  if (accountRequest) return accountRequest;
  if (accountOverview.value && !force) return Promise.resolve();
  accountLoading.value = true;
  accountError.value = "";
  const version = accountVersion;
  accountRequest = request("action", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action: "account_overview", token: state.value.panel.token}),
  }).then(result => { if (version === accountVersion) accountOverview.value = result; })
    .catch(e => { if (version === accountVersion) accountError.value = e.message; })
    .finally(() => { if (version === accountVersion) {accountLoading.value = false; accountRequest = null;} });
  return accountRequest;
}
let sequence = 0,
  timer,
  stopped = false;
function navigate(params) {
  if (location.search === "?" + new URLSearchParams(params)) return;
  history.pushState(null, "", "?" + new URLSearchParams(params));
  route.value = readRoute();
}
function back() {
  route.value = readRoute();
}
function openTask(task) {
  navigate({
    menu: "employees",
    owner: task.employee_key,
    task: task.id,
    filter: "all",
  });
}
async function refresh() {
  const current = ++sequence;
  try {
    const data = await request("state");
    if (current !== sequence || stopped) return;
    state.value = data;
    updated.value = new Date().toLocaleTimeString("zh-CN");
    error.value = "";
  } catch (e) {
    if (current === sequence && !stopped)
      error.value = "读取平台状态失败：" + e.message;
  }
}
async function action(name, id, extra) {
  if (busy.value || stopped) return;
  busy.value = true;
  try {
    await runAction(name, id, state.value.panel.token, extra);
    if (name === "shutdown") {
      error.value = "";
      notice.value = "服务正在收尾，队列已保留。可继续查看日志和执行进度。";
      return;
    }
    notice.value = "操作已提交";
    await refresh();
  } catch (e) {
    notice.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function poll() {
  await refresh();
  if (!stopped) timer = setTimeout(poll, 2000);
}
onMounted(() => {
  poll();
  addEventListener("popstate", back);
});
onUnmounted(() => {
  stopped = true;
  clearTimeout(timer);
  removeEventListener("popstate", back);
});
provide("workbench", { state, route, navigate, openTask, action, busy, refresh,
  accountOverview, accountLoading, accountError, loadAccounts });
</script>
<template>
  <div id="agent-console-demo" aria-label="员工工作台">
    <header class="ap-header shell-nav">
      <strong class="brand"><svg viewBox="0 0 32 32" width="32" height="32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#9ce4c8"/><path d="M6 22 13 9h5l-7 13zm10 0 5-9 5 9z" fill="#143e37"/></svg> Agent 工作台</strong>
      <nav aria-label="主导航">
        <button
          v-for="([label], key) in menus"
          :key="key"
          :aria-current="menu === key ? 'page' : undefined"
          @click="navigate({ menu: key })"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="navIcons[key]" /></svg>
          {{ label }}
        </button>
      </nav>
      <span v-if="state?.connection" class="ap-demo">{{ state.connection.mode === 'webdriver' ? 'WebDriver · 本机端口 ' + state.connection.port : '紫鸟 CLI' }}</span>
    </header>
    <main class="ap-main">
      <p v-if="state?.fault" class="ap-issue" role="alert">完成记录写入失败，已停止新接单。仍可查看日志、取消执行及处理窗口。具体原因：{{ state.fault.error }}</p>
      <p v-if="state?.draining" class="ap-issue" role="status">服务正在收尾，已停止接收和派发新任务。已有执行按配置结束，期间可查看日志和进度。</p>
      <p v-if="error" class="sync-error" role="alert">{{ error }} {{ state ? "当前显示上次同步的数据。" : "" }}
        <button class="ap-btn" @click="refresh">重新读取</button>
      </p>
      <component :is="menus[menu][1]" v-if="state || menu === 'logs'" />
      <p v-else-if="!error">正在读取工作台…</p>
    </main>
    <div v-if="notice" class="ap-notice" role="status" @click="notice = ''">
      {{ notice }}
    </div>
    <footer>
      <time>最近同步 {{ updated || "—" }}</time
      ><button
        v-if="menu === 'config' && state?.panel.can_shutdown"
        class="ap-btn"
        :disabled="busy"
        @click="action('shutdown', 0)"
      >
        停止服务
      </button>
    </footer>
  </div>
</template>
<style>
:root {
  color-scheme: light dark;
}
body {
  margin: 0;
  padding: 1rem;
  background: Canvas;
}
#agent-console-demo :is(button, summary) {
  cursor: pointer;
}
#agent-console-demo footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
#agent-console-demo a {
  color: var(--ap-accent);
}
</style>
