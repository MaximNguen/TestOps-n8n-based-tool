from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import create_app


@pytest.fixture()
def client() -> TestClient:
    with TestClient(create_app()) as test_client:
        yield test_client


def _wait(client: TestClient, run_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    run: dict = {}
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run.get("status") != "running":
            return run
        time.sleep(0.1)
    return run


def test_api_health_and_nodes(client: TestClient) -> None:
    health = client.get("/api/health").json()
    assert health["ok"] is True
    node_types = {node["type"] for node in client.get("/api/nodes").json()}
    assert "trigger.testResults" in node_types
    assert "ai.summarizeResults" in node_types
    assert "qa.runCollection" in node_types


def test_seeded_workflow_runs(client: TestClient) -> None:
    workflows = client.get("/api/workflows").json()
    assert workflows, "example workflow should be seeded"
    workflow = workflows[0]
    response = client.post(f"/api/workflows/{workflow['id']}/run", json={})
    assert response.status_code == 200
    run = _wait(client, response.json()["runId"])
    assert run["status"] == "success", run.get("error")
    assert any(
        node["nodeId"] == "publish-file" and node["status"] == "success"
        for node in run["nodeRuns"]
    )


def test_webhook_trigger_accepts_results(client: TestClient) -> None:
    payload = {
        "results": [
            {
                "name": "GET /users",
                "method": "GET",
                "url": "https://api.demo.local/users",
                "status": 502,
                "passed": False,
                "error": "Bad Gateway",
            }
        ]
    }
    response = client.post("/webhook/qa/test-results", json=payload)
    assert response.status_code == 200
    run = _wait(client, response.json()["runId"])
    assert run["status"] == "success", run.get("error")
    summary = next(node for node in run["nodeRuns"] if node["nodeId"] == "summarize")
    short_summary = summary["output"]["main"][0]["json"]["shortSummary"]
    assert "Бэкенд" in short_summary or "сервис" in short_summary.lower()
