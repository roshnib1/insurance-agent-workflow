"""
adk_runtime.py

Thin synchronous wrapper around Google ADK's async Runner API, so each
business agent module can expose a plain `run(payload: dict) -> dict`
function without every caller needing to manage asyncio/session plumbing
directly. Same pattern as the reference project's adk_runtime.py.

Each call is a fresh, independent single-turn session: we hand the agent
a JSON payload as the user message, the agent returns JSON, and we parse
+ return it as a plain dict. Every agent invocation is stateless from the
ADK Runner's point of view -- workflow/state.py is the single source of
truth for state across the pipeline.

Extended beyond the reference version with an optional `progress_callback`
so every agent call fires a `before`/`after` event, matching the same
convention every tool in tools/ already uses (see tools/_common.py::emit).
"""

import asyncio
import json
import uuid
from typing import Any, Callable, Dict, Optional

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

_session_service = InMemorySessionService()
_APP_NAME = "commercial_property_underwriting_adk"

ProgressCallback = Optional[Callable[[Dict[str, Any]], None]]


def _emit(callback: ProgressCallback, event: str, agent_name: str, **data: Any) -> None:
    if callback is None:
        return
    try:
        callback({"event": event, "agent": agent_name, **data})
    except Exception:
        pass


def _extract_json_text(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned.strip())


async def _call_agent_async(agent: LlmAgent, payload: Dict[str, Any]) -> Dict[str, Any]:
    user_id = "underwriting_system"
    session_id = str(uuid.uuid4())

    await _session_service.create_session(
        app_name=_APP_NAME, user_id=user_id, session_id=session_id
    )

    runner = Runner(agent=agent, app_name=_APP_NAME, session_service=_session_service)

    message = types.Content(role="user", parts=[types.Part(text=json.dumps(payload, default=str))])

    final_output = None
    final_text = None
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
        if not event.is_final_response():
            continue
        if getattr(event, "output", None) is not None:
            final_output = event.output
        if event.content and event.content.parts:
            texts = [p.text for p in event.content.parts if getattr(p, "text", None)]
            if texts:
                final_text = "".join(texts)

    if final_output is not None:
        if hasattr(final_output, "model_dump"):
            return final_output.model_dump()
        if isinstance(final_output, dict):
            return final_output
        if isinstance(final_output, str):
            return _extract_json_text(final_output)

    if final_text is not None:
        return _extract_json_text(final_text)

    raise RuntimeError(f"Agent '{agent.name}' produced no final response.")


def call_agent(
    agent: LlmAgent,
    payload: Dict[str, Any],
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """Run one ADK LlmAgent turn synchronously and return its parsed JSON
    output. Fires before/after progress events around the call."""
    _emit(progress_callback, "before", agent.name)
    try:
        result = asyncio.run(_call_agent_async(agent, payload))
    except Exception as exc:
        _emit(progress_callback, "failed", agent.name, error=str(exc))
        raise
    _emit(progress_callback, "after", agent.name)
    return result
