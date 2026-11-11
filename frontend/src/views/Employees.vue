<script setup>
import { computed, inject, ref, watch } from "vue";
import { attempts, shop, taskStage, taskLabel, taskShopId } from "../api/platform";
import ShopLink from "../components/ShopLink.vue";
import TaskDetail from "../components/TaskDetail.vue";
import ManagerDialog from "../components/ManagerDialog.vue";
const { state, route, navigate, accountOverview } = inject("workbench");
const shopName = (id) => id === "无店铺" ? "未关联店铺" :
  accountOverview.value?.shops.find(s => String(s.id) === String(id))?.name || id;
const employees = computed(() => state.value.employees || []);
const query = ref("");
const directory = computed(() => {
  const term = query.value.trim().toLocaleLowerCase();
  return employees.value.filter(entry => [entry.name, entry.description, entry.key]
    .some(value => String(value || "").toLocaleLowerCase().includes(term)));
});
const employee = (key) => employees.value.find((entry) => entry.key === key);
const editor = ref(null);
function edit(action, record) { editor.value = {action, record}; }
function saved(result) {
  const action = editor.value.action;
  const taskId = result.id || editor.value.record.id;
  editor.value = null;
  if (action === "create_task" || action === "edit_task") {
    openOwner(owner.value, {task:taskId, filter:"all"});
    defaultOpen();
  }
}
const owner = computed(() => route.value.owner);
const owned = (key) => state.value.tasks.filter((t) => t.employee_key === key);
const count = (list, status) =>
  list.filter((t) => taskStage(t) === status).length;
function day(offset) {
  const date = new Date();
  date.setDate(date.getDate() + offset);
  return date.toDateString();
}
const yesterday = (list) =>
  list.filter(
    (t) =>
      t.board_column !== "done" &&
      new Date(t.created_at * 1000).toDateString() === day(-1),
  ).length;
const filter = computed(() => route.value.filter || "incomplete");
const date = computed(() => route.value.date || "all");
const store = computed(() => route.value.store || "all");
const advanced = ref(false);
function changeFilters(patch) {
  const params = { ...route.value, ...patch };
  delete params.task;
  for (const key of ["date", "store"]) {
    if (params[key] === "all") delete params[key];
  }
  navigate(params);
}
function showAll() {
  changeFilters({filter: "all", date: "all", store: "all"});
}
const rank = { failed: 0, queued: 1, running: 2, done: 3 };
const visible = computed(() =>
  owned(owner.value)
    .filter(
      (t) =>
        (filter.value === "all" ||
          (t.board_column === "done") === (filter.value === "done")) &&
        (store.value === "all" || store.value === shop(t)) &&
        (date.value === "all" ||
          new Date(t.created_at * 1000).toDateString() ===
            day(date.value === "today" ? 0 : -1)),
    )
    .sort(
      (a, b) =>
        rank[a.board_column] - rank[b.board_column] ||
        a.created_at - b.created_at ||
        a.id - b.id,
    ),
);
const groups = computed(() => [...new Set(visible.value.map(shop))]);
const openShops = ref(new Set()),
  openTasks = ref(new Set());
function defaultOpen() {
  const chosen =
    visible.value.find((t) => String(t.id) === route.value.task) ||
    visible.value[0];
  openShops.value = new Set(chosen ? [shop(chosen)] : []);
  openTasks.value = new Set(chosen ? [chosen.id] : []);
}
watch(
  route,
  (current, previous) => {
    if (current.owner !== previous?.owner) advanced.value = false;
    defaultOpen();
  },
  { immediate: true },
);

function toggle(set, key) {
  set.has(key) ? set.delete(key) : set.add(key);
}
const openOwner = (key, other = {}) =>
  navigate({ menu: "employees", owner: key, ...other });
</script>
<template>
  <template v-if="!owner || !employee(owner)">
    <div class="ap-heading">
      <h1>员工</h1>
      <div class="manage-actions"><span class="ap-muted">{{ employees.length }} 位员工</span>
        <button class="ap-btn ap-create" @click="edit('create_employee', {})">新增员工</button>
      </div>
    </div>
    <input v-if="employees.length" v-model="query" type="search" class="work-search" aria-label="搜索员工" placeholder="搜索员工姓名或职责" />
    <div class="ap-cards">
      <section v-for="{key, name, description} in directory" :key="key" class="ap-person">
        <div class="ap-personhead">
          <div class="ap-avatar">{{ name.slice(0, 1) }}</div>
          <div>
            <h2>{{ name }}</h2>
            <p v-if="description">{{ description }}</p>
          </div>
        </div>
        <div class="ap-current">
          <small>当前工作</small
          >{{
            count(owned(key), "running")
              ? count(owned(key), "running") +
                " 项执行中 · " +
                new Set(
                  owned(key)
                    .filter(
                      (t) =>
                        t.board_column === "running" && shop(t) !== "无店铺",
                    )
                    .map(shop),
                ).size +
                " 家店铺"
              : "暂无执行"
          }}
        </div>
        <div class="ap-counts">
          <span
            ><b>{{ count(owned(key), "running") }}</b
            >正在执行</span
          ><span
            ><b>{{ count(owned(key), "failed") }}</b
            >待跟进</span
          ><span
            ><b>{{ count(owned(key), "queued") }}</b
            >待执行</span
          >
          <span v-if="count(owned(key), 'inactive')"><b>{{ count(owned(key), "inactive") }}</b>未就绪</span>
        </div>
        <div v-if="yesterday(owned(key))" class="ap-follow">
          昨日未完成 {{ yesterday(owned(key)) }} 项<br /><button
            class="ap-link"
            @click="openOwner(key, { date: 'yesterday' })"
          >
            查看昨日未完成 →
          </button>
        </div>
        <p v-else class="ap-muted" style="margin-bottom: 19px">
          {{ count(owned(key), "done") }} 项工作已完成。
        </p>
        <div class="ap-cardfoot">
          <div class="manage-actions"><button class="ap-link" @click="edit('edit_employee', employee(key))">编辑</button>
            <button class="ap-link remove" @click="edit('delete_employee', employee(key))">删除</button>
            <span class="ap-muted">{{ owned(key).length }} 项工作</span></div
          ><button class="ap-link" @click="openOwner(key, { filter: 'all' })">查看工作 →</button>
        </div>
      </section>
      <div v-if="employees.length && !directory.length" class="ap-empty">没有找到匹配的员工 <button class="ap-link" @click="query = ''">清除搜索</button></div>
      <div v-if="!employees.length" class="ap-empty">点击「新增员工」建立第一个员工档案。</div>
    </div>
  </template>
  <template v-else>
    <div class="ap-back">
      <button class="ap-link" @click="navigate({ menu: 'employees' })">
        ← 员工列表
      </button>
    </div>
    <div class="ap-heading">
      <div class="ap-title">
        <div class="ap-avatar" aria-hidden="true">{{ employee(owner).name.slice(0, 1) }}</div>
        <div><h1>{{ employee(owner).name }}的任务</h1>
          <p>共 {{ owned(owner).length }} 项任务 · 已完成 {{ count(owned(owner), "done") }} 项</p>
        </div>
      </div>
      <div class="manage-actions">
        <button class="ap-btn ap-create" @click="edit('create_task', {employee_key: owner})">新增任务</button>
      </div>
    </div>
    <div class="ap-compactfilters">
      <div class="ap-tabs" aria-label="工作状态">
        <button
          v-for="(name, key) in {
            incomplete: '未完成',
            all: '全部',
            done: '已完成',
          }"
          :key="key"
          :aria-pressed="filter === key"
          @click="changeFilters({filter:key})"
        >
          {{ name }}
        </button>
      </div>
      <button class="ap-btn" :aria-expanded="advanced" @click="advanced = !advanced">筛选</button>
    </div>
    <div v-if="advanced" class="ap-advanced">
      <label
        >店铺<select :value="store" @change="changeFilters({store:$event.target.value})">
          <option value="all">全部店铺</option>
          <option v-for="s in new Set(owned(owner).map(shop))" :key="s" :value="s">
            {{ shopName(s) }}
          </option>
        </select></label
      ><label
        >任务创建日期<select :value="date" @change="changeFilters({date:$event.target.value})">
          <option value="all">不限</option>
          <option value="today">今天</option>
          <option value="yesterday">昨天</option>
        </select></label
      >
    </div>
    <div v-if="store !== 'all' || date !== 'all'" class="ap-filter-note">
      <span>{{ [store !== 'all' ? store : '', date === 'today' ? '今天创建' : date === 'yesterday' ? '昨天创建' : ''].filter(Boolean).join(' · ') }} · {{ visible.length }} 项任务</span>
      <button class="ap-link" @click="changeFilters({store:'all', date:'all'})">清除条件</button>
    </div>
    <div class="ap-shopcards">
      <section v-for="s in groups" :key="s" class="ap-shopcard">
        <button
          class="ap-shophead"
          :aria-expanded="openShops.has(s)"
          @click="toggle(openShops, s)"
        >
          <span class="ap-shopname">{{ shopName(s) }}</span
          ><span class="ap-shopcount"
            >{{ visible.filter((t) => shop(t) === s).length }} 项任务</span
          ><span class="ap-shopcue">{{
            openShops.has(s) ? "收起 ⌃" : "展开 ⌄"
          }}</span>
        </button>
        <div v-if="openShops.has(s)" class="ap-shoptasks">
          <article
            v-for="t in visible.filter((t) => shop(t) === s)"
            :key="t.id"
            class="ap-inlinetask"
            :data-task="t.id"
          >
            <button
              class="ap-taskhead"
              :aria-expanded="openTasks.has(t.id)"
              @click="toggle(openTasks, t.id)"
            >
              <span class="ap-taskname"
                ><strong>{{ t.name }}</strong
                ><small>任务 #{{ t.id }}</small></span
              ><span class="ap-taskstatus"
                ><span :class="['ap-badge', taskStage(t)]">{{
                  taskLabel(t)
                }}</span></span
              ><span class="ap-taskattempt"
                >{{ attempts(state, t).length }} 次执行</span
              ><span class="ap-taskcue">{{
                openTasks.has(t.id) ? "收起" : "查看"
              }}</span>
            </button>
            <div v-if="openTasks.has(t.id)" class="manage-actions task-manage">
              <span class="task-shop">关联店铺：<ShopLink v-if="taskShopId(t)" :id="taskShopId(t)" /><span v-else class="ap-muted">未关联，可在编辑任务中选择</span></span>
              <button class="ap-link" @click="edit('edit_task', t)">编辑任务</button>
              <button class="ap-link remove" @click="edit('delete_task', t)">删除任务</button>
            </div>
            <div v-if="openTasks.has(t.id) && !t.handler" class="draft-guide">
              <strong>运行前需要绑定执行函数</strong>
              <p>{{ state.handlers?.length ? '打开「编辑任务」，选择执行函数并保存。' : '当前服务还没有可选的执行函数。请先让平台维护者注册函数，再到「编辑任务」中绑定。' }}</p>
            </div>
            <TaskDetail
              v-if="openTasks.has(t.id) && (t.handler || attempts(state, t).length ||
                state.requests.some(r => r.task_id === t.id && r.status === 'QUEUED'))"
              :task="t"
            />
          </article>
        </div>
      </section>
      <div v-if="!visible.length" class="ap-empty">
        <template v-if="owned(owner).length">没有符合当前条件的任务
          <button class="ap-link" @click="showAll">查看全部任务</button>
        </template>
        <template v-else>这位员工还没有任务，可点击「新增任务」创建。</template>
      </div>
    </div>
  </template>
  <ManagerDialog v-if="editor" :action="editor.action" :record="editor.record" @saved="saved" @close="editor = null" />
</template>

<style scoped>
.manage-actions {display:flex; align-items:center; gap:12px; flex-wrap:wrap}
.task-manage {justify-content:flex-end; padding:0 14px 8px}
.task-shop {margin-right:auto;font-size:13px;overflow-wrap:anywhere}
#agent-console-demo .ap-create {background:var(--ap-accent);color:var(--ap-panel);border-color:var(--ap-accent)}
#agent-console-demo .remove {color:var(--ap-red)}
.draft-guide {margin:12px 20px 16px; padding:14px 16px; background:var(--ap-soft); border-left:3px solid var(--ap-accent);border-radius:4px}
#agent-console-demo .draft-guide p {margin-top:4px;color:var(--ap-text);font-size:13px}
#agent-console-demo .task-manage {padding:8px 20px;border-bottom:1px solid var(--ap-line)}
#agent-console-demo .ap-empty .ap-link {display:block;margin:8px auto 0}
#agent-console-demo .ap-taskname strong {font-size:15px;overflow-wrap:anywhere}
</style>
