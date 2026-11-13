from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.types import (
    CredentialSummary,
    Item,
    NodeSpec,
    Run,
    Workflow,
)

from .crypto import SecretBox

SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credentials (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_workflow ON runs(workflow_id, started_at DESC);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path, secret: str) -> None:
        self.path = path
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._box = SecretBox(secret)
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ---------- workflows ----------

    def list_workflows(self) -> list[Workflow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM workflows ORDER BY updated_at DESC"
            ).fetchall()
        return [Workflow.from_dict(json.loads(row["data"])) for row in rows]

    def get_workflow(self, workflow_id: str) -> Workflow | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM workflows WHERE id = ?", (workflow_id,)
            ).fetchone()
        return Workflow.from_dict(json.loads(row["data"])) if row else None

    def create_workflow(self, name: str, description: str, active: bool, nodes: list[NodeSpec], connections: list) -> Workflow:
        now = utcnow()
        workflow = Workflow(
            id=uuid.uuid4().hex,
            name=name,
            description=description,
            active=active,
            nodes=nodes,
            connections=connections,
            created_at=now,
            updated_at=now,
        )
        return self.save_workflow(workflow)

    def save_workflow(self, workflow: Workflow) -> Workflow:
        workflow.updated_at = utcnow()
        if not workflow.created_at:
            workflow.created_at = workflow.updated_at
        data = json.dumps(workflow.to_dict(), ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO workflows (id, name, active, data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    active = excluded.active,
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (
                    workflow.id,
                    workflow.name,
                    1 if workflow.active else 0,
                    data,
                    workflow.created_at,
                    workflow.updated_at,
                ),
            )
            self._conn.commit()
        return workflow

    def delete_workflow(self, workflow_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    def find_webhook(self, path: str, method: str) -> tuple[Workflow, NodeSpec] | None:
        wanted_path = path.strip("/")
        wanted_method = method.upper()
        for workflow in self.list_workflows():
            if not workflow.active:
                continue
            for node in workflow.nodes:
                if node.type not in ("trigger.webhook", "trigger.testResults"):
                    continue
                node_path = str(node.parameters.get("path") or "").strip("/")
                node_method = str(node.parameters.get("method") or "POST").upper()
                if node_path == wanted_path and node_method in (wanted_method, "ANY"):
                    return workflow, node
        return None

    # ---------- credentials ----------

    def list_credentials(self) -> list[CredentialSummary]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, type, created_at, updated_at FROM credentials ORDER BY name"
            ).fetchall()
        return [
            CredentialSummary(
                id=row["id"],
                name=row["name"],
                type=row["type"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def save_credential(
        self,
        *,
        name: str,
        credential_type: str,
        data: dict[str, Any],
        credential_id: str | None = None,
    ) -> CredentialSummary:
        now = utcnow()
        encrypted = self._box.encrypt(data)
        credential_id = credential_id or uuid.uuid4().hex
        with self._lock:
            existing = self._conn.execute(
                "SELECT created_at FROM credentials WHERE id = ?", (credential_id,)
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            self._conn.execute(
                """
                INSERT INTO credentials (id, name, type, data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    type = excluded.type,
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (credential_id, name, credential_type, encrypted, created_at, now),
            )
            self._conn.commit()
        return CredentialSummary(
            id=credential_id,
            name=name,
            type=credential_type,
            created_at=created_at,
            updated_at=now,
        )

    def delete_credential(self, credential_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM credentials WHERE id = ?", (credential_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    def get_credential_bundle(self, credential_id: str) -> tuple[str, dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT data, type FROM credentials WHERE id = ?", (credential_id,)
            ).fetchone()
        if not row:
            raise ValueError(f"Credential not found: {credential_id}")
        return str(row["type"]), self._box.decrypt(row["data"])

    def get_credential_data(self, credential_id: str) -> dict[str, Any]:
        _, data = self.get_credential_bundle(credential_id)
        return data

    # ---------- runs ----------

    def save_run(self, run: Run) -> None:
        payload = json.dumps(run.to_dict(), ensure_ascii=False, default=str)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO runs (id, workflow_id, status, started_at, finished_at, data)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    finished_at = excluded.finished_at,
                    data = excluded.data
                """,
                (run.id, run.workflow_id, run.status, run.started_at, run.finished_at, payload),
            )
            self._conn.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM runs WHERE id = ?", (run_id,)).fetchone()
        return json.loads(row["data"]) if row else None

    def list_runs(self, workflow_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            if workflow_id:
                rows = self._conn.execute(
                    "SELECT data FROM runs WHERE workflow_id = ? ORDER BY started_at DESC LIMIT ?",
                    (workflow_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT data FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [json.loads(row["data"]) for row in rows]

    # ---------- helpers ----------

    def count_workflows(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS total FROM workflows").fetchone()
        return int(row["total"]) if row else 0

    def close(self) -> None:
        self._conn.close()
