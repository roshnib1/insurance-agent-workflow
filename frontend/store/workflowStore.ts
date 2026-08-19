"use client";

import { create } from "zustand";

import { getDecision, getSampleCases, runWorkflow as apiRunWorkflow } from "@/lib/api";
import { connectToEvents } from "@/lib/sse";
import { matchEventToNode } from "@/lib/graph";
import type { WorkflowRunStatus } from "@/components/run/RunPanel";
import type { DecisionPayload, NodeStatus, WorkflowEvent } from "@/types/workflow";

interface WorkflowStoreState {
  // --- Run Case (left panel) ---
  samples: string[];
  samplesLoading: boolean;
  selectedSample: string | null;
  uploadedFile: File | null;

  // --- Run lifecycle ---
  runId: string | null;
  runStatus: WorkflowRunStatus;
  startedAt: number | null;
  completedAt: number | null;
  error: string | null;

  // --- Live telemetry, derived from the SSE stream ---
  events: WorkflowEvent[];
  nodeStatuses: Record<string, NodeStatus>;
  executionMs: Record<string, number>;
  resolvedRoutes: Record<string, string>;
  activeNodeId: string | null;

  // --- UI selection ---
  selectedNodeId: string | null;

  // --- Final artifacts ---
  decision: DecisionPayload | null;

  /** internal: disconnect function for the current SSE stream, if any */
  _disconnect: (() => void) | null;
  /** internal: per-node "started" timestamp, used to compute executionMs on completion */
  _nodeStartedAt: Record<string, number>;
  /** internal: forward one parsed SSE frame into store state */
  _handleEvent: (event: WorkflowEvent) => void;

  // --- actions ---
  loadSamples: () => Promise<void>;
  selectSample: (sample: string) => void;
  setUploadedFile: (file: File | null) => void;
  selectNode: (nodeId: string | null) => void;
  run: () => Promise<void>;
  reset: () => void;
}

const initialLiveState = {
  runId: null as string | null,
  runStatus: "IDLE" as WorkflowRunStatus,
  startedAt: null as number | null,
  completedAt: null as number | null,
  error: null as string | null,
  events: [] as WorkflowEvent[],
  nodeStatuses: {} as Record<string, NodeStatus>,
  executionMs: {} as Record<string, number>,
  resolvedRoutes: {} as Record<string, string>,
  activeNodeId: null as string | null,
  selectedNodeId: null as string | null,
  decision: null as DecisionPayload | null,
  _nodeStartedAt: {} as Record<string, number>,
};

export const useWorkflowStore = create<WorkflowStoreState>((set, get) => ({
  samples: [],
  samplesLoading: false,
  selectedSample: null,
  uploadedFile: null,
  _disconnect: null,
  ...initialLiveState,

  async loadSamples() {
    set({ samplesLoading: true });
    try {
      const { samples } = await getSampleCases();
      set({ samples, samplesLoading: false });
    } catch {
      // Leave samples empty; the Run panel already handles an empty list gracefully.
      set({ samplesLoading: false });
    }
  },

  selectSample(sample) {
    set({ selectedSample: sample, uploadedFile: null });
  },

  setUploadedFile(file) {
    set({ uploadedFile: file, selectedSample: null });
  },

  selectNode(nodeId) {
    set({ selectedNodeId: nodeId });
  },

  async run() {
    const { selectedSample, uploadedFile, _disconnect } = get();
    if (!selectedSample && !uploadedFile) return;

    // Tear down any previous stream before starting a new run.
    _disconnect?.();

    set({
      ...initialLiveState,
      runStatus: "RUNNING",
      startedAt: Date.now(),
    });

    try {
      const { run_id } = await apiRunWorkflow(uploadedFile ? { file: uploadedFile } : { sampleCase: selectedSample! });
      set({ runId: run_id });

      const disconnect = connectToEvents(run_id, {
        onEvent: (event) => get()._handleEvent(event),
        onError: () => {
          // EventSource retries transient errors on its own; a hard failure
          // is surfaced instead via the terminal workflow_failed frame.
        },
      });
      set({ _disconnect: disconnect });
    } catch (err) {
      set({
        runStatus: "FAILED",
        error: err instanceof Error ? err.message : "Failed to start the workflow run.",
        completedAt: Date.now(),
      });
    }
  },

  reset() {
    get()._disconnect?.();
    set({ ...initialLiveState, _disconnect: null });
  },

  _handleEvent(event: WorkflowEvent) {
    // Terminal frame from RunRecord.finalize(): no phase/step, carries the
    // final status and (if successful) the full decision artifact inline.
    if (event.step === undefined) {
      const finished = event.status === "COMPLETED" ? "COMPLETED" : "FAILED";
      set({
        runStatus: finished,
        completedAt: Date.now(),
        decision: (event.decision as DecisionPayload | undefined) ?? null,
        error: (event.error as string | undefined) ?? null,
      });
      get()._disconnect?.();
      set({ _disconnect: null });

      // If the workflow failed, make sure whatever node was mid-flight
      // reflects that rather than sitting on "running" forever.
      if (finished === "FAILED") {
        set((state) => {
          const activeId = state.activeNodeId;
          if (!activeId || state.nodeStatuses[activeId] === "completed") return state;
          return { nodeStatuses: { ...state.nodeStatuses, [activeId]: "failed" } };
        });
      } else {
        // Mark the terminal "Decision" node as completed on success.
        set((state) => ({
          nodeStatuses: { ...state.nodeStatuses, decision: "completed" },
          activeNodeId: "decision",
        }));
      }
      return;
    }

    const nodeId = matchEventToNode({ step: event.step, phase: event.phase });
    set((state) => {
      const events = [...state.events, event];
      if (!nodeId) return { events };

      const nodeStatuses = { ...state.nodeStatuses };
      const executionMs = { ...state.executionMs };
      const resolvedRoutes = { ...state.resolvedRoutes };
      const nodeStartedAt = { ...state._nodeStartedAt };

      switch (event.event) {
        case "started":
          nodeStatuses[nodeId] = "running";
          nodeStartedAt[nodeId] = event.timestamp;
          break;
        case "completed":
          nodeStatuses[nodeId] = "completed";
          if (nodeStartedAt[nodeId]) {
            executionMs[nodeId] = Math.max(0, (event.timestamp - nodeStartedAt[nodeId]) * 1000);
          }
          break;
        case "gate_decision":
          nodeStatuses[nodeId] = "completed";
          if (typeof event.route === "string") resolvedRoutes[nodeId] = event.route;
          if (nodeStartedAt[nodeId]) {
            executionMs[nodeId] = Math.max(0, (event.timestamp - nodeStartedAt[nodeId]) * 1000);
          }
          break;
        case "failed":
          nodeStatuses[nodeId] = "failed";
          break;
        default:
          break;
      }

      return {
        events,
        nodeStatuses,
        executionMs,
        resolvedRoutes,
        activeNodeId: nodeId,
        _nodeStartedAt: nodeStartedAt,
      };
    });
  },
}));

/**
 * Best-effort refresh of the decision artifact for a run that already
 * finished but whose terminal SSE frame was missed (e.g. the tab was
 * backgrounded). Not called automatically -- wire up if reconnect support
 * is needed later.
 */
export async function refetchDecision(runId: string): Promise<DecisionPayload | null> {
  try {
    return await getDecision(runId);
  } catch {
    return null;
  }
}