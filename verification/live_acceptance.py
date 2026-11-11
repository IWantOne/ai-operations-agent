"""Optional single-shop live smoke test of the unified controller; never run by unittest."""
import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))
from scenarios import build_application
from agent_platform.database import Store
from agent_platform.connectors.ziniao import CliBrowser
from agent_platform.settings.service_lock import database_lock
from agent_platform.queueing.models import TERMINAL

SHOP="27156808109149"
STORES={SHOP:"VCC子账号-US"}


async def run(path):
    with Store(path) as store:
        browser=CliBrowser(store,STORES)
        service,_=build_application(store,browser)
        await service.recover()
        service.queue_settings.save({**service.queue_settings.read(),"tasks":2,"windows":1})
        ids=[]
        for name in ("A","B"):
            tid=service.create_task(name,handler="browser_demo",input_data={"shop_id":SHOP,"work_seconds":2,"subprocess":True})
            ids.append(service.submit(tid))
        try:
            while not all(service.repository.get(r)["status"] in TERMINAL for r in ids):
                await service.tick()
                await asyncio.sleep(.03)
            for rid in ids:
                row=service.repository.get(rid)
                if row["status"]!="SUCCEEDED":
                    raise RuntimeError(row["error_data"])
            print(f"Two task requests completed through the unified queue. Evidence: {path}")
        finally:
            await service.drain()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-store",required=True,choices=[SHOP],help="Confirm the real authorized store to open and close")
    parser.parse_args()
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path=ROOT/"data"/"acceptance"/f"unified-real-{stamp}.sqlite3"
    path.parent.mkdir(parents=True,exist_ok=True)
    with database_lock(path):
        asyncio.run(run(path))
