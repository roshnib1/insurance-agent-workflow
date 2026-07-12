"""
Internal helpers shared by the tools in this package.

Not exposed as an ADK tool itself (not passed in any agent's `tools=[...]`)
-- just small utilities so each tool doesn't duplicate the same logic.
"""

import functools
import inspect
import json
import sys
from dataclasses import fields as dataclass_fields
from typing import Any, Callable, Dict, TypeVar

from schemas.models import ApplicantData

_APPLICANT_FIELD_NAMES = {f.name for f in dataclass_fields(ApplicantData)}

F = TypeVar("F", bound=Callable[..., Any])


def dict_to_applicant(data: Dict[str, Any]) -> ApplicantData:
    """Reconstruct an ApplicantData instance from a plain dict (e.g. as
    passed back and forth through an LLM tool call), ignoring any extra
    keys that aren't part of the schema."""
    filtered = {k: v for k, v in (data or {}).items() if k in _APPLICANT_FIELD_NAMES}
    return ApplicantData(**filtered)


def _json_safe(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def _emit(message: str) -> None:
    """Write tool I/O to stderr so it always shows in the CLI."""
    print(message, file=sys.stderr, flush=True)


def log_tool_io(func: F) -> F:
    """Decorator that logs each tool call's bound inputs and return value."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        tool_name = func.__name__
        try:
            bound = inspect.signature(func).bind_partial(*args, **kwargs)
            bound.apply_defaults()
            input_repr = _json_safe(dict(bound.arguments))
        except Exception:
            input_repr = _json_safe({"args": args, "kwargs": kwargs})
        _emit(f"[tool] {tool_name} input={input_repr}")

        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            _emit(f"[tool] {tool_name} raised={exc!r}")
            raise

        try:
            output_repr = _json_safe(result)
        except Exception:
            output_repr = repr(result)
        _emit(f"[tool] {tool_name} output={output_repr}")
        return result

    return wrapper  # type: ignore[return-value]
