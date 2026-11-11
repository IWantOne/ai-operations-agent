"""差评处理编排：选 case → 找账号 → 开窗 → 页面核验 → 写状态与证据。

页面动作在 pages.py，判定规则在 cases.py，映射在 bindings.py；本文件只做编排。
"""
import json
import time

from .bindings import REQUEST_LABELS, load_bindings, url_for
from .cases import judge
from . import apply, pages


def register(manager):
    def mark(case, status, reason, evidence):
        manager.store.update("feedback_case", case["id"], status=status, reason=reason,
                             evidence=json.dumps(evidence, ensure_ascii=False), updated_at=time.time())

    async def process(ctx):
        limit = int(ctx.input.get("limit", 3))
        cases = manager.store.all(
            "SELECT * FROM feedback_case WHERE status='NEW' ORDER BY id LIMIT ?", (limit,))
        if not cases:
            ctx.log("feedback_processed", {"checked": 0, "reason": "没有待处理的差评"})
            return
        bindings = load_bindings()
        counts = {"checked": 0, "removed": 0, "submitted": 0, "manual": 0, "kept": 0}

        for case in cases:
            binding = bindings.get(str(case["sid"]))
            if not binding or not binding.get("browser_id"):
                mark(case, "MANUAL", f"店铺 sid={case['sid']} 没有映射到紫鸟账号", {})
                counts["manual"] += 1
                continue
            if not url_for(case["marketplace_id"]):
                mark(case, "MANUAL", f"站点 {case['marketplace_id']} 没有对应的 Seller Central 地址", {})
                counts["manual"] += 1
                continue
            shop = binding["browser_id"]
            try:
                running = await manager.pool.browser.find_windows(shop)
            except Exception as exc:
                mark(case, "MANUAL", f"检查店铺窗口失败：{exc}", {})
                counts["manual"] += 1
                continue
            if running:
                mark(case, "MANUAL", f"{binding.get('account_name') or shop} 的窗口已在运行"
                                      "（不是工作台开的），请先在紫鸟里关闭它再处理", {"running": running})
                counts["manual"] += 1
                continue

            lease = await ctx.window(shop)
            try:
                try:
                    await pages.open(ctx, shop, case["marketplace_id"])
                    state, trail = await pages.find_order(ctx, shop, case["order_id"])
                except Exception as exc:
                    shot = await pages.screenshot(ctx, shop, f"feedback-{case['order_id']}")
                    mark(case, "MANUAL", f"打开反馈页失败：{exc}", {"screenshot": shot.get("path")})
                    counts["manual"] += 1
                    continue

                kind = pages.page_kind(state)
                evidence = {"url": state.get("url"), "title": state.get("title"), "pages": trail}
                if kind == "login":
                    shot = await pages.screenshot(ctx, shop, f"feedback-login-{case['order_id']}")
                    evidence["screenshot"] = shot.get("path")
                    mark(case, "MANUAL", "页面跳到了登录页，需要先在该店铺里人工登录", evidence)
                    counts["manual"] += 1
                    continue

                status, reason, extra = judge(state, case["order_id"])
                evidence.update(extra)
                if status == "NEW":
                    try:
                        menu = await pages.open_menu(ctx, shop, case["order_id"])
                        evidence.update(menu=menu.get("items", []),
                                        page_text=(menu.get("text") or "")[:2000])
                        labels = [str(item.get("text", "")).lower() for item in evidence["menu"]]
                        if any(any(label in text for label in REQUEST_LABELS) for text in labels):
                            result, reason, extra = await apply.run(ctx, shop, case["order_id"])
                            evidence.update(extra)
                            mark(case, result, reason, evidence)
                            counts[{"SUBMITTED": "submitted", "MANUAL": "manual"}.get(result, "kept")] += 1
                        else:
                            mark(case, "NEW", "菜单里没有识别到“请求审核”，页面文本已记录", evidence)
                            counts["kept"] += 1
                    except Exception as exc:
                        shot = await pages.screenshot(ctx, shop, f"feedback-menu-{case['order_id']}")
                        evidence.update(menu_error=str(exc), screenshot=shot.get("path"))
                        mark(case, "MANUAL", f"打开申请菜单失败：{exc}", evidence)
                        counts["manual"] += 1
                else:
                    mark(case, status, reason, evidence)
                    key = {"REMOVED": "removed", "SUBMITTED": "submitted", "MANUAL": "manual"}[status]
                    counts[key] += 1
                counts["checked"] += 1
            finally:
                await ctx.release(lease["id"])

        ctx.log("feedback_processed", counts)
        return counts

    manager.register("feedback.process", process)
