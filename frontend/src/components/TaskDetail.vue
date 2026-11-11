<script setup>
import { computed, inject, ref, watch } from "vue";
import WorkRequests from "./WorkRequests.vue";
import { request, attempts, states, stamp } from "../api/platform";
const props = defineProps({ task: { type: Object, required: true } });
const { state, action, busy, navigate } = inject("workbench");
const rows = computed(() => attempts(state.value, props.task)),
  latest = computed(() => rows.value[0]);
const pending = computed(() =>
  state.value.requests.filter(
    (r) => r.task_id === props.task.id && ["QUEUED","RETRY_WAIT"].includes(r.status),
  ),
);
const logs = ref([]),
  selected = ref(""),
  logError = ref(""),
  page = ref(1);
const pages = computed(() =>
  Math.max(1, Math.ceil((rows.value.length - 1) / 20)),
);
const active = (row) => ["STARTING", "RUNNING", "PAUSED"].includes(row.status);
const key = (log) => log.table + ":" + log.id;
const events = {
  execution_error: "执行异常",
  cleanup_incomplete: "资源清理失败",
  CLOSE_FAILED: "关闭窗口失败",
  OPEN_FAILED: "打开窗口失败",
  started: "开始执行",
  window_wait: "申请店铺窗口",
  business_prepared: "准备完成",
  business_window_enter: "进入窗口",
  business_window_exit: "窗口操作结束",
  ACQUIRED: "获得窗口",
  CLOSED: "窗口关闭",
  script_start: "启动脚本",
  script_result: "脚本返回",
  script_stopped: "脚本停止",
};
const node = computed(() => logs.value.find((l) => key(l) === selected.value));
watch(
  () => [state.value, latest.value?.id],
  async ([, id], prev, onCleanup) => {
    let valid = true;
    onCleanup(() => {
      valid = false;
    });
    if (prev?.[1] !== id) {
      logs.value = [];
      selected.value = "";
      page.value = 1;
    }
    if (!id) return;
    try {
      const rows = await request("logs?execution_id=" + id);
      if (valid) {
        logs.value = rows;
        logError.value = "";
      }
    } catch (e) {
      if (valid) logError.value = e.message;
    }
  },
  { immediate: true },
);
</script>
<template>
  <div class="ap-inlineexecution">
    <WorkRequests v-if="latest" :execution-id="latest.id" />
    <div class="ap-timelinehead">
      <h2>执行时间线</h2>
      <div class="ap-actions">
        <button v-if="latest" class="ap-btn" @click="navigate({menu: 'logs', execution_id: latest.id})">查看日志列表</button>
        <button
          v-if="task.enabled && task.handler"
          class="ap-btn"
          :disabled="busy"
          @click="action('run', task.id)"
        >
          运行一次
        </button>
        <button
          v-if="task.handler" class="ap-btn"
          :disabled="busy"
          @click="action(task.enabled ? 'disable' : 'enable', task.id)"
        >
          {{ task.enabled ? "停用" : "启用" }}
        </button>
        <template v-if="latest && active(latest)"
          ><button
            class="ap-btn"
            :disabled="busy"
            @click="
              action(latest.status === 'PAUSED' ? 'resume' : 'pause', latest.id)
            "
          >
            {{ latest.status === "PAUSED" ? "继续" : "暂停" }}</button
          ><button
            class="ap-btn"
            :disabled="busy"
            @click="action('cancel', latest.request_id)"
          >
            结束
          </button></template
        >
        <button
          v-else-if="latest?.resume_enabled"
          class="ap-btn"
          :disabled="busy"
          @click="action('continue', latest.id)"
        >
          从业务进度续跑
        </button>
      </div>
    </div>
    <div v-for="r in pending" :key="r.id" class="ap-issue">
      请求 #{{ r.id }} · 等待派发
      <button class="ap-btn" :disabled="busy" @click="action('cancel', r.id)">
        取消排队
      </button>
    </div>
    <div v-if="!latest" class="ap-empty">暂无执行记录</div>
    <template v-else>
      <p v-if="logError" role="alert">{{ logError }}</p>
      <div
        v-if="logs.length"
        class="ap-timeline"
        role="region"
        aria-label="最新执行时间线"
      >
        <div class="ap-timeline-track">
          <button
            v-for="l in logs"
            :key="key(l)"
            :class="[
              'ap-node',
              l.level === 'ERROR'
                ? 'failed'
                : l.action === 'window_wait'
                  ? 'wait'
                  : 'step',
            ]"
            :aria-pressed="selected === key(l)"
            @click="selected = selected === key(l) ? '' : key(l)"
          >
            <time>{{ stamp(l.occurred_at).slice(-8) }}</time
            ><span class="ap-node-symbol">{{
              l.level === "ERROR" ? "!" : l.action === "window_wait" ? "◷" : "✓"
            }}</span
            ><strong>{{ events[l.action] || l.action }}</strong
            ><small>{{ l.table }}</small>
          </button>
        </div>
      </div>
      <p v-else class="ap-muted">本次执行暂无时间线记录</p>
      <div v-if="node" class="ap-node-info">
        <span>{{ node.content }}</span
        ><small>{{ stamp(node.occurred_at) }}</small
        ><button class="ap-link" @click="selected = ''">关闭</button>
      </div>
      <p class="ap-muted">
        执行 #{{ latest.id }} · {{ states[latest.status] || latest.status }} ·
        累计运行 {{ Number(latest.elapsed_seconds).toFixed(2) }} 秒
      </p>
      <p
        v-if="latest.pause_reason || latest.error_message || latest.wait_reason"
        class="ap-issue"
      >
        {{
          latest.pause_reason ||
          latest.error_message ||
          (latest.wait_reason === "WINDOW"
            ? "等待紫鸟窗口"
            : latest.wait_reason)
        }}
      </p>
      <p
        v-if="latest.result_data && latest.result_data !== '{}'"
        class="ap-result"
      >
        {{ latest.result_data }}
      </p>
      <div
        v-for="r in rows.slice(1).filter(active)"
        :key="r.id"
        class="ap-issue"
      >
        执行 #{{ r.id }} · {{ states[r.status] }}
        <button
          class="ap-btn"
          :disabled="busy"
          @click="action(r.status === 'PAUSED' ? 'resume' : 'pause', r.id)"
        >
          {{ r.status === "PAUSED" ? "继续" : "暂停" }}</button
        ><button
          class="ap-btn"
          :disabled="busy"
          @click="action('cancel', r.request_id)"
        >
          结束
        </button>
      </div>
      <div class="ap-disclosures">
        <details v-if="rows.length > 1">
          <summary>历史 {{ rows.length - 1 }} 次</summary>
          <ul class="ap-history-list">
            <li
              v-for="r in rows.slice(1 + 20 * (page - 1), 1 + 20 * page)"
              :key="r.id"
            >
              <div>
                执行 #{{ r.id }} · {{ states[r.status]
                }}<small>{{ stamp(r.started_at) }}</small>
              </div>
              <div>
                {{ r.error_message || r.result_data
                }}<small
                  ><a :href="'?menu=logs&execution_id=' + r.id"
                    >原始日志</a
                  ></small
                >
              </div>
            </li>
          </ul>
          <template v-if="pages > 1"
            ><button :disabled="page === 1" @click="page--">上一页</button>
            {{ page }} / {{ pages }}
            <button :disabled="page >= pages" @click="page++">
              下一页
            </button></template
          >
        </details>
        <details>
          <summary>日志</summary>
          <ol class="ap-logrows">
            <li v-for="l in logs" :key="key(l)">
              <time>{{ stamp(l.occurred_at).slice(-8) }}</time
              ><span>{{ l.action }} · {{ l.content }}</span>
            </li>
          </ol>
        </details>
        <details>
          <summary>详情</summary>
          <pre>
Task：{{ task.id }}
Execution：{{ latest.id }}
创建：{{ stamp(task.created_at) }}</pre>
        </details>
      </div>
    </template>
  </div>
</template>
