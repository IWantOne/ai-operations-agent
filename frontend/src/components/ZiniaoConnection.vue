<script setup>
import { inject, ref, watch } from "vue";
import { request } from "../api/platform";
const { state, refresh, navigate } = inject("workbench");
const current = state.value.connection || {};
const mode = ref(current.mode || "cli");
const company = ref(current.company || "");
const username = ref(current.username || "");
const password = ref("");
const port = ref(current.port || "");
const detecting = ref(false);
const detection = ref("");
async function detectPort() {
  if (detecting.value) return;
  detecting.value = true;
  detection.value = "正在检测本机紫鸟接口…";
  try {
    const result = await request("action", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({action:"detect_webdriver", token:state.value.panel.token})
    });
    port.value = result.port;
    detection.value = "已检测到本机 WebDriver，端口已填写。";
  } catch(e) {
    detection.value = e.message;
  } finally { detecting.value = false; }
}
const busy = ref(false), message = ref(""), failed = ref(false);
watch(mode, value => {
  if (value === "webdriver" && !port.value) detectPort();
}, {immediate:true});
async function submit(save) {
  if (busy.value || detecting.value) return;
  if (mode.value === "webdriver" && !port.value) {
    await detectPort();
    if (!port.value) return;
  }
  busy.value = true;
  message.value = "";
  failed.value = false;
  try {
    await request("action", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({action:save ? "save_connection" : "verify_connection",
        token:state.value.panel.token, mode:mode.value, company:company.value,
        username:username.value, password:password.value, port:port.value})
    });
    if (save) {
      password.value = "";
      await refresh();
      message.value = "连接已保存，下次店铺任务将使用此连接。";
    } else {
      message.value = "账号验证通过，已找到当前服务授权的店铺。";
    }
  } catch(e) {
    failed.value = true;
    message.value = e.message;
  } finally { busy.value = false; }
}
</script>
<template>
  <section class="ap-panel connection-panel">
    <div class="ap-panelhead"><div><h2>紫鸟连接</h2>
      <p>{{ state.connection?.mode === 'webdriver' ? '已保存 WebDriver · 本机端口 ' + state.connection.port : state.connection ? '使用本机紫鸟 CLI' : '尚未载入连接设置' }}</p></div>
      <span class="ap-badge">{{ state.connection?.mode === 'webdriver' ? '当前使用 WebDriver' : state.connection ? '当前使用 CLI' : '当前服务不支持配置' }}</span>
    </div>
    <p v-if="!state.connection" class="ap-muted">当前服务尚未载入连接设置。请停止服务，再运行项目的 deploy/start.ps1，刷新此页即可配置。</p>
    <form @submit.prevent="submit(true)" @input="message = ''">
      <fieldset :disabled="busy || !state.connection">
        <label>连接方式<select v-model="mode" @change="password = ''; message = ''">
          <option value="cli">紫鸟 CLI · 使用本机应用</option>
          <option value="webdriver">紫鸟 WebDriver · 使用账号密码</option>
        </select></label>
        <template v-if="mode === 'webdriver'">
          <label>公司名称<input v-model.trim="company" required /></label>
          <label>紫鸟账号<input v-model.trim="username" required autocomplete="off" /></label>
          <label>密码<input v-model="password" type="password" required autocomplete="new-password" /></label>
          <div class="port-detection">
            <p role="status">{{ detection || (port ? '已保存本机端口 ' + port : '等待检测本机 WebDriver') }}</p>
            <button type="button" class="ap-btn" :disabled="detecting" @click="detectPort">{{ detecting ? '检测中…' : '重新检测' }}</button>
          </div>
          <details><summary>高级设置</summary>
            <label>本机 WebDriver 端口<input v-model.number="port" type="number" min="1" max="65535" placeholder="自动检测" @input="detection = ''" /></label>
          </details>
          <p class="ap-muted">验证账号会读取授权店铺列表。保存后，后续任务将使用此连接。</p>
        </template>
        <p v-else class="ap-muted">使用本机紫鸟 CLI 当前应用的 API Key。在本机终端运行 <code>ziniao-cli config init</code> 设置应用，运行 <code>ziniao-cli doctor</code> 检查连接。</p>
        <div class="connection-actions">
          <button v-if="mode === 'webdriver'" type="button" class="ap-btn"  :disabled="detecting" @click="submit(false)">验证账号</button>
          <button type="submit" class="ap-btn primary" :disabled="detecting || (mode === 'cli' && state.connection?.mode === 'cli')">保存并使用</button>
        </div>
      </fieldset>
      <p v-if="busy" role="status">正在检查连接…</p>
      <button v-if="state.connection?.mode === 'webdriver'" type="button" class="ap-link" @click="navigate({menu:'resources'})">查看账户与店铺</button>
      <p v-if="message" :role="failed ? 'alert' : 'status'">{{ message }}</p>
    </form>
  </section>
</template>
<style scoped>
.connection-panel {width:min(100%,660px)}
fieldset {padding:0;border:none;display:grid;gap:14px;margin:0}
#agent-console-demo fieldset label {font-size:13px}
input,select {width:100%;font:inherit;padding:8px;border-radius:5px;border:1px solid var(--ap-line);background:var(--ap-panel);color:var(--ap-text)}
.port-detection {display:flex;align-items:center;gap:12px;font-size:13px}
summary {cursor:pointer;margin-bottom:8px}
.connection-actions {display:flex;gap:10px}
form>p {padding-top:12px}
[role=alert] {color:var(--ap-red)}
</style>
