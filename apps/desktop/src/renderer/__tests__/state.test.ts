import { describe, expect, it } from "vitest";
import { eventFixture } from "@yagcode/contracts/fixtures";

interface LoadedStateModule {
  createInitialWorkbenchState(args?: { generation?: number; lastSequence?: number; runState?: string }): {
    generation: number;
    lastSequence: number;
    runState: string;
    connection: string;
    rejectedEvents: readonly { reason: string }[];
  };
  isModelLocked(runState: string): boolean;
  reduceEvent(state: ReturnType<LoadedStateModule["createInitialWorkbenchState"]>, event: unknown): ReturnType<LoadedStateModule["createInitialWorkbenchState"]>;
}

async function loadStateProduction(): Promise<LoadedStateModule> {
  const modulePath = "../state/reducer";
  try {
    return (await import(modulePath)) as LoadedStateModule;
  } catch (error) {
    throw new Error(`RENDERER_PRODUCTION_MISSING:${modulePath}`, { cause: error });
  }
}

function testOwnedReduceOracle(state: { lastSequence: number; generation: number; runState: string }, event: typeof eventFixture) {
  if (event.sequence !== state.lastSequence + 1) return { ...state, connection: "resync-required" };
  if (event.generation !== null && event.generation < state.generation) return state;
  if (state.runState === "STOPPING" && event.payload.state === "RUNNING") {
    return { ...state, lastSequence: event.sequence, rejected: "INVALID_RUN_TRANSITION" };
  }
  return { ...state, lastSequence: event.sequence, runState: event.payload.state };
}

describe("state test-owned oracle", () => {
  it("test_owned_state_oracle_rejects_sequence_gap_stale_generation_and_impossible_transition", () => {
    expect(testOwnedReduceOracle({ lastSequence: 0, generation: 1, runState: "IDLE" }, eventFixture)).toMatchObject({
      lastSequence: 1,
      runState: "RUNNING",
    });
    expect(testOwnedReduceOracle({ lastSequence: 4, generation: 1, runState: "IDLE" }, eventFixture)).toMatchObject({
      connection: "resync-required",
    });
    expect(testOwnedReduceOracle({ lastSequence: 0, generation: 3, runState: "IDLE" }, eventFixture)).toMatchObject({
      generation: 3,
      runState: "IDLE",
    });
    expect(
      testOwnedReduceOracle(
        { lastSequence: 0, generation: 1, runState: "STOPPING" },
        { ...eventFixture, payload: { run_id: "run-1", state: "RUNNING" } },
      ),
    ).toMatchObject({ rejected: "INVALID_RUN_TRANSITION" });
  });
});

describe("workbench reducer", () => {
  it("applies only the next SSE event sequence", async () => {
    const { createInitialWorkbenchState, reduceEvent } = await loadStateProduction();
    const initial = createInitialWorkbenchState();
    const next = reduceEvent(initial, eventFixture);
    expect(next).toMatchObject({ lastSequence: 1, generation: 1, runState: "RUNNING", connection: "connected" });

    const gap = reduceEvent(next, { ...eventFixture, sequence: 3, payload: { run_id: "run-1", state: "FINISHED" } });
    expect(gap).toMatchObject({ lastSequence: 1, runState: "RUNNING", connection: "resync-required" });
  });

  it("ignores older generation events without mutating current UI state", async () => {
    const { createInitialWorkbenchState, reduceEvent } = await loadStateProduction();
    const current = createInitialWorkbenchState({ generation: 3, lastSequence: 1, runState: "RUNNING" });
    const stale = reduceEvent(current, { ...eventFixture, sequence: 2, generation: 2, payload: { run_id: "run-1", state: "FINISHED" } });
    expect(stale).toBe(current);
  });

  it("rejects impossible run-state transitions with a stable reason", async () => {
    const { createInitialWorkbenchState, reduceEvent } = await loadStateProduction();
    const current = createInitialWorkbenchState({ generation: 2, lastSequence: 1, runState: "STOPPING" });
    const rejected = reduceEvent(current, { ...eventFixture, sequence: 2, generation: 2, payload: { run_id: "run-1", state: "RUNNING" } });
    expect(rejected.runState).toBe("STOPPING");
    expect(rejected.lastSequence).toBe(2);
    expect(rejected.rejectedEvents).toEqual([{ sequence: 2, reason: "INVALID_RUN_TRANSITION" }]);
  });

  it("locks model switching for every active execution state", async () => {
    const { isModelLocked } = await loadStateProduction();
    for (const state of ["RUNNING", "COMPACTING", "WAITING_PERMISSION", "WAITING_PRIVACY", "STOPPING", "INTERRUPTED"]) {
      expect(isModelLocked(state)).toBe(true);
    }
    for (const state of ["IDLE", "FINISHED", "FAILED"]) {
      expect(isModelLocked(state)).toBe(false);
    }
  });
});
