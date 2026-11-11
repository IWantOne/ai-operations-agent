<script setup>
import { inject, reactive, ref } from "vue";
import { request } from "../api/platform";
import ZiniaoConnection from "./ZiniaoConnection.vue";

const { state, refresh } = inject("workbench");

const codex = state.value.settings?.tools;
const command = ref(codex?.codex_command ?? "");
const args = ref(codex?.codex_args ?? "");
const busy = ref(false), message = ref(""), failed = ref(false);

// 所有外部应用走同一个列表：飞书、领星、智易飞。认证方式随接入方固定，页面只填凭据。
const integrations = state.value.settings?.integrations || {};
const forms = reactive({});
const open = reactive({ codex: false });
for (const [key, value] of Object.entries(integrations)) {
  forms[key] = { ...value, app_secret: "", busy: false, message: "", failed: false };
  open[key] = false;
}
const authLabels = { token: "先换 token 再带 Bearer", headers: "App ID／Secret 放请求头", none: "不带认证" };

async function post(payload) {
  return request("action", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, token: state.value.panel.token }),
  });
}

async function saveCodex() {
  if (busy.value) return;
  message.value = "";
  failed.value = false;
  busy.value = true;
  try {
    await post({ action: "save_tool_settings", codex_command: command.value, codex_args: args.value });
    message.value = "配置已保存，下次工具调用立即生效。";
    await refresh();
  } catch (e) {
    failed.value = true;
    message.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function saveIntegration(key) {
  const form = forms[key];
  if (form.busy) return;
  form.message = "";
  form.failed = false;
  form.busy = true;
  try {
    await post({ action: "save_integration", provider: key,
                 transport: form.transport, base_url: form.base_url, app_id: form.app_id,
                 app_secret: form.app_secret, token_path: form.token_path,
                 token_field: form.token_field, mcp_command: form.mcp_command });
    form.app_secret = "";
    form.message = "配置已保存，下次调用立即生效。";
    await refresh();
  } catch (e) {
    form.failed = true;
    form.message = e.message;
  } finally {
    form.busy = false;
  }
}

async function testIntegration(key) {
  const form = forms[key];
  if (form.busy) return;
  form.message = "";
  form.failed = false;
  form.busy = true;
  try {
    const result = (await post({ action: "test_integration", provider: key })).integration || {};
    if (result.transport === "mcp") {
      form.message = `MCP 可用：${result.tools ?? 0} 个工具` +
        (Array.isArray(result.names) && result.names.length ? `（${result.names.join("、")}）` : "");
    } else if (result.stores !== undefined) {
      form.message = `连接成功：可访问店铺 ${result.stores ?? "未提供"} 家` +
        (Array.isArray(result.api_types) ? `（${result.api_types.join("、")}）` : "");
    } else if (result.auth === "token") {
      form.message = "认证成功，token 已获取。";
    } else {
      form.message = `连通，HTTP ${result.status ?? "未提供"}。`;
    }
  } catch (e) {
    form.failed = true;
    form.message = e.message;
  } finally {
    form.busy = false;
  }
}
</script>

<template>
  <div class="tool-grid">
  <ZiniaoConnection />
  <section class="ap-panel tool-panel">
    <div class="ap-panelhead" role="button" tabindex="0" :aria-expanded="open.codex"
         @click="open.codex = !open.codex" @keydown.enter.prevent="open.codex = !open.codex">
      <div><h2>Codex</h2>
        <p>把本机 codex-cli 当作工具调用，业务通过 <code>ctx.tool("codex", prompt=...)</code> 使用。</p></div>
      <span class="ap-badge">{{ codex?.codex_command ? '自定义路径' : '使用 PATH 中的 codex' }}</span>
      <span class="chev">{{ open.codex ? '▾' : '▸' }}</span>
    </div>
    <p v-if="!codex" role="alert">当前服务尚不支持工具配置，请重启后端服务后刷新页面。</p>
    <form v-show="open.codex" @submit.prevent="saveCodex" @input="message = ''">
      <fieldset :disabled="busy || !codex">
        <label>可执行文件路径
          <input v-model="command" placeholder="留空使用 PATH 中的 codex" />
        </label>
        <label>额外参数
          <input v-model="args" placeholder="例如 --skip-git-repo-check（非 git 目录）、-m 模型名" />
        </label>
        <p class="ap-muted">
          工具执行 <code>codex exec [额外参数] &lt;prompt&gt;</code>。本机装了 codex-cli 时可以全部留空；
          非零退出会保留退出码和 stderr。单次调用上限在「时间与停止策略」里配置。
        </p>
        <div><button type="submit" class="ap-btn primary">{{ busy ? '保存中…' : '保存配置' }}</button></div>
      </fieldset>
      <p v-if="message" :role="failed ? 'alert' : 'status'">{{ message }}</p>
    </form>
  </section>

  <section v-for="(form, key) in forms" :key="key" class="ap-panel tool-panel">
    <div class="ap-panelhead" role="button" tabindex="0" :aria-expanded="open[key]"
         @click="open[key] = !open[key]" @keydown.enter.prevent="open[key] = !open[key]">
      <div><h2>{{ form.label }}</h2>
        <p v-if="key === 'effiseller'">Amazon 原生 API 通道：店铺查询与 SP-API／Ads 请求透传。</p>
        <p v-else>外部应用接入，业务通过 <code>api.request</code> 或 <code>mcp.call</code> 使用。</p>
      </div>
      <span class="ap-badge">{{ form.secret_set ? '已配置凭据' : '未配置' }}</span>
      <span class="chev">{{ open[key] ? '▾' : '▸' }}</span>
    </div>
    <form v-show="open[key]" @submit.prevent="saveIntegration(key)" @input="form.message = ''">
      <fieldset :disabled="form.busy">
        <label v-if="form.transports.length > 1">传输方式
          <select v-model="form.transport">
            <option value="api">API（HTTP）</option>
            <option value="mcp">MCP（stdio）</option>
          </select>
        </label>
        <template v-if="form.transport === 'api'">
          <label>部署地址
            <input v-model="form.base_url" placeholder="https://..." />
          </label>
          <label>App ID
            <input v-model="form.app_id" placeholder="应用 App ID" />
          </label>
          <label>App Secret
            <input v-model="form.app_secret" type="password" autocomplete="new-password"
                   :placeholder="form.secret_set ? '已保存；留空表示不修改' : '应用 App Secret'" />
          </label>
          <template v-if="form.auth === 'token'">
            <label>获取 token 的路径
              <input v-model="form.token_path" placeholder="/open-apis/auth/v3/tenant_access_token/internal" />
            </label>
            <label>token 字段名
              <input v-model="form.token_field" placeholder="tenant_access_token" />
            </label>
          </template>
        </template>
        <template v-else>
          <label>启动命令
            <input v-model="form.mcp_command" placeholder='"C:\\path\\node.exe" server.js' />
          </label>
        </template>
        <p class="ap-muted">
          认证方式：{{ authLabels[form.auth] || form.auth }}（随接入方固定）。请求超时在「时间与停止策略」里配置。
          <template v-if="key === 'effiseller'">
            业务通过 <code>ctx.tool("amazon.stores")</code> 和
            <code>ctx.tool("amazon.request", sid=..., api_type="sp-api", method="GET", path="/sellers/v1/marketplaceParticipations")</code> 使用。
          </template>
          <template v-else>
            API：<code>ctx.tool("api.request", provider="{{ key }}", method="GET", path="/...")</code>；
            MCP：<code>ctx.tool("mcp.call", provider="{{ key }}", tool="...", arguments={})</code>。
          </template>
        </p>
        <div>
          <button type="submit" class="ap-btn primary">{{ form.busy ? '处理中…' : '保存配置' }}</button>
          <button type="button" class="ap-link" @click="testIntegration(key)">测试连接</button>
        </div>
      </fieldset>
      <p v-if="form.message" :role="form.failed ? 'alert' : 'status'">{{ form.message }}</p>
    </form>
  </section>
  </div>
</template>

<style scoped>
.tool-grid {display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;align-items:start}
.tool-panel {width:100%;margin:0}
.ap-panelhead {cursor:pointer;user-select:none}
.chev {margin-left:8px;color:var(--ap-muted);font-size:12px}
fieldset {padding:0;border:none;display:grid;gap:14px;margin:0;min-width:0}
label {display:grid;gap:8px;font-size:13px}
input,select {width:100%;box-sizing:border-box;font:inherit;padding:8px;border-radius:5px;border:1px solid var(--ap-line);background:var(--ap-panel);color:var(--ap-text)}
form>p {padding-top:12px}
[role=alert] {color:var(--ap-red)}
</style>
