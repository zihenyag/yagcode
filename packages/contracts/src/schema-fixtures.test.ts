import { describe, expect, it } from "vitest";

async function loadContractsProduction() {
  try {
    const validationPath = new URL("./validate.ts", import.meta.url).href;
    const fixturesPath = new URL("./generated/fixtures.ts", import.meta.url).href;
    const validation = await import(/* @vite-ignore */ validationPath);
    const fixtures = await import(/* @vite-ignore */ fixturesPath);
    return { ...validation, ...fixtures };
  } catch (error) {
    throw new Error("CONTRACTS_PRODUCTION_MISSING", { cause: error });
  }
}

describe("schema fixtures", () => {
  it("accepts the exported review and event fixtures", async () => {
    const { validateEventEnvelope, validateReviewView, eventFixture, reviewFixture } = await loadContractsProduction();
    expect(validateReviewView(reviewFixture)).toEqual({ ok: true });
    expect(validateEventEnvelope(eventFixture)).toEqual({ ok: true });
  });

  it("rejects missing required fields, unknown fields, invalid enum values, and camelCase aliases", async () => {
    const { validateEventEnvelope, validateReviewView, eventFixture, reviewFixture } = await loadContractsProduction();

    const reviewWithoutRequired = { ...reviewFixture };
    delete reviewWithoutRequired.review_id;
    expect(validateReviewView(reviewWithoutRequired).ok).toBe(false);
    expect(validateReviewView({ ...reviewFixture, extra: true }).ok).toBe(false);
    expect(validateReviewView({ ...reviewFixture, state: "DONE" }).ok).toBe(false);
    expect(validateReviewView({ ...reviewFixture, reviewId: reviewFixture.review_id }).ok).toBe(false);

    const eventWithoutRequired = { ...eventFixture };
    delete eventWithoutRequired.sequence;
    expect(validateEventEnvelope(eventWithoutRequired).ok).toBe(false);
    expect(validateEventEnvelope({ ...eventFixture, extra: true }).ok).toBe(false);
    expect(validateEventEnvelope({ ...eventFixture, event_type: "run.done" }).ok).toBe(false);
    expect(validateEventEnvelope({ ...eventFixture, profileId: eventFixture.profile_id }).ok).toBe(false);
  });
});
