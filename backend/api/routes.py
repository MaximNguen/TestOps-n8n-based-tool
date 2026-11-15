from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from engine.events import EventBus
from engine.executor import Executor, build_graph
from engine.registry import catalog, has_definition
from engine.types import Connection, Item, NodeSpec, Workflow
from listener import ListenerManager
from store.db import Database


class WorkflowPayload(BaseModel):
    name: str = "Untitled workflow"
    description: str = ""
    active: bool = True
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    connections: list[dict[str, Any]] = Field(default_factory=list)


class RunPayload(BaseModel):
    data: Any = None
    startNodeId: str | None = None


class CredentialPayload(BaseModel):
    name: str
    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class CredentialUpdatePayload(BaseModel):
    name: str | None = None
    type: str | None = None
    data: dict[str, Any] | None = None


class ImportPayload(BaseModel):
    workflow: dict[str, Any]
    keepId: bool = False


def _build_workflow(payload: WorkflowPayload, existing: Workflow | None = None) -> Workflow:
    try:
        nodes = [NodeSpec.from_dict(node) for node in payload.nodes]
        connections = [Connection.from_dict(connection) for connection in payload.connections]
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"Invalid workflow shape: {error}") from error

    for node in nodes:
        if not has_definition(node.type):
            raise HTTPException(status_code=400, detail=f"Unknown node type: {node.type}")

    ids = {node.id for node in nodes}
    for connection in connections:
        if connection.source not in ids or connection.target not in ids:
            raise HTTPException(
                status_code=400,
                detail=f"Connection points to a missing node: {connection.source} -> {connection.target}",
            )

    now = workflow_now()
    workflow = Workflow(
        id=existing.id if existing else uuid.uuid4().hex,
        name=payload.name.strip() or "Untitled workflow",
        description=payload.description,
        active=payload.active,
        nodes=nodes,
        connections=connections,
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    if nodes:
        try:
            build_graph(workflow)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    return workflow


def workflow_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _to_item(value: Any) -> Item:
    if (
        isinstance(value, dict)
        and isinstance(value.get("json"), dict)
        and set(value.keys()) <= {"json", "binary"}
    ):
        return Item(json=value["json"], binary=value.get("binary"))
    if isinstance(value, dict):
        return Item(json=value)
    return Item(json={"value": value})


def _run_items(data: Any) -> list[Item] | None:
    if data is None:
        return None
    if isinstance(data, list):
        return [_to_item(entry) for entry in data]
    if isinstance(data, str):
        return [Item(json={"body": data})]
    return [Item(json=data)]


async def _read_webhook_body(request: Request) -> Any:
    raw = await request.body()
    if not raw:
        return None
    content_type = request.headers.get("content-type", "")
    if "json" in content_type or raw.lstrip()[:1] in (b"{", b"["):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.decode("utf-8", "replace")
    return raw.decode("utf-8", "replace")


def build_router(
    db: Database,
    executor: Executor,
    bus: EventBus,
    listeners: ListenerManager,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "workflows": db.count_workflows()}

    @router.get("/api/nodes")
    async def nodes_catalog() -> list[dict[str, Any]]:
        return catalog()

    @router.get("/api/workflows")
    async def list_workflows() -> list[dict[str, Any]]:
        return [workflow.to_dict() for workflow in db.list_workflows()]

    @router.post("/api/workflows", status_code=201)
    async def create_workflow(payload: WorkflowPayload) -> dict[str, Any]:
        workflow = _build_workflow(payload)
        if not workflow.nodes:
            workflow.nodes = [
                NodeSpec(
                    id=uuid.uuid4().hex,
                    type="trigger.manual",
                    name="Manual trigger",
                    position={"x": 80, "y": 200},
                    parameters={},
                )
            ]
        db.save_workflow(workflow)
        return workflow.to_dict()

    @router.get("/api/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str) -> dict[str, Any]:
        workflow = db.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return workflow.to_dict()

    @router.put("/api/workflows/{workflow_id}")
    async def update_workflow(workflow_id: str, payload: WorkflowPayload) -> dict[str, Any]:
        existing = db.get_workflow(workflow_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Workflow not found")
        workflow = _build_workflow(payload, existing)
        db.save_workflow(workflow)
        return workflow.to_dict()

    @router.delete("/api/workflows/{workflow_id}")
    async def delete_workflow(workflow_id: str) -> dict[str, Any]:
        if not db.delete_workflow(workflow_id):
            raise HTTPException(status_code=404, detail="Workflow not found")
        return {"deleted": True}

    @router.post("/api/workflows/{workflow_id}/run")
    async def run_workflow(workflow_id: str, payload: RunPayload) -> dict[str, Any]:
        workflow = db.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        listener_node = None
        if payload.startNodeId:
            candidate = next(
                (node for node in workflow.nodes if node.id == payload.startNodeId),
                None,
            )
            if candidate and candidate.type == "trigger.testResultsFile":
                listener_node = candidate
        else:
            listener_node = next(
                (node for node in workflow.nodes if node.type == "trigger.testResultsFile"),
                None,
            )

        if listener_node is not None:
            run = listeners.start(workflow, listener_node)
            return {"runId": run.id, "listener": True}

        run_id = uuid.uuid4().hex
        asyncio.create_task(
            executor.run(
                workflow,
                trigger="manual",
                start_node_id=payload.startNodeId,
                items=_run_items(payload.data),
                run_id=run_id,
            )
        )
        await asyncio.sleep(0)
        return {"runId": run_id}

    @router.post("/api/workflows/import", status_code=201)
    async def import_workflow(payload: ImportPayload) -> dict[str, Any]:
        data = dict(payload.workflow)
        data.setdefault("id", uuid.uuid4().hex)
        try:
            workflow = Workflow.from_dict(data)
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=f"Invalid workflow: {error}") from error
        for node in workflow.nodes:
            if not has_definition(node.type):
                raise HTTPException(status_code=400, detail=f"Unknown node type: {node.type}")
        if not payload.keepId or db.get_workflow(workflow.id):
            workflow.id = uuid.uuid4().hex
        workflow.created_at = workflow_now()
        workflow.updated_at = workflow.created_at
        db.save_workflow(workflow)
        return workflow.to_dict()

    @router.get("/api/runs")
    async def list_runs(workflowId: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return db.list_runs(workflowId, min(max(limit, 1), 200))

    @router.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        run = db.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @router.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict[str, Any]:
        canceled = listeners.cancel(run_id)
        if not canceled:
            canceled = executor.cancel(run_id)
        return {"canceled": canceled}

    @router.post("/api/runs/{run_id}/retry/{node_id}")
    async def retry_node(run_id: str, node_id: str) -> dict[str, Any]:
        run = db.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        workflow = db.get_workflow(str(run.get("workflowId") or ""))
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        node = next((entry for entry in workflow.nodes if entry.id == node_id), None)
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        if node.type == "trigger.testResultsFile":
            raise HTTPException(
                status_code=400,
                detail="Listener trigger cannot be retried separately; start the workflow again",
            )
        stored = db.get_node_input(run_id, node_id)
        if not stored:
            raise HTTPException(
                status_code=409,
                detail="Input for this node was not stored or is too large; run the workflow again",
            )
        items = [
            Item(json=entry.get("json") or {}, binary=entry.get("binary"))
            for entry in stored
            if isinstance(entry, dict)
        ]
        new_run_id = uuid.uuid4().hex
        asyncio.create_task(
            executor.run(
                workflow,
                trigger="retry",
                start_node_id=node_id,
                items=items,
                run_id=new_run_id,
                single_node=True,
            )
        )
        await asyncio.sleep(0)
        return {"runId": new_run_id}

    @router.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str) -> StreamingResponse:
        async def stream():
            snapshot = db.get_run(run_id)
            if snapshot:
                yield (
                    "event: snapshot\n"
                    f"data: {json.dumps({'type': 'snapshot', 'run': snapshot}, ensure_ascii=False, default=str)}\n\n"
                )
                if snapshot.get("status") != "running":
                    return
            queue = await bus.subscribe(run_id)
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    yield (
                        f"event: {event.get('type', 'message')}\n"
                        f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                    )
                    if event.get("type") == "run.end":
                        break
            finally:
                bus.unsubscribe(run_id, queue)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/api/credentials")
    async def list_credentials() -> list[dict[str, Any]]:
        return [credential.to_dict() for credential in db.list_credentials()]

    @router.post("/api/credentials", status_code=201)
    async def create_credential(payload: CredentialPayload) -> dict[str, Any]:
        credential = db.save_credential(
            name=payload.name,
            credential_type=payload.type,
            data=payload.data,
        )
        return credential.to_dict()

    @router.put("/api/credentials/{credential_id}")
    async def update_credential(
        credential_id: str, payload: CredentialUpdatePayload
    ) -> dict[str, Any]:
        try:
            existing_data = db.get_credential_data(credential_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        data = payload.data if payload.data is not None else existing_data
        try:
            credential = db.save_credential(
                name=payload.name or "credential",
                credential_type=payload.type or "http",
                data=data,
                credential_id=credential_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return credential.to_dict()

    @router.delete("/api/credentials/{credential_id}")
    async def delete_credential(credential_id: str) -> dict[str, Any]:
        return {"deleted": db.delete_credential(credential_id)}

    @router.api_route(
        "/webhook/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )
    async def webhook(path: str, request: Request) -> dict[str, Any]:
        found = db.find_webhook(path, request.method)
        if not found:
            raise HTTPException(status_code=404, detail=f"No active webhook trigger for '{path}'")
        workflow, node = found
        body = await _read_webhook_body(request)
        items = [
            Item(
                json={
                    "body": body,
                    "headers": dict(request.headers),
                    "query": dict(request.query_params),
                    "method": request.method,
                    "path": path,
                }
            )
        ]
        run_id = uuid.uuid4().hex
        asyncio.create_task(
            executor.run(
                workflow,
                trigger="webhook",
                start_node_id=node.id,
                items=items,
                run_id=run_id,
            )
        )
        await asyncio.sleep(0)
        return {"runId": run_id, "workflowId": workflow.id, "trigger": path}

    return router
