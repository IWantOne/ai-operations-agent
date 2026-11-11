<script setup>
import { computed, inject, ref } from "vue";
import { states, stamp, object } from "../api/platform";
const props=defineProps({executionId:Number});
const {state}=inject("workbench");
const page=ref(1), size=20;
const rows=computed(()=>[...state.value.requests].filter(r=>!props.executionId || r.execution_id===props.executionId || r.last_execution_id===props.executionId).reverse());
const pages=computed(()=>Math.max(1,Math.ceil(rows.value.length/size)));
const commands=computed(()=>[...(state.value.commands||[])].filter(c=>!props.executionId || c.target_id===props.executionId || rows.value.some(r=>r.id===c.target_id)).reverse().slice(0,20));
const commandStates={SUBMITTED:"已提交，尚未确认",CONFIRMED:"已确认",FAILED:"未完成，查看原因"};
</script>
<template>
  <section class="ap-panel">
    <h2>执行请求</h2>
    <div style="overflow:auto"><table style="width:100%;text-align:left">
      <thead><tr><th>请求 / 操作</th><th>时间</th><th>状态</th><th>共享重试预算</th><th>实际原因与证据</th></tr></thead>
      <tbody><tr v-for="r in rows.slice((page-1)*size,page*size)" :key="r.id">
        <td>#{{r.id}} · {{r.kind}}<small v-if="r.parent_attempt_id">父尝试 #{{r.parent_attempt_id}}</small></td>
        <td>{{stamp(r.created_at)}}</td><td>{{states[r.status]||r.status}}<small v-if="r.wait_reason">{{r.wait_reason}}</small></td>
        <td>已用 {{r.retry_count}} / {{r.retry_limit}} · 剩余 {{r.retry_limit-r.retry_count}}</td>
        <td><p v-if="r.error_data">{{object(r.error_data).error}}</p>
          <details><summary>完整执行记录</summary><pre v-for="a in state.attempts.filter(a=>a.request_id===r.id)" :key="a.id">{{a}}</pre></details></td>
      </tr></tbody>
    </table></div>
    <p v-if="!rows.length" class="ap-muted">暂无请求</p>
    <div class="ap-actions"><button class="ap-btn" :disabled="page===1" @click="page--">上一页</button><span>{{page}} / {{pages}}</span><button class="ap-btn" :disabled="page>=pages" @click="page++">下一页</button></div>
    <details v-if="commands.length"><summary>最近控制命令</summary>
      <p v-for="c in commands" :key="c.id">命令 #{{c.id}} · {{c.kind}} · {{commandStates[c.status]||c.status}}<span v-if="c.error_data"> · {{object(c.error_data).error}}</span></p>
    </details>
  </section>
</template>
<style scoped>td,th {padding:10px;vertical-align:top;border-bottom:1px solid var(--ap-line)}small{display:block}pre{max-width:650px;white-space:pre-wrap;overflow-wrap:anywhere}</style>
