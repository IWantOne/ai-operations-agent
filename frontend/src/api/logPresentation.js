// Display-only projections. Never replace or mutate stored log evidence.
export function payload(row) {
  try { return JSON.parse(row.content); } catch { return null; }
}
const text = value => typeof value === "string" ? value : JSON.stringify(value);
const object = value => value && typeof value === "object" && !Array.isArray(value);
const operations = {getBrowserList: "读取店铺列表", getRunningInfo: "查询运行窗口", startBrowser: "打开店铺窗口", stopBrowser: "关闭店铺窗口"};
export function operationLabel(row) {
  const operation = payload(row)?.operation;
  return operations[operation] || operation || "";
}
export function summary(row) {
  const data = payload(row);
  if (!object(data)) return row.content;
  if (data.error) return text(data.error);
  if (row.action === "script_output") return `${data.stream} · 第 ${data.sequence} 段\n${data.text ?? ""}`;
  if (row.action === "CONNECTOR_RAW" && row.source === "resource_log" && data.body !== undefined) {
    let body = data.body;
    if (typeof body === "string") {
      try { body = JSON.parse(body); } catch { /* Keep the actual non-JSON reply. */ }
    }
    const parts = [`收到响应 · HTTP ${data.http_status ?? '未提供'}`];
    if (object(body)) {
      parts.push(`紫鸟返回码 ${body.statusCode ?? '未提供'}`);
      if (body.err) parts.push(text(body.err));
      if (body.error) parts.push(text(body.error));
      if (Array.isArray(body.browserList)) parts.push(`返回店铺 ${body.browserList.length} 家`);
      if (Array.isArray(body.browsers)) parts.push(`返回窗口 ${body.browsers.length} 个`);
      // Unknown reply structures remain visible, not reduced to an invented result.
      if (!body.err && !body.error && !Array.isArray(body.browserList) && !Array.isArray(body.browsers)) parts.push(text(body));
    } else if (body != null) parts.push(text(body));
    return parts.join(" · ");
  }
  const parts = [];
  if (data.returncode != null) parts.push(`退出码 ${data.returncode}`);
  if (data.stdout_bytes != null) parts.push(`标准输出 ${data.stdout_bytes} 字节`);
  if (data.stderr_bytes != null) parts.push(`标准错误 ${data.stderr_bytes} 字节`);
  if (data.status != null) parts.push(`记录状态 ${text(data.status)}`);
  for (const key of ["message", "reason", "stderr", "stdout", "body"]) {
    if (data[key]) parts.push(text(data[key]));
  }
  return parts.length ? parts.join("\n") : row.content;
}
