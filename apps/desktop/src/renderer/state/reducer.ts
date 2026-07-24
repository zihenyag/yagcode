import type { EventEnvelope } from "@yagcode/contracts";
import { toEventEnvelope } from "../api/events.js";

export type ConnectionState = "connected" | "disconnected" | "resync-required";
export type RunState =
  | "IDLE"
  | "RUNNING"
  | "COMPACTING"
  | "WAITING_PERMISSION"
  | "WAITING_PRIVACY"
  | "STOPPING"
  | "INTERRUPTED"
  | "FINISHED"
  | "FAILED";

export interface WorkbenchState {
  generation: number;
  lastSequence: number;
  runState: RunState;
  connection: ConnectionState;
  rejectedEvents: readonly { sequence: number; reason: string }[];
}

const modelLockedStates = new Set<RunState>(["RUNNING", "COMPACTING", "WAITING_PERMISSION", "WAITING_PRIVACY", "STOPPING", "INTERRUPTED"]);

const allowedRunTransitions: Record<RunState, readonly RunState[]> = {
  IDLE: ["RUNNING", "IDLE"],
  RUNNING: ["COMPACTING", "WAITING_PERMISSION", "WAITING_PRIVACY", "STOPPING", "INTERRUPTED", "FINISHED", "FAILED", "RUNNING"],
  COMPACTING: ["RUNNING", "STOPPING", "INTERRUPTED", "FINISHED", "FAILED", "COMPACTING"],
  WAITING_PERMISSION: ["RUNNING", "STOPPING", "INTERRUPTED", "FINISHED", "FAILED", "WAITING_PERMISSION"],
  WAITING_PRIVACY: ["RUNNING", "STOPPING", "INTERRUPTED", "FINISHED", "FAILED", "WAITING_PRIVACY"],
  STOPPING: ["INTERRUPTED", "FINISHED", "FAILED", "STOPPING"],
  INTERRUPTED: ["RUNNING", "STOPPING", "FINISHED", "FAILED", "INTERRUPTED"],
  FINISHED: ["FINISHED"],
  FAILED: ["FAILED"],
};

export function createInitialWorkbenchState(args: { generation?: number; lastSequence?: number; runState?: string } = {}): WorkbenchState {
  return {
    generation: args.generation ?? 0,
    lastSequence: args.lastSequence ?? 0,
    runState: normalizeRunState(args.runState ?? "IDLE"),
    connection: "connected",
    rejectedEvents: [],
  };
}

export function isModelLocked(runState: string): boolean {
  return modelLockedStates.has(normalizeRunState(runState));
}

function normalizeRunState(value: string): RunState {
  if (
    value === "IDLE" ||
    value === "RUNNING" ||
    value === "COMPACTING" ||
    value === "WAITING_PERMISSION" ||
    value === "WAITING_PRIVACY" ||
    value === "STOPPING" ||
    value === "INTERRUPTED" ||
    value === "FINISHED" ||
    value === "FAILED"
  ) {
    return value;
  }
  return "FAILED";
}

function canTransition(from: RunState, to: RunState): boolean {
  return allowedRunTransitions[from].includes(to);
}

function applyValidatedEvent(state: WorkbenchState, event: EventEnvelope): WorkbenchState {
  if (event.event_type !== "run.state") return state;
  if (!("state" in event.payload)) return state;
  const nextRunState = normalizeRunState(event.payload.state);
  if (!canTransition(state.runState, nextRunState)) {
    return {
      ...state,
      lastSequence: event.sequence,
      rejectedEvents: [...state.rejectedEvents, { sequence: event.sequence, reason: "INVALID_RUN_TRANSITION" }],
    };
  }
  return {
    ...state,
    generation: event.generation ?? state.generation,
    lastSequence: event.sequence,
    runState: nextRunState,
    connection: "connected",
  };
}

export function reduceEvent(state: WorkbenchState, event: unknown): WorkbenchState {
  const envelope = toEventEnvelope(event);
  if (envelope.sequence !== state.lastSequence + 1) return { ...state, connection: "resync-required" };
  if (envelope.generation !== undefined && envelope.generation !== null && envelope.generation < state.generation) return state;
  return applyValidatedEvent(state, envelope);
}
