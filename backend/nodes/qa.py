from __future__ import annotations

import asyncio
import html as html_module
import json
import os
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import yaml

from engine.registry import register as register_node
from engine.types import Item, NodeContext, NodeDefinition, NodeProperty

from .ai_backend import ask_json, resolve_ai_settings
from .analysis import analyze
from .triggers import normalize_tests


def _schema_example(schema: Any, root: dict[str, Any], depth: int = 0) -> Any:
    if depth > 6 or not isinstance(schema, dict):
        return None
    if "$ref" in schema and isinstance(schema["$ref"], str):
        ref = schema["$ref"].split("/")[-1]
        resolved = ((root.get("components") or {}).get("schemas") or {}).get(ref)
        if isinstance(resolved, dict):
            return _schema_example(resolved, root, depth + 1)
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return schema["enum"][0]
    for combinator in ("allOf", "oneOf", "anyOf"):
        if isinstance(schema.get(combinator), list) and schema[combinator]:
            merged: dict[str, Any] = {}
            for entry in schema[combinator]:
                value = _schema_example(entry, root, depth + 1)
                if isinstance(value, dict):
                    merged.update(value)
            return merged or _schema_example(schema[combinator][0], root, depth + 1)

    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        result: dict[str, Any] = {}
        for name, prop in (schema.get("properties") or {}).items():
            value = _schema_example(prop, root, depth + 1)
            if value is not None:
                result[name] = value
        return result
    if schema_type == "array":
        item = _schema_example(schema.get("items") or {}, root, depth + 1)
        return [item] if item is not None else []
    if schema_type == "string":
        fmt = schema.get("format")
        if fmt in ("date", "date-time"):
            return "2024-01-01T00:00:00Z"
        if fmt == "email":
            return "user@example.com"
        if fmt == "uuid":
            return "00000000-0000-4000-8000-000000000000"
        return "string"
    if schema_type in ("integer", "number"):
        return 0
    if schema_type == "boolean":
        return True
    return None


def _parse_spec(text: str) -> dict[str, Any]:
    try:
        spec = json.loads(text)
    except json.JSONDecodeError:
        spec = yaml.safe_load(text)
    if not isinstance(spec, dict):
        raise ValueError("OpenAPI spec must be a JSON/YAML object")
    return spec


async def _fetch_spec(url: str) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


def _register_openapi_cases() -> None:
    async def execute(context: NodeContext) -> dict[str, list[Item]]:
        params = context.params
        spec_value = params.get("spec")
        spec_url = str(params.get("specUrl") or "").strip()
        if isinstance(spec_value, dict):
            spec = spec_value
        else:
            spec_text = str(spec_value or "").strip()
            if spec_url:
                spec_text = await _fetch_spec(spec_url)
            if not spec_text:
                raise ValueError("openapiCases: provide 'spec' or 'specUrl'")
            spec = _parse_spec(spec_text)

        base_url = str(params.get("baseUrl") or "").rstrip("/")
        include = str(params.get("include") or "").strip()
        max_cases = int(params.get("maxCases") or 50)
        include_deprecated = bool(params.get("includeDeprecated"))

        cases: list[Item] = []
        for path, path_item in (spec.get("paths") or {}).items():
            if not isinstance(path_item, dict):
                continue
            path_level_params = path_item.get("parameters") or []
            for method, operation in path_item.items():
                if method.lower() not in ("get", "post", "put", "patch", "delete", "head", "options"):
                    continue
                if not isinstance(operation, dict):
                    continue
                if include and include not in path:
                    continue
                if operation.get("deprecated") and not include_deprecated:
                    continue

                operation_params = [*path_level_params, *(operation.get("parameters") or [])]
                path_params = {}
                query = {}
                headers = {}
                for parameter in operation_params:
                    if not isinstance(parameter, dict):
                        continue
                    name = parameter.get("name")
                    location = parameter.get("in")
                    if not name or location not in ("path", "query", "header"):
                        continue
                    value = _schema_example(parameter.get("schema") or {}, spec)
                    if value is None:
                        value = parameter.get("example") or "1"
                    if location == "path":
                        path_params[name] = value
                    elif location == "query" and parameter.get("required"):
                        query[name] = value
                    elif location == "header" and parameter.get("required") and name.lower() != "authorization":
                        headers[name] = value

                resolved_path = path
                for name, value in path_params.items():
                    resolved_path = resolved_path.replace("{" + name + "}", quote(str(value)))

                body = None
                request_body = operation.get("requestBody") or {}
                content = (request_body.get("content") or {}) if isinstance(request_body, dict) else {}
                json_content = content.get("application/json") or content.get("application/*+json")
                if isinstance(json_content, dict) and json_content.get("schema"):
                    body = _schema_example(json_content["schema"], spec)
                    headers.setdefault("Content-Type", "application/json")

                expected_statuses: list[int] = []
                for code in (operation.get("responses") or {}):
                    try:
                        status = int(str(code))
                    except ValueError:
                        continue
                    if 200 <= status < 300:
                        expected_statuses.append(status)
                if not expected_statuses:
                    expected_statuses = [200]

                query_string = ""
                if query:
                    from urllib.parse import urlencode

                    query_string = "?" + urlencode({k: str(v) for k, v in query.items()})

                cases.append(
                    Item(
                        json={
                            "caseId": operation.get("operationId")
                            or f"{method.upper()} {path}",
                            "name": operation.get("summary")
                            or operation.get("operationId")
                            or f"{method.upper()} {path}",
                            "method": method.upper(),
                            "path": resolved_path,
                            "url": f"{base_url}{resolved_path}{query_string}",
                            "headers": headers,
                            "query": query,
                            "body": body,
                            "expectedStatuses": expected_statuses,
                            "tags": operation.get("tags") or [],
                        }
                    )
                )
                if len(cases) >= max_cases:
                    break
            if len(cases) >= max_cases:
                break

        context.log(f"Сгенерировано кейсов из OpenAPI: {len(cases)}")
        return {"main": cases}

    register_node(
        NodeDefinition(
            type="qa.openapiCases",
            display_name="OpenAPI → test cases",
            description="Generate API test cases from an OpenAPI/Swagger spec (JSON or YAML).",
            group="qa",
            properties=[
                NodeProperty(name="specUrl", display_name="Spec URL", type="string", default=""),
                NodeProperty(
                    name="spec",
                    display_name="Spec (JSON/YAML)",
                    type="code",
                    default="",
                    rows=10,
                    description="Used when Spec URL is empty.",
                ),
                NodeProperty(
                    name="baseUrl",
                    display_name="Base URL",
                    type="string",
                    default="https://api.example.com",
                ),
                NodeProperty(
                    name="include",
                    display_name="Path filter",
                    type="string",
                    default="",
                    description="Only paths containing this substring.",
                ),
                NodeProperty(name="maxCases", display_name="Max cases", type="number", default=50),
                NodeProperty(
                    name="includeDeprecated",
                    display_name="Include deprecated operations",
                    type="boolean",
                    default=False,
                ),
            ],
            execute=execute,
        )
    )


def _template_plan(context: NodeContext, reason: str | None = None) -> dict[str, Any]:
    cases = []
    for item in context.input:
        data = item.json
        cases.append(
            {
                "id": data.get("caseId") or f"TC-{len(cases) + 1:03d}",
                "title": data.get("name") or data.get("caseId") or "API test case",
                "priority": data.get("priority") or "medium",
                "type": "api",
                "method": data.get("method"),
                "url": data.get("url"),
                "expectedStatuses": data.get("expectedStatuses") or [200],
                "steps": [
                    {
                        "action": f"{data.get('method', 'GET')} {data.get('url') or data.get('path') or ''}",
                        "data": data.get("body"),
                    }
                ],
                "expected": f"HTTP status in {data.get('expectedStatuses') or [200]}",
            }
        )
    plan = {
        "title": str(context.params.get("title") or f"Test plan: {context.workflow.name}"),
        "objective": str(context.params.get("objective") or "Verify API behavior described by requirements."),
        "requirements": str(context.params.get("requirements") or ""),
        "cases": cases,
        "generatedBy": "template",
        "generatedAt": context.scope.get("_now") if context.scope else None,
    }
    if reason:
        plan["fallbackReason"] = reason
    return plan


def _register_test_plan() -> None:
    async def execute(context: NodeContext) -> dict[str, list[Item]]:
        mode = str(context.params.get("mode") or "template")
        if mode == "llm" and context.env.get("AI_DISABLED") == "1":
            context.log("AI_DISABLED=1, используется шаблонный тест-план", "warn")
            return {"main": [Item(json=_template_plan(context, "AI_DISABLED=1"))]}
        if mode == "llm":
            settings = resolve_ai_settings(context)
            if settings.provider != "opencode" and not settings.api_key:
                raise ValueError(
                    "LLM mode requires a credential or DEEPSEEK_API_KEY / OPENAI_API_KEY. "
                    "Use provider=opencode or mode=template for offline generation."
                )

            requirements = str(context.params.get("requirements") or "")
            sample = [item.json for item in context.input[:100]]
            system = (
                "You are a senior QA engineer. Produce a compact, executable API test plan as JSON. "
                "Return only JSON with keys: title, objective, scope, risks, cases. "
                "Each case: id, title, priority (high|medium|low), type, method, url, "
                "expectedStatuses (array of ints), steps (array of {action,data}), expected. "
                "Base cases on the provided OpenAPI-derived cases and requirements."
            )
            user = json.dumps(
                {
                    "requirements": requirements,
                    "apiCases": sample,
                    "maxCases": int(context.params.get("maxCases") or 40),
                    "language": str(context.params.get("language") or "ru"),
                },
                ensure_ascii=False,
            )
            try:
                plan = await ask_json(
                    settings,
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                if not isinstance(plan, dict):
                    raise ValueError("LLM returned a non-object JSON payload")
                plan.setdefault("generatedBy", "llm")
                plan["aiProvider"] = settings.provider
                context.log(
                    f"LLM ({settings.provider}) сгенерировал тест-план: "
                    f"{len(plan.get('cases') or [])} кейсов"
                )
                return {"main": [Item(json=plan)]}
            except Exception as error:  # noqa: BLE001
                if bool(context.params.get("fallbackToTemplate", True)):
                    context.log(f"LLM недоступен, fallback на шаблон: {error}", "warn")
                    return {"main": [Item(json=_template_plan(context, str(error)))]}
                raise

        return {"main": [Item(json=_template_plan(context))]}

    register_node(
        NodeDefinition(
            type="qa.testPlan",
            display_name="Generate test plan",
            description="Build a test plan from OpenAPI-derived cases or requirements. Template or LLM mode.",
            group="qa",
            properties=[
                NodeProperty(
                    name="mode",
                    display_name="Mode",
                    type="options",
                    default="template",
                    options=[
                        {"label": "Template (offline)", "value": "template"},
                        {"label": "LLM (OpenAI-compatible)", "value": "llm"},
                    ],
                ),
                NodeProperty(
                    name="title",
                    display_name="Plan title",
                    type="string",
                    default="API test plan",
                ),
                NodeProperty(
                    name="requirements",
                    display_name="Requirements / context",
                    type="text",
                    default="",
                    rows=5,
                ),
                NodeProperty(name="maxCases", display_name="Max cases", type="number", default=40),
                NodeProperty(
                    name="provider",
                    display_name="LLM provider",
                    type="options",
                    default="auto",
                    options=[
                        {"label": "Auto (opencode, then DeepSeek, then OpenAI)", "value": "auto"},
                        {"label": "opencode CLI (local auth)", "value": "opencode"},
                        {"label": "DeepSeek API (API key)", "value": "deepseek"},
                        {"label": "Anthropic Claude API (API key)", "value": "anthropic"},
                        {"label": "OpenAI-compatible API (GPT, local)", "value": "openai"},
                    ],
                ),
                NodeProperty(
                    name="credentialId",
                    display_name="AI credential",
                    type="credential",
                    credential_type="ai",
                    default="",
                ),
                NodeProperty(name="baseUrl", display_name="OpenAI base URL", type="string", default=""),
                NodeProperty(
                    name="model",
                    display_name="Model",
                    type="string",
                    default="",
                    description="For opencode: provider/model, e.g. opencode/deepseek-v4.1-flash-free.",
                ),
                NodeProperty(name="agent", display_name="opencode agent", type="string", default=""),
                NodeProperty(name="opencodeBin", display_name="opencode binary", type="string", default=""),
                NodeProperty(
                    name="fallbackToTemplate",
                    display_name="Fallback to template on LLM error",
                    type="boolean",
                    default=True,
                ),
            ],
            execute=execute,
        )
    )


def _find_report(directory: Path) -> tuple[Any, str | None]:
    summaries = sorted(directory.glob("*collection-run-summary.yaml"))
    executions = sorted(directory.glob("*collection-run-executions.yaml"))
    summary: Any = None
    if summaries:
        summary = yaml.safe_load(summaries[0].read_text(encoding="utf-8"))
    execution_data: Any = None
    if executions:
        execution_data = yaml.safe_load(executions[0].read_text(encoding="utf-8"))
    return summary, execution_data


async def _run_process(command: list[str], timeout: float) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as error:
        process.kill()
        await process.wait()
        raise ValueError(f"Test runner timed out after {timeout} seconds") from error
    return (
        process.returncode or 0,
        stdout.decode("utf-8", "replace"),
        stderr.decode("utf-8", "replace"),
    )


def _register_run_collection() -> None:
    async def execute(context: NodeContext) -> dict[str, list[Item]]:
        params = context.params
        collection = str(params.get("collection") or "").strip()
        if not collection:
            raise ValueError("runCollection: 'collection' path or ID is required")

        newman_bin = str(params.get("newmanBin") or context.env.get("NEWMAN_BIN") or "newman")
        postman_bin = str(params.get("postmanBin") or context.env.get("POSTMAN_BIN") or "postman")
        runner = str(params.get("runner") or "auto")
        if runner == "auto":
            runner = "newman" if shutil.which(newman_bin) else "postman"

        environment = str(params.get("environment") or "").strip()
        extra_args = str(params.get("extraArgs") or "").strip()
        timeout = float(params.get("timeoutSeconds") or 600)
        report_dir = Path(tempfile.mkdtemp(prefix="custom-n8n-collection-run-"))

        raw_summary: Any = None
        stdout = ""
        stderr = ""
        exit_code = 0

        if runner == "newman":
            if shutil.which(newman_bin) is None:
                raise ValueError(
                    f"Newman not found ({newman_bin}). Install it with 'npm i -g newman' "
                    "or set NEWMAN_BIN / newmanBin."
                )
            report_file = report_dir / "newman-report.json"
            command = [newman_bin, "run", collection]
            if environment:
                command.extend(["-e", environment])
            if extra_args:
                command.extend(shlex.split(extra_args, posix=os.name != "nt"))
            command.extend(
                [
                    "--reporters",
                    "json",
                    "--reporter-json-export",
                    str(report_file),
                    "--suppress-exit-code",
                ]
            )
            context.log(f"Запуск (newman): {' '.join(command)}")
            exit_code, stdout, stderr = await _run_process(command, timeout)
            if report_file.exists():
                raw_summary = json.loads(report_file.read_text(encoding="utf-8"))
            tests, _ = normalize_tests(raw_summary or {}, "newman")
        elif runner == "postman":
            if shutil.which(postman_bin) is None:
                raise ValueError(
                    f"Postman CLI not found ({postman_bin}). Install it or set POSTMAN_BIN."
                )
            command = [postman_bin, "collection", "run", collection]
            if environment:
                command.extend(["-e", environment])
            if extra_args:
                command.extend(shlex.split(extra_args, posix=os.name != "nt"))
            command.extend(["--output", str(report_dir), "--silent", "-x"])
            context.log(f"Запуск (postman): {' '.join(command)}")
            exit_code, stdout, stderr = await _run_process(command, timeout)
            if "signed in" in stderr.lower() or "authorization data" in stderr.lower():
                raise ValueError(
                    "Postman CLI requires login for --output. Run 'postman login' or "
                    "use runner=newman (no login required)."
                )
            summary, executions = _find_report(report_dir)
            raw_summary = summary if summary is not None else executions
            tests, _ = normalize_tests(raw_summary or {}, "postman")
        else:
            raise ValueError(f"Unknown runner: {runner}")

        if not tests and exit_code != 0:
            raise ValueError(
                f"{runner} exited with {exit_code} and produced no test results: "
                f"{(stderr or stdout)[-1000:]}"
            )

        analysis = analyze(tests)
        result = {
            "runner": runner,
            "exitCode": exit_code,
            "reportDir": str(report_dir),
            "tests": tests,
            "summary": analysis["summary"],
            "analysis": analysis,
            "rawStats": (raw_summary or {}).get("run", {}).get("stats")
            if isinstance(raw_summary, dict)
            else None,
            "stderrTail": stderr[-4000:],
            "stdoutTail": stdout[-2000:],
        }
        context.log(
            f"{runner} завершился с кодом {exit_code}; "
            f"провалено {analysis['summary']['failed']} из {analysis['summary']['total']}"
        )
        if bool(params.get("failOnTestFailure")) and analysis["summary"]["failed"] > 0:
            raise ValueError(
                f"Autotests failed: {analysis['summary']['failed']} of {analysis['summary']['total']}"
            )
        return {"main": [Item(json=result)]}

    register_node(
        NodeDefinition(
            type="qa.runCollection",
            display_name="Run Postman collection",
            description=(
                "Execute a Postman/Newman collection locally and parse the run report. "
                "Newman needs no login; Postman CLI needs 'postman login' for --output."
            ),
            group="qa",
            properties=[
                NodeProperty(
                    name="collection",
                    display_name="Collection path or ID",
                    type="string",
                    default="./postman/collection.yaml",
                    required=True,
                ),
                NodeProperty(name="environment", display_name="Environment path", type="string", default=""),
                NodeProperty(name="extraArgs", display_name="Extra CLI args", type="string", default=""),
                NodeProperty(name="timeoutSeconds", display_name="Timeout (sec)", type="number", default=600),
                NodeProperty(
                    name="runner",
                    display_name="Runner",
                    type="options",
                    default="auto",
                    options=[
                        {"label": "Auto (newman, then postman)", "value": "auto"},
                        {"label": "Newman (no login)", "value": "newman"},
                        {"label": "Postman CLI (login required for --output)", "value": "postman"},
                    ],
                ),
                NodeProperty(
                    name="newmanBin",
                    display_name="Newman binary",
                    type="string",
                    default="",
                    description="Defaults to NEWMAN_BIN or 'newman'.",
                ),
                NodeProperty(
                    name="postmanBin",
                    display_name="Postman binary",
                    type="string",
                    default="",
                    description="Defaults to POSTMAN_BIN or 'postman'.",
                ),
                NodeProperty(
                    name="failOnTestFailure",
                    display_name="Fail workflow on test failures",
                    type="boolean",
                    default=False,
                ),
            ],
            execute=execute,
        )
    )


def _report_score(data: dict[str, Any]) -> int:
    score = 0
    if "summary" in data:
        score += 5
    if "tests" in data:
        score += 3
    if "analysis" in data:
        score += 4
    if "markdown" in data:
        score += 2
    if "cases" in data:
        score += 2
    return score


def _section_from_item(data: dict[str, Any], index: int) -> dict[str, str] | None:
    if not isinstance(data, dict):
        return {"title": f"Additional branch {index + 1}", "markdown": str(data)}
    title = str(
        data.get("title") or data.get("name") or f"Additional branch {index + 1}"
    )
    body = data.get("markdown")
    if not isinstance(body, str) or not body.strip():
        text = data.get("text")
        if isinstance(text, str):
            body = text
    if not isinstance(body, str) or not body.strip():
        payload = data.get("review", data)
        try:
            rendered = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            rendered = str(payload)
        body = f"```json\n{rendered[:20000]}\n```"
    return {"title": title, "markdown": body}


def _render_markdown(report: dict[str, Any], title: str) -> str:
    summary = report.get("summary") or {}
    analysis = report.get("analysis") or report
    problems = analysis.get("likelyProblems") or []
    ai_insights = analysis.get("aiInsights") or []
    extra_sections = report.get("extraSections") or analysis.get("extraSections") or []
    endpoints = analysis.get("topFailingEndpoints") or []
    tests = report.get("tests") or analysis.get("tests") or []
    recommendations = analysis.get("recommendations") or []
    cases = report.get("cases") or []

    lines = [f"# {title}", ""]
    if analysis.get("shortSummary"):
        lines.extend([f"> {analysis['shortSummary']}", ""])
    if analysis.get("aiUsed"):
        lines.extend([f"> AI analysis: {analysis.get('aiProvider') or 'LLM'}", ""])

    if summary.get("total") or not cases:
        lines.extend(
            [
                "## Summary",
                "",
                "| Metric | Value |",
                "| --- | --- |",
                f"| Total | {summary.get('total', 0)} |",
                f"| Passed | {summary.get('passed', 0)} |",
                f"| Failed | {summary.get('failed', 0)} |",
                f"| Skipped | {summary.get('skipped', 0)} |",
                f"| Pass rate | {summary.get('passRate', 0)}% |",
                "",
            ]
        )

    if cases:
        if report.get("objective"):
            lines.extend(["## Objective", "", str(report["objective"]), ""])
        lines.extend(
            [
                "## Test cases",
                "",
                "| ID | Title | Priority | Method | URL | Expected |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for case in cases[:100]:
            lines.append(
                "| {id} | {title} | {priority} | {method} | `{url}` | {expected} |".format(
                    id=case.get("id") or "—",
                    title=str(case.get("title") or "—").replace("|", "\\|"),
                    priority=case.get("priority") or "—",
                    method=case.get("method") or "—",
                    url=case.get("url") or case.get("path") or "—",
                    expected=case.get("expected") or case.get("expectedStatuses") or "—",
                )
            )
        lines.append("")

        details_started = False
        for case in cases[:50]:
            steps = case.get("steps") or []
            expected = case.get("expected")
            if not steps and not expected:
                continue
            if not details_started:
                lines.extend(["### Case details", ""])
                details_started = True
            lines.append(f"**{case.get('id') or '—'}. {case.get('title') or '—'}**")
            lines.append("")
            if expected:
                lines.append(f"Expected: {expected}")
            for index, step in enumerate(steps, 1):
                if isinstance(step, dict):
                    action = step.get("action") or "step"
                    step_data = step.get("data")
                else:
                    action = str(step)
                    step_data = None
                if step_data is not None:
                    rendered = json.dumps(step_data, ensure_ascii=False)
                    if len(rendered) > 500:
                        rendered = rendered[:500] + "..."
                    lines.append(f"{index}. {action}; data: `{rendered}`")
                else:
                    lines.append(f"{index}. {action}")
            lines.append("")

    if problems:
        lines.extend(["## Likely problems", ""])
        for problem in problems:
            lines.append(
                f"### {problem.get('area')} — {problem.get('confidence')} confidence "
                f"({problem.get('failureCount')} failures)"
            )
            lines.append("")
            lines.append(f"**Cause:** {problem.get('cause')}")
            lines.append("")
            if problem.get("evidence"):
                lines.append("**Evidence:**")
                for evidence in problem["evidence"]:
                    lines.append(
                        f"- `{evidence.get('endpoint')}` / {evidence.get('test')} "
                        f"(status {evidence.get('status')}): {evidence.get('error')}"
                    )
                lines.append("")

    if ai_insights:
        lines.extend(["## AI hypotheses", ""])
        for insight in ai_insights:
            lines.append(
                f"### {insight.get('area') or 'AI-гипотеза'} — "
                f"{insight.get('confidence') or 'low'} confidence"
            )
            lines.append("")
            lines.append(f"**Cause:** {insight.get('cause') or '—'}")
            lines.append("")
            for evidence in insight.get("evidence") or []:
                lines.append(f"- {evidence}")
            if insight.get("evidence"):
                lines.append("")

    if extra_sections:
        for section in extra_sections:
            if not isinstance(section, dict):
                continue
            section_title = str(section.get("title") or "Additional section")
            body = section.get("markdown") or section.get("body") or ""
            if not isinstance(body, str):
                body = json.dumps(body, ensure_ascii=False, indent=2, default=str)
            lines.extend([f"## {section_title}", "", body, ""])

    if endpoints:
        lines.extend(["## Top failing endpoints", "", "| Endpoint | Failures |", "| --- | --- |"])
        for endpoint in endpoints:
            lines.append(f"| `{endpoint.get('endpoint')}` | {endpoint.get('failures')} |")
        lines.append("")

    failed_tests = [test for test in tests if not test.get("passed")]
    if failed_tests:
        lines.extend(["## Failed tests", "", "| Test | Endpoint | Status | Error |", "| --- | --- | --- | --- |"])
        for test in failed_tests[:50]:
            error = str(test.get("error") or "").replace("|", "\\|")[:200]
            lines.append(
                f"| {test.get('name')} | `{test.get('url') or '—'}` | {test.get('status') or '—'} | {error} |"
            )
        lines.append("")

    if recommendations:
        lines.extend(["## Recommendations", ""])
        lines.extend(f"- {recommendation}" for recommendation in recommendations)
        lines.append("")

    return "\n".join(lines)


def _render_html(report: dict[str, Any], title: str) -> str:
    markdown = _render_markdown(report, title)
    escaped = html_module.escape(markdown)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html_module.escape(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:960px;margin:40px auto;"
        "padding:0 16px;line-height:1.5}pre{white-space:pre-wrap;background:#f6f8fa;"
        "padding:16px;border-radius:8px}</style></head><body>"
        f"<pre>{escaped}</pre></body></html>"
    )


def _register_report() -> None:
    def execute(context: NodeContext) -> dict[str, list[Item]]:
        if not context.input:
            raise ValueError("Report node requires input")
        inputs = context.input
        primary_index = max(
            range(len(inputs)),
            key=lambda index: _report_score(inputs[index].json),
        )
        report = dict(inputs[primary_index].json)
        extras = list(report.get("extraSections") or [])
        for index, item in enumerate(inputs):
            if index == primary_index:
                continue
            section = _section_from_item(item.json, index)
            if section:
                extras.append(section)
        if extras:
            report["extraSections"] = extras
        if "analysis" not in report and "summary" in report:
            report["analysis"] = {
                key: value for key, value in report.items() if key != "analysis"
            }
        if "tests" not in report and isinstance(report.get("analysis"), dict):
            report["tests"] = report["analysis"].get("tests") or []
        title = str(context.params.get("title") or f"QA report: {context.workflow.name}")
        markdown = _render_markdown(report, title)
        result = {
            "title": title,
            "markdown": markdown,
            "html": _render_html(report, title),
            "summary": report.get("summary") or {},
            "analysis": report.get("analysis") or {},
            "generatedAt": context.scope.get("_now") if context.scope else None,
        }
        context.log(f"Отчёт сформирован ({len(markdown)} символов)")
        return {"main": [Item(json=result)]}

    register_node(
        NodeDefinition(
            type="qa.report",
            display_name="Build QA report",
            description="Render a Markdown/HTML report from test results and analysis.",
            group="qa",
            properties=[
                NodeProperty(name="title", display_name="Report title", type="string", default="QA report"),
            ],
            execute=execute,
        )
    )


def register_nodes() -> None:
    _register_openapi_cases()
    _register_test_plan()
    _register_run_collection()
    _register_report()
