"""Run the A/B workbench against the authorized real shop in a fresh acceptance DB."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from scenarios import build_application
from agent_platform.__main__ import main
from live_acceptance import SHOP, STORES


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual", action="store_true",
                        help="Run tasks only when started from the Vue workbench.")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    state_dir = here.parent / "data" / "acceptance" / f"workbench-real-{stamp}"
    state_dir.mkdir(parents=True)
    config = json.loads((here / "manifest.json").read_text(encoding="utf-8"))
    due = time.time() + 15
    for task in config["tasks"]:
        if task["input"]["shop_id"] != SHOP:
            raise ValueError("Acceptance manifest must name the authorized shop")
        if args.manual:
            task["schedules"] = []
        else:
            for plan in task["schedules"]:
                plan["first_at"] = due
    manifest = state_dir / "tasks.json"
    manifest.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    main(["serve", "--db", str(state_dir / "workbench.sqlite3"),
          "--state-dir", str(state_dir), "--port", "8766",
          "--store-id", SHOP, "--store-name", STORES[SHOP], "--config", str(manifest)],
         app_factory=build_application)
