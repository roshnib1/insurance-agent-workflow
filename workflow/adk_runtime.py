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
import re
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

_session_service = InMemorySessionService()
_APP_NAME = "commercial_property_underwriting_adk"

# How many times to retry a single agent turn if the provider gives back
# an empty/errored response (e.g. LiteLLM's "Unmapped finish_reason
# 'error'" warning, or a rate-limit hiccup on a free/lite model tier).
# This is a transient-failure retry, not a fix for a code bug -- if every
# attempt fails, the error is very likely real (bad payload, bad model
# name, auth issue) and is raised as-is after the last attempt.
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5

ProgressCallback = Optional[Callable[[Dict[str, Any]], None]]


def _emit(callback: ProgressCallback, event: str, agent_name: str, **data: Any) -> None:
    if callback is None:
        return
    try:
        callback({"event": event, "agent": agent_name, **data})
    except Exception:
        pass


class _RetryableAgentError(RuntimeError):
    """Base class for agent-turn failures that are likely a transient
    upstream hiccup (provider rate limit, timeout, or an errored
    finish_reason) rather than a code bug -- retried by call_agent()."""


class _NoFinalResponse(_RetryableAgentError):
    """Raised when a single agent turn produced no usable output at all."""


class _MalformedJSONResponse(_RetryableAgentError):
    """Raised when the model's response wasn't valid JSON -- including a
    response that was cut off mid-generation (e.g. `{"a": 1, "b": ` with
    no closing brace). We've observed this happen in the exact same
    situations as _NoFinalResponse (right after a LiteLLM "Unmapped
    finish_reason 'error'" warning) -- the provider call errored out
    partway through streaming, so the agent got a real but truncated
    response rather than nothing at all. Treated the same way: retried,
    not failed immediately, since a fresh attempt reliably gets a
    complete response."""


def _find_balanced_json(text: str) -> Optional[str]:
    """Scans for the first balanced {...} object anywhere in text, correctly
    skipping over braces that appear inside string literals (so a value
    like "uses a {template} string" doesn't break the brace count). Returns
    the matched substring, or None if no balanced object is found."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        # Unbalanced from this start point -- try the next '{' in case the
        # model wrote a stray brace in prose before the real JSON object.
        start = text.find("{", start + 1)
    return None


def _extract_json_text(text: str) -> Dict[str, Any]:
    cleaned = text.strip()

    # Prefer a fenced ```json ... ``` (or bare ``` ... ```) block if one
    # exists ANYWHERE in the text -- not just at the very start. Models
    # sometimes prepend a sentence or two of reasoning before the fence
    # even when told not to; the old logic only stripped a fence that led
    # the response, so prose-first answers fell straight through to a
    # failed json.loads() on the whole blob.
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
    candidates = []
    if fence_match:
        candidates.append(fence_match.group(1).strip())
    candidates.append(cleaned)

    last_error: Optional[json.JSONDecodeError] = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc

    # Last resort: no fence, and the whole text isn't valid JSON on its
    # own (almost always because the model wrote explanatory prose before
    # or after it) -- scan for the first balanced {...} object anywhere in
    # the text and parse just that.
    balanced = _find_balanced_json(cleaned)
    if balanced is not None:
        try:
            return json.loads(balanced)
        except json.JSONDecodeError as exc:
            last_error = exc

    preview = cleaned[:500] + ("..." if len(cleaned) > 500 else "")
    raise _MalformedJSONResponse(
        f"Model response was not valid JSON ({last_error}). Raw response:\n{preview}"
    ) from last_error


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
    # Fallback: some providers (via LiteLLM/OpenRouter) emit the model's
    # actual answer on an event that isn't flagged is_final_response() --
    # e.g. the true final event arrives with empty content right after a
    # function-call round-trip, while the answer text was already on the
    # prior event. Track the last non-empty text seen on ANY model event
    # so we're not solely dependent on the is_final_response() flag.
    last_seen_text = None
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
        event_text = None
        if event.content and event.content.parts:
            texts = [p.text for p in event.content.parts if getattr(p, "text", None)]
            if texts:
                event_text = "".join(texts)
                last_seen_text = event_text

        if not event.is_final_response():
            continue

        if getattr(event, "output", None) is not None:
            final_output = event.output
        if event_text is not None:
            final_text = event_text

    if final_output is not None:
        if hasattr(final_output, "model_dump"):
            return final_output.model_dump()
        if isinstance(final_output, dict):
            return final_output
        if isinstance(final_output, str):
            return _extract_json_text(final_output)

    if final_text is not None:
        return _extract_json_text(final_text)

    # Last resort: use the last non-empty text seen on any event, even if
    # it was never marked as the final response.
    if last_seen_text is not None:
        return _extract_json_text(last_seen_text)

    raise _NoFinalResponse(f"Agent '{agent.name}' produced no final response.")


def _run_coroutine_sync(coro: Any) -> Any:
    """Run a coroutine from either sync or already-running event-loop contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    if loop.is_running():
        result: Dict[str, Any] = {}
        error: Optional[BaseException] = None

        def runner() -> None:
            nonlocal error
            try:
                result["value"] = asyncio.run(coro)
            except BaseException as exc:  # pragma: no cover - exercised in runtime
                error = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join()
        if error is not None:
            raise error
        return result["value"]

    return asyncio.run(coro)


def call_agent(
    agent: LlmAgent,
    payload: Dict[str, Any],
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """Run one ADK LlmAgent turn synchronously and return its parsed JSON
    output. Fires before/after progress events around the call.

    Retries automatically (up to MAX_RETRIES total attempts) if the
    provider turn looks like a transient upstream hiccup -- either no
    usable output at all, or a response that came back truncated/invalid
    JSON (both observed alongside LiteLLM's "Unmapped finish_reason
    'error'" warning, i.e. the provider call errored out mid-response).
    Not a code bug in either case, since the identical call pattern
    succeeds on other agents/turns in the same run. A tool raising its
    own exception, or any other unexpected error, is NOT retried -- it's
    surfaced immediately since retrying wouldn't help."""
    _emit(progress_callback, "before", agent.name)
    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = _run_coroutine_sync(_call_agent_async(agent, payload))
            _emit(progress_callback, "after", agent.name)
            return result
        except _RetryableAgentError as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                _emit(
                    progress_callback, "retry", agent.name,
                    attempt=attempt, max_retries=MAX_RETRIES,
                    error=f"{exc} (likely a transient upstream hiccup -- retrying)",
                )
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
        except Exception as exc:
            _emit(progress_callback, "failed", agent.name, error=str(exc))
            raise

    _emit(progress_callback, "failed", agent.name, error=str(last_exc))
    raise RuntimeError(
        f"{last_exc} -- gave up after {MAX_RETRIES} attempts. This is usually a "
        f"transient rate-limit/timeout from the model provider; if it persists, "
        f"check your OpenRouter dashboard for rate-limit or error details on the "
        f"configured model."
    )
