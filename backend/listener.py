from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from engine.executor import Executor, utcnow
from engine.types import Item, NodeSpec, Run, Workflow
from nodes.triggers import matching_files, resolve_directory
from store.db import Database

logger = logging.getLogger("custom-n8n.listener")


class ListenerSession:
    def __init__(
        self,
        manager: "ListenerManager",
        workflow: Workflow,
        node: NodeSpec,
        run: Run,
    ) -> None:
        self.manager = manager
        self.workflow = workflow
        self.node = node
        self.run = run
        self.cancel_event = asyncio.Event()
        self.task: asyncio.Task | None = None
        self._seen: dict[Path, tuple[int, int]] = {}
        self._pending: dict[Path, tuple[int, int]] = {}
        self._current_child_id: str | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self._loop(), name=f"listener-{self.run.id}")

    def cancel(self) -> None:
        self.cancel_event.set()
        if self._current_child_id:
            self.manager.executor.cancel(self._current_child_id)

    def _log(self, message: str, level: str = "info") -> None:
        logger.info("%s: %s", self.workflow.name, message)
        self.manager.executor.bus.publish(
            {
                "type": "log",
                "runId": self.run.id,
                "nodeId": self.node.id,
                "level": level,
                "message": message,
            }
        )

    def _finish(self, status: str, error: str | None = None) -> None:
        if self.run.status != "running":
            return
        self.run.status = status
        self.run.error = error
        self.run.finished_at = utcnow()
        self.manager.executor.save_run(self.run)
        self.manager.executor.bus.publish({"type": "run.end", "run": self.run.to_dict()})
        self.manager._finished(self)

    async def _loop(self) -> None:
        try:
            directory = resolve_directory(self.node.parameters.get("directory"))
            if not directory.is_dir():
                self._log(f"Папка не найдена: {directory}", "error")
                self._finish("error", f"Directory not found: {directory}")
                return

            patterns = str(
                self.node.parameters.get("patterns")
                or "results*.json,*.xml,newman*.json"
            )
            try:
                interval = max(
                    float(self.node.parameters.get("intervalSeconds") or 10), 1.0
                )
            except (TypeError, ValueError):
                interval = 10.0

            for path in matching_files(directory, patterns):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                self._seen[path.resolve()] = (stat.st_mtime_ns, stat.st_size)

            self._log(
                f"Слушаю {directory} ({patterns}), проверка каждые {interval:g} c. "
                "Старые файлы игнорируются. Остановить: Cancel или active=false."
            )

            while not self.cancel_event.is_set():
                current = self.manager.db.get_workflow(self.workflow.id)
                if not current or not current.active:
                    self._log("Workflow отключён, listener остановлен")
                    self._finish("canceled")
                    return

                try:
                    await asyncio.wait_for(self.cancel_event.wait(), timeout=interval)
                    break
                except asyncio.TimeoutError:
                    pass

                await self._scan(directory, patterns)

            self._finish("canceled")
        except asyncio.CancelledError:
            self._finish("canceled")
            raise
        except Exception as error:  # noqa: BLE001
            self._log(f"Ошибка listener: {error}", "error")
            self._finish("error", str(error))

    async def _scan(self, directory: Path, patterns: str) -> None:
        for path in matching_files(directory, patterns):
            resolved = path.resolve()
            try:
                stat = path.stat()
            except OSError:
                continue
            signature = (stat.st_mtime_ns, stat.st_size)

            if resolved not in self._seen:
                if self._pending.get(resolved) == signature:
                    self._seen[resolved] = signature
                    self._pending.pop(resolved, None)
                    await self._process(path)
                else:
                    self._pending[resolved] = signature
                continue

            if self._seen[resolved] == signature:
                self._pending.pop(resolved, None)
                continue

            if self._pending.get(resolved) == signature:
                self._seen[resolved] = signature
                self._pending.pop(resolved, None)
                await self._process(path)
            else:
                self._pending[resolved] = signature

    def _forward_child_event(self, child_id: str, event: dict[str, Any]) -> None:
        if event.get("type") not in ("node.start", "node.end", "log"):
            return
        forwarded = dict(event)
        forwarded["runId"] = self.run.id
        forwarded["childRunId"] = child_id
        self.manager.executor.bus.publish(forwarded)

    async def _process(self, path: Path) -> None:
        self._log(f"Найден новый отчёт: {path}")
        child_id = uuid.uuid4().hex
        unsubscribe = self.manager.executor.bus.subscribe_callback(
            child_id, lambda event: self._forward_child_event(child_id, event)
        )
        self._current_child_id = child_id
        try:
            child = await self.manager.executor.run(
                self.workflow,
                trigger="file",
                start_node_id=self.node.id,
                items=[Item(json={"filePath": str(path)})],
                run_id=child_id,
            )
        finally:
            unsubscribe()
            self._current_child_id = None

        if child.status == "success":
            self._log(f"Отчёт обработан (run {child.id})")
        else:
            self._log(
                f"Обработка завершилась со статусом {child.status}: {child.error}",
                "error",
            )


class ListenerManager:
    def __init__(self, db: Database, executor: Executor) -> None:
        self.db = db
        self.executor = executor
        self._sessions: dict[str, ListenerSession] = {}
        self._by_workflow: dict[str, str] = {}

    def start(self, workflow: Workflow, node: NodeSpec) -> Run:
        existing_id = self._by_workflow.get(workflow.id)
        if existing_id:
            existing = self._sessions.get(existing_id)
            if existing and existing.run.status == "running":
                return existing.run

        run = Run(
            id=uuid.uuid4().hex,
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            trigger="file-listener",
            started_at=utcnow(),
            status="running",
        )
        self.executor.save_run(run)
        self.executor.bus.publish({"type": "run.start", "run": run.to_dict()})

        session = ListenerSession(self, workflow, node, run)
        self._sessions[run.id] = session
        self._by_workflow[workflow.id] = run.id
        session.start()
        return run

    def cancel(self, run_id: str) -> bool:
        session = self._sessions.get(run_id)
        if session is None:
            return False
        session.cancel()
        return True

    def _finished(self, session: ListenerSession) -> None:
        self._sessions.pop(session.run.id, None)
        if self._by_workflow.get(session.workflow.id) == session.run.id:
            self._by_workflow.pop(session.workflow.id, None)

    async def shutdown(self) -> None:
        sessions = list(self._sessions.values())
        for session in sessions:
            session.cancel()
        for session in sessions:
            if session.task:
                try:
                    await asyncio.wait_for(session.task, timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    session.task.cancel()
