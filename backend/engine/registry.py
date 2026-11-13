from __future__ import annotations

from .types import NodeDefinition

_registry: dict[str, NodeDefinition] = {}


def register(definition: NodeDefinition) -> NodeDefinition:
    if definition.type in _registry:
        raise ValueError(f"Node type already registered: {definition.type}")
    _registry[definition.type] = definition
    return definition


def register_many(definitions: list[NodeDefinition]) -> None:
    for definition in definitions:
        register(definition)


def get_definition(node_type: str) -> NodeDefinition:
    definition = _registry.get(node_type)
    if definition is None:
        raise ValueError(f"Unknown node type: {node_type}")
    return definition


def has_definition(node_type: str) -> bool:
    return node_type in _registry


def catalog() -> list[dict]:
    return [
        definition.to_catalog()
        for definition in sorted(
            _registry.values(),
            key=lambda item: (item.group, item.display_name.lower()),
        )
    ]
