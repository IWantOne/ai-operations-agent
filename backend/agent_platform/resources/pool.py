"""Window ownership facts and single external operations; no dispatcher.

租约只有五种状态：OPENING → ACTIVE → CLOSING → RETURNED / FAILED。
没有 UNKNOWN，没有 blocked：关窗失败就留在 CLOSING，由催债人重试，
确认关闭才转 RETURNED。规则见 docs/window-lifecycle.md。
"""
import time
from ..connectors.errors import is_foreign, no_effect
from ..logs.errors import exception_details
from ..logs.writer import LogWriter
from ..settings.timing import TimingSettings

# resource_log 的 action 名称（唯一来源）
ACQUIRED = "ACQUIRED"
CLOSED = "CLOSED"
CLOSE_FAILED = "CLOSE_FAILED"
INSPECT_FAILED = "INSPECT_FAILED"
OPEN_FAILED = "OPEN_FAILED"
OPEN_REJECTED = "OPEN_REJECTED"
OWNERSHIP_CONFLICT = "OWNERSHIP_CONFLICT"
RECLAIMED = "RECLAIMED"
RECONCILED = "RECONCILED"

# 仍占着窗口的租约状态；其余（RETURNED / FAILED）已结案。
OPEN_LEASES = ("OPENING", "ACTIVE", "CLOSING")


class ResourcePool:
    def __init__(self, store, browser, *, clock=time.time, lease_seconds=None):
        self.store, self.browser, self.clock = store, browser, clock
        self.log = LogWriter(store, "resource_log")
        self.lease_seconds = lease_seconds

    def get(self, lease_id):
        row = self.store.one("SELECT * FROM resource_lease WHERE id=?", (lease_id,))
        if row is None:
            raise KeyError(lease_id)
        return row

    def _log(self, action, lease, content, level="INFO"):
        self.log.write(action, {"shop_id": lease["shop_id"],
                       "resource_id": lease.get("resource_id"), "window_ref": lease.get("window_ref"), **content},
                       execution_id=lease["execution_id"], borrow_id=lease["id"], level=level)

    def eligible(self, execution_id, shop_id, capacity):
        if not shop_id:
            raise ValueError("shop_id is required")
        stores = getattr(self.browser, "stores", None)
        if isinstance(stores, dict):
            if not stores:
                raise ValueError("店铺池为空：请先在「API 设置」里配置紫鸟连接并刷新店铺列表")
            if shop_id not in stores:
                raise ValueError(f"店铺 {shop_id} 不在紫鸟账户的 {len(stores)} 个店铺里")
        else:
            check = getattr(self.browser, "validate_shop", None)
            if callable(check):
                check(shop_id)
        own = self.store.one("SELECT * FROM resource_lease WHERE execution_id=? AND status IN (?,?,?)",
                             (execution_id, *OPEN_LEASES))
        if own:
            raise ValueError(f"执行仍持有店铺 {own['shop_id']} 的窗口；请先归还")
        resource = self.store.one("SELECT * FROM resource_info WHERE shop_id=?", (shop_id,))
        if resource and resource["status"] != "CLOSED":
            return False
        return self.store.one("SELECT COUNT(*) AS n FROM resource_info WHERE status!='CLOSED'")["n"] < capacity

    def reserve(self, execution_id, shop_id):
        # Caller holds the same transaction as the work claim.
        resource = self.store.one("SELECT * FROM resource_info WHERE shop_id=?", (shop_id,))
        rid = resource["id"] if resource else self.store.insert("resource_info", {"shop_id": shop_id})
        self.store.update("resource_info", rid, status="OPENING", window_ref=None,
                          last_checked_at=self.clock(), error_message=None)
        return self.store.insert("resource_lease", {"execution_id": execution_id, "shop_id": shop_id,
                                 "resource_id": rid, "status": "OPENING", "requested_at": self.clock()})

    def mark_closing(self, lease, error):
        """把租约转入回收中；关窗交给催债人，失败也不产生新状态。"""
        with self.store.transaction():
            self.store.update("resource_info", lease["resource_id"], status="CLOSING",
                              last_checked_at=self.clock(), error_message=error)
            self.store.update("resource_lease", lease["id"], status="CLOSING", error_message=error)

    async def acquire_once(self, lease_id):
        lease = self.get(lease_id)
        try:
            window = await self.browser.open(lease["shop_id"])
            now = self.clock()
            duration = self.lease_seconds if self.lease_seconds is not None else TimingSettings(self.store).read()["window_lease_seconds"]
            with self.store.transaction():
                self.store.update("resource_info", lease["resource_id"], status="OPEN", window_ref=window,
                                  last_checked_at=now, error_message=None)
                self.store.update("resource_lease", lease_id, status="ACTIVE", window_ref=window,
                                  acquired_at=now, expires_at=now+duration, error_message=None)
                self._log(ACQUIRED, lease, {"window_ref": window})
            return self.get(lease_id)
        except BaseException as exc:
            details = exception_details(exc)
            exc.retry_safe = False
            if no_effect(exc):
                # A declared pre-effect rejection still needs positive absence evidence.
                try:
                    observed = await self.browser.inspect(lease["shop_id"])
                    if observed is False:
                        with self.store.transaction():
                            self.store.update("resource_info", lease["resource_id"], status="CLOSED",
                                              last_checked_at=self.clock(), error_message=details["error"])
                            self.store.update("resource_lease", lease_id, status="FAILED", released_at=self.clock(),
                                              error_message=details["error"])
                            self._log(OPEN_REJECTED, lease, {"operation": "open", "confirmed_no_effect": True, **details}, "ERROR")
                        exc.retry_safe = True
                except Exception as inspection:
                    self._log(INSPECT_FAILED, lease, {"operation": "verify_open_absence",
                              **exception_details(inspection), "original_error": details}, "ERROR")
                if getattr(exc, "retry_safe", False):
                    raise
            if is_foreign(exc):
                # 本子之外的窗口：不动，报错让人处理（见 docs/window-lifecycle.md）。
                with self.store.transaction():
                    self.store.update("resource_info", lease["resource_id"], status="CLOSED",
                                      last_checked_at=self.clock(), error_message=details["error"])
                    self.store.update("resource_lease", lease_id, status="FAILED", released_at=self.clock(),
                                      error_message=details["error"])
                    self._log(OWNERSHIP_CONFLICT, lease, {"operation": "open", **details}, "ERROR")
                raise
            # 远端结果不明：窗口可能已经打开，交给催债人回收。
            self.mark_closing(lease, details["error"])
            self._log(OPEN_FAILED, lease, {"operation": "open", **details}, "ERROR")
            raise

    async def release_once(self, lease_id, *, user_stopped):
        lease = self.get(lease_id)
        if lease["status"] in {"RETURNED", "FAILED"}:
            return lease
        if not user_stopped:
            raise RuntimeError("窗口使用者尚未确认停止，不能关闭或释放容量")
        self.mark_closing(lease, None)
        return await self._close(lease_id, "release")

    async def reclaim(self, lease):
        """催债人：关窗并确认；失败留在 CLOSING，下次再试。"""
        lease = self.get(lease["id"])
        if lease["status"] in {"RETURNED", "FAILED"}:
            return True
        if lease["status"] == "OPENING":
            # 窗口可能根本没打开：先核验，确认没开就直接结案。
            try:
                observed = await self.browser.inspect(lease["shop_id"])
            except Exception:
                observed = None
            if observed is False:
                with self.store.transaction():
                    self.store.update("resource_info", lease["resource_id"], status="CLOSED",
                                      last_checked_at=self.clock(), error_message=None)
                    self.store.update("resource_lease", lease["id"], status="RETURNED",
                                      released_at=self.clock(), error_message=None)
                    self._log(RECONCILED, lease, {"operation": "reclaim_absent"})
                return True
        self.mark_closing(lease, lease.get("error_message") or "等待回收")
        try:
            await self._close(lease["id"], "reclaim")
            return True
        except Exception:
            return False

    async def _close(self, lease_id, operation):
        lease = self.get(lease_id)
        try:
            # Connector ownership checks must reject unrelated windows.
            refs = [lease["window_ref"]] if lease.get("window_ref") else await self.browser.find_windows(lease["shop_id"])
            for ref in refs:
                await self.browser.close(ref)
                observed = await self.browser.inspect(ref)
                if observed is not False:
                    raise RuntimeError(f"关闭后检查窗口 {ref} 返回 {observed!r}，未确认关闭；对端未提供更具体原因")
            with self.store.transaction():
                self.store.update("resource_info", lease["resource_id"], status="CLOSED", window_ref=None,
                                  last_checked_at=self.clock(), error_message=None)
                self.store.update("resource_lease", lease_id, status="RETURNED", released_at=self.clock(), error_message=None)
                self._log(CLOSED, lease, {"operation": operation})
            return self.get(lease_id)
        except BaseException as exc:
            details = exception_details(exc)
            changed = details["error"] != (lease.get("error_message") or "")
            with self.store.transaction():
                self.store.update("resource_info", lease["resource_id"], status="CLOSING",
                                  last_checked_at=self.clock(), error_message=details["error"])
                self.store.update("resource_lease", lease_id, status="CLOSING", error_message=details["error"])
                if changed:
                    self._log(CLOSE_FAILED, lease, {"operation": operation, **details}, "ERROR")
            raise

    async def inspect_once(self, lease_id, *, user_stopped):
        lease = self.get(lease_id)
        if lease["status"] in {"RETURNED", "FAILED"}:
            return lease
        if not user_stopped:
            raise RuntimeError("所属执行尚未停止，核验不能解除窗口占用")
        try:
            # Ziniao inspect accepts the authorized shop ID even when open never returned a ref.
            refs = [lease.get("window_ref") or lease["shop_id"]]
            for ref in refs:
                observed = await self.browser.inspect(ref)
                if observed is not False:
                    raise RuntimeError(f"核验窗口 {ref} 返回 {observed!r}，窗口仍存在或对端未提供关闭确认")
            with self.store.transaction():
                self.store.update("resource_info", lease["resource_id"], status="CLOSED", window_ref=None,
                                  last_checked_at=self.clock(), error_message=None)
                self.store.update("resource_lease", lease_id, status="RETURNED", released_at=self.clock(), error_message=None)
                self._log(RECONCILED, lease, {"operation": "inspect_closed"})
            return self.get(lease_id)
        except BaseException as exc:
            details = exception_details(exc)
            self._log(INSPECT_FAILED, lease, {"operation": "inspect_closed", **details}, "ERROR")
            raise
