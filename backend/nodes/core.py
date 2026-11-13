from __future__ import annotations

import datetime as datetime_module
import json
import math
import re
import textwrap
from typing import Any

import httpx

from engine.expressions import resolve_value, wrap
from engine.types import Item, NodeContext, NodeDefinition, NodeProperty
from engine.registry import register as register_node

SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": range,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}


def _as_json(value: Any, fallback: Any) -> Any:
    if isinstance(value, str):
        if not value.strip():
            return fallback
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _register_set() -> None:
    def execute(context: NodeContext) -> dict[str, list[Item]]:
        values = _as_json(context.params.get("values"), {})
        if not isinstance(values, dict):
            raise ValueError("'values' must be a JSON object")
        keep_only_set = bool(context.params.get("keepOnlySet"))
        inputs = context.input or [Item()]
        output: list[Item] = []
        for item in inputs:
            base = {} if keep_only_set else dict(item.json)
            base.update(values)
            output.append(Item(json=base))
        return {"main": output}

    register_node(
        NodeDefinition(
            type="core.set",
            display_name="Set fields",
            description="Add or overwrite fields on each item. Supports {{ expressions }}.",
            group="transform",
            properties=[
                NodeProperty(
                    name="values",
                    display_name="Fields (JSON)",
                    type="json",
                    default='{"status": "ok"}',
                    required=True,
                    rows=6,
                ),
                NodeProperty(
                    name="keepOnlySet",
                    display_name="Keep only set fields",
                    type="boolean",
                    default=False,
                ),
            ],
            execute=execute,
        )
    )


def _compare(left: Any, operator: str, right: Any, case_sensitive: bool) -> bool:
    if operator in ("equals", "notEquals") and isinstance(left, str) and isinstance(right, str):
        if not case_sensitive:
            left, right = left.lower(), right.lower()
    if operator == "equals":
        return left == right
    if operator == "notEquals":
        return left != right
    if operator in ("contains", "notContains"):
        haystack = left if isinstance(left, str) else json.dumps(left, default=str)
        needle = right if isinstance(right, str) else json.dumps(right, default=str)
        if not case_sensitive:
            haystack, needle = haystack.lower(), needle.lower()
        found = needle in haystack
        return found if operator == "contains" else not found
    if operator == "startsWith":
        return str(left).lower().startswith(str(right).lower()) if not case_sensitive else str(left).startswith(str(right))
    if operator == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        return re.search(str(right), str(left), flags) is not None
    if operator == "exists":
        return left is not None
    if operator == "empty":
        return left in (None, "", [], {})
    if operator in ("gt", "gte", "lt", "lte"):
        try:
            left_number = float(left)
            right_number = float(right)
        except (TypeError, ValueError):
            left_number, right_number = str(left), str(right)  # type: ignore[assignment]
        if operator == "gt":
            return left_number > right_number
        if operator == "gte":
            return left_number >= right_number
        if operator == "lt":
            return left_number < right_number
        return left_number <= right_number
    raise ValueError(f"Unsupported operator: {operator}")


def _register_if() -> None:
    def execute(context: NodeContext) -> dict[str, list[Item]]:
        operator = str(context.params.get("operator") or "equals")
        case_sensitive = bool(context.params.get("caseSensitive"))
        raw_left = context.raw_params.get("left", context.params.get("left"))
        raw_right = context.raw_params.get("right", context.params.get("right"))
        true_items: list[Item] = []
        false_items: list[Item] = []
        for item in context.input or [Item()]:
            item_scope = {
                **context.scope,
                "_json": wrap(item.json),
                "_items": [item],
                "_input": [item],
            }
            left = resolve_value(raw_left, item_scope) if raw_left is not None else None
            right = resolve_value(raw_right, item_scope) if raw_right is not None else None
            (true_items if _compare(left, operator, right, case_sensitive) else false_items).append(
                item
            )
        return {"true": true_items, "false": false_items}

    register_node(
        NodeDefinition(
            type="core.if",
            display_name="If",
            description="Split items into true/false branches by a condition.",
            group="transform",
            outputs=["true", "false"],
            properties=[
                NodeProperty(
                    name="left",
                    display_name="Left value",
                    type="string",
                    default="{{ $json.status }}",
                    required=True,
                ),
                NodeProperty(
                    name="operator",
                    display_name="Operator",
                    type="options",
                    default="equals",
                    options=[
                        {"label": "equals", "value": "equals"},
                        {"label": "not equals", "value": "notEquals"},
                        {"label": "contains", "value": "contains"},
                        {"label": "not contains", "value": "notContains"},
                        {"label": "starts with", "value": "startsWith"},
                        {"label": "regex", "value": "regex"},
                        {"label": "greater than", "value": "gt"},
                        {"label": "greater or equal", "value": "gte"},
                        {"label": "less than", "value": "lt"},
                        {"label": "less or equal", "value": "lte"},
                        {"label": "exists", "value": "exists"},
                        {"label": "empty", "value": "empty"},
                    ],
                ),
                NodeProperty(name="right", display_name="Right value", type="string", default=""),
                NodeProperty(
                    name="caseSensitive",
                    display_name="Case sensitive",
                    type="boolean",
                    default=False,
                ),
            ],
            execute=execute,
        )
    )


def _run_python(code: str, context: NodeContext, global_scope: dict[str, Any]) -> Any:
    body = textwrap.indent(code.strip() or "return input_items", "    ")
    source = f"def __run():\n{body}\n"
    namespace: dict[str, Any] = {
        "__builtins__": SAFE_BUILTINS,
        "json": json,
        "re": re,
        "math": math,
        "datetime": datetime_module,
        "log": context.log,
        **global_scope,
    }
    exec(compile(source, "<workflow-code>", "exec"), namespace)  # noqa: S102
    return namespace["__run"]()


def _register_code() -> None:
    def execute(context: NodeContext) -> dict[str, list[Item]]:
        code = str(context.params.get("code") or "")
        mode = str(context.params.get("mode") or "all")
        input_items = [item.json for item in context.input]
        base_scope = {
            "input_items": input_items,
            "items": context.input,
            "params": context.params,
            "node": context.node.to_dict(),
            "workflow": context.workflow.to_dict(),
        }

        if mode == "each":
            output: list[Item] = []
            for index, item in enumerate(context.input or [Item()]):
                result = _run_python(
                    code,
                    context,
                    {**base_scope, "json": item.json, "index": index, "input_items": [item.json]},
                )
                if result is None:
                    output.append(item)
                elif isinstance(result, list):
                    output.extend(result)
                else:
                    output.append(result)
            return {"main": output}

        result = _run_python(code, context, {**base_scope, "json": (input_items or [{}])[0]})
        if result is None:
            return {"main": list(context.input)}
        return {"main": result if isinstance(result, list) else [result]}

    register_node(
        NodeDefinition(
            type="core.code",
            display_name="Code (Python)",
            description="Run Python for custom logic. Must return a list of dicts (or set result).",
            group="transform",
            properties=[
                NodeProperty(
                    name="mode",
                    display_name="Mode",
                    type="options",
                    default="all",
                    options=[
                        {"label": "Run once for all items", "value": "all"},
                        {"label": "Run once for each item", "value": "each"},
                    ],
                ),
                NodeProperty(
                    name="code",
                    display_name="Python code",
                    type="code",
                    default="return input_items",
                    description="Return a list of objects. Available: input_items, items, json, params, log.",
                    rows=12,
                ),
            ],
            execute=execute,
        )
    )


def _register_http() -> None:
    async def execute(context: NodeContext) -> dict[str, list[Item]]:
        params = context.params
        url = str(params.get("url") or "")
        method = str(params.get("method") or "GET").upper()
        headers = _as_json(params.get("headers"), {}) or {}
        query = _as_json(params.get("query"), {}) or {}
        body = _as_json(params.get("body"), None)
        body_type = str(params.get("bodyType") or "json")
        timeout = float(params.get("timeout") or 30)
        fail_on_error = bool(params.get("failOnError", True))

        credential_id = params.get("credentialId")
        if credential_id:
            credential = context.credentials.get(str(credential_id))
            base_url = str(credential.get("baseUrl") or "").rstrip("/")
            if base_url and url.startswith("/"):
                url = base_url + url
            if isinstance(credential.get("headers"), dict):
                headers = {**credential["headers"], **headers}
            token = credential.get("token") or credential.get("apiKey")
            if token and "Authorization" not in headers:
                header_name = str(credential.get("apiKeyHeader") or "")
                if header_name:
                    headers[header_name] = str(token)
                else:
                    headers["Authorization"] = f"Bearer {token}"

        if not url:
            raise ValueError("HTTP node: 'url' is required")

        request_kwargs: dict[str, Any] = {
            "method": method,
            "url": url,
            "headers": {str(key): str(value) for key, value in headers.items()},
            "params": query,
            "timeout": timeout,
            "follow_redirects": True,
        }
        if body is not None:
            if body_type == "raw":
                request_kwargs["content"] = body if isinstance(body, str) else json.dumps(body)
            elif body_type == "form":
                request_kwargs["data"] = body
            else:
                request_kwargs["json"] = body

        async with httpx.AsyncClient() as client:
            response = await client.request(**request_kwargs)

        content_type = response.headers.get("content-type", "")
        parsed: Any
        if "json" in content_type:
            try:
                parsed = response.json()
            except ValueError:
                parsed = response.text
        else:
            parsed = response.text

        result = {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body": parsed,
            "url": str(response.url),
        }
        context.log(f"{method} {response.url} -> {response.status_code}")

        if fail_on_error and response.status_code >= 400:
            raise ValueError(f"HTTP {method} {response.url} failed with {response.status_code}")

        return {"main": [Item(json=result)]}

    register_node(
        NodeDefinition(
            type="core.http",
            display_name="HTTP request",
            description="Call any HTTP API. Uses credentials for auth/baseUrl when provided.",
            group="action",
            properties=[
                NodeProperty(
                    name="method",
                    display_name="Method",
                    type="options",
                    default="GET",
                    options=[
                        {"label": "GET", "value": "GET"},
                        {"label": "POST", "value": "POST"},
                        {"label": "PUT", "value": "PUT"},
                        {"label": "PATCH", "value": "PATCH"},
                        {"label": "DELETE", "value": "DELETE"},
                    ],
                ),
                NodeProperty(
                    name="url",
                    display_name="URL",
                    type="string",
                    default="https://httpbin.org/get",
                    required=True,
                    description="Absolute URL or path when a credential with baseUrl is selected.",
                ),
                NodeProperty(name="headers", display_name="Headers (JSON)", type="json", default="{}", rows=4),
                NodeProperty(name="query", display_name="Query (JSON)", type="json", default="{}", rows=4),
                NodeProperty(
                    name="bodyType",
                    display_name="Body type",
                    type="options",
                    default="json",
                    options=[
                        {"label": "JSON", "value": "json"},
                        {"label": "Raw", "value": "raw"},
                        {"label": "Form", "value": "form"},
                    ],
                ),
                NodeProperty(name="body", display_name="Body (JSON / raw)", type="json", default="", rows=6),
                NodeProperty(
                    name="credentialId",
                    display_name="Credential",
                    type="credential",
                    credential_type="http",
                    default="",
                ),
                NodeProperty(name="timeout", display_name="Timeout (sec)", type="number", default=30),
                NodeProperty(
                    name="failOnError",
                    display_name="Fail on HTTP >= 400",
                    type="boolean",
                    default=True,
                ),
            ],
            execute=execute,
        )
    )


def register_nodes() -> None:
    _register_set()
    _register_if()
    _register_code()
    _register_http()
