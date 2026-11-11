<script setup>
import { inject, reactive, ref } from "vue";
import { request } from "../api/platform";
const { state, refresh } = inject("workbench");
const current = state.value.settings?.runtime?.timing;
const values = reactive({ ...current });
const busy = ref(false), message = ref(""), failed = ref(false);
const fields = [
  ["discovery_scan_seconds", "本机紫鸟端口枚举超时", 1, 300, "下次检测请求提交时冻结。超时保留扫描命令的原始异常。"],
  ["discovery_probe_seconds", "单个 WebDriver 端口探测超时", 0.1, 60, "下次检测请求提交时冻结。每个端口的探测错误分别记录。"],
  ["shutdown_wait_seconds", "停止服务等待时长", 1, 86400, "本次停止开始时读取。到期后按下方策略处理；不包含后续窗口清理耗时。"],
  ["task_timeout_seconds", "新任务默认执行上限", 1, 604800, "仅用于新建且未指定时限的任务。现有任务在任务编辑中单独调整；正在执行的任务不变。"],
  ["window_lease_seconds", "窗口最长占用时间", 1, 604800, "新取得的窗口生效，已借出窗口的到期时间不变。到期会停止所属执行并回收窗口。"],
  ["retry_delay_seconds", "失败重试等待间隔", 0.1, 86400, "新根请求提交时冻结，父子操作沿用同一间隔。已提交请求不变。"],
  ["cli_timeout_seconds", "紫鸟 CLI 单次调用超时", 1, 3600, "下一次 CLI 调用生效。超时会中止调用并记录异常。"],
  ["api_action_timeout_seconds", "工作台操作接口等待上限", 1, 86400, "下一次操作请求生效。限制提交入口的响应等待；外部工作返回操作 ID 后由页面查询实际结果。"],
  ["webdriver_timeout_seconds", "紫鸟 WebDriver HTTP 超时", 1, 3600, "下一次 HTTP 调用生效，限制连接和读取等待。"],
  ["codex_timeout_seconds", "Codex 单次调用上限", 1, 86400, "下一次 Codex 工具调用生效。超时会停止整个进程树并保留已收到的输出。"],
];
async function save() {
  busy.value = true; message.value = ""; failed.value = false;
  try {
    await request("action", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...values, action: "save_timing_settings", token: state.value.panel.token }) });
    message.value = "时间配置已保存。各项按下方说明生效，服务重启后保留。";
    await refresh();
  } catch (e) { failed.value = true; message.value = e.message; }
  finally { busy.value = false; }
}
</script>
<template>
  <section class="ap-panel timing-panel">
    <h2>运行时限与停止服务</h2>
    <p>时间统一以秒为单位。停止服务时不再派发新任务，已有执行可继续申请窗口，日志和进度保持可查看。</p>
    <p v-if="!current" role="alert">当前后端尚不支持时间配置，请重启后端后刷新页面。</p>
    <form @submit.prevent="save">
      <fieldset :disabled="busy || !current || state.draining">
        <label>停止服务等待到期后
          <select v-model="values.shutdown_timeout_action">
            <option value="wait">继续等待已有执行结束（默认）</option>
            <option value="cancel">取消运行中的执行，停止脚本并清理窗口</option>
          </select>
        </label>
        <p class="ap-muted">继续等待模式到期时记录提醒，不因停止等待时长而取消任务。任务自身执行上限和窗口占用上限仍然有效。等待模式下暂停的执行继续等待人工处理；到期取消模式会取消并收尾。</p>
        <label v-for="[key, label, min, max, help] in fields" :key="key">{{ label }}（秒）
          <input v-model.number="values[key]" type="number" :min="min" :max="max" step="any" required />
          <small>{{ help }}</small>
        </label>
        <button class="ap-btn primary" type="submit">{{ busy ? '保存中…' : '保存时间配置' }}</button>
      </fieldset>
      <p v-if="message" :role="failed ? 'alert' : 'status'">{{ message }}</p>
    </form>
  </section>
</template>
<style scoped>
.timing-panel {max-width:760px}fieldset {border:0;padding:0;margin:20px 0;display:grid;gap:18px;min-width:0}label {display:grid;gap:8px;font-size:14px}input,select {padding:9px;font:inherit;border:1px solid var(--ap-line);border-radius:5px;background:var(--ap-panel);color:var(--ap-text);width:100%;box-sizing:border-box}small {line-height:1.6;color:var(--ap-muted)}button {justify-self:start}[role=alert] {color:var(--ap-red)}
</style>
