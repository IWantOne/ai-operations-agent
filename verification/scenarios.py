"""Example business jobs, not a general workflow interpreter.

The browser demo records progress for inspection. Process-loss work is not replayed automatically.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from agent_platform.application import build_application as build_platform


async def browser_demo(ctx):
    if not ctx.data.get("prepared"):
        await ctx.sleep(float(ctx.input.get("prepare_seconds", 0)))
        ctx.save(prepared=True)
        ctx.log("business_prepared", {})
    lease = await ctx.window(ctx.input["shop_id"])
    ctx.save(phase="using_window")
    ctx.log("business_window_enter", {"lease_id": lease["id"], "window_ref": lease["window_ref"]})
    seconds = float(ctx.input.get("work_seconds", 0.05))
    if ctx.input.get("subprocess"):
        result = await ctx.script([sys.executable, "-c",
                                   f"import time; print('test-script-start', flush=True); time.sleep({seconds!r}); print('test-script-end')"])
        if result["returncode"] != 0:
            raise RuntimeError(f"Script exited: {result['returncode']}")
    else:
        await ctx.sleep(seconds)
    ctx.log("business_window_exit", {"lease_id": lease["id"]})
    await ctx.release(lease["id"])
    ctx.save(phase="complete")
    return {"completed": True, "shop_id": ctx.input["shop_id"]}


async def echo(ctx):
    await ctx.sleep(float(ctx.input.get("seconds", 0)))
    return {"completed": True, "input": ctx.input}


def register_examples(manager):
    manager.register("browser_demo", browser_demo)
    manager.register("echo", echo)

def build_application(store, browser, **options):
    manager, scheduler = build_platform(store, browser, **options)
    register_examples(manager)
    return manager, scheduler

