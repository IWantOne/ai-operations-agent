export async function request(path, options) {
  const response = await fetch("/api/" + path, {
    cache: "no-store",
    ...options,
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || response.statusText);
  if (body.operation_id) {
    const id = body.operation_id;
    for (;;) {
      const operation = await request("operations/" + id);
      if (operation.status === "SUCCEEDED") return {...(operation.result || {}), operation_id: id};
      if (["FAILED", "CANCELLED", "TIMEOUT", "NEEDS_REVIEW"].includes(operation.status)) {
        throw new Error(`请求 #${id}：${operation.error?.error || operation.status}`);
      }
      await new Promise(resolve => setTimeout(resolve, 300));
    }
  }
  return body;
}

export function runAction(action, id, token, extra = {}) {
  return request("action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action,
      id,
      token,
      ...extra,
      operation_key: crypto.randomUUID(),
    }),
  });
}

export function object(value) {
  return typeof value === "string" ? JSON.parse(value || "{}") : value || {};
}

export const taskShopId = (task) => String(object(task.input_data).shop_id ?? "");
export const shop = (task) => taskShopId(task) || "无店铺";
export const shopRoute = (id) => ({menu: "resources", shop: String(id)});
export const taskRoute = (task) => ({menu: "employees", owner: task.employee_key, task: task.id, filter: "all"});
export const routeHref = (params) => "?" + new URLSearchParams(params);
export const stamp = (seconds) =>
  seconds == null
    ? "—"
    : new Date(seconds * 1000).toLocaleString("zh-CN", { hour12: false });
// 执行记录和用例时间都要能分清今天/昨天，不能只给时分秒。
export function when(seconds) {
  if (seconds == null) return "—";
  const date = new Date(seconds * 1000);
  const now = new Date();
  const hm = date.toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return "今天 " + hm;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "昨天 " + hm;
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" }) + " " + hm;
}
export const columns = {
  queued: "待执行",
  running: "执行中",
  failed: "待跟进",
  done: "已完成",
};
// Preserve active work and previous failures even if the task configuration changes.
export function taskStage(task) {
  if (task.board_column === "queued" && task.status_label === "已停用") return "inactive";
  return task.board_column;
}
export function taskLabel(task) {
  return taskStage(task) === "inactive" && !task.handler ? "待配置" : task.status_label;
}
export const stages = {...columns, inactive: "未就绪"};
export const states = {
  STARTING: "启动中",
  RUNNING: "执行中",
  PAUSED: "人工暂停",
  NEEDS_REVIEW: "需人工",
  RETRY_WAIT: "等待自动重试",
  QUEUED: "已排队",
  FAILED: "失败",
  SUCCEEDED: "执行成功",
  CANCELLED: "已取消",
  TIMEOUT: "超时",
};
export const attempts = (state, task) =>
  state.executions
    .filter((row) => row.task_id === task.id)
    .sort((a, b) => b.id - a.id);
