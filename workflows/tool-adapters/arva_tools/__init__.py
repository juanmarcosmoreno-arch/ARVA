"""ARVA tool adapters.

Each external tool is wrapped by an adapter that knows how to find it, read
its version, build its command line as an argument vector (never a shell
string) and parse its outputs. Adapters never install anything.
"""
from arva_tools.base import DetectedTool, ToolAdapter, ToolInfo, ToolStatus
from arva_tools.registry import ADAPTERS, detect_all, get_adapter
from arva_tools.runner import (
    SIGKILL_STATUSES,
    RunResult,
    ToolExecutionError,
    ToolTimeoutError,
    nice_prefix,
    run_command,
)

__version__ = "0.2.0"

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
