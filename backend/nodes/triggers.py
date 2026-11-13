from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

from engine.types import Item, NodeContext, NodeDefinition, NodeProperty
from engine.registry import register as register_node

from .analysis import analyze


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _url_of(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("raw") or value.get("href") or value.get("url") or "")
    return str(value or "")


def _normalize_assertions(assertions: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(assertions, list):
        return normalized
    for assertion in assertions:
        if isinstance(assertion, dict):
            error = assertion.get("error")
            skipped = bool(assertion.get("skipped"))
            normalized.append(
                {
                    "name": assertion.get("assertion") or assertion.get("name") or "assertion",
                    "passed": not error and not skipped,
                    "error": str(error) if error else None,
                }
            )
    return normalized


def _normalize_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {
            "name": str(entry),
            "method": None,
            "url": "",
            "status": None,
            "passed": False,
            "skipped": False,
            "error": "Unrecognized test entry",
            "assertions": [],
            "duration": None,
        }

    request = entry.get("request") if isinstance(entry.get("request"), dict) else {}
    response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
    assertions = _normalize_assertions(entry.get("assertions"))
    status = _as_int(
        entry.get("status")
        if entry.get("status") is not None and not isinstance(entry.get("status"), str)
        else entry.get("statusCode")
        or entry.get("status")
        or response.get("code")
    )
    if status is None:
        status = _as_int(entry.get("statusCode") or response.get("code"))

    skipped = bool(entry.get("skipped")) or str(entry.get("status") or "").lower() == "skipped"

    passed = entry.get("passed")
    if not isinstance(passed, bool):
        if assertions:
            passed = all(assertion["passed"] for assertion in assertions)
        elif status is not None:
            passed = 200 <= status < 400
        else:
            passed = False

    error = entry.get("error") or entry.get("message")
    if not passed and not error:
        failed_assertions = [a for a in assertions if not a["passed"] and a["error"]]
        if failed_assertions:
            error = failed_assertions[0]["error"]
        elif status is not None:
            error = f"HTTP {status}"

    name = entry.get("name") or entry.get("title") or entry.get("test") or "unnamed test"
    duration = entry.get("duration") or entry.get("responseTime") or response.get("responseTime")
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None

    return {
        "name": str(name),
        "method": request.get("method") or entry.get("method"),
        "url": _url_of(entry.get("url") or request.get("url") or entry.get("path")),
        "status": status,
        "passed": bool(passed),
        "skipped": skipped,
        "error": str(error) if error else None,
        "assertions": assertions,
        "duration": duration,
    }


def _from_junit(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    tests: list[dict[str, Any]] = []
    for case in root.iter("testcase"):
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        problem = failure if failure is not None else error
        message = ""
        if problem is not None:
            message = problem.get("message") or (problem.text or "").strip()
        tests.append(
            {
                "name": case.get("name") or case.get("classname") or "junit testcase",
                "method": None,
                "url": "",
                "status": None,
                "passed": problem is None and skipped is None,
                "skipped": skipped is not None,
                "error": message or None,
                "assertions": [],
                "duration": _as_float(case.get("time")),
            }
        )
    return tests


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _unwrap_payload(payload: Any) -> Any:
    if isinstance(payload, dict) and "body" in payload:
        return payload["body"]
    return payload


def normalize_tests(payload: Any, source: str = "auto") -> tuple[list[dict[str, Any]], str]:
    payload = _unwrap_payload(payload)

    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("<"):
            return _from_junit(text), "junit"
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return [], "unknown"

    if isinstance(payload, dict) and isinstance(payload.get("tests"), list):
        return [_normalize_entry(entry) for entry in payload["tests"]], str(
            payload.get("source") or source
        )

    entries: Any = None
    detected = "generic"

    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict):
        run = payload.get("run") if isinstance(payload.get("run"), dict) else None
        if isinstance(payload.get("executions"), list):
            entries = payload["executions"]
            detected = "newman"
        elif isinstance(run, dict) and isinstance(run.get("executions"), list):
            entries = run["executions"]
            detected = "newman"
        elif isinstance(payload.get("results"), list):
            entries = payload["results"]
            detected = "postman"
        elif isinstance(payload.get("items"), list):
            entries = payload["items"]
        elif isinstance(payload.get("stats"), dict):
            entries = []
            detected = "postman"

    if source in ("postman", "newman", "junit", "generic") and source != "generic":
        detected = source

    tests = [_normalize_entry(entry) for entry in (entries or [])]

    if not tests and isinstance(payload, dict):
        stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
        assertions = stats.get("assertions") if isinstance(stats.get("assertions"), dict) else {}
        total = _as_int(assertions.get("total")) or 0
        failed = _as_int(assertions.get("failed")) or 0
        passed = max(total - failed, 0)
        tests = [
            {
                "name": f"synthetic assertion {index + 1}",
                "method": None,
                "url": "",
                "status": None,
                "passed": True,
                "skipped": False,
                "error": None,
                "assertions": [],
                "duration": None,
            }
            for index in range(passed)
        ] + [
            {
                "name": f"synthetic failed assertion {index + 1}",
                "method": None,
                "url": "",
                "status": None,
                "passed": False,
                "skipped": False,
                "error": "Assertion failed (details are in the Postman run report)",
                "assertions": [],
                "duration": None,
            }
            for index in range(failed)
        ]

    return tests, detected


def _sample_payload(context: NodeContext) -> Any:
    sample = context.params.get("sample")
    if isinstance(sample, str) and sample.strip():
        try:
            return json.loads(sample)
        except json.JSONDecodeError:
            return sample
    return sample


def _register_manual() -> None:
    def execute(context: NodeContext) -> dict[str, list[Item]]:
        if context.input:
            return {"main": context.input}
        sample = _sample_payload(context)
        if sample is not None:
            return {"main": [Item(json={"body": sample})]}
        return {"main": [Item()]}

    register_node(
        NodeDefinition(
            type="trigger.manual",
            display_name="Manual trigger",
            description="Start the workflow from the UI or API. Optional sample payload for testing.",
            group="trigger",
            is_trigger=True,
            properties=[
                NodeProperty(
                    name="sample",
                    display_name="Sample payload (JSON)",
                    type="json",
                    default="",
                    description="Used when running manually without an external payload.",
                    rows=6,
                )
            ],
            execute=execute,
        )
    )


def _register_webhook() -> None:
    def execute(context: NodeContext) -> dict[str, list[Item]]:
        return {"main": context.input or [Item(json={"body": _sample_payload(context) or {}})]}

    register_node(
        NodeDefinition(
            type="trigger.webhook",
            display_name="Webhook trigger",
            description="Start the workflow with an HTTP request. Payload is exposed as body/headers/query/method.",
            group="trigger",
            is_trigger=True,
            properties=[
                NodeProperty(
                    name="path",
                    display_name="Path",
                    type="string",
                    default="qa/webhook",
                    required=True,
                    description="POST /webhook/<path>",
                ),
                NodeProperty(
                    name="method",
                    display_name="Method",
                    type="options",
                    default="POST",
                    options=[
                        {"label": "POST", "value": "POST"},
                        {"label": "GET", "value": "GET"},
                        {"label": "PUT", "value": "PUT"},
                        {"label": "ANY", "value": "ANY"},
                    ],
                ),
                NodeProperty(
                    name="sample",
                    display_name="Sample payload (JSON)",
                    type="json",
                    default="",
                    rows=6,
                ),
            ],
            execute=execute,
        )
    )


def _register_schedule() -> None:
    def execute(context: NodeContext) -> dict[str, list[Item]]:
        return {"main": context.input or [Item(json={"scheduledAt": context.params.get("cron")})]}

    register_node(
        NodeDefinition(
            type="trigger.schedule",
            display_name="Schedule trigger",
            description="Start the workflow on a cron schedule (evaluated by the built-in scheduler).",
            group="trigger",
            is_trigger=True,
            properties=[
                NodeProperty(
                    name="cron",
                    display_name="Cron expression",
                    type="string",
                    default="0 9 * * 1-5",
                    required=True,
                    description="Standard 5-field cron, e.g. 0 9 * * 1-5",
                )
            ],
            execute=execute,
        )
    )


def _register_test_results() -> None:
    def execute(context: NodeContext) -> dict[str, list[Item]]:
        payload = None
        if context.input:
            first = context.input[0].json
            payload = first.get("body") if "body" in first else first
        if payload in (None, {}, ""):
            payload = _sample_payload(context)

        source = str(context.params.get("source") or "auto")
        tests, detected = normalize_tests(payload, source)
        report = analyze(tests)
        report["source"] = detected
        report["tests"] = tests[:500]
        report["totalTests"] = len(tests)
        if not tests:
            report["note"] = (
                "Не удалось распознать результаты. Поддерживаются Newman/Postman JSON, "
                "JUnit XML и массив {name,status,passed,error}."
            )
        context.log(
            f"Распознано тестов: {len(tests)} (источник: {detected}), "
            f"провалено: {report['summary']['failed']}"
        )
        return {"main": [Item(json=report)]}

    register_node(
        NodeDefinition(
            type="trigger.testResults",
            display_name="Test results trigger",
            description=(
                "Accepts autotest results (Newman/Postman/JUnit/JSON), normalizes them and "
                "immediately builds a short summary with likely problem areas."
            ),
            group="trigger",
            is_trigger=True,
            properties=[
                NodeProperty(
                    name="path",
                    display_name="Webhook path",
                    type="string",
                    default="qa/test-results",
                    required=True,
                ),
                NodeProperty(
                    name="method",
                    display_name="Method",
                    type="options",
                    default="POST",
                    options=[
                        {"label": "POST", "value": "POST"},
                        {"label": "PUT", "value": "PUT"},
                        {"label": "ANY", "value": "ANY"},
                    ],
                ),
                NodeProperty(
                    name="source",
                    display_name="Result format",
                    type="options",
                    default="auto",
                    options=[
                        {"label": "Auto-detect", "value": "auto"},
                        {"label": "Postman CLI summary", "value": "postman"},
                        {"label": "Newman JSON", "value": "newman"},
                        {"label": "JUnit XML", "value": "junit"},
                        {"label": "Generic JSON", "value": "generic"},
                    ],
                ),
                NodeProperty(
                    name="sample",
                    display_name="Sample payload (JSON)",
                    type="json",
                    default='{"results":[{"name":"GET /users","method":"GET","url":"/users","status":500,"passed":false,"error":"Internal Server Error"}]}',
                    rows=6,
                ),
            ],
            execute=execute,
        )
    )


def register_nodes() -> None:
    _register_manual()
    _register_webhook()
    _register_schedule()
    _register_test_results()
