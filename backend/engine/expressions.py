from __future__ import annotations

import datetime as _datetime
import json as _json_module
import math as _math
import re as _re
from typing import Any, Callable

from .types import Item

_SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "map": map,
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

_FULL_EXPRESSION = _re.compile(r"^\s*\{\{(.+)\}\}\s*$", _re.DOTALL)
_INLINE_EXPRESSION = _re.compile(r"\{\{(.+?)\}\}", _re.DOTALL)
_DOLLAR_NAME = _re.compile(r"\$(json|items|item|node|env|now|run|workflow|input)\b")
_MAX_EXPRESSION_LENGTH = 4000


class DotDict(dict):
    """Dict that also supports attribute access: $json.user.name."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None

    def __getitem__(self, key: Any) -> Any:
        return wrap(super().__getitem__(key))


def wrap(value: Any) -> Any:
    if isinstance(value, DotDict):
        return value
    if isinstance(value, dict):
        return DotDict({key: wrap(entry) for key, entry in value.items()})
    if isinstance(value, list):
        return [wrap(entry) for entry in value]
    return value


class NodeRef:
    def __init__(self, items: list[Item]) -> None:
        self.items = items
        self.json = wrap(items[0].json) if items else DotDict()

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


def _transform_expression(expression: str) -> str:
    return _DOLLAR_NAME.sub(lambda match: "_" + match.group(1), expression)


def _evaluate(expression: str, scope: dict[str, Any]) -> Any:
    if len(expression) > _MAX_EXPRESSION_LENGTH:
        raise ValueError("Expression is too long")
    code = _transform_expression(expression)
    globals_dict = {
        "__builtins__": _SAFE_BUILTINS,
        "json": _json_module,
        "datetime": _datetime,
        "math": _math,
        "re": _re,
    }
    try:
        return eval(code, globals_dict, scope)  # noqa: S307 - user-authored workflows
    except Exception as error:  # noqa: BLE001
        raise ValueError(f"Expression failed: {{{{{expression}}}}} -> {error}") from error


def create_scope(
    *,
    json_data: dict[str, Any],
    items: list[Item],
    env: dict[str, str],
    run_id: str,
    workflow_id: str,
    workflow_name: str,
    get_node_items: Callable[[str], list[Item]],
    now: str | None = None,
) -> dict[str, Any]:
    wrapped_items = [Item(json=wrap(item.json), binary=item.binary) for item in items]

    def _node(name_or_id: str) -> NodeRef:
        return NodeRef(get_node_items(name_or_id))

    def _item(index: int = 0) -> dict[str, Any]:
        if index < 0 or index >= len(wrapped_items):
            return DotDict()
        return wrapped_items[index].json

    return {
        "_json": wrap(json_data),
        "_items": wrapped_items,
        "_input": wrapped_items,
        "_item": _item,
        "_node": _node,
        "_env": DotDict(env),
        "_now": now or _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
        "_run": DotDict({"id": run_id, "workflowId": workflow_id}),
        "_workflow": DotDict({"id": workflow_id, "name": workflow_name}),
    }


def resolve_value(value: Any, scope: dict[str, Any]) -> Any:
    if isinstance(value, str):
        full = _FULL_EXPRESSION.match(value)
        if full:
            return _evaluate(full.group(1), scope)

        def replace(match: _re.Match[str]) -> str:
            result = _evaluate(match.group(1), scope)
            if result is None:
                return ""
            return result if isinstance(result, str) else _json_module.dumps(result, default=str)

        return _INLINE_EXPRESSION.sub(replace, value)

    if isinstance(value, list):
        return [resolve_value(entry, scope) for entry in value]

    if isinstance(value, dict):
        return {key: resolve_value(entry, scope) for key, entry in value.items()}

    return value


def resolve_parameters(parameters: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    return resolve_value(parameters or {}, scope)
