"""
Operational Assurance integration for the insurance underwriting workflow.

Follows the sample-workflow pattern: opt-in via ASSURANCE_* env vars,
non-blocking delivery, AssuranceADKPlugin on the ADK Runner, plus manual
domain events at underwriting gates.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"
WORKFLOW_TYPE = "insurance_underwriting"

_active_run: AssuranceRunContext | None = None

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None
else:
    load_dotenv(DOTENV_PATH, override=False)


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _log_delivery_failure(exc: Exception, event_id: str) -> None:
    logger.warning(
        "Operational Assurance delivery failed for event_id=%s: %s",
        event_id,
        exc,
        exc_info=True,
    )


def create_assurance_config() -> Any | None:
    """Build AssuranceConfig from environment, or None when instrumentation is off."""
    if _truthy(os.getenv("ASSURANCE_DISABLED")):
        logger.info("Operational Assurance is disabled via ASSURANCE_DISABLED.")
        return None

    if load_dotenv is None:
        logger.warning(
            "python-dotenv is not installed, so %s could not be loaded automatically.",
            DOTENV_PATH,
        )

    try:
        from assurance import AssuranceConfig
        from assurance.privacy import CaptureMode
    except ImportError:
        logger.info("Operational Assurance SDK is not installed; instrumentation disabled.")
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
        "Operational Assurance enabled for gateway_url=%s producer_id=%s tenant_id=%s capture_mode=%s",
        config.gateway_url,
        config.producer_id,
        config.tenant_id,
        config.capture_mode.value,
    )
    return config


def is_assurance_active() -> bool:
    return create_assurance_config() is not None


@dataclass
class AssuranceRunContext:
    client: Any
    plugin: Any
    workflow_instance_id: str


def begin_run(file_path: str) -> AssuranceRunContext | None:
    """Start an assurance run for a v2 workflow invocation."""
    global _active_run

    config = create_assurance_config()
    if config is None:
        _active_run = None
        return None

    try:
        from assurance import AssuranceClient
        from assurance.integrations.adk import AssuranceADKPlugin
    except ImportError:
        logger.info(
            "Operational Assurance ADK plugin is unavailable; install assurance-sdk[adk]."
        )
        _active_run = None
        return None

    workflow_instance_id = f"wf_{uuid.uuid4()}"
    client = AssuranceClient(config)
    plugin = AssuranceADKPlugin(
        config=config,
        client=client,
        workflow_type=WORKFLOW_TYPE,
        business_object={"type": "proposal_file", "id": os.path.basename(file_path)},
        workflow_instance_id=workflow_instance_id,
        labels={"file_path": file_path, "controller": "v2"},
        name="assurance-insurance-underwriting",
    )

    ctx = AssuranceRunContext(
        client=client,
        plugin=plugin,
        workflow_instance_id=workflow_instance_id,
    )
    _active_run = ctx
    return ctx


async def close_run(ctx: AssuranceRunContext | None) -> None:
    """Flush and close assurance resources after a workflow run.

    Designed exits rely on AssuranceADKPlugin.after_run_callback to emit
    WORKFLOW_RUN_COMPLETED. plugin.close() emits WORKFLOW_RUN_FAILED only when
    no terminal workflow event was recorded (crash / timeout / cancel).
    """
    global _active_run
    _active_run = None
    if ctx is None:
        return
    try:
        await ctx.plugin.close()
    except Exception:  # noqa: BLE001
        logger.warning("Failed to close assurance ADK plugin", exc_info=True)


def _record_event(event_type: str, payload: dict[str, Any] | None, metadata: dict[str, Any] | None = None) -> None:
    if _active_run is None:
        return
    try:
        _active_run.client.record_event(
            event_type=event_type,
            payload=payload,
            metadata=metadata or {"source": "insurance_underwriting_v2"},
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to record assurance event %s", event_type, exc_info=True)


def emit_gate_evaluated(
    gate: str,
    route: str,
    application_id: str | None,
    details: dict[str, Any],
) -> None:
    _record_event(
        "UNDERWRITING_GATE_EVALUATED",
        {
            "gate": gate,
            "route": route,
            "application_id": application_id or "UNKNOWN",
            "details": details,
        },
    )


def emit_human_approval(
    trigger: str,
    action: str | None,
    reason: str | None,
    application_id: str | None,
) -> None:
    _record_event(
        "HUMAN_APPROVAL",
        {
            "trigger": trigger,
            "action": action,
            "reason": reason,
            "application_id": application_id or "UNKNOWN",
        },
    )


def emit_decision_finalized(decision: dict[str, Any]) -> None:
    communication = decision.get("communication")
    _record_event(
        "UNDERWRITING_DECISION_FINALIZED",
        {
            "application_id": decision.get("application_id") or "UNKNOWN",
            "status": decision.get("status") or "UNKNOWN",
            "recommendation": decision.get("recommendation") or "UNKNOWN",
            "risk_category": decision.get("risk_category"),
            "risk_score": decision.get("risk_score"),
            "confidence": decision.get("confidence"),
            "premium": decision.get("premium"),
            "had_communication_draft": communication is not None,
        },
    )


def _function_node_run_id() -> str:
    if _active_run is None:
        return "unknown"
    return _active_run.workflow_instance_id


def _function_node_metadata() -> dict[str, Any]:
    return {"source": "insurance_underwriting_v2", "origin": "function_node"}


def emit_tool_call_started(
    tool_name: str,
    tool_args: dict[str, Any] | None,
    *,
    agent_name: str,
) -> None:
    """Emit TOOL_CALL_STARTED for a tool invoked inside a FunctionNode."""
    payload: dict[str, Any] = {
        "tool_name": tool_name,
        "agent_name": agent_name,
        "run_id": _function_node_run_id(),
    }
    if tool_args is not None:
        payload["tool_args"] = tool_args
    _record_event("TOOL_CALL_STARTED", payload, metadata=_function_node_metadata())


def emit_tool_call_completed(
    tool_name: str,
    *,
    agent_name: str,
    execution_time_ms: int,
    tool_args: dict[str, Any] | None = None,
    result: Any = None,
) -> None:
    """Emit TOOL_CALL_COMPLETED for a tool invoked inside a FunctionNode."""
    payload: dict[str, Any] = {
        "tool_name": tool_name,
        "agent_name": agent_name,
        "run_id": _function_node_run_id(),
        "execution_time_ms": int(execution_time_ms),
        "status": "success",
    }
    if tool_args is not None:
        payload["tool_args"] = tool_args
    if result is not None:
        payload["result"] = result
    _record_event("TOOL_CALL_COMPLETED", payload, metadata=_function_node_metadata())


def emit_tool_call_failed(
    tool_name: str,
    error: BaseException,
    *,
    agent_name: str,
    tool_args: dict[str, Any] | None = None,
) -> None:
    """Emit TOOL_CALL_FAILED for a tool invoked inside a FunctionNode."""
    import hashlib

    stack_digest = hashlib.sha256(
        f"{type(error).__name__}:{error}".encode("utf-8", errors="replace")
    ).hexdigest()[:32]
    payload: dict[str, Any] = {
        "tool_name": tool_name,
        "agent_name": agent_name,
        "run_id": _function_node_run_id(),
        "status": "failed",
        "error_class": type(error).__name__,
        "stack_hash": stack_digest,
    }
    if tool_args is not None:
        payload["tool_args"] = tool_args
    _record_event("TOOL_CALL_FAILED", payload, metadata=_function_node_metadata())

