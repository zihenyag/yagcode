import assert from "node:assert/strict";
import test from "node:test";

test("test_owned_deployed_pages_oracle_rejects_runtime_surfaces", async () => {
  const html = "<!doctype html><title>YagCode</title><iframe src=\"x\"></iframe>";
  await assert.rejects(
    () => testOwnedOracle({ html, assets: new Map() }),
    /DEPLOYED_PAGE_FORBIDDEN_RUNTIME_SURFACE/
  );
});

test("deployed pages checker verifies html and linked same-origin assets", async () => {
  const { evaluateDeployedPages } = await import("../../scripts/check-deployed-pages.mjs");
  const baseUrl = "https://example.test/yagcode/";
  const html = [
    "<!doctype html>",
    "<title>YagCode</title>",
    "<meta http-equiv=\"Content-Security-Policy\" content=\"connect-src 'none'; frame-src 'none'\">",
    "<h1>YagCode</h1>",
    "<p>受约束、可回档、可审计的本地 Coding Agent</p>",
    "<p>机制演示 npm run demo</p>",
    "<link rel=\"stylesheet\" href=\"docs/landing/landing.css\">",
    "<img src=\"docs/landing/assets/screenshots/setup-agent.png\" alt=\"setup agent screenshot\">",
  ].join("");
  const responses = new Map([
    [baseUrl, { status: 200, body: html, contentType: "text/html" }],
    [`${baseUrl}docs/landing/landing.css`, { status: 200, body: "body{}", contentType: "text/css" }],
    [`${baseUrl}docs/landing/assets/screenshots/setup-agent.png`, { status: 200, body: "png", contentType: "image/png" }],
  ]);
  const result = await evaluateDeployedPages({
    url: baseUrl,
    fetchImpl: async (url) => {
      const response = responses.get(String(url));
      if (!response) return fakeResponse({ status: 404, body: "", contentType: "text/plain" });
      return fakeResponse(response);
    },
  });
  assert.deepEqual(result, {
    checked_url: baseUrl,
    linked_assets_checked: 2,
    required_text_found: 3,
  });
});

test("deployed pages checker rejects missing assets and non-https urls", async () => {
  const { evaluateDeployedPages } = await import("../../scripts/check-deployed-pages.mjs");
  await assert.rejects(
    () => evaluateDeployedPages({ url: "http://example.test/yagcode/" }),
    /DEPLOYED_PAGES_URL_REQUIRES_HTTPS/
  );
  await assert.rejects(
    () =>
      evaluateDeployedPages({
        url: "https://example.test/yagcode/",
        fetchImpl: async () => fakeResponse({ status: 404, body: "", contentType: "text/plain" }),
      }),
    /DEPLOYED_PAGES_HTML_UNAVAILABLE/
  );
});

async function testOwnedOracle({ html }) {
  if (/<iframe/i.test(html) || /bilibili/i.test(html)) {
    throw new Error("DEPLOYED_PAGE_FORBIDDEN_RUNTIME_SURFACE");
  }
  return true;
}

function fakeResponse({ status, body, contentType }) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: {
      get(name) {
        return name.toLowerCase() === "content-type" ? contentType : null;
      },
    },
    async text() {
      return body;
    },
  };
}
