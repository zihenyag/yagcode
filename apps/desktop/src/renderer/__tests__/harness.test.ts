import { describe, expect, it, vi } from "vitest";
import { eventFixture, reviewFixture } from "@yagcode/contracts/fixtures";

interface LoadedClientModule {
  createSidecarClient(options: {
    baseUrl: string;
    token: string;
    fetchImpl: typeof fetch;
    sseTransport?: {
      connect(args: {
        url: string;
        headers: Record<string, string>;
        onMessage(raw: string): void;
        onDisconnect(reason: string): void;
      }): { close(): void };
    };
  }): {
    getReview(reviewId: string): Promise<unknown>;
    subscribe(args: {
      profileId: string;
      lastSequence: number;
      onEvent(event: unknown): void;
      onDisconnect(reason: string): void;
    }): { close(): void };
    command(command: { type: string }): Promise<{ ok: boolean; reason?: string }>;
  };
}

async function loadClientProduction(): Promise<LoadedClientModule> {
  const modulePath = "../api/client";
  try {
    return (await import(modulePath)) as LoadedClientModule;
  } catch (error) {
    throw new Error(`RENDERER_PRODUCTION_MISSING:${modulePath}`, { cause: error });
  }
}

function testOwnedFixtureClient(snapshot: unknown) {
  const commands: unknown[] = [];
  let closed = false;
  return {
    commands,
    async getSnapshot() {
      return snapshot;
    },
    subscribe({ onEvent }: { onEvent(event: unknown): void }) {
      onEvent(eventFixture);
      return {
        close() {
          closed = true;
        },
      };
    },
    async command(command: unknown) {
      commands.push(command);
      return { ok: true };
    },
    isClosed() {
      return closed;
    },
  };
}

function testOwnedSequenceOracle(current: { lastSequence: number; generation: number }, event: typeof eventFixture) {
  if (event.sequence !== current.lastSequence + 1) return "gap";
  if (event.generation !== null && event.generation < current.generation) return "stale-generation";
  return "accepted";
}

describe("renderer test-owned harness", () => {
  it("test_owned_fixture_client_records_commands_and_closes_subscription", async () => {
    const client = testOwnedFixtureClient({ ready: true });
    const events: unknown[] = [];
    const subscription = client.subscribe({ onEvent: (event) => events.push(event) });
    await client.command({ type: "stop" });
    subscription.close();
    expect(await client.getSnapshot()).toEqual({ ready: true });
    expect(events).toEqual([eventFixture]);
    expect(client.commands).toEqual([{ type: "stop" }]);
    expect(client.isClosed()).toBe(true);
  });

  it("test_owned_sse_sequence_oracle_rejects_gaps_and_stale_generations", () => {
    expect(testOwnedSequenceOracle({ lastSequence: 0, generation: 1 }, eventFixture)).toBe("accepted");
    expect(testOwnedSequenceOracle({ lastSequence: 3, generation: 1 }, eventFixture)).toBe("gap");
    expect(testOwnedSequenceOracle({ lastSequence: 0, generation: 2 }, eventFixture)).toBe("stale-generation");
  });
});

describe("sidecar client runtime boundary", () => {
  it("sends startup token in Authorization headers, never query strings", async () => {
    const { createSidecarClient } = await loadClientProduction();
    const requests: Array<{ url: string; authorization: string | null }> = [];
    const fetchImpl = vi.fn<typeof fetch>(async (input, init) => {
      const request = new Request(input, init);
      requests.push({ url: request.url, authorization: request.headers.get("authorization") });
      return new Response(JSON.stringify(reviewFixture), {
        headers: { "content-type": "application/json" },
        status: 200,
      });
    });
    let sseRequest: { url: string; headers: Record<string, string> } | undefined;
    const client = createSidecarClient({
      baseUrl: "http://127.0.0.1:49152",
      token: "startup-secret-token",
      fetchImpl,
      sseTransport: {
        connect(args) {
          sseRequest = { url: args.url, headers: args.headers };
          return { close() {} };
        },
      },
    });

    await client.getReview("review-1");
    client.subscribe({ profileId: "profile-1", lastSequence: 41, onEvent() {}, onDisconnect() {} });

    expect(requests).toEqual([
      { url: "http://127.0.0.1:49152/api/reviews/review-1", authorization: "Bearer startup-secret-token" },
    ]);
    expect(requests[0]?.url).not.toContain("startup-secret-token");
    expect(sseRequest?.url).toBe("http://127.0.0.1:49152/api/events?profile_id=profile-1&last_sequence=41");
    expect(sseRequest?.url).not.toContain("startup-secret-token");
    expect(sseRequest?.headers.Authorization).toBe("Bearer startup-secret-token");
  });

  it("marks the client disconnected after invalid SSE and blocks mutations until resync", async () => {
    const { createSidecarClient } = await loadClientProduction();
    let onMessage: ((raw: string) => void) | undefined;
    const fetchImpl = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));
    const disconnects: string[] = [];
    const client = createSidecarClient({
      baseUrl: "http://127.0.0.1:49152",
      token: "startup-secret-token",
      fetchImpl,
      sseTransport: {
        connect(args) {
          onMessage = args.onMessage;
          return { close() {} };
        },
      },
    });

    client.subscribe({
      profileId: "profile-1",
      lastSequence: 0,
      onEvent() {},
      onDisconnect(reason) {
        disconnects.push(reason);
      },
    });
    onMessage?.("{\"not\":\"an event\"}");

    await expect(client.command({ type: "accept_change" })).resolves.toEqual({
      ok: false,
      reason: "SIDECAR_DISCONNECTED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(disconnects).toEqual(["SCHEMA_VALIDATION_FAILED"]);
  });
});
