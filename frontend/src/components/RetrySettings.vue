<script setup>
import { inject, ref } from "vue";
import { request } from "../api/platform";

const { state, refresh } = inject("workbench");
const current = state.value.settings?.retry;
const enabled = ref(current?.enabled ?? false);
const maxRetries = ref(current?.total_retries ?? 3);
const busy = ref(false), message = ref(""), failed = ref(false);

async function save() {
  if (busy.value) return;
  message.value = "";
  failed.value = false;
  if (!Number.isInteger(maxRetries.value) || maxRetries.value < 1 || maxRetries.value > 100) {
    failed.value = true;
    message.value = "根请求总重试预算必须为 1 到 100 的整数。";
    return;
  }
  busy.value = true;
  try {
    await request("action", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "save_retry_settings", token: state.value.panel.token,
        enabled: enabled.value, total_retries: maxRetries.value }),
    });
    message.value = "配置已保存，对新提交的任务生效。";
    await refresh();
  } catch (e) {
    failed.value = true;
    message.value = e.message;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="ap-panel retry-panel">
    <div class="ap-panelhead"><div><h2>统一自动重试预算</h2>
      <p>任务及子操作共用一份根请求预算。</p></div>
      <span class="ap-badge">{{ state.settings?.retry?.enabled ? '已开启' : '已关闭' }}</span>
    </div>
    <p v-if="!current" role="alert">当前服务尚不支持重试配置，请重启后端服务后刷新页面。</p>
    <form @submit.prevent="save" @input="message = ''">
      <fieldset :disabled="busy || !current">
        <label class="toggle"><input v-model="enabled" type="checkbox" />启用自动失败重试</label>
        <label>根请求总重试预算
          <input v-model.number="maxRetries" type="number" min="1" max="100" step="1" required :disabled="!enabled" aria-describedby="retry-count-help" />
        </label>
        <p id="retry-count-help" class="ap-muted">不含首次执行。{{ enabled ? `所有父子操作合计最多自动重试 ${Number(maxRetries)} 次。` : '关闭时，任务失败后不会自动重试。' }}</p>
        <p class="ap-muted">整个任务仅在执行器明确声明 restart_safe 时允许重跑；未声明安全性的操作默认不重试。失败后的等待间隔在“时间与停止策略”中配置，仅重新执行已声明可安全重做的操作。超时、取消或资源状态不明时不会自动重试。</p>
        <p class="ap-muted">保存后立即用于新提交的任务，已提交任务保留原有重试次数。配置和已使用次数在服务重启后保留。</p>
        <div><button type="submit" class="ap-btn primary">{{ busy ? '保存中…' : '保存配置' }}</button></div>
      </fieldset>
      <p v-if="message" :role="failed ? 'alert' : 'status'">{{ message }}</p>
    </form>
  </section>
</template>

<style scoped>
.retry-panel {width:min(100%,660px)}
fieldset {padding:0;border:none;display:grid;gap:14px;margin:0;min-width:0}
label {display:grid;gap:8px;font-size:13px}
.toggle {display:flex;align-items:center;gap:8px}
input[type=number] {width:100%;box-sizing:border-box;font:inherit;padding:8px;border-radius:5px;border:1px solid var(--ap-line);background:var(--ap-panel);color:var(--ap-text)}
form>p {padding-top:12px}
[role=alert] {color:var(--ap-red)}
</style>
