"""Owned subprocess execution. This adapter does not change task status or timing."""
from __future__ import annotations

import asyncio
from ..logs.errors import exception_details
from ..logs.writer import LogWriter

import json
import os
from uuid import uuid4
from .output import ProcessOutput
from .posix import PosixSupervisor
from .windows import WindowsSupervisor


class ScriptRuntime:
    def __init__(self, store, supervisor=None):
        self.store = store
        self.log = LogWriter(store, "runtime_log")
        self.supervisor = supervisor or (WindowsSupervisor() if os.name == "nt" else PosixSupervisor())
        self.processes: dict[int, asyncio.subprocess.Process] = {}
        self.spawning: dict[int, asyncio.Task] = {}
        self.handles = {}

    def _log(self, action, execution_id, content, level="INFO", call_id=None):
        self.log.write(action, json.dumps(content, ensure_ascii=False),
                       execution_id=execution_id, level=level, call_id=call_id)

    async def run(self, execution_id: int, argv: list[str], cwd=None, timeout=None) -> dict:
        if execution_id in self.processes:
            raise RuntimeError("This execution already owns a running script")
        if not argv or not all(isinstance(arg, str) for arg in argv):
            raise ValueError("argv must be a nonempty list of strings")
        # Reserve before awaiting process creation, including concurrent calls on one execution.
        self.processes[execution_id] = None
        process = None
        communication = None
        creation = None
        monitor = None
        handle = None
        output = None
        call_id = uuid4().hex

        def capture():
            return ProcessOutput(process, lambda content: self._log(
                "script_output", execution_id, content, call_id=call_id))

        try:
            handle = self.supervisor.prepare()
            options = self.supervisor.options()
            self._log("script_start", execution_id, {"argv": argv, "cwd": str(cwd) if cwd else None}, call_id=call_id)
            creation = asyncio.create_task(asyncio.create_subprocess_exec(
                *argv, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
                **options))
            self.spawning[execution_id] = creation
            process = await asyncio.shield(creation)
            self.processes[execution_id] = process
            if handle is not None:
                # No await between receiving the owned process handle and assigning its job.
                self.supervisor.start(process, handle)
                self.handles[execution_id] = handle
                self._log("script_managed", execution_id,
                          {"pid": process.pid, "crash_cleanup": self.supervisor.NAME})
                watcher = self.supervisor.watch(process, handle)
                if watcher is not None:
                    monitor = asyncio.create_task(watcher)
            output = capture()
            communication = asyncio.create_task(output.wait())
            await asyncio.wait_for(asyncio.shield(communication), timeout)
            self._log("script_result", execution_id, output.metadata(), call_id=call_id)
            return {**output.result(), "output_call_id": call_id}
        except (asyncio.CancelledError, TimeoutError) as exc:
            if isinstance(exc, TimeoutError):
                exc.timeout_seconds = timeout
                exc.output_call_id = call_id
            # Cancellation during spawn must still collect and stop the newly created child.
            if process is None and creation is not None:
                process = await creation
                self.processes[execution_id] = process
            if output is None and process is not None:
                output = capture()
            await self.stop(execution_id)
            if output is not None:
                await output.finish()
            self._log("script_timeout" if isinstance(exc, TimeoutError) else "script_cancelled",
                      execution_id, {**(output.metadata() if output else {}), **exception_details(exc)},
                      "WARNING", call_id=call_id)
            raise
        except Exception as exc:
            if output is None and process is not None:
                output = capture()
            if process is not None and process.returncode is None:
                await self.stop(execution_id)
            if output is not None:
                await output.finish()
            self._log("script_error", execution_id, exception_details(exc), "ERROR", call_id=call_id)
            raise
        finally:
            if communication is not None:
                if not communication.done():
                    communication.cancel()
                await asyncio.gather(communication, return_exceptions=True)
            if handle is not None:
                self.supervisor.release(handle)
                self.handles.pop(execution_id, None)
            if monitor is not None:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
            self.spawning.pop(execution_id, None)
            # Keep ownership when an actual stop failed, so a collector can retry.
            if process is None or process.returncode is not None:
                self.processes.pop(execution_id, None)

    async def stop(self, execution_id: int):
        process = self.processes.get(execution_id)
        if process is None and execution_id in self.spawning:
            process = await asyncio.shield(self.spawning[execution_id])
            self.processes[execution_id] = process
        if process is None or process.returncode is not None:
            return
        await self.supervisor.stop(process, self.handles.get(execution_id))
        await process.wait()
        self._log("script_stopped", execution_id, {"pid": process.pid, "returncode": process.returncode})
