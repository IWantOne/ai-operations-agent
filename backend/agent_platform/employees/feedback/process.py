"""差评处理编排：选 case → 找账号 → 开窗 → 页面核验 → 写状态与证据。

原则：先写原因，再截图。截图只是辅助证据，失败就跳过，不能影响原因落库，
也不能让一条 case 的失败中断整批。
"""
import json
import time

from .bindings import load_bindings, url_for
from .cases import judge
from . import apply, pages
from ...resources import market


def register(manager):
    def mark(case, status, reason, evidence):
        manager.store.update("feedback_case", case["id"], status=status, reason=reason,
                             evidence=json.dumps(evidence, ensure_ascii=False), updated_at=time.time())

    async def capture(ctx, shop, case, label, evidence):
        """理由已经落库之后才截图；失败直接跳过。"""
        try:
            shot = await pages.screenshot(ctx, shop, label)
        except Exception:
            return
        path = shot.get("path") if isinstance(shot, dict) else None
        if path:
            evidence["screenshot"] = path
            manager.store.update("feedback_case", case["id"],
                                 evidence=json.dumps(evidence, ensure_ascii=False))

    async def process(ctx):
        limit = int(ctx.input.get("limit", 3))
        cases = manager.store.all(
            "SELECT * FROM feedback_case WHERE status='NEW' ORDER BY id LIMIT ?", (limit,))
        if not cases:
            ctx.log("feedback_processed", {"checked": 0, "reason": "没有待处理的差评"})
            return
        bindings = load_bindings()
        login_wait = manager.timing_settings.read()["login_wait_seconds"]
        counts = {"checked": 0, "removed": 0, "submitted": 0, "manual": 0, "kept": 0}

        for case in cases:
            manager.store.update("feedback_case", case["id"], execution_id=ctx.id)
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
                    state, _code = await market.prepare(ctx, shop, case["marketplace_id"], login_wait)
                except Exception as exc:
                    evidence = {}
                    mark(case, "MANUAL", f"打开店铺站点失败：{exc}", evidence)
                    await capture(ctx, shop, case, f"feedback-prepare-{case['order_id']}", evidence)
                    counts["manual"] += 1
                    continue

                if state.get("gate") != "LOGGED_IN":
                    reason = {"BLOCKED": "亚马逊反爬拦截（Robot Check）",
                              "CAPTCHA": "出现验证码"}.get(state.get("gate"), "登录没有完成")
                    evidence = {"url": state.get("loginHref"), "gate": state.get("gate"),
                                "emailFilled": state.get("emailFilled"),
                                "passwordFilled": state.get("passwordFilled"),
                                "otpFilled": state.get("otpFilled")}
                    mark(case, "MANUAL",
                         f"{reason}，{login_wait} 秒内没有等到紫鸟自动登录，需要人工登录", evidence)
                    await capture(ctx, shop, case, f"feedback-login-{case['order_id']}", evidence)
                    counts["manual"] += 1
                    continue

                try:
                    await pages.open(ctx, shop, case["marketplace_id"])
                    state, trail = await pages.find_order(ctx, shop, case["order_id"])
                except Exception as exc:
                    evidence = {}
                    mark(case, "MANUAL", f"打开反馈页失败：{exc}", evidence)
                    await capture(ctx, shop, case, f"feedback-{case['order_id']}", evidence)
                    counts["manual"] += 1
                    continue

                kind = pages.page_kind(state)
                evidence = {"url": state.get("url"), "title": state.get("title"), "pages": trail}
                if kind == "login":
                    mark(case, "MANUAL", "页面跳到了登录页，需要先在该店铺里人工登录", evidence)
                    await capture(ctx, shop, case, f"feedback-login-{case['order_id']}", evidence)
                    counts["manual"] += 1
                    continue

                status, reason, extra = judge(state, case["order_id"])
                evidence.update(extra)
                if status == "NEW":
                    try:
                        menu = await pages.open_menu(ctx, shop, case["order_id"])
                        evidence.update(menu=menu.get("items", []),
                                        page_text=(menu.get("text") or "")[:2000])
                        if pages.requests_review(menu):
                            result, reason, extra = await apply.run(ctx, shop, case["order_id"])
                            evidence.update(extra)
                            mark(case, result, reason, evidence)
                            counts[{"SUBMITTED": "submitted", "MANUAL": "manual",
                                    "REMOVED": "removed", "REJECTED": "kept"}.get(result, "kept")] += 1
                        else:
                            mark(case, "MANUAL",
                                 "操作菜单里没有可点的“请求审核”（可能已审核过），页面文本已记录", evidence)
                            counts["manual"] += 1
                    except Exception as exc:
                        mark(case, "MANUAL", f"打开申请菜单失败：{exc}", evidence)
                        await capture(ctx, shop, case, f"feedback-menu-{case['order_id']}", evidence)
                        counts["manual"] += 1
                else:
                    mark(case, status, reason, evidence)
                    key = {"REMOVED": "removed", "SUBMITTED": "submitted", "MANUAL": "manual"}[status]
                    counts[key] += 1
                counts["checked"] += 1
            finally:
                try:
                    await ctx.release(lease["id"])
                except Exception:
                    pass

        counts["completed"] = True
        ctx.log("feedback_processed", counts)
        return counts

    manager.register("feedback.process", process)
