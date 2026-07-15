"""FastAPI bridge for the existing Google ADK underwriting workflow.

This module exposes the workflow in workflow/property_controller.py as a thin
REST API layer. It never performs underwriting logic itself; it only:
- accepts requests from a frontend,
- launches the existing workflow,
- stores run state and progress, and
- returns workflow artifacts such as decisions, audit trails, and drafts.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import time
import uuid
from dotenv import load_dotenv
load_dotenv(override=True)
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from workflow import property_controller
from workflow.progress import ProgressTracker

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = PROJECT_ROOT / "output"
EMAILS_DIR = OUTPUT_DIR / "emails"

SUPPORTED_UPLOAD_EXTENSIONS = {".html", ".htm", ".pdf"}


class HealthResponse(BaseModel):
    service: str = "Commercial Property Underwriting API"
    status: str = "running"
    version: str = "1.0"


class HealthCheckResponse(BaseModel):
    status: str = "ok"


class RunRequest(BaseModel):
    sample_case: Optional[str] = Field(default=None, description="Name of a sample proposal file under data/")


class RunResponse(BaseModel):
    run_id: str
    status: str = "RUNNING"


class ErrorResponse(BaseModel):
    success: bool = False
    message: str
    details: Optional[str] = None


@dataclass
class RunRecord:
    """In-memory state for a single workflow execution."""

    run_id: str
    status: str = "RUNNING"
    file_path: Optional[str] = None
    sample_case: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None
    decision: Optional[Dict[str, Any]] = None
    progress: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    event_queue: queue.Queue = field(default_factory=queue.Queue)
    tracker: Optional["TrackedProgressTracker"] = None

    def record_event(self, payload: Dict[str, Any]) -> None:
        """Persist a workflow event and push it to the live event stream queue."""
        self.events.append(payload)
        self.progress = _build_progress_payload(self)
        self.event_queue.put(payload)

    def finalize(self, status: str, decision: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
        """Mark the run as completed or failed."""
        self.status = status
        self.decision = decision
        self.error = error
        self.completed_at = time.time()
        if self.started_at:
            self.duration_seconds = round(self.completed_at - self.started_at, 3)
        self.progress = _build_progress_payload(self)
        self.event_queue.put({
            "type": "workflow_completed" if status == "COMPLETED" else "workflow_failed",
            "run_id": self.run_id,
            "status": self.status,
            "timestamp": self.completed_at,
            "decision": decision,
            "error": error,
        })


class TrackedProgressTracker(ProgressTracker):
    """ProgressTracker subclass that bridges ADK workflow events into the API state."""

    def __init__(self) -> None:
        super().__init__()
        self.run_record = getattr(property_controller, "_ACTIVE_RUN_RECORD", None)
        if self.run_record is not None:
            self.run_record.tracker = self

    def emit(self, phase: str, step: str, event: str, **detail: Any) -> Any:
        entry = super().emit(phase, step, event, **detail)
        if self.run_record is not None:
            payload = {
                "type": _map_event_type(event),
                "phase": phase,
                "step": step,
                "event": event,
                "timestamp": entry.timestamp,
                **detail,
            }
            self.run_record.record_event(payload)
        return entry


app = FastAPI(title="Commercial Property Underwriting API", version="1.0", docs_url="/docs", redoc_url="/redoc")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RUNS: Dict[str, RunRecord] = {}
RUN_LOCK = threading.Lock()


@app.get("/", response_model=HealthResponse)
async def root() -> HealthResponse:
    """Return service metadata for the API gateway."""
    return HealthResponse()


@app.get("/health", response_model=HealthCheckResponse)
async def health() -> HealthCheckResponse:
    """Simple health check endpoint used by load balancers and monitoring."""
    return HealthCheckResponse(status="ok")


@app.get("/sample-cases")
async def sample_cases() -> Dict[str, Any]:
    """List the sample proposal files that can be used as workflow inputs."""
    candidates = []
    if DATA_DIR.exists():
        for path in sorted(DATA_DIR.iterdir()):
            if path.is_file() and path.suffix.lower() in SUPPORTED_UPLOAD_EXTENSIONS:
                candidates.append(path.name)
    return {"samples": candidates}


@app.post("/run", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_workflow_endpoint(
    request: Request,
    sample_case: Optional[str] = Form(default=None),
    file: Optional[UploadFile] = File(default=None),
) -> RunResponse:
    """Start a workflow run using either a sample case or an uploaded HTML/PDF file."""
    source_path: Optional[Path] = None
    resolved_sample = None

    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        sample_case = form.get("sample_case") or sample_case
        uploaded_file = form.get("file")
        if uploaded_file is not None and hasattr(uploaded_file, "filename"):
            file = uploaded_file  # type: ignore[assignment]
    elif request.headers.get("content-type", "").startswith("application/json"):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            sample_case = payload.get("sample_case") or sample_case

    if file is not None and getattr(file, "filename", None):
        source_path = await _store_uploaded_file(file)
    elif sample_case:
        resolved_sample = str(sample_case)
        candidate = _resolve_input_path(resolved_sample)
        if candidate is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sample case not found")
        source_path = candidate
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide sample_case or upload an HTML/PDF file")

    if source_path is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to resolve workflow input")

    run_id = uuid.uuid4().hex
    record = RunRecord(run_id=run_id, sample_case=resolved_sample or sample_case, file_path=str(source_path))

    with RUN_LOCK:
        RUNS[run_id] = record

    thread = threading.Thread(target=_run_workflow_sync, args=(run_id, str(source_path)), daemon=True)
    thread.start()
    return RunResponse(run_id=run_id, status="RUNNING")


@app.get("/progress/{run_id}")
async def progress(run_id: str) -> Dict[str, Any]:
    """Return the current progress snapshot for a running workflow."""
    record = _get_run_record(run_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return _build_progress_payload(record)


@app.get("/decision/{run_id}")
async def decision(run_id: str) -> Dict[str, Any]:
    """Return the latest decision artifact for a completed workflow."""
    record = _get_run_record(run_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if record.decision is not None:
        return record.decision
    if record.status != "COMPLETED":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow is still running")
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decision not available")


@app.get("/audit/{run_id}")
async def audit(run_id: str) -> Dict[str, Any]:
    """Return the audit trail from the workflow decision artifact."""
    record = _get_run_record(run_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if record.decision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit trail not available")
    return {
        "run_id": run_id,
        "audit_trail": record.decision.get("audit_trail", []),
    }


@app.get("/communications/{run_id}")
async def communications(run_id: str) -> Dict[str, Any]:
    """Return stored draft emails generated by the workflow."""
    record = _get_run_record(run_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    drafts = _read_email_drafts()
    return {
        "run_id": run_id,
        "communications": drafts,
    }


@app.get("/workflow-state/{run_id}")
async def workflow_state(run_id: str) -> Dict[str, Any]:
    """Return the complete in-memory workflow state for debugging and observability."""
    record = _get_run_record(run_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return {
        "run_id": run_id,
        "status": record.status,
        "file_path": record.file_path,
        "sample_case": record.sample_case,
        "started_at": record.started_at,
        "completed_at": record.completed_at,
        "duration_seconds": record.duration_seconds,
        "error": record.error,
        "progress": record.progress,
        "events": record.events,
        "decision": record.decision,
    }


@app.get("/metrics")
async def metrics() -> Dict[str, Any]:
    """Return aggregate workflow execution metrics."""
    with RUN_LOCK:
        runs = list(RUNS.values())

    completed = sum(1 for run in runs if run.status == "COMPLETED")
    failed = sum(1 for run in runs if run.status == "FAILED")
    durations = [run.duration_seconds for run in runs if run.duration_seconds is not None]
    average_execution_time = round(sum(durations) / len(durations), 3) if durations else 0.0

    return {
        "total_runs": len(runs),
        "completed": completed,
        "failed": failed,
        "average_execution_time": average_execution_time,
    }


@app.get("/events/{run_id}")
async def events(run_id: str) -> StreamingResponse:
    """Stream workflow progress events as Server-Sent Events."""
    record = _get_run_record(run_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    async def event_generator() -> Any:
        for event in list(record.events):
            yield _format_sse(event)

        while True:
            if record.status in {"COMPLETED", "FAILED"} and record.event_queue.empty():
                break
            try:
                event = record.event_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.25)
                continue
            yield _format_sse(event)
            if event.get("type") in {"workflow_completed", "workflow_failed"}:
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    """Return structured JSON errors for API-level failures."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.detail, "details": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    """Return structured JSON errors for unexpected server-side failures."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"success": False, "message": "Internal server error", "details": str(exc)},
    )


def _run_workflow_sync(run_id: str, input_path: str) -> None:
    """Execute the existing workflow in a worker thread and mirror its state to the API."""
    record = _get_run_record(run_id)
    if record is None:
        return

    try:
        original_tracker_cls = property_controller.ProgressTracker
        property_controller.ProgressTracker = TrackedProgressTracker
        property_controller._ACTIVE_RUN_RECORD = record
        decision = property_controller.run_workflow(input_path)
        record.finalize("COMPLETED", decision=decision)
    except Exception as exc:  # pragma: no cover - exercised in runtime
        record.finalize("FAILED", error=str(exc))
    finally:
        property_controller.ProgressTracker = original_tracker_cls
        property_controller._ACTIVE_RUN_RECORD = None


def _build_progress_payload(record: RunRecord) -> Dict[str, Any]:
    """Create a frontend-friendly progress snapshot from the current run state."""
    completed_nodes = sum(1 for event in record.events if event.get("event") in {"completed", "gate_decision"})
    failed_nodes = sum(1 for event in record.events if event.get("event") == "failed")
    total_estimate = 12
    progress_percentage = int(min(100, max(0, round((completed_nodes / total_estimate) * 100))))
    if record.status == "COMPLETED":
        progress_percentage = 100

    latest_event = record.events[-1] if record.events else None
    current_phase = latest_event.get("phase") if latest_event else None
    current_agent = latest_event.get("step") if latest_event else None
    active_node = current_agent

    return {
        "current_phase": current_phase,
        "current_agent": current_agent,
        "status": record.status,
        "progress_percentage": progress_percentage,
        "active_node": active_node,
        "completed_nodes": completed_nodes,
        "waiting_nodes": max(0, total_estimate - completed_nodes - failed_nodes),
        "failed_nodes": failed_nodes,
        "event_history": list(record.events)[-50:],
    }


def _map_event_type(event_name: str) -> str:
    """Map the internal tracker event names into the SSE event names expected by the frontend."""
    mapping = {
        "started": "phase_started",
        "completed": "phase_completed",
        "failed": "workflow_failed",
        "gate_decision": "gate_decision",
    }
    return mapping.get(event_name, "workflow_event")


def _format_sse(payload: Dict[str, Any]) -> str:
    """Format a progress payload as a Server-Sent Event."""
    event_type = payload.get("type", "workflow_event")
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


def _get_run_record(run_id: str) -> Optional[RunRecord]:
    """Return a stored run record, if present."""
    with RUN_LOCK:
        return RUNS.get(run_id)


def _resolve_input_path(sample_case: str) -> Optional[Path]:
    """Resolve a sample case name to a file path under data/."""
    if not sample_case:
        return None
    for base in (DATA_DIR, PROJECT_ROOT):
        candidate = (base / sample_case).resolve()
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


async def _store_uploaded_file(upload: UploadFile) -> Path:
    """Save an uploaded HTML/PDF file into the data/uploads directory."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = Path(upload.filename or "upload").name
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only HTML or PDF uploads are supported")

    destination = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    await upload.close()
    return destination


def _read_email_drafts() -> List[Dict[str, Any]]:
    """Read stored draft emails from output/emails and return their JSON payloads."""
    if not EMAILS_DIR.exists():
        return []
    drafts: List[Dict[str, Any]] = []
    for path in sorted(EMAILS_DIR.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                drafts.append(json.load(handle))
        except (OSError, json.JSONDecodeError):
            continue
    return drafts


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
