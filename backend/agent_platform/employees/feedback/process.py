"""差评处理编排：选 case → 找账号 → 开窗 → 页面核验 → 写状态与证据 → 直接回传。

原则：先写原因，再截图。截图只是辅助证据，失败就跳过，不能影响原因落库，
也不能让一条 case 的失败中断整批。回传失败只记日志，不改变已处理出的结果。
"""
import json

from .bindings import url_for
from .cases import judge
from . import apply, delivery, pages, repository
from .classify import classify
from ...resources import market


def register(manager):
    async def capture(ctx, shop, case, label, evidence):
        """理由已经落库之后才截图；失败直接跳过。"""
        try:
            shot = await pages.screenshot(ctx, shop, label)
        except Exception:
            return
        path = shot.get("path") if isinstance(shot, dict) else None
        if path:
            evidence["screenshot"] = path
            repository.update_case(manager, case["id"],
                                   evidence=json.dumps(evidence, ensure_ascii=False))

    async def process(ctx):
        limit = int(ctx.input.get("limit", 3))
        # 单条重试只处理指定 case，不按顺序抓一批。
        target = ctx.input.get("case_id")
        if target:
            case = repository.new_case(manager, target)
            cases = [case] if case else []
        else:
            cases = repository.new_cases(manager, limit)
        if not cases:
            ctx.log("feedback_processed", {"checked": 0, "reason": "没有待处理的差评"})
            return
        # 理由分类：一次 codex 调用给这批评论选理由，拿不准的不提交。
        decisions = await classify(ctx, cases)
        login_wait = manager.timing_settings.read()["login_wait_seconds"]
        counts = {"checked": 0, "removed": 0, "submitted": 0, "manual": 0, "kept": 0,
                  "reported": 0, "report_failed": 0}

        async def mark(case, status, reason, evidence):
            repository.mark(manager, case["id"], status, reason, evidence)
            if status in delivery.REPORTABLE:
                ok = await delivery.deliver(manager, ctx, case, status, reason, evidence)
                counts["reported" if ok else "report_failed"] += 1

        for case in cases:
            repository.set_execution(manager, case["id"], ctx.id)
            if not url_for(case["marketplace_id"]):
                await mark(case, "MANUAL", f"站点 {case['marketplace_id']} 没有对应的 Seller Central 地址", {})
                counts["manual"] += 1
                continue
            try:
                running = await ctx.running_windows(case["sid"])
            except Exception as exc:
                await mark(case, "MANUAL", str(exc), {})
                counts["manual"] += 1
                continue
            if running:
                await mark(case, "MANUAL", "该店铺的窗口已在运行（不是工作台开的），请先在紫鸟里关闭它再处理",
                           {"running": running})
                counts["manual"] += 1
                continue

            try:
                lease = await ctx.window_for(case["sid"])
            except Exception as exc:
                await mark(case, "MANUAL", f"申请店铺窗口失败：{exc}", {})
                counts["manual"] += 1
                continue
            shop = lease["shop_id"]
            try:
                try:
                    state, _code = await market.prepare(ctx, shop, case["marketplace_id"], login_wait)
                except Exception as exc:
                    evidence = {}
                    await mark(case, "MANUAL", f"打开店铺站点失败：{exc}", evidence)
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
                    await mark(case, "MANUAL",
                               f"{reason}，{login_wait} 秒内没有等到紫鸟自动登录，需要人工登录", evidence)
                    await capture(ctx, shop, case, f"feedback-login-{case['order_id']}", evidence)
                    counts["manual"] += 1
                    continue

                try:
                    await pages.open(ctx, shop, case["marketplace_id"])
                    state, trail = await pages.find_order(ctx, shop, case["order_id"])
                except Exception as exc:
                    evidence = {}
                    await mark(case, "MANUAL", f"打开反馈页失败：{exc}", evidence)
                    await capture(ctx, shop, case, f"feedback-{case['order_id']}", evidence)
                    counts["manual"] += 1
                    continue

                kind = pages.page_kind(state)
                evidence = {"url": state.get("url"), "title": state.get("title"), "pages": trail}
                if kind == "login":
                    # 打开反馈页时才弹登录页：紫鸟已填好账号密码，工作台补点“登录”后重试一次。
                    state = await market.wait_login(ctx, shop, login_wait)
                    if state.get("gate") == "LOGGED_IN":
                        try:
                            await pages.open(ctx, shop, case["marketplace_id"])
                            state, trail = await pages.find_order(ctx, shop, case["order_id"])
                            kind = pages.page_kind(state)
                            evidence = {"url": state.get("url"), "title": state.get("title"), "pages": trail}
                        except Exception as exc:
                            evidence = {}
                            await mark(case, "MANUAL", f"登录后打开反馈页失败：{exc}", evidence)
                            await capture(ctx, shop, case, f"feedback-{case['order_id']}", evidence)
                            counts["manual"] += 1
                            continue
                    if kind == "login":
                        await mark(case, "MANUAL", "页面跳到了登录页，紫鸟自动登录没有通过，需要人工登录", evidence)
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
                            result, reason, extra = await apply.run(
                                ctx, shop, case["order_id"], decisions.get(case["id"]))
                            evidence.update(extra)
                            await mark(case, result, reason, evidence)
                            counts[{"SUBMITTED": "submitted", "MANUAL": "manual",
                                    "REMOVED": "removed", "REJECTED": "kept"}.get(result, "kept")] += 1
                        else:
                            await mark(case, "MANUAL",
                                       "操作菜单里没有可点的“请求审核”（可能已审核过），页面文本已记录", evidence)
                            counts["manual"] += 1
                    except Exception as exc:
                        await mark(case, "MANUAL", f"打开申请菜单失败：{exc}", evidence)
                        await capture(ctx, shop, case, f"feedback-menu-{case['order_id']}", evidence)
                        counts["manual"] += 1
                else:
                    await mark(case, status, reason, evidence)
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
