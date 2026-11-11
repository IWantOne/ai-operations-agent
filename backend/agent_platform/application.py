"""Wire the modules together in one Python process."""
from .employees import register_handlers
from .resources import ResourcePool
from .scheduler import Scheduler
from .queueing import QueueService
from .tools import register_codex


def build_application(store, browser, *, lease_seconds=None, clock=None):
    options = {"clock": clock} if clock else {}
    manager = QueueService(store, **options)
    manager.pool = ResourcePool(store, browser,
                                lease_seconds=lease_seconds, **options)
    register_handlers(manager)
    register_codex(manager)
    scheduler = Scheduler(manager, **options)
    return manager, scheduler
