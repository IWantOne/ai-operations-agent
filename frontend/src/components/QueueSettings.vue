<script setup>
import { inject, reactive, ref } from "vue";
import { request } from "../api/platform";
const { state, refresh } = inject("workbench");
const values = reactive({...state.value.settings.queue});
const labels = {tasks:"同时执行的任务", ziniao:"普通紫鸟操作", operations:"脚本与工具操作", control:"保留的窗口清理与核验", commands:"保留的取消命令", windows:"窗口总占用上限", control_retries:"每项清理／核验的重试预算"};
const message = ref(""), busy = ref(false);
async function save() {
  busy.value = true;
  try {
    await request("action", {method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({...values, action:"save_queue_settings", token:state.value.panel.token})});
    await refresh(); message.value = "已保存。容量在下一次派发时生效；降低上限不会强停已运行操作。";
  } catch(e) { message.value=e.message; } finally { busy.value=false; }
}
</script>
<template>
  <section class="ap-panel">
    <h2>统一队列容量</h2>
    <p class="ap-muted">任务等待窗口或工具时保留任务名额；子操作使用独立名额。清理与取消始终保留容量。</p>
    <form @submit.prevent="save">
      <label v-for="(label,key) in labels" :key="key">{{ label }}
        <input type="number" v-model.number="values[key]" :min="key==='control_retries'?0:1" max="100" step="1" required />
      </label>
      <p class="ap-muted">控制预算仅用于可安全重做的清理／核验，不会重跑任务。窗口占用包括未取得关闭确认的窗口。</p>
      <button class="ap-btn primary" :disabled="busy">保存容量</button>
      <p role="status">{{ message }}</p>
    </form>
  </section>
</template>
<style scoped>
form {display:grid;gap:12px;max-width:560px} label {display:flex;justify-content:space-between;gap:16px} input {width:90px}
</style>
