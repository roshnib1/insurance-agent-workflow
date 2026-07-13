"""
workflow/progress.py


"""

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ProgressEvent:
    timestamp: float
    phase: str
    step: str
    event: str  # "started" | "completed" | "failed" | "gate_decision"
    detail: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "phase": self.phase,
            "step": self.step,
            "event": self.event,
            **self.detail,
        }


class ProgressTracker:
    """
    Usage:
        tracker = ProgressTracker(on_event=lambda e: st.write(e))
        tracker.emit("PHASE_1_SUBMISSION_INTAKE", "SubmissionIntakeAgent", "started")
        ... do work ...
        tracker.emit("PHASE_1_SUBMISSION_INTAKE", "SubmissionIntakeAgent", "completed", complete=True)

    Or wrap a step with the context manager:
        with tracker.step("PHASE_3_CAT_EXPOSURE", "cat_vendor_tool"):
            result = call_cat_vendor(...)
    """

    def __init__(self, on_event: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.on_event = on_event
        self.events: List[ProgressEvent] = []

    def emit(self, phase: str, step: str, event: str, **detail: Any) -> ProgressEvent:
        entry = ProgressEvent(timestamp=time.time(), phase=phase, step=step, event=event, detail=detail)
        self.events.append(entry)
        if self.on_event is not None:
            try:
                self.on_event(entry.as_dict())
            except Exception:
                pass
        return entry

    def started(self, phase: str, step: str, **detail: Any) -> None:
        self.emit(phase, step, "started", **detail)

    def completed(self, phase: str, step: str, **detail: Any) -> None:
        self.emit(phase, step, "completed", **detail)

    def failed(self, phase: str, step: str, error: str) -> None:
        self.emit(phase, step, "failed", error=error)

    def gate_decision(self, phase: str, step: str, route: str, **detail: Any) -> None:
        self.emit(phase, step, "gate_decision", route=route, **detail)

    def step(self, phase: str, step: str):
        return _StepContext(self, phase, step)

    def tool_callback(self, phase: str, step: str) -> Callable[[Dict[str, Any]], None]:
        """
        Adapts this tracker into the `progress_callback(event_dict)` shape
        every function in tools/ already accepts (see tools/_common.py::emit),
        so a single call site can wire a tool straight into the tracker:

            hz = detect_hazards(fields, progress_callback=tracker.tool_callback(
                "PHASE_2_DOCUMENT_INTELLIGENCE", "hazard_detection_tool"))
        """
        def _callback(event_dict: Dict[str, Any]) -> None:
            tool_event = event_dict.get("event", "info")
            mapped = {"before": "started", "after": "completed", "failed": "failed"}.get(tool_event, tool_event)
            extra = {k: v for k, v in event_dict.items() if k not in ("event", "tool", "timestamp")}
            self.emit(phase, step, mapped, **extra)
        return _callback

    def agent_callback(self, phase: str) -> Callable[[Dict[str, Any]], None]:
        """Same adaptation for workflow.adk_runtime.call_agent's progress_callback."""
        def _callback(event_dict: Dict[str, Any]) -> None:
            agent_event = event_dict.get("event", "info")
            mapped = {"before": "started", "after": "completed", "failed": "failed"}.get(agent_event, agent_event)
            step = event_dict.get("agent", "agent")
            extra = {k: v for k, v in event_dict.items() if k not in ("event", "agent")}
            self.emit(phase, step, mapped, **extra)
        return _callback

    def as_list(self) -> List[Dict[str, Any]]:
        return [e.as_dict() for e in self.events]


class _StepContext:
    def __init__(self, tracker: ProgressTracker, phase: str, step: str):
        self.tracker = tracker
        self.phase = phase
        self.step = step

    def __enter__(self):
        self.tracker.started(self.phase, self.step)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.tracker.failed(self.phase, self.step, error=str(exc_val))
            return False
        self.tracker.completed(self.phase, self.step)
        return False
