"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, Clock, FileStack, Maximize2, Minimize2, Radio, ShieldCheck } from "lucide-react";

import WorkflowCanvas from "@/components/workflow/WorkflowCanvas";
import ActiveNodePanel from "@/components/workflow/ActiveNodePanel";
import type { AgentDrawerDetail } from "@/components/workflow/AgentDrawer";
import EventConsole from "@/components/workflow/EventConsole";
import RunPanel, { type WorkflowRunStatus } from "@/components/run/RunPanel";
import DecisionCard from "@/components/decision/DecisionCard";
import { getNodeDefinition } from "@/lib/graph";
import { useWorkflowStore } from "@/store/workflowStore";

function StatusPill({ status }: { status: WorkflowRunStatus }) {
  const isRunning = status === "RUNNING";
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1 text-xs font-medium text-[var(--color-ink-muted)]">
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: isRunning ? "var(--color-wire)" : "var(--color-ink-faint)" }}
      />
      {status[0] + status.slice(1).toLowerCase()}
    </span>
  );
}

/** Ticks once a second while a run is in flight; otherwise reports the final elapsed time. */
function useElapsedMs(startedAt: number | null, completedAt: number | null, status: WorkflowRunStatus): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (status !== "RUNNING" || !startedAt) return;
    const id = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(id);
  }, [status, startedAt]);

  if (!startedAt) return 0;
  const end = status === "RUNNING" ? now : completedAt ?? now;
  return Math.max(0, end - startedAt);
}

export default function DashboardPage() {
  const samples = useWorkflowStore((s) => s.samples);
  const selectedSample = useWorkflowStore((s) => s.selectedSample);
  const loadSamples = useWorkflowStore((s) => s.loadSamples);
  const selectSample = useWorkflowStore((s) => s.selectSample);
  const setUploadedFile = useWorkflowStore((s) => s.setUploadedFile);
  const run = useWorkflowStore((s) => s.run);

  const runStatus = useWorkflowStore((s) => s.runStatus);
  const startedAt = useWorkflowStore((s) => s.startedAt);
  const completedAt = useWorkflowStore((s) => s.completedAt);
  const error = useWorkflowStore((s) => s.error);

  const nodeStatuses = useWorkflowStore((s) => s.nodeStatuses);
  const executionMs = useWorkflowStore((s) => s.executionMs);
  const resolvedRoutes = useWorkflowStore((s) => s.resolvedRoutes);
  const activeNodeId = useWorkflowStore((s) => s.activeNodeId);
  const events = useWorkflowStore((s) => s.events);

  const selectedNodeId = useWorkflowStore((s) => s.selectedNodeId);
  const selectNode = useWorkflowStore((s) => s.selectNode);

  const decision = useWorkflowStore((s) => s.decision);

  const elapsedMs = useElapsedMs(startedAt, completedAt, runStatus);

  const [canvasFullscreen, setCanvasFullscreen] = useState(false);

  useEffect(() => {
    if (!canvasFullscreen) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setCanvasFullscreen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [canvasFullscreen]);

  useEffect(() => {
    loadSamples();
  }, [loadSamples]);

  // The right-hand panel always shows *some* node's details: whichever node
  // is currently live, unless the person has clicked a different one -- in
  // which case it "pins" to that node until they click back to live.
  const panelNodeId = selectedNodeId ?? activeNodeId;
  const isPinned = selectedNodeId !== null && selectedNodeId !== activeNodeId;

  const panelDetail: AgentDrawerDetail | null = useMemo(() => {
    if (!panelNodeId) return null;
    const def = getNodeDefinition(panelNodeId);
    if (!def) return null;

    const nodeEvents = events.filter((e) => e.step !== undefined && def.matchSteps.includes(e.step));
    const latest = nodeEvents[nodeEvents.length - 1];

    return {
      nodeId: def.id,
      agentName: def.label,
      status: nodeStatuses[def.id] ?? "waiting",
      phase: latest?.phase ?? def.phase ?? undefined,
      executionMs: executionMs[def.id],
      currentStep: latest?.step,
      summary: typeof latest?.summary === "string" ? latest.summary : undefined,
      inputs: (latest?.inputs as Record<string, unknown> | undefined) ?? undefined,
      outputs: (latest?.outputs as Record<string, unknown> | undefined) ?? undefined,
      decision: resolvedRoutes[def.id] ?? (typeof latest?.decision === "string" ? latest.decision : undefined),
      confidence: typeof latest?.confidence === "number" ? latest.confidence : undefined,
      businessPolicy: typeof latest?.business_policy === "string" ? latest.business_policy : undefined,
      nextAgent: typeof latest?.next_agent === "string" ? latest.next_agent : undefined,
    };
  }, [panelNodeId, nodeStatuses, executionMs, resolvedRoutes, events]);

  function handleRun() {
    selectNode(null); // resume following live as a new run starts
    run();
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-[var(--color-app-bg)]">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-[var(--color-border)] bg-[var(--color-surface)] px-6 py-3.5">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-wire)]">
            <ShieldCheck className="h-4.5 w-4.5 text-white" strokeWidth={2} />
          </div>
          <div>
            <h1 className="text-[15px] font-semibold leading-tight text-[var(--color-ink)]">
              Commercial Property Underwriting AI Workflow
            </h1>
            <p className="text-[12px] leading-tight text-[var(--color-ink-muted)]">
              Multi-agent underwriting run &amp; audit console
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {error && (
            <span className="rounded-full border border-[var(--color-danger)] bg-[var(--color-danger-soft)] px-3 py-1 text-xs font-medium text-[var(--color-danger)]">
              {error}
            </span>
          )}
          <StatusPill status={runStatus} />
          <span className="font-mono-data inline-flex items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1 text-xs text-[var(--color-ink-muted)]">
            <Clock className="h-3.5 w-3.5" strokeWidth={1.75} />
            {(elapsedMs / 1000).toFixed(1)}s
          </span>
        </div>
      </header>

      {/* Main grid: 20% / 60% / 20% -- the canvas is the primary surface.
          Uses flex-1 (not a fixed vh height) so it -- together with the
          bottom panel below -- always fills exactly the space left under
          the header, with no dead gap at the bottom of the viewport. */}
      {canvasFullscreen && (
        <div className="fixed inset-0 z-40 bg-black/70" onClick={() => setCanvasFullscreen(false)} />
      )}
      <div className="flex min-h-0 flex-1 flex-col">
      <div className="grid min-h-0 flex-[3] grid-cols-[1fr_3fr_1fr] gap-4 p-4">
        {/* Left: Run Case (20%) */}
        <section className="flex min-h-0 flex-col rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)]">
          <header className="flex items-center gap-2 border-b border-[var(--color-border)] px-4 py-3">
            <FileStack className="h-4 w-4 text-[var(--color-ink-muted)]" strokeWidth={1.75} />
            <h2 className="text-[13px] font-semibold tracking-wide text-[var(--color-ink)]">Run Case</h2>
          </header>
          <div className="min-h-0 flex-1">
            <RunPanel
              samples={samples}
              selectedSample={selectedSample}
              onSelectSample={selectSample}
              onUpload={setUploadedFile}
              onRun={handleRun}
              status={runStatus}
              elapsedMs={elapsedMs}
              canRun={Boolean(selectedSample) && runStatus !== "RUNNING"}
            />
          </div>
        </section>

        {/* Center: Workflow Canvas (60%) -- the primary experience */}
        <section
          className={
            canvasFullscreen
              ? "canvas-grid fixed inset-4 z-50 flex flex-col overflow-hidden rounded-[var(--radius-card)] border border-[var(--color-canvas-border)] shadow-[var(--shadow-card)]"
              : "canvas-grid relative flex flex-col overflow-hidden rounded-[var(--radius-card)] border border-[var(--color-canvas-border)] shadow-[var(--shadow-card)]"
          }
        >
          <header className="flex items-center justify-between gap-2 border-b border-[var(--color-canvas-border)] bg-[var(--color-canvas-raised)] px-4 py-3">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-[var(--color-canvas-ink-muted)]" strokeWidth={1.75} />
              <h2 className="text-[13px] font-semibold tracking-wide text-[var(--color-canvas-ink)]">Workflow Canvas</h2>
            </div>
            <button
              onClick={() => setCanvasFullscreen((v) => !v)}
              className="rounded-md p-1.5 text-[var(--color-canvas-ink-muted)] transition hover:bg-white/10 hover:text-[var(--color-canvas-ink)]"
              aria-label={canvasFullscreen ? "Exit fullscreen" : "Expand to fullscreen"}
              title={canvasFullscreen ? "Exit fullscreen (Esc)" : "Expand to fullscreen"}
            >
              {canvasFullscreen ? (
                <Minimize2 className="h-3.5 w-3.5" strokeWidth={2} />
              ) : (
                <Maximize2 className="h-3.5 w-3.5" strokeWidth={2} />
              )}
            </button>
          </header>
          <div className="min-h-0 flex-1">
            <WorkflowCanvas
              nodeStatuses={nodeStatuses}
              activeNodeId={activeNodeId}
              selectedNodeId={panelNodeId}
              resolvedRoutes={resolvedRoutes}
              executionMs={executionMs}
              onSelectNode={selectNode}
            />
          </div>
        </section>

        {/* Right: Live Agent Details (20%) -- always shows the active/selected node, never a raw log */}
        <section className="flex min-h-0 flex-col rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)]">
          <header className="flex items-center gap-2 border-b border-[var(--color-border)] px-4 py-3">
            <Radio className="h-4 w-4 text-[var(--color-ink-muted)]" strokeWidth={1.75} />
            <h2 className="text-[13px] font-semibold tracking-wide text-[var(--color-ink)]">Live Agent Details</h2>
          </header>
          <div className="min-h-0 flex-1">
            <ActiveNodePanel
              detail={panelDetail}
              isPinned={isPinned}
              isRunning={runStatus === "RUNNING"}
              onReturnToLive={() => selectNode(null)}
            />
          </div>
        </section>
      </div>

      {/* Bottom: compact event log + decision summary -- secondary, not the primary UI.
          flex-[2] (not a fixed vh cap) so it fills the rest of the viewport
          exactly, with its own scroll once content overflows -- no leftover
          gap between it and the bottom of the window, and no clipped content. */}
      <div className="scrollbar-thin flex min-h-0 flex-[2] flex-col overflow-y-auto border-t border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="shrink-0">
          <EventConsole events={events} variant="compact" />
        </div>
        <div className="border-t border-[var(--color-border)] px-4 py-3">
          <DecisionCard decision={decision} isRunning={runStatus === "RUNNING"} />
        </div>
      </div>
      </div>
    </div>
  );
}