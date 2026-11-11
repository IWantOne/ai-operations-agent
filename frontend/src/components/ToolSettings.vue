<script setup>
import { inject, reactive, ref } from "vue";
import { request } from "../api/platform";

const { state, refresh } = inject("workbench");

const codex = state.value.settings?.tools;
const command = ref(codex?.codex_command ?? "");
const args = ref(codex?.codex_args ?? "");
const busy = ref(false), message = ref(""), failed = ref(false);

const erp = state.value.settings?.erp;
const baseUrl = ref(erp?.base_url ?? "https://test.effiseller.com");
const appId = ref(erp?.app_id ?? "");
const appSecret = ref("");
const erpBusy = ref(false), erpMessage = ref(""), erpFailed = ref(false);

// 通用外部应用：飞书、领星等，API 与 MCP 两种传输。
const integrations = state.value.settings?.integrations || {};
const forms = reactive({});
for (const [key, value] of Object.entries(integrations)) {
  forms[key] = { ...value, app_secret: "", busy: false, message: "", failed: false };
}

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
    message.value = "配置已保存，下次工具调用生效。";
    await refresh();
  } catch (e) {
    failed.value = true;
    message.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function saveErp() {
  if (erpBusy.value) return;
  erpMessage.value = "";
  erpFailed.value = false;
  erpBusy.value = true;
  try {
    await post({ action: "save_erp_settings", base_url: baseUrl.value,
                 app_id: appId.value, app_secret: appSecret.value });
    appSecret.value = "";
    erpMessage.value = "配置已保存，凭据加密存放。";
    await refresh();
  } catch (e) {
    erpFailed.value = true;
    erpMessage.value = e.message;
  } finally {
    erpBusy.value = false;
  }
}

async function testErp() {
  if (erpBusy.value) return;
  erpMessage.value = "";
  erpFailed.value = false;
  erpBusy.value = true;
  try {
    const result = await post({ action: "test_erp" });
    const erpResult = result.erp || {};
    erpMessage.value = `连接成功：可访问店铺 ${erpResult.stores ?? "未提供"} 家` +
      (Array.isArray(erpResult.api_types) ? `（${erpResult.api_types.join("、")}）` : "");
  } catch (e) {
    erpFailed.value = true;
    erpMessage.value = e.message;
  } finally {
    erpBusy.value = false;
  }
}

function payloadOf(form) {
  return {
    transport: form.transport, base_url: form.base_url, app_id: form.app_id,
    app_secret: form.app_secret, auth: form.auth, token_path: form.token_path,
    token_field: form.token_field, mcp_command: form.mcp_command,
  };
}

async function saveIntegration(key) {
  const form = forms[key];
  if (form.busy) return;
  form.message = "";
  form.failed = false;
  form.busy = true;
  try {
    await post({ action: "save_integration", provider: key, ...payloadOf(form) });
    form.app_secret = "";
    form.message = "配置已保存，凭据加密存放。";
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
  <section class="ap-panel tool-panel">
    <div class="ap-panelhead">
      <div><h2>Codex</h2>
        <p>把本机 codex-cli 当作工具调用，业务通过 <code>ctx.tool("codex", prompt=...)</code> 使用。</p></div>
      <span class="ap-badge">{{ codex?.codex_command ? '自定义路径' : '使用 PATH 中的 codex' }}</span>
    </div>
    <p v-if="!codex" role="alert">当前服务尚不支持工具配置，请重启后端服务后刷新页面。</p>
    <form @submit.prevent="saveCodex" @input="message = ''">
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

  <section class="ap-panel tool-panel">
    <div class="ap-panelhead">
      <div><h2>智易飞</h2><p>Amazon 原生 API 通道：店铺查询与 SP-API／Ads 请求透传。</p></div>
      <span class="ap-badge">{{ erp?.secret_set ? '已配置凭据' : '未配置' }}</span>
    </div>
    <p v-if="!erp" role="alert">当前服务尚不支持智易飞配置，请重启后端服务后刷新页面。</p>
    <form @submit.prevent="saveErp" @input="erpMessage = ''">
      <fieldset :disabled="erpBusy || !erp">
        <label>部署地址
          <input v-model="baseUrl" placeholder="https://test.effiseller.com" />
        </label>
        <label>App ID
          <input v-model="appId" placeholder="管理员提供的 App ID" />
        </label>
        <label>App Secret
          <input v-model="appSecret" type="password" autocomplete="new-password"
                 :placeholder="erp?.secret_set ? '已保存；留空表示不修改' : '管理员提供的 App Secret'" />
        </label>
        <p class="ap-muted">
          App Secret 用本机用户凭据加密后保存，页面不回显。请求超时在「时间与停止策略」里配置。
          业务通过 <code>ctx.tool("amazon.stores")</code> 和
          <code>ctx.tool("amazon.request", sid=..., api_type="sp-api", method="GET", path="/sellers/v1/marketplaceParticipations")</code> 使用。
        </p>
        <div>
          <button type="submit" class="ap-btn primary">{{ erpBusy ? '处理中…' : '保存配置' }}</button>
          <button type="button" class="ap-link" @click="testErp">测试连接</button>
        </div>
      </fieldset>
      <p v-if="erpMessage" :role="erpFailed ? 'alert' : 'status'">{{ erpMessage }}</p>
    </form>
  </section>

  <section v-for="(form, key) in forms" :key="key" class="ap-panel tool-panel">
    <div class="ap-panelhead">
      <div><h2>{{ form.label }}</h2>
        <p>API 或 MCP 接入，业务通过 <code>api.request</code>／<code>mcp.call</code> 使用。</p></div>
      <span class="ap-badge">{{ form.secret_set ? '已配置凭据' : '未配置' }}</span>
    </div>
    <form @submit.prevent="saveIntegration(key)" @input="form.message = ''">
      <fieldset :disabled="form.busy">
        <label>传输方式
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
          <label>认证方式
            <select v-model="form.auth">
              <option value="token">先换 token，再带 Bearer</option>
              <option value="headers">App ID／Secret 放请求头</option>
              <option value="none">不带认证</option>
            </select>
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
          请求超时在「时间与停止策略」里配置。API 工具：
          <code>ctx.tool("api.request", provider="{{ key }}", method="GET", path="/...")</code>；
          MCP 工具：<code>ctx.tool("mcp.call", provider="{{ key }}", tool="...", arguments={})</code>。
        </p>
        <div>
          <button type="submit" class="ap-btn primary">{{ form.busy ? '处理中…' : '保存配置' }}</button>
          <button type="button" class="ap-link" @click="testIntegration(key)">测试连接</button>
        </div>
      </fieldset>
      <p v-if="form.message" :role="form.failed ? 'alert' : 'status'">{{ form.message }}</p>
    </form>
  </section>
</template>

<style scoped>
.tool-panel {width:min(100%,660px);margin-bottom:16px}
fieldset {padding:0;border:none;display:grid;gap:14px;margin:0;min-width:0}
label {display:grid;gap:8px;font-size:13px}
input,select {width:100%;box-sizing:border-box;font:inherit;padding:8px;border-radius:5px;border:1px solid var(--ap-line);background:var(--ap-panel);color:var(--ap-text)}
form>p {padding-top:12px}
[role=alert] {color:var(--ap-red)}
</style>
