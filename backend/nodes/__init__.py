from __future__ import annotations

from . import ai, core, publish, qa, triggers

_registered = False


def register_all() -> None:
    global _registered
    if _registered:
        return
    triggers.register_nodes()
    core.register_nodes()
    qa.register_nodes()
    ai.register_nodes()
    publish.register_nodes()
    _registered = True
