<script setup>
import { computed, inject, onMounted, ref } from "vue";
import { object, request } from "../api/platform";

const props = defineProps({ action: String, record: Object });
const emit = defineEmits(["close", "saved"]);
const { state, refresh, accountOverview, accountLoading, accountError, loadAccounts } = inject("workbench");
const row = props.record;
const isEmployee = props.action.endsWith("_employee");
const deleting = props.action.startsWith("delete");
const creating = props.action.startsWith("create");
const heading = (deleting ? "删除" : creating ? "新增" : "编辑") + (isEmployee ? "员工" : "任务");
const dialog = ref(null), saving = ref(false), error = ref("");
const name = ref(row.name || ""), description = ref(row.description || "");
const initialInputs = {...object(row.input_data)};
const shopId = ref(String(initialInputs.shop_id ?? ""));
delete initialInputs.shop_id;
const shops = computed(() => accountOverview.value?.shops || []);
const handler = ref(row.handler || ""), inputs = ref(JSON.stringify(initialInputs, null, 2));
const advanced = ref(false);
const timeout = ref(row.timeout_seconds ?? state.value.settings?.runtime?.timing?.task_timeout_seconds ?? 3600), resume = ref(Boolean(row.resume_enabled));
const plans = ref((object(row.sync_data).schedules || []).map(p => ({...p})));
const handlers = state.value.handlers || [];
onMounted(() => { dialog.value.showModal(); if (!isEmployee && !deleting) loadAccounts(); });

async function submit() {
  if (saving.value) return;
  error.value = "";
  try {
    let values;
    if (isEmployee) {
      values = creating ? {} : {key: row.key};
      if (!deleting) Object.assign(values, {name:name.value.trim(), description:description.value.trim()});
    } else {
      values = creating ? {employee_key:row.employee_key} : {id:row.id, employee_key:row.employee_key};
      if (!deleting) {
        let params;
        try { params = JSON.parse(inputs.value || "{}"); }
        catch { throw new Error("任务参数请填写有效的 JSON 对象。"); }
        if (!params || typeof params !== "object" || Array.isArray(params)) throw new Error("任务参数必须是对象。");
        delete params.shop_id;
        if (shopId.value) params.shop_id = shopId.value;
        if (new Set(plans.value.map(p => p.key.trim())).size !== plans.value.length)
          throw new Error("每个定时计划的名称须不同。");
        Object.assign(values, {name:name.value.trim(), handler:handler.value, input_data:params,
          timeout_seconds:timeout.value, resume_enabled:resume.value,
          schedules:plans.value.map(p => ({...p, key:p.key.trim()}))});
      }
    }
    if (!deleting && !name.value.trim()) throw new Error("请填写名称。");
    saving.value = true;
    const result = await request("action", {method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({...values, action:props.action, token:state.value.panel.token})});
    await refresh();
    emit("saved", result);
  } catch (e) {error.value = e.message; if (e.message.includes("任务参数")) advanced.value = true;}
  finally {saving.value = false;}
}
</script>

<template>
  <dialog ref="dialog" aria-labelledby="manage-title" @cancel.prevent="!saving && $emit('close')">
    <form @submit.prevent="submit">
      <h2 id="manage-title">{{ heading }}</h2>
      <p v-if="deleting" class="question">确定删除「{{ row.name }}」？{{ isEmployee ? "员工代码会保留。" : "已有执行记录会保留。" }}</p>
      <template v-else>
        <label>{{ isEmployee ? "员工名称" : "任务名称" }}<input v-model="name" required autofocus /></label>
        <label v-if="isEmployee">职责说明<textarea v-model="description" rows="3" /></label>
        <template v-else>
          <label>关联店铺
            <select v-model="shopId">
              <option value="">不关联店铺</option>
              <option v-if="shopId && !shops.some(s => String(s.id) === shopId)" :value="shopId">{{ shopId }}（当前账户未返回）</option>
              <option v-for="shop in shops" :key="shop.id" :value="String(shop.id)">{{ shop.name }} · {{ shop.id }}</option>
            </select>
          </label>
          <p v-if="accountLoading" class="hint" role="status">正在读取可关联店铺…</p>
          <p v-if="accountError" class="error" role="alert">{{ accountError }} <button type="button" class="ap-link" @click="loadAccounts(true)">重新读取店铺</button></p>
          <label>执行函数
            <select v-model="handler">
              <option value="">暂不绑定</option>
              <option v-if="handler && !handlers.includes(handler)" :value="handler">{{ handler }}（未注册）</option>
              <option v-for="h in handlers" :key="h" :value="h">{{ h }}</option>
            </select>
          </label>
          <p v-if="!handler" class="hint">{{ handlers.length ? '保存后为草稿，绑定执行函数后才能运行。' : '当前服务尚未注册执行函数。可以先保存草稿，待平台维护者注册函数后再绑定。' }}</p>
          <details :open="advanced" @toggle="advanced = $event.target.open">
            <summary>高级运行设置</summary>
            <div class="advanced-fields">
          <label>任务参数（JSON）<textarea v-model="inputs" rows="3" spellcheck="false" /></label>
          <p class="hint">店铺由上方「关联店铺」设置，保存时写入 shop_id。</p>
          <label>运行上限（秒）<input v-model.number="timeout" type="number" min="1" step="1" required /></label>
          <label class="check"><input type="checkbox" v-model="resume" />启用断点续跑</label>
          </div></details>
          <div class="plan-title"><strong>定时计划</strong><button class="ap-link" type="button" @click="plans.push({key:'',interval_seconds:300})">添加计划</button></div>
          <div v-for="(plan,i) in plans" :key="i" class="plan">
            <label>计划名称<input v-model="plan.key" required /></label>
            <label>间隔（秒）<input v-model.number="plan.interval_seconds" type="number" min="1" step="1" required /></label>
            <button class="ap-link" type="button" @click="plans.splice(i,1)">移除</button>
          </div>
        </template>
      </template>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="buttons">
        <button class="ap-btn" type="button" :disabled="saving" @click="$emit('close')">取消</button>
        <button class="ap-btn submit" :class="{danger:deleting}" type="submit" :disabled="saving">{{ saving ? "提交中…" : deleting ? "确认删除" : !isEmployee && !handler ? "保存草稿" : "保存" }}</button>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
dialog {border:1px solid var(--ap-line);border-radius:10px;color:var(--ap-text);background:var(--ap-panel);width:min(430px, calc(100% - 32px));max-height:85dvh;padding:22px;box-shadow:0 12px 52px #0002}
dialog::backdrop {background:#10202765}
form,.advanced-fields {display:grid;gap:14px}
.advanced-fields {padding-top:12px}
summary {cursor:pointer}
label {display:grid;gap:5px;font-size:13px}
input:not([type=checkbox]),textarea,select {box-sizing:border-box;width:100%;border:1px solid var(--ap-line);border-radius:5px;background:var(--ap-panel);color:var(--ap-text);font:inherit;padding:7px 9px}
textarea {resize:vertical}
.check,.buttons,.plan-title {display:flex;align-items:center;gap:8px}
.buttons {justify-content:flex-end}.plan-title {justify-content:space-between}.plan {display:grid;grid-template-columns:1fr 1fr auto;align-items:end;gap:8px}
.hint {font-size:12px;color:var(--ap-muted)}.error {color:var(--ap-red)}.question {line-height:1.6}
#agent-console-demo .submit {background:var(--ap-accent);color:var(--ap-panel)}#agent-console-demo .danger {background:var(--ap-red)}
</style>
