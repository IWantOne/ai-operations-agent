"""差评明细：只读查询，供任务详情面板按需读取，不进入状态快照。"""

STATUS_LABELS = {"NEW": "待处理", "MANUAL": "需人工", "SUBMITTED": "已提交",
                 "REMOVED": "已移除", "REJECTED": "审核后保留"}
STATUS_TONES = {"NEW": "queued", "MANUAL": "failed", "SUBMITTED": "done",
                "REMOVED": "done", "REJECTED": "running"}
LIMIT = 200


def detail(manager, task):
    rows = manager.store.all(
        "SELECT id,sid,store_name,marketplace_id,order_id,rating,status,reason,execution_id,case_ref,updated_at "
        "FROM feedback_case ORDER BY id DESC LIMIT ?", (LIMIT,))
    counts = manager.store.all("SELECT status,count(*) AS total FROM feedback_case GROUP BY status")
    summary = " · ".join(f"{STATUS_LABELS.get(row['status'], row['status'])} {row['total']}"
                         for row in counts) or "暂无差评记录"
    pending = next((row["total"] for row in counts if row["status"] == "NEW"), 0)
    return {
        "title": "差评明细",
        "summary": summary,
        "action": ({"name": "run", "label": f"处理 {pending} 条待处理", "input": {"limit": pending}}
                   if pending else None),
        "row_action": {"name": "retry_case", "label": "重试", "when": {"key": "status", "in": ["MANUAL"]}},
        "status": {"key": "status", "labels": STATUS_LABELS, "tones": STATUS_TONES},
        "columns": [
            {"key": "order_id", "label": "订单"},
            {"key": "store_name", "label": "店铺"},
            {"key": "rating", "label": "星级", "suffix": "★"},
            {"key": "status", "label": "状态"},
            {"key": "reason", "label": "原因"},
            {"key": "updated_at", "label": "更新时间", "type": "time"},
        ],
        "rows": rows,
    }
