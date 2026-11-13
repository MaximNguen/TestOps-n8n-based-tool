from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._all: set[asyncio.Queue[dict[str, Any]]] = set()

    def publish(self, event: dict[str, Any]) -> None:
        run_id = event.get("runId") or (event.get("run") or {}).get("id")
        targets = list(self._subscribers.get(run_id, set())) if run_id else []
        targets.extend(list(self._all))
        for queue in targets:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    async def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2000)
        self._subscribers[run_id].add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers[run_id].discard(queue)
        if not self._subscribers[run_id]:
            self._subscribers.pop(run_id, None)

    async def subscribe_all(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2000)
        self._all.add(queue)
        return queue

    def unsubscribe_all(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._all.discard(queue)
