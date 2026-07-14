"""
Assurance ADK plugin factory + FunctionNode emitter for the v2 workflow.

Builds an AssuranceADKPlugin from ASSURANCE_* env vars when the SDK is
installed and configured. Returns None when instrumentation is disabled
or unavailable so the host workflow never fails because of observability.

Also provides:

- ``assurance_node`` — drop-in for ADK's ``@node`` that emits FunctionNode
  TOOL_CALL_* events on the gateway timeline.
- ``nested_agent_plugins`` — plugins for nested LlmAgent Runners used by
  ``adk_runtime.call_agent``, so AGENT_RUN_*, MODEL_INVOCATION_*, and agent
  TOOL_CALL_* are captured without a second WORKFLOW_RUN_* boundary.
"""

from __future__ import annotations

import functools
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

WORKFLOW_TYPE = "commercial_property_underwriting"
_FUNCTION_AGENT_NAME = "FunctionNode"

_active_plugin: ContextVar[Any] = ContextVar("assurance_active_plugin", default=None)


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _log_delivery_failure(exc: Exception, event_id: str) -> None:
    logger.warning(
        "Operational Assurance delivery failed for event_id=%s: %s",
        event_id,
        exc,
        exc_info=True,
    )


def set_active_assurance_plugin(plugin: Any | None) -> Any:
    """Bind the run's AssuranceADKPlugin so FunctionNodes can emit on it."""
    return _active_plugin.set(plugin)


def reset_active_assurance_plugin(token: Any) -> None:
    _active_plugin.reset(token)


def get_active_assurance_plugin() -> Any | None:
    return _active_plugin.get()


def nested_agent_plugins(parent: Any | None = None) -> list[Any]:
    """Return plugins for nested LlmAgent Runners (``adk_runtime.call_agent``).

    The property-underwriting graph runs each business agent in a *separate*
    ADK ``Runner``. AGENT_RUN_*, MODEL_INVOCATION_*, and agent TOOL_CALL_* are
    only emitted when that Runner has an Assurance plugin.

    We must **not** reuse the parent ``AssuranceADKPlugin`` as-is: its
    ``before_run`` / ``after_run`` would emit a second WORKFLOW_RUN_* pair and
    tear down the outer workflow context. This wrapper delegates only the
    agent / model / tool hooks to the parent plugin.
    """
    if parent is None:
        parent = get_active_assurance_plugin()
    if parent is None:
        return []

    base_plugin_cls: Any = None
    try:
        from google.adk.plugins.base_plugin import BasePlugin as _BasePlugin

        base_plugin_cls = _BasePlugin
    except ImportError:
        for cls in type(parent).__mro__:
            if cls.__name__ == "BasePlugin" and cls is not object:
                base_plugin_cls = cls
                break
    if base_plugin_cls is None:
        logger.warning(
            "Cannot attach nested assurance plugin: ADK BasePlugin unavailable."
        )
        return []

    class _NestedAgentAssurancePlugin(base_plugin_cls):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__(name="assurance-nested-agent")

        async def before_run_callback(self, *, invocation_context: Any) -> Any:
            # Outer workflow already emitted WORKFLOW_RUN_STARTED.
            return None

        async def after_run_callback(self, *, invocation_context: Any) -> None:
            # Do not emit WORKFLOW_RUN_COMPLETED or clear the parent context/trace.
            try:
                client = getattr(parent, "client", None)
                flush = getattr(client, "flush", None)
                if callable(flush):
                    flush()
            except Exception:  # noqa: BLE001
                pass

        async def before_agent_callback(self, **kwargs: Any) -> Any:
            return await parent.before_agent_callback(**kwargs)

        async def after_agent_callback(self, **kwargs: Any) -> Any:
            return await parent.after_agent_callback(**kwargs)

        async def before_model_callback(self, **kwargs: Any) -> Any:
            return await parent.before_model_callback(**kwargs)

        async def after_model_callback(self, **kwargs: Any) -> Any:
            return await parent.after_model_callback(**kwargs)

        async def on_model_error_callback(self, **kwargs: Any) -> Any:
            return await parent.on_model_error_callback(**kwargs)

        async def before_tool_callback(self, **kwargs: Any) -> Any:
            return await parent.before_tool_callback(**kwargs)

        async def after_tool_callback(self, **kwargs: Any) -> Any:
            return await parent.after_tool_callback(**kwargs)

        async def on_tool_error_callback(self, **kwargs: Any) -> Any:
            return await parent.on_tool_error_callback(**kwargs)

    return [_NestedAgentAssurancePlugin()]


def create_assurance_config() -> Any | None:
    """Build AssuranceConfig from environment, or None when instrumentation is off."""
    if _truthy(os.getenv("ASSURANCE_DISABLED")):
        logger.info("Operational Assurance is disabled via ASSURANCE_DISABLED.")
        return None

    try:
        from assurance import AssuranceConfig
        from assurance.privacy import CaptureMode
    except ImportError:
        logger.info(
            "Operational Assurance SDK is not installed; instrumentation disabled. "
            "Install with: pip install -e \"/path/to/sdk-gateway/sdk[adk]\""
        )
        return None

    config = AssuranceConfig.from_env()
    if config is None:
        logger.info(
            "Operational Assurance is inactive. Missing one or more required env vars: "
            "ASSURANCE_GATEWAY_URL, ASSURANCE_API_KEY, ASSURANCE_PRODUCER_ID."
        )
        return None

    tenant_id = os.getenv("ASSURANCE_TENANT_ID")
    if tenant_id:
        config.tenant_id = tenant_id
    config.failure_callback = _log_delivery_failure

    capture_mode_name = os.getenv("ASSURANCE_CAPTURE_MODE")
    if capture_mode_name:
        try:
            config.capture_mode = CaptureMode(capture_mode_name)
        except ValueError:
            config.capture_mode = CaptureMode.METADATA_ONLY

    logger.info(
        "Operational Assurance enabled for gateway_url=%s producer_id=%s "
        "tenant_id=%s capture_mode=%s",
        config.gateway_url,
        config.producer_id,
        config.tenant_id,
        config.capture_mode.value,
    )
    return config


def build_assurance_plugin(
    *,
    workflow_type: str = WORKFLOW_TYPE,
    business_object: Optional[Dict[str, Any]] = None,
    workflow_instance_id: Optional[str] = None,
    labels: Optional[Dict[str, str]] = None,
    client: Any | None = None,
    config: Any | None = None,
) -> Any | None:
    """Create an AssuranceADKPlugin for this workflow run, or None if disabled."""
    try:
        from assurance.integrations.adk import AssuranceADKPlugin
    except ImportError:
        logger.info(
            "Operational Assurance ADK plugin is unavailable; install assurance-sdk[adk]."
        )
        return None

    resolved_config = config if config is not None else create_assurance_config()
    if resolved_config is None and client is None:
        return None

    plugin_kwargs: Dict[str, Any] = {
        "workflow_type": workflow_type,
        "business_object": business_object or {},
        "labels": labels or {},
        "name": "assurance-commercial-property-underwriting",
    }
    if workflow_instance_id is not None:
        plugin_kwargs["workflow_instance_id"] = workflow_instance_id
    if resolved_config is not None:
        plugin_kwargs["config"] = resolved_config
    if client is not None:
        plugin_kwargs["client"] = client

    return AssuranceADKPlugin(**plugin_kwargs)


def _normalize_value(value: Any) -> Any:
    """Turn ADK Event / Pydantic / dataclass-ish values into plain structures."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    # google.adk.Event stores route on actions.route, not a top-level .route attr.
    type_name = type(value).__name__
    if type_name == "Event" and hasattr(value, "actions") and hasattr(value, "output"):
        actions = getattr(value, "actions", None)
        route = getattr(actions, "route", None) if actions is not None else None
        return {
            "type": "Event",
            "route": route,
            "output": _normalize_value(getattr(value, "output", None)),
        }

    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(mode="python")
        except Exception:  # noqa: BLE001
            try:
                dumped = value.model_dump()
            except Exception:  # noqa: BLE001
                return type_name
        # Prefer a slim Event projection if model_dump exposed actions.route.
        if isinstance(dumped, dict) and "actions" in dumped and "output" in dumped:
            actions = dumped.get("actions") or {}
            route = actions.get("route") if isinstance(actions, dict) else None
            return {
                "type": "Event",
                "route": route,
                "output": _normalize_value(dumped.get("output")),
            }
        return dumped

    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(v) for v in value]
    if hasattr(value, "__dict__") and not isinstance(value, type):
        public = {
            k: v
            for k, v in vars(value).items()
            if not k.startswith("_") and not callable(v)
        }
        if public and len(public) <= 40:
            return {str(k): _normalize_value(v) for k, v in public.items()}
        return type_name
    return value


def _summarize(value: Any) -> Any:
    """Compact, PII-light summary of FunctionNode inputs/outputs for event payloads."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 400 else value[:400] + "…"
    if type(value).__name__ == "Event" and hasattr(value, "actions"):
        actions = getattr(value, "actions", None)
        return {
            "type": "Event",
            "route": getattr(actions, "route", None) if actions is not None else None,
        }
    if isinstance(value, dict):
        summary: Dict[str, Any] = {"_keys": sorted(str(k) for k in list(value.keys())[:40])}
        for key in (
            "status",
            "application_id",
            "complete",
            "action",
            "approve",
            "file_path",
            "risk_category",
            "decision_mode",
            "decision_maker",
            "route",
        ):
            if key in value:
                summary[key] = _summarize(value[key])
        return summary
    if isinstance(value, (list, tuple)):
        return {"_type": type(value).__name__, "_len": len(value)}
    if hasattr(value, "model_dump"):
        try:
            return _summarize(value.model_dump())
        except Exception:  # noqa: BLE001
            return type(value).__name__
    return type(value).__name__


def _shape_tool_value(plugin: Any, value: Any) -> Any:
    """Serialize FunctionNode args/results according to the active capture mode.

    ``full_payload`` / ``redacted`` → full JSON-able structure via SDK ``to_jsonable``.
    ``hash_only`` → content hash only.
    ``metadata_only`` → omit (None); plugin ``apply_capture_mode`` also drops payload.
    """
    try:
        from assurance.privacy import CaptureMode
    except ImportError:
        return _summarize(value)

    capture_mode = CaptureMode.METADATA_ONLY
    config = getattr(plugin, "_config", None) or getattr(getattr(plugin, "client", None), "config", None)
    if config is not None:
        capture_mode = getattr(config, "capture_mode", capture_mode)

    if capture_mode == CaptureMode.METADATA_ONLY:
        return None
    if capture_mode == CaptureMode.HASH_ONLY:
        try:
            from assurance.integrations.adk.hashing import canonical_hash
            from assurance.integrations.adk.payloads import to_jsonable

            return {"content_hash": canonical_hash(to_jsonable(_normalize_value(value)))}
        except Exception:  # noqa: BLE001
            return {"content_hash": None}

    # full_payload / redacted / anything else: send the real structure
    try:
        from assurance.integrations.adk.payloads import to_jsonable

        return to_jsonable(_normalize_value(value))
    except Exception:  # noqa: BLE001
        return _summarize(value)


def _emit_via_plugin(
    plugin: Any,
    event_type: str,
    payload: Dict[str, Any],
    *,
    span_id: str | None = None,
    parent_span_id: str | None = None,
) -> None:
    """Emit through the plugin's sequenced _emit when available; else raw client."""
    try:
        emit = getattr(plugin, "_emit", None)
        if callable(emit):
            emit(event_type, payload, span_id=span_id, parent_span_id=parent_span_id)
            return
        client = getattr(plugin, "client", None)
        if client is not None:
            client.record_event(event_type, payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("FunctionNode assurance emit failed for %s: %s", event_type, exc)


@contextmanager
def instrument_function_step(
    tool_name: str,
    *,
    tool_args: Any = None,
    agent_name: str = _FUNCTION_AGENT_NAME,
) -> Iterator[Dict[str, Any]]:
    """Context manager that emits STARTED, and COMPLETED/FAILED with optional result.

    Usage::

        with instrument_function_step("intake", tool_args=node_input) as step:
            out = do_work()
            step["result"] = out
            return out
    """
    plugin = get_active_assurance_plugin()
    step: Dict[str, Any] = {"result": None}
    if plugin is None:
        yield step
        return

    try:
        from assurance.integrations.adk.payloads import (
            tool_completed_payload,
            tool_failed_payload,
            tool_started_payload,
        )
        from assurance.integrations.adk.trace import get_trace, monotonic_ms
    except ImportError:
        yield step
        return

    try:
        from assurance import get_workflow_context

        wf = get_workflow_context()
        run_id = wf.trace_id or wf.correlation_id or wf.workflow_id or "unknown"
    except Exception:  # noqa: BLE001
        run_id = "unknown"

    trace = get_trace()
    span_id = trace.new_span_id()
    parent_span_id = trace.current_span_id()
    args_payload = _shape_tool_value(plugin, tool_args)
    started_at = time.perf_counter()

    _emit_via_plugin(
        plugin,
        "TOOL_CALL_STARTED",
        tool_started_payload(
            tool_name=tool_name,
            agent_name=agent_name,
            run_id=run_id,
            tool_args=args_payload,
        ),
        span_id=span_id,
        parent_span_id=parent_span_id,
    )

    try:
        yield step
    except Exception as exc:
        _emit_via_plugin(
            plugin,
            "TOOL_CALL_FAILED",
            tool_failed_payload(
                tool_name=tool_name,
                agent_name=agent_name,
                run_id=run_id,
                error=exc,
                tool_args=args_payload,
            ),
            span_id=span_id,
            parent_span_id=parent_span_id,
        )
        raise

    _emit_via_plugin(
        plugin,
        "TOOL_CALL_COMPLETED",
        tool_completed_payload(
            tool_name=tool_name,
            agent_name=agent_name,
            run_id=run_id,
            execution_time_ms=monotonic_ms(started_at),
            tool_args=args_payload,
            result=_shape_tool_value(plugin, step.get("result")),
        ),
        span_id=span_id,
        parent_span_id=parent_span_id,
    )


def assurance_node(node_like: Any = None, **node_kwargs: Any) -> Any:
    """Drop-in for ``google.adk.workflow.node`` that also emits TOOL_CALL_* events.

    Use as ``@assurance_node`` or ``@assurance_node(name=...)`` — same API as ADK ``@node``.
    """
    from google.adk.workflow import node as adk_node

    def decorate(fn: Any) -> Any:
        @functools.wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            node_input = kwargs.get("node_input")
            if node_input is None and len(args) >= 2:
                node_input = args[1]
            with instrument_function_step(fn.__name__, tool_args=node_input) as step:
                result = fn(*args, **kwargs)
                step["result"] = result
                return result

        return adk_node(wrapped, **node_kwargs)

    if node_like is not None:
        return decorate(node_like)
    return decorate
