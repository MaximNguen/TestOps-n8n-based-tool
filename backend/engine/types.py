from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

JsonObject = dict[str, Any]


@dataclass
class Item:
    json: JsonObject = field(default_factory=dict)
    binary: dict[str, str] | None = None

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {"json": self.json}
        if self.binary:
            payload["binary"] = self.binary
        return payload


@dataclass
class NodeSpec:
    id: str
    type: str
    name: str
    position: dict[str, float] = field(default_factory=lambda: {"x": 0.0, "y": 0.0})
    parameters: JsonObject = field(default_factory=dict)
    disabled: bool = False

    def to_dict(self) -> JsonObject:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "position": self.position,
            "parameters": self.parameters,
            "disabled": self.disabled,
        }

    @classmethod
    def from_dict(cls, data: JsonObject) -> "NodeSpec":
        position = data.get("position") or {}
        return cls(
            id=str(data["id"]),
            type=str(data["type"]),
            name=str(data.get("name") or data["type"]),
            position={
                "x": float(position.get("x", 0)),
                "y": float(position.get("y", 0)),
            },
            parameters=dict(data.get("parameters") or {}),
            disabled=bool(data.get("disabled", False)),
        )


@dataclass
class Connection:
    source: str
    target: str
    output: str = "main"

    def to_dict(self) -> JsonObject:
        return {"from": self.source, "to": self.target, "output": self.output}

    @classmethod
    def from_dict(cls, data: JsonObject) -> "Connection":
        return cls(
            source=str(data.get("from") or data.get("source")),
            target=str(data.get("to") or data.get("target")),
            output=str(data.get("output") or "main"),
        )


@dataclass
class Workflow:
    id: str
    name: str
    nodes: list[NodeSpec]
    connections: list[Connection]
    active: bool = True
    description: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> JsonObject:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "active": self.active,
            "nodes": [node.to_dict() for node in self.nodes],
            "connections": [connection.to_dict() for connection in self.connections],
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: JsonObject) -> "Workflow":
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or "Untitled workflow"),
            description=str(data.get("description") or ""),
            active=bool(data.get("active", True)),
            nodes=[NodeSpec.from_dict(node) for node in data.get("nodes") or []],
            connections=[
                Connection.from_dict(connection) for connection in data.get("connections") or []
            ],
            created_at=str(data.get("createdAt") or ""),
            updated_at=str(data.get("updatedAt") or ""),
        )


@dataclass
class NodeRun:
    node_id: str
    name: str
    type: str
    status: str = "running"
    started_at: str = ""
    finished_at: str | None = None
    error: str | None = None
    items_in: int = 0
    items_out: int = 0
    logs: list[str] = field(default_factory=list)
    output: Any = None

    def to_dict(self) -> JsonObject:
        return {
            "nodeId": self.node_id,
            "name": self.name,
            "type": self.type,
            "status": self.status,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "error": self.error,
            "itemsIn": self.items_in,
            "itemsOut": self.items_out,
            "logs": self.logs,
            "output": self.output,
        }


@dataclass
class Run:
    id: str
    workflow_id: str
    workflow_name: str
    trigger: str
    status: str = "running"
    started_at: str = ""
    finished_at: str | None = None
    error: str | None = None
    node_runs: list[NodeRun] = field(default_factory=list)

    def to_dict(self) -> JsonObject:
        return {
            "id": self.id,
            "workflowId": self.workflow_id,
            "workflowName": self.workflow_name,
            "trigger": self.trigger,
            "status": self.status,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "error": self.error,
            "nodeRuns": [node_run.to_dict() for node_run in self.node_runs],
        }


@dataclass
class CredentialSummary:
    id: str
    name: str
    type: str
    created_at: str
    updated_at: str

    def to_dict(self) -> JsonObject:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class CredentialReader(Protocol):
    def get(self, credential_id: str) -> JsonObject: ...


@dataclass
class NodeProperty:
    name: str
    display_name: str
    type: str
    default: Any = None
    description: str = ""
    required: bool = False
    options: list[dict[str, str]] | None = None
    credential_type: str | None = None
    rows: int = 3

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "name": self.name,
            "displayName": self.display_name,
            "type": self.type,
            "default": self.default,
            "description": self.description,
            "required": self.required,
            "rows": self.rows,
        }
        if self.options:
            payload["options"] = self.options
        if self.credential_type:
            payload["credentialType"] = self.credential_type
        return payload


NodeExecute = Callable[["NodeContext"], Awaitable[dict[str, list[Item]]] | dict[str, list[Item]]]


@dataclass
class NodeDefinition:
    type: str
    display_name: str
    description: str
    group: str
    properties: list[NodeProperty]
    execute: NodeExecute
    inputs: list[str] = field(default_factory=lambda: ["main"])
    outputs: list[str] = field(default_factory=lambda: ["main"])
    is_trigger: bool = False

    def to_catalog(self) -> JsonObject:
        return {
            "type": self.type,
            "displayName": self.display_name,
            "description": self.description,
            "group": self.group,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "isTrigger": self.is_trigger,
            "properties": [prop.to_dict() for prop in self.properties],
        }


@dataclass
class NodeContext:
    workflow: Workflow
    node: NodeSpec
    input: list[Item]
    params: JsonObject
    credentials: CredentialReader
    env: dict[str, str]
    run_id: str
    log: Callable[[str, str], None]
    get_node_items: Callable[[str], list[Item]]
    cancel_event: Any = None
    raw_params: JsonObject = field(default_factory=dict)
    scope: dict[str, Any] = field(default_factory=dict)
