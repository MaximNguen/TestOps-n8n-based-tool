from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from engine.events import EventBus
from engine.executor import Executor
from engine.expressions import create_scope, resolve_value
from engine.types import Item, NodeContext, NodeSpec, Workflow
from nodes.ai_backend import _merge_chunks, _parse_opencode_events, resolve_ai_settings
from nodes.qa import _render_markdown
from store.crypto import SecretBox
from store.db import Database


class EmptyCredentials:
    def get(self, credential_id: str) -> dict:
        return {}


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.sqlite3", "test-secret")
    yield database
    database.close()


@pytest.fixture()
def executor(db: Database) -> Executor:
    return Executor(
        credentials=EmptyCredentials(),
        env={"AI_BASE_URL": "https://api.openai.com/v1"},
        save_run=db.save_run,
        bus=EventBus(),
    )


def make_workflow(nodes: list[dict], connections: list[dict]) -> Workflow:
    return Workflow.from_dict(
        {
            "id": "wf-test",
            "name": "Test workflow",
            "nodes": nodes,
            "connections": connections,
        }
    )


def test_expression_supports_dot_access() -> None:
    scope = create_scope(
        json_data={"user": {"name": "Ivan"}, "count": 2},
        items=[Item(json={"user": {"name": "Ivan"}, "count": 2})],
        env={"TOKEN": "abc"},
        run_id="run-1",
        workflow_id="wf-1",
        workflow_name="Demo",
        get_node_items=lambda _name: [],
    )
    assert resolve_value("{{ $json.user.name }}", scope) == "Ivan"
    assert resolve_value("Hi {{ $json.user.name }}, n={{ $json.count + 1 }}", scope) == "Hi Ivan, n=3"
    assert resolve_value("{{ $json.count > 1 }}", scope) is True


def test_secret_box_roundtrip() -> None:
    box = SecretBox("secret")
    token = box.encrypt({"apiKey": "k"})
    assert token != "k"
    assert box.decrypt(token) == {"apiKey": "k"}


def test_opencode_event_parsing() -> None:
    stdout = "\n".join(
        [
            '{"type":"step_start","part":{"type":"step-start"}}',
            '{"type":"text","part":{"type":"text","text":"{\\"ok\\": true}"}}',
            '{"type":"step_finish","part":{"type":"step-finish"}}',
        ]
    )
    text, errors = _parse_opencode_events(stdout)
    assert text == '{"ok": true}'
    assert errors == []


def test_opencode_error_and_chunk_merge() -> None:
    stdout = '{"type":"error","error":{"data":{"message":"Model access is disabled"}}}'
    text, errors = _parse_opencode_events(stdout)
    assert text == ""
    assert errors == ["Model access is disabled"]
    assert _merge_chunks(['{"a":', '{"a": 1}']) == '{"a": 1}'
    assert _merge_chunks(["one", "two"]) == "one\ntwo"


class FakeCredentials:
    def __init__(self, data: dict) -> None:
        self.data = data

    def get(self, _credential_id: str) -> dict:
        return self.data


def _ai_context(credential: dict, env: dict | None = None) -> NodeContext:
    workflow = make_workflow(nodes=[], connections=[])
    return NodeContext(
        workflow=workflow,
        node=NodeSpec(id="ai", type="ai.agent", name="AI"),
        input=[],
        params={"credentialId": "cred-1"},
        credentials=FakeCredentials(credential),
        env=env or {},
        run_id="run-1",
        log=lambda *_args: None,
        get_node_items=lambda _name: [],
    )


def test_deepseek_provider_settings() -> None:
    context = _ai_context({"__credentialType": "deepseek", "apiKey": "sk-test"})
    settings = resolve_ai_settings(context)
    assert settings.provider == "deepseek"
    assert settings.base_url == "https://api.deepseek.com"
    assert settings.model == "deepseek-flash"
    assert settings.api_key == "sk-test"


def test_report_renders_ai_insights_separately() -> None:
    markdown = _render_markdown(
        {
            "summary": {"total": 1, "passed": 0, "failed": 1, "skipped": 0, "passRate": 0},
            "likelyProblems": [],
            "aiInsights": [
                {
                    "area": "Auth",
                    "cause": "Token expired",
                    "confidence": "high",
                    "evidence": ["POST /auth/login -> 401"],
                }
            ],
            "tests": [],
        },
        "Report",
    )
    assert "## AI hypotheses" in markdown
    assert "Auth" in markdown
    assert "Token expired" in markdown


def test_anthropic_provider_settings() -> None:
    context = _ai_context({"__credentialType": "anthropic", "apiKey": "sk-ant"})
    settings = resolve_ai_settings(context)
    assert settings.provider == "anthropic"
    assert settings.base_url == "https://api.anthropic.com"
    assert settings.model == "claude-sonnet-4-5"
    assert settings.api_key == "sk-ant"


def test_opencode_credential_wins_over_env() -> None:
    context = _ai_context(
        {"__credentialType": "opencode", "model": "opencode-go/deepseek-v4.1-flash"},
        env={"OPENCODE_BIN": "opencode"},
    )
    settings = resolve_ai_settings(context)
    assert settings.provider == "opencode"
    assert settings.model == "opencode-go/deepseek-v4.1-flash"


def test_executor_runs_branches(executor: Executor, db: Database) -> None:
    workflow = make_workflow(
        nodes=[
            {
                "id": "trigger",
                "type": "trigger.manual",
                "name": "Manual",
                "parameters": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "if",
                "type": "core.if",
                "name": "Check",
                "parameters": {"left": "{{ $json.n }}", "operator": "equals", "right": 2},
                "position": {"x": 200, "y": 0},
            },
            {
                "id": "ok",
                "type": "core.set",
                "name": "OK",
                "parameters": {"values": {"tag": "ok"}},
                "position": {"x": 400, "y": -100},
            },
            {
                "id": "bad",
                "type": "core.set",
                "name": "Bad",
                "parameters": {"values": {"tag": "bad"}},
                "position": {"x": 400, "y": 100},
            },
        ],
        connections=[
            {"from": "trigger", "to": "if"},
            {"from": "if", "to": "ok", "output": "true"},
            {"from": "if", "to": "bad", "output": "false"},
        ],
    )
    run = asyncio.run(executor.run(workflow, trigger="manual", items=[Item(json={"n": 2})]))
    assert run.status == "success"
    ok_run = next(node for node in run.node_runs if node.node_id == "ok")
    assert ok_run.status == "success"
    assert ok_run.output["main"][0]["json"]["tag"] == "ok"
    bad_run = next(node for node in run.node_runs if node.node_id == "bad")
    assert bad_run.status == "skipped"


def test_test_results_trigger_and_summary(executor: Executor) -> None:
    workflow = make_workflow(
        nodes=[
            {
                "id": "trigger",
                "type": "trigger.testResults",
                "name": "Results",
                "parameters": {"source": "auto"},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "summary",
                "type": "ai.summarizeResults",
                "name": "Summary",
                "parameters": {"useAi": False},
                "position": {"x": 200, "y": 0},
            },
            {
                "id": "report",
                "type": "qa.report",
                "name": "Report",
                "parameters": {"title": "Autotest report"},
                "position": {"x": 400, "y": 0},
            },
        ],
        connections=[
            {"from": "trigger", "to": "summary"},
            {"from": "summary", "to": "report"},
        ],
    )
    payload = {
        "results": [
            {"name": "GET /users", "method": "GET", "url": "/users", "status": 500, "passed": False, "error": "Internal Server Error"},
            {"name": "GET /orders/1", "method": "GET", "url": "/orders/1", "status": 404, "passed": False, "error": "Not Found"},
            {"name": "GET /health", "method": "GET", "url": "/health", "status": 200, "passed": True},
        ]
    }
    run = asyncio.run(executor.run(workflow, trigger="webhook", items=[Item(json={"body": payload})]))
    assert run.status == "success"

    report_run = next(node for node in run.node_runs if node.node_id == "report")
    markdown = report_run.output["main"][0]["json"]["markdown"]
    assert "Failed | 2" in markdown
    assert "Бэкенд / сервис" in markdown
    assert "Контракт / маршрутизация" in markdown
