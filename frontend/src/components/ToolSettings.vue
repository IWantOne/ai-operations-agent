<script setup>
import { inject, ref } from "vue";
import { request } from "../api/platform";

const { state, refresh } = inject("workbench");
const current = state.value.settings?.tools;
const command = ref(current?.codex_command ?? "");
const args = ref(current?.codex_args ?? "");
const timeout = ref(current?.codex_timeout_seconds ?? 600);
const busy = ref(false), message = ref(""), failed = ref(false);

async function save() {
  if (busy.value) return;
  message.value = "";
  failed.value = false;
  if (!Number.isFinite(Number(timeout.value)) || Number(timeout.value) < 1 || Number(timeout.value) > 86400) {
    failed.value = true;
    message.value = "单次调用上限必须为 1–86400 秒。";
    return;
  }
  busy.value = true;
  try {
    await request("action", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "save_tool_settings", token: state.value.panel.token,
        codex_command: command.value, codex_args: args.value,
        codex_timeout_seconds: Number(timeout.value) }),
    });
    message.value = "配置已保存，下次工具调用生效。";
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
  <section class="ap-panel tool-panel">
    <div class="ap-panelhead">
      <div><h2>Codex</h2>
        <p>把本机 codex-cli 当作工具调用，业务通过 <code>ctx.tool("codex", prompt=...)</code> 使用。</p></div>
      <span class="ap-badge">{{ current?.codex_command ? '自定义路径' : '使用 PATH 中的 codex' }}</span>
    </div>
    <p v-if="!current" role="alert">当前服务尚不支持工具配置，请重启后端服务后刷新页面。</p>
    <form @submit.prevent="save" @input="message = ''">
      <fieldset :disabled="busy || !current">
        <label>可执行文件路径
          <input v-model="command" placeholder="留空使用 PATH 中的 codex" />
        </label>
        <label>额外参数
          <input v-model="args" placeholder="例如 --skip-git-repo-check（非 git 目录）、-m 模型名" />
        </label>
        <label>单次调用上限（秒）
          <input v-model.number="timeout" type="number" min="1" max="86400" step="1" />
        </label>
        <p class="ap-muted">
          工具执行 <code>codex exec [额外参数] &lt;prompt&gt;</code>。本机装了 codex-cli 时可全部留空；
          非零退出会保留退出码和 stderr，超过上限会停止整个进程树。
        </p>
        <div><button type="submit" class="ap-btn primary">{{ busy ? '保存中…' : '保存配置' }}</button></div>
      </fieldset>
      <p v-if="message" :role="failed ? 'alert' : 'status'">{{ message }}</p>
    </form>
  </section>

  <section class="ap-panel tool-panel">
    <div class="ap-panelhead">
      <div><h2>智易飞</h2><p>业务文件传输与远端引用。</p></div>
      <span class="ap-badge">未接入</span>
    </div>
    <p class="ap-muted">接口协议尚未确认，本版不提供配置；接入时再补连接参数和文件引用。</p>
  </section>
</template>

<style scoped>
.tool-panel {width:min(100%,660px);margin-bottom:16px}
fieldset {padding:0;border:none;display:grid;gap:14px;margin:0;min-width:0}
label {display:grid;gap:8px;font-size:13px}
input {width:100%;box-sizing:border-box;font:inherit;padding:8px;border-radius:5px;border:1px solid var(--ap-line);background:var(--ap-panel);color:var(--ap-text)}
form>p {padding-top:12px}
[role=alert] {color:var(--ap-red)}
</style>
