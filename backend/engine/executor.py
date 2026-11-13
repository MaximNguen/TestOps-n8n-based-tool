from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .events import EventBus
from .expressions import create_scope, resolve_parameters
from .registry import get_definition
from .types import (
    Connection,
    CredentialReader,
    Item,
    NodeContext,
    NodeRun,
    NodeSpec,
    Run,
    Workflow,
)


class RunCanceled(Exception):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_items(values: Any) -> list[Item]:
    if not isinstance(values, list):
        raise ValueError("Node output branch must be a list of items")
    items: list[Item] = []
    for value in values:
        if isinstance(value, Item):
            items.append(value)
        elif isinstance(value, dict) and isinstance(value.get("json"), dict):
            items.append(Item(json=value["json"], binary=value.get("binary")))
        elif isinstance(value, dict):
            items.append(Item(json=value))
        else:
            items.append(Item(json={"value": value}))
    return items


def normalize_outputs(result: Any, input_items: list[Item]) -> dict[str, list[Item]]:
    if result is None:
        return {"main": list(input_items)}
    if isinstance(result, list):
        return {"main": normalize_items(result)}
    if isinstance(result, dict):
        outputs = {str(branch): normalize_items(items) for branch, items in result.items()}
        return outputs or {"main": []}
    raise ValueError(f"Unsupported node output type: {type(result).__name__}")


def count_items(outputs: dict[str, list[Item]]) -> int:
    return sum(len(items) for items in outputs.values())


def preview_outputs(outputs: dict[str, list[Item]]) -> Any:
    sample = {branch: [item.to_dict() for item in items[:5]] for branch, items in outputs.items()}
    try:
        serialized = json.dumps(sample, default=str)
    except (TypeError, ValueError):
        serialized = repr(sample)
    if len(serialized) <= 20_000:
        return sample
    return {"truncated": True, "totalCharacters": len(serialized), "sample": sample}


@dataclass
class _Graph:
    nodes_by_id: dict[str, NodeSpec]
    names_to_ids: dict[str, str]
    incoming: dict[str, list[Connection]] = field(default_factory=dict)
    outgoing: dict[str, list[Connection]] = field(default_factory=dict)
    indegree: dict[str, int] = field(default_factory=dict)


def build_graph(workflow: Workflow) -> _Graph:
    nodes_by_id: dict[str, NodeSpec] = {}
    names_to_ids: dict[str, str] = {}
    for node in workflow.nodes:
        if node.id in nodes_by_id:
            raise ValueError(f"Duplicate node id: {node.id}")
        if node.name in names_to_ids:
            raise ValueError(f"Duplicate node name: {node.name}")
        nodes_by_id[node.id] = node
        names_to_ids[node.name] = node.id

    graph = _Graph(nodes_by_id=nodes_by_id, names_to_ids=names_to_ids)
    for node in workflow.nodes:
        graph.incoming[node.id] = []
        graph.outgoing[node.id] = []
        graph.indegree[node.id] = 0

    for connection in workflow.connections:
        if connection.source not in nodes_by_id or connection.target not in nodes_by_id:
            raise ValueError(
                f"Invalid connection {connection.source} -> {connection.target}: node does not exist"
            )
        graph.incoming[connection.target].append(connection)
        graph.outgoing[connection.source].append(connection)
        graph.indegree[connection.target] += 1

    return graph


class Executor:
    def __init__(
        self,
        *,
        credentials: CredentialReader,
        env: dict[str, str],
        save_run: Callable[[Run], None],
        bus: EventBus,
    ) -> None:
        self.credentials = credentials
        self.env = env
        self.save_run = save_run
        self.bus = bus
        self._cancellations: dict[str, asyncio.Event] = {}

    def cancel(self, run_id: str) -> bool:
        event = self._cancellations.get(run_id)
        if event is None:
            return False
        event.set()
        return True

    async def run(
        self,
        workflow: Workflow,
        *,
        trigger: str,
        start_node_id: str | None = None,
        items: list[Item] | None = None,
        run_id: str | None = None,
    ) -> Run:
        run = Run(
            id=run_id or uuid.uuid4().hex,
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            trigger=trigger,
            started_at=utcnow(),
        )
        cancel = asyncio.Event()
        self._cancellations[run.id] = cancel
        self.bus.publish({"type": "run.start", "run": run.to_dict()})
        self.save_run(run)

        try:
            await self._execute(workflow, run, start_node_id, items, cancel)
            if cancel.is_set():
                run.status = "canceled"
                run.error = "Run canceled"
            elif any(node_run.status == "error" for node_run in run.node_runs):
                run.status = "error"
            else:
                run.status = "success"
        except RunCanceled:
            run.status = "canceled"
            run.error = "Run canceled"
        except Exception as error:  # noqa: BLE001
            run.status = "error"
            run.error = str(error)
        finally:
            self._cancellations.pop(run.id, None)
            run.finished_at = utcnow()
            self.save_run(run)
            self.bus.publish({"type": "run.end", "run": run.to_dict()})

        return run

    async def _execute(
        self,
        workflow: Workflow,
        run: Run,
        start_node_id: str | None,
        initial_items: list[Item] | None,
        cancel: asyncio.Event,
    ) -> None:
        graph = build_graph(workflow)
        if not workflow.nodes:
            raise ValueError("Workflow has no nodes")

        outputs_by_node: dict[str, dict[str, list[Item]]] = {}
        items_by_node: dict[str, list[Item]] = {}
        remaining = dict(graph.indegree)
        executed: set[str] = set()

        def get_node_items(name_or_id: str) -> list[Item]:
            node_id = name_or_id if name_or_id in graph.nodes_by_id else graph.names_to_ids.get(name_or_id)
            if not node_id:
                return []
            outputs = outputs_by_node.get(node_id)
            if not outputs:
                return []
            return outputs.get("main") or next(iter(outputs.values()), [])

        seed_items = initial_items if initial_items is not None else [Item()]

        start_nodes = [node for node in workflow.nodes if graph.indegree[node.id] == 0]
        if not start_nodes:
            raise ValueError("Workflow has no start node (every node has an incoming connection)")

        if start_node_id:
            if start_node_id not in graph.nodes_by_id:
                raise ValueError(f"Start node not found: {start_node_id}")
            queue: deque[str] = deque([start_node_id])
            items_by_node[start_node_id] = list(seed_items)
        else:
            queue = deque(node.id for node in start_nodes)
            for node in start_nodes:
                items_by_node[node.id] = list(seed_items)

        reachable: set[str] = set()
        stack = list(queue)
        while stack:
            node_id = stack.pop()
            if node_id in reachable or node_id not in graph.nodes_by_id:
                continue
            reachable.add(node_id)
            stack.extend(connection.target for connection in graph.outgoing.get(node_id, []))

        while queue:
            if cancel.is_set():
                raise RunCanceled()

            node_id = queue.popleft()
            if node_id in executed:
                continue
            executed.add(node_id)

            node = graph.nodes_by_id[node_id]
            incoming = graph.incoming.get(node_id, [])
            input_items = items_by_node.get(node_id, [])
            node_run = NodeRun(
                node_id=node.id,
                name=node.name,
                type=node.type,
                started_at=utcnow(),
                items_in=len(input_items),
            )
            run.node_runs.append(node_run)
            self.bus.publish(
                {
                    "type": "node.start",
                    "runId": run.id,
                    "nodeId": node.id,
                    "nodeName": node.name,
                    "nodeType": node.type,
                }
            )

            try:
                if node.disabled:
                    node_run.status = "skipped"
                    node_run.logs.append("Node is disabled, items passed through")
                    outputs: dict[str, list[Item]] = {"main": list(input_items)}
                elif incoming and not input_items:
                    node_run.status = "skipped"
                    node_run.logs.append("No input items, node skipped")
                    outputs = {}
                else:
                    outputs = await self._execute_node(
                        workflow,
                        node,
                        input_items,
                        run,
                        graph,
                        outputs_by_node,
                        cancel,
                        node_run,
                    )
                    node_run.status = "success"
            except Exception as error:  # noqa: BLE001
                node_run.status = "error"
                node_run.error = str(error)
                node_run.finished_at = utcnow()
                node_run.output = preview_outputs(outputs_by_node.get(node.id, {}))
                self.bus.publish({"type": "node.end", "runId": run.id, "nodeRun": node_run.to_dict()})
                self.save_run(run)
                raise

            node_run.items_out = count_items(outputs)
            node_run.finished_at = utcnow()
            node_run.output = preview_outputs(outputs)
            outputs_by_node[node.id] = outputs
            self.bus.publish({"type": "node.end", "runId": run.id, "nodeRun": node_run.to_dict()})
            self.save_run(run)

            for connection in graph.outgoing.get(node_id, []):
                branch_items = outputs.get(connection.output or "main", [])
                items_by_node[connection.target] = items_by_node.get(connection.target, []) + list(
                    branch_items
                )
                remaining[connection.target] -= 1
                if remaining[connection.target] == 0 and connection.target not in executed:
                    queue.append(connection.target)

        missing = [
            node.name for node in workflow.nodes if node.id in reachable and node.id not in executed
        ]
        if missing:
            raise ValueError(f"Cycle detected, nodes never became ready: {', '.join(missing)}")

    async def _execute_node(
        self,
        workflow: Workflow,
        node: NodeSpec,
        input_items: list[Item],
        run: Run,
        graph: _Graph,
        outputs_by_node: dict[str, dict[str, list[Item]]],
        cancel: asyncio.Event,
        node_run: NodeRun,
    ) -> dict[str, list[Item]]:
        definition = get_definition(node.type)

        def get_node_items(name_or_id: str) -> list[Item]:
            node_id = name_or_id if name_or_id in graph.nodes_by_id else graph.names_to_ids.get(name_or_id)
            if not node_id:
                return []
            outputs = outputs_by_node.get(node_id)
            if not outputs:
                return []
            return outputs.get("main") or next(iter(outputs.values()), [])

        scope = create_scope(
            json_data=input_items[0].json if input_items else {},
            items=input_items,
            env=self.env,
            run_id=run.id,
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            get_node_items=get_node_items,
        )
        params = resolve_parameters(node.parameters or {}, scope)

        def log(message: str, level: str = "info") -> None:
            node_run.logs.append(message)
            self.bus.publish(
                {
                    "type": "log",
                    "runId": run.id,
                    "nodeId": node.id,
                    "level": level,
                    "message": message,
                }
            )

        context = NodeContext(
            workflow=workflow,
            node=node,
            input=input_items,
            params=params,
            credentials=self.credentials,
            env=self.env,
            run_id=run.id,
            log=log,
            get_node_items=get_node_items,
            cancel_event=cancel,
            raw_params=dict(node.parameters or {}),
            scope=scope,
        )

        result = definition.execute(context)
        if inspect.isawaitable(result):
            result = await result
        return normalize_outputs(result, input_items)
