"""ARVA tool adapters.

Each external tool is wrapped by an adapter that knows how to find it, read
its version, build its command line as an argument vector (never a shell
string) and parse its outputs. Adapters never install anything.

The registry (every adapter, some of which use arva_core) is imported on first use of ADAPTERS, detect_all or
get_adapter, so that a single adapter such as arva_tools.flye imports with the standard library only: ARVA.app
runs it on the user's Mac with the Python of Flye's own environment (arva_tools.native).
"""
from importlib import import_module
from typing import TYPE_CHECKING, Any

from arva_tools.base import DetectedTool, ToolAdapter, ToolInfo, ToolStatus
from arva_tools.runner import (
    SIGKILL_STATUSES,
    RunResult,
    ToolExecutionError,
    ToolTimeoutError,
    nice_prefix,
    run_command,
)

if TYPE_CHECKING:
    from arva_tools.registry import ADAPTERS, detect_all, get_adapter

__version__ = "0.2.0"

_FROM_REGISTRY = ("ADAPTERS", "detect_all", "get_adapter")


def __getattr__(name: str) -> Any:
    if name in _FROM_REGISTRY:
        return getattr(import_module("arva_tools.registry"), name)
    raise AttributeError(f"module 'arva_tools' has no attribute {name!r}")


__all__ = [
    "ADAPTERS",
    "SIGKILL_STATUSES",
    "DetectedTool",
    "RunResult",
    "ToolAdapter",
    "ToolExecutionError",
    "ToolInfo",
    "ToolStatus",
    "ToolTimeoutError",
    "detect_all",
    "get_adapter",
    "nice_prefix",
    "run_command",
]
