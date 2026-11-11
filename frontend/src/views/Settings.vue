<script setup>
import { inject, onMounted, ref } from "vue";
import QueueSettings from "../components/QueueSettings.vue";
import RetrySettings from "../components/RetrySettings.vue";
import TimingSettings from "../components/TimingSettings.vue";
import ToolSettings from "../components/ToolSettings.vue";
import { object, request } from "../api/platform";
const { state, openTask, navigate } = inject("workbench");
// Categories group independent policies; add future categories here.
const categories = { tools: '工具', queue: '统一执行控制', tasks: '任务配置', runtime: '时间与停止策略' };
const tab = ref("tools"),
  skills = ref({}),
  error = ref("");
const employeeName = (key) => state.value.employees?.find((employee) => employee.key === key)?.name || key;
const path = (t) => object(t.input_data).skill_path;
const schedule = (t) =>
  (object(t.sync_data).schedules || [])
    .map((p) => p.key + " · 每 " + p.interval_seconds + " 秒")
    .join("、") || "无";
async function loadSkills() {
  try {
    skills.value = await request("skills");
    error.value = "";
  } catch (e) {
    error.value = e.message;
  }
}
onMounted(loadSkills);
</script>
<template>
  <div class="ap-heading">
    <h1>配置</h1>

  </div>
  <div class="ap-tabs" style="margin-bottom: 18px">
    <button
      v-for="(label, key) in categories"
      :key="key"
      :aria-pressed="tab === key"
      @click="tab = key"
    >
      {{ label }}
    </button>
  </div>
  <ToolSettings v-if="tab === 'tools'" />
  <template v-else-if="tab === 'queue'"><QueueSettings /><RetrySettings /></template>
  <TimingSettings v-else-if="tab === 'runtime'" />
  <div v-else class="ap-config">
    <template v-if="tab === 'tasks'">
      <h2>任务运行信息</h2>
      <p v-if="error" role="alert">
        {{ error }} <button class="ap-link" @click="loadSkills">重试</button>
      </p>
      <div v-if="!state.tasks.length" class="ap-empty">创建任务后，这里会显示它的运行配置。 <button class="ap-link" @click="navigate({menu:'employees'})">前往员工目录</button></div>
      <section v-for="t in state.tasks" :key="t.id" class="ap-panel">
        <div class="ap-panelhead"><div><h2>{{ t.name }}</h2><p>{{ employeeName(t.employee_key) }} · 任务 #{{ t.id }}</p></div>
          <button class="ap-link" @click="openTask(t)">打开任务详情</button></div>
        <p>执行函数 · {{ t.handler || "尚未绑定" }}</p>
        <p class="ap-muted">{{ path(t) || "未配置 Skill" }}</p>
        <details>
          <summary>配置详情</summary>
          <pre>
员工目录：{{ employeeName(t.employee_key) }}
执行函数：{{ t.handler || "暂未绑定" }}
配置文件：{{ t.manifest_ref || "—" }}
执行上限：{{ t.timeout_seconds }} 秒
定时计划：{{ schedule(t) }}</pre>
        </details>
        <details v-if="path(t)" @toggle="$event.target.open && loadSkills()">
          <summary>Skill 原文</summary>
          <pre>{{ skills[path(t)] }}</pre>
        </details>
      </section></template
    >
  </div>
</template>
