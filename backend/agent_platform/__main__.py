import argparse
import asyncio
import json
import hashlib
from pathlib import Path

from .application import build_application
from .employees import ROOT as EMPLOYEES_ROOT, load_employee_tasks
from .settings import load_tasks
from .settings.platform import ROOT, database_target, read_settings
from .connectors.connections import Connections
from .database import Store
from .settings.service_lock import database_lock


async def serve(args, app_factory):
    from .api import start_panel
    store = Store(args.db)
    stores = {str(args.store_id): args.store_name} if args.store_id else {}
    connections = Connections(store, stores, args.connection_file)
    browser = connections.browser
    manager, scheduler = app_factory(store, browser)
    manager.external_manifest = Path(args.config).resolve() if args.config else None
    manager.employee_root = (manager.external_manifest.parent / "employees"
                             if manager.external_manifest else EMPLOYEES_ROOT)
    if manager.external_manifest:
        load_tasks(manager, manager.external_manifest)
    load_employee_tasks(manager)
    from .queueing.connections import register_connections
    register_connections(manager, connections)
    try:
        await connections.refresh()
    except Exception as exc:
        print(f"店铺池加载失败：{exc}", flush=True)
    await manager.recover()
    scheduler.skip_missed()
    shutdown = asyncio.Event()
    panel = start_panel(manager, args.port, shutdown_event=shutdown, connections=connections)
    print(f"Agent Platform: http://127.0.0.1:{args.port}", flush=True)
    try:
        while not shutdown.is_set():
            scheduler.tick()
            await manager.tick()
            await asyncio.sleep(0.05)
    finally:
        try:
            await manager.drain()
        finally:
            await asyncio.to_thread(panel.shutdown)
            await asyncio.to_thread(panel.server_close)
            store.close()


def main(argv=None, *, app_factory=build_application):
    config = read_settings()
    service = config["service"]
    parser = argparse.ArgumentParser(description="Agent platform backend")
    commands = parser.add_subparsers(dest="command", required=True)
    web = commands.add_parser("serve", help="Start the local API and Vue workbench")
    web.add_argument("--db", help="SQLite file or PostgreSQL connection URL")
    web.add_argument("--config", help="Task manifest path")
    web.add_argument("--port", type=int, default=service["port"])
    web.add_argument("--store-id", help="Authorized Ziniao store ID; supply together with --store-name")
    web.add_argument("--store-name", help="Exact Ziniao store name; supply together with --store-id")
    web.add_argument("--state-dir", default=str(ROOT / service["state_dir"]))
    inspect = commands.add_parser("inspect", help="Read database task/execution counts")
    inspect.add_argument("--db")
    args = parser.parse_args(argv)
    if args.command == "serve":
        if args.store_id is None and args.store_name is None:
            stores = config.get("ziniao", {})
            args.store_id = stores.get("store_id")
            args.store_name = stores.get("store_name")
        if (args.store_id is None) != (args.store_name is None):
            parser.error("--store-id 与 --store-name 必须同时提供")
        if args.store_id is not None and (not str(args.store_id).isdigit() or not str(args.store_name).strip()):
            parser.error("店铺 ID 必须是数字，店铺名称不能为空")
    if not args.db:
        args.db = database_target(config["database"])
    if args.command == "serve":
        try:
            identity = args.db if args.db.startswith(("postgres://", "postgresql://")) else str(Path(args.db).resolve())
            key = hashlib.sha256(identity.encode()).hexdigest()[:20]
            args.connection_file = Path(args.state_dir) / (key + ".connection")
            with database_lock(args.db):
                asyncio.run(serve(args, app_factory))
        except KeyboardInterrupt:
            pass
    else:
        with Store(args.db) as store:
            print(json.dumps({table: store.all(f"SELECT * FROM {table} ORDER BY id") for table in
                              ("task_info", "work_request", "work_attempt", "retry_budget", "control_command", "execution_info", "resource_info", "resource_lease")},
                             ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
