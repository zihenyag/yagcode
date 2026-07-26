import { describe, expect, it } from "vitest";
import { startFixtureSidecar } from "./fixtures.js";

function fixtureTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("TEST_OWNED_TIMEOUT")), timeoutMs);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}

describe("electron e2e fixture harness", () => {
  it("test_owned_fixture_sidecar_requires_token_and_origin", async () => {
    const sidecar = await startFixtureSidecar({ token: "fixture-token", origin: "app://yagcode" });
    try {
      const ok = await fetch(`${sidecar.baseUrl}/api/v1/health`, {
        headers: { Authorization: "Bearer fixture-token", Origin: "app://yagcode" }
      });
      const wrongToken = await fetch(`${sidecar.baseUrl}/api/v1/health`, {
        headers: { Authorization: "Bearer wrong", Origin: "app://yagcode" }
      });
      const wrongOrigin = await fetch(`${sidecar.baseUrl}/api/v1/health`, {
        headers: { Authorization: "Bearer fixture-token", Origin: "https://evil.invalid" }
      });
      expect(ok.status).toBe(200);
      expect(wrongToken.status).toBe(401);
      expect(wrongOrigin.status).toBe(401);
    } finally {
      await sidecar.close();
    }
  });

  it("test_owned_fixture_sidecar_consumes_intents_once", async () => {
    const sidecar = await startFixtureSidecar();
    try {
      const headers = { Authorization: `Bearer ${sidecar.token}`, Origin: sidecar.origin };
      const challenge = (await (
        await fetch(`${sidecar.baseUrl}/api/v1/review/review-1/accept-intent`, { headers, method: "POST" })
      ).json()) as { intent_id: string; one_time_token: string };
      const consumed = await fetch(`${sidecar.baseUrl}/api/v1/intents/${challenge.intent_id}/consume`, {
        body: JSON.stringify({ one_time_token: challenge.one_time_token }),
        headers: { ...headers, "content-type": "application/json", "X-Yagcode-Principal": "main" },
        method: "POST"
      });
      const replay = await fetch(`${sidecar.baseUrl}/api/v1/intents/${challenge.intent_id}/consume`, {
        body: JSON.stringify({ one_time_token: challenge.one_time_token }),
        headers: { ...headers, "content-type": "application/json", "X-Yagcode-Principal": "main" },
        method: "POST"
      });
      expect(consumed.status).toBe(200);
      expect(replay.status).toBe(403);
      expect(sidecar.consumedIntents()).toEqual([challenge.intent_id]);
    } finally {
      await sidecar.close();
    }
  });

  it("test_owned_fixture_timeout_fails_instead_of_hanging", async () => {
    await expect(fixtureTimeout(new Promise(() => {}), 10)).rejects.toThrow("TEST_OWNED_TIMEOUT");
  });

});
