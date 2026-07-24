import { describe, expect, it } from "vitest";

async function loadGenerator() {
  try {
    const modulePath = new URL("../scripts/generate-api-types.mjs", import.meta.url).href;
    return await import(/* @vite-ignore */ modulePath);
  } catch (error) {
    throw new Error("CONTRACT_GENERATOR_MISSING", { cause: error });
  }
}

describe("generated API drift", () => {
  it("keeps generated api and fixture sources byte stable", async () => {
    const { generateContractSources, readCommittedContractSources } = await loadGenerator();
    await expect(generateContractSources()).resolves.toEqual(readCommittedContractSources());
  });
});
