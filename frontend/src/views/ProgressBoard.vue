<script setup>
import { computed, inject, ref } from "vue";
import { columns, shop, attempts, taskStage, taskLabel } from "../api/platform";
import TaskDetail from "../components/TaskDetail.vue";
const { state, openTask } = inject("workbench");
const selected = ref(null);
const owners = computed(() => state.value.employees || []);
const tasks = (owner, column) =>
  state.value.tasks.filter(
    (t) => t.employee_key === owner.key && (!column || taskStage(t) === column),
  );
const laneColumns = owner => tasks(owner, "inactive").length ? {...columns, inactive:"未就绪"} : columns;
const chosen = computed(() =>
  state.value.tasks.find((t) => t.id === selected.value),
);
</script>
<template>
  <div class="ap-heading">
    <h1>进度看板</h1>
    <span class="ap-muted"
      >{{ owners.length }} 位员工 · {{ state.tasks.length }} 项任务</span
    >
  </div>
  <div v-if="!owners.length" class="ap-empty">添加员工后，可以在这里查看每位员工的任务进度。</div>
  <div class="ap-board">
    <section v-for="owner in owners" :key="owner.key" class="ap-board-lane">
      <header class="ap-board-lanehead">
        <div class="ap-board-person">
          <span class="ap-board-avatar">{{ owner.name.slice(0, 1) }}</span>
          <div>
            <h2>{{ owner.name }}</h2>
            <span v-if="owner.description">{{ owner.description }}</span>
          </div>
        </div>
        <div class="ap-board-count">
          <span
            >完成
            <b
              >{{ tasks(owner, "done").length }}/{{ tasks(owner).length }}</b
            ></span
          ><span v-if="tasks(owner, 'failed').length" class="ap-board-follow"
            >跟进 {{ tasks(owner, "failed").length }}</span
          >
        </div>
      </header>
      <div class="ap-board-scroll">
        <div class="ap-board-grid" :style="{'--lane-count': Object.keys(laneColumns(owner)).length}">
          <section
            v-for="(label, key) in laneColumns(owner)"
            :key="key"
            :class="['ap-board-column', key]"
          >
            <h3>
              <span>{{ label }}</span
              ><b>{{ tasks(owner, key).length }}</b>
            </h3>
            <div class="ap-board-stack">
              <button
                v-for="t in tasks(owner, key)"
                :key="t.id"
                :data-task="t.id"
                :class="['ap-board-task', key]"
                :aria-expanded="selected === t.id"
                @click="selected = selected === t.id ? null : t.id"
              >
                <span class="ap-board-cardtop"
                  ><span>{{ shop(t) }}</span
                  ><small>{{
                    attempts(state, t).length
                      ? "第 " + attempts(state, t).length + " 次"
                      : "尚未执行"
                  }}</small></span
                ><strong>{{ t.name }}</strong
                ><span class="ap-board-progress">{{ taskLabel(t) }}</span>
              </button>
              <div v-if="!tasks(owner, key).length" class="ap-board-empty">
                —
              </div>
            </div>
          </section>
        </div>
      </div>
      <article
        v-if="chosen?.employee_key === owner.key"
        class="ap-board-detail"
        :data-task="chosen.id"
      >
        <div class="ap-board-detailhead">
          <div>
            <strong>{{ shop(chosen) }}</strong
            ><span>{{ chosen.name }}</span>
          </div>
          <div class="ap-board-detailactions">
            <button class="ap-link" @click="openTask(chosen)">打开任务详情</button
            ><button class="ap-link" @click="selected = null">收起</button>
          </div>
        </div>
        <p v-if="!chosen.handler" class="ap-empty">此任务尚未绑定执行函数，可在任务详情中查看配置要求。</p>
        <TaskDetail v-if="chosen.handler || attempts(state, chosen).length || state.requests.some(r => r.task_id === chosen.id && r.status === 'QUEUED')" :task="chosen" />
      </article>
    </section>
  </div>
</template>
