from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from croniter import croniter

from engine.executor import Executor
from engine.types import Item
from store.db import Database

logger = logging.getLogger("custom-n8n.scheduler")


class Scheduler:
    def __init__(self, db: Database, executor: Executor, interval_seconds: float = 20.0) -> None:
        self.db = db
        self.executor = executor
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None
        self._fired: set[tuple[str, str, str]] = set()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="cron-scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as error:  # noqa: BLE001
                logger.warning("Scheduler tick failed: %s", error)
            await asyncio.sleep(self.interval_seconds)

    def tick(self) -> None:
        now = datetime.now().astimezone()
        minute_key = now.strftime("%Y-%m-%dT%H:%M")
        for workflow in self.db.list_workflows():
            if not workflow.active:
                continue
            for node in workflow.nodes:
                if node.type != "trigger.schedule":
                    continue
                expression = str(node.parameters.get("cron") or "").strip()
                if not expression:
                    continue
                key = (workflow.id, node.id, minute_key)
                if key in self._fired:
                    continue
                try:
                    matched = croniter.match(expression, now)
                except (ValueError, KeyError) as error:
                    logger.warning("Invalid cron '%s' on %s: %s", expression, node.name, error)
                    continue
                if matched:
                    self._fired.add(key)
                    logger.info("Scheduling workflow '%s' by cron '%s'", workflow.name, expression)
                    asyncio.create_task(
                        self.executor.run(
                            workflow,
                            trigger="schedule",
                            start_node_id=node.id,
                            items=[Item(json={"scheduledAt": now.isoformat(), "cron": expression})],
                        )
                    )

        cutoff = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        self._fired = {key for key in self._fired if key[2] >= cutoff}
