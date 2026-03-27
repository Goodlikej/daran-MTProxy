"""Lightweight in-process task executor backed by daemon threads.

Usage::

    from daran_proxy_stack.lib.executor import executor

    task = executor.submit("warp-connect", lambda: warp_mod.connect_warp(cfg))
    # task.id → run_id; task.status → TaskStatus.pending / running / done / failed
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from .models import TaskInfo, TaskStatus


class TaskExecutor:
    """Submit callables, track status by run_id; no external dependencies."""

    def __init__(self) -> None:
        self._runs: dict[str, TaskInfo] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def submit(self, name: str, fn: Callable[[], str]) -> TaskInfo:
        """Dispatch *fn* in a daemon thread; return a TaskInfo immediately."""
        run_id = uuid4().hex[:12]
        task = TaskInfo(id=run_id, name=name, status=TaskStatus.pending)
        with self._lock:
            self._runs[run_id] = task
        threading.Thread(target=self._execute, args=(task, fn), daemon=True).start()
        return task

    def _execute(self, task: TaskInfo, fn: Callable[[], str]) -> None:
        task.status = TaskStatus.running
        task.started_at = datetime.now(timezone.utc)
        try:
            output = fn()
            task.output = str(output) if output else "ok"
            task.status = TaskStatus.done
        except Exception as exc:  # noqa: BLE001
            task.output = f"error: {exc}"
            task.status = TaskStatus.failed
        finally:
            task.finished_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    def get(self, run_id: str) -> TaskInfo | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_all(self) -> list[TaskInfo]:
        with self._lock:
            return list(self._runs.values())


# Module-level singleton shared across the web layer
executor = TaskExecutor()
