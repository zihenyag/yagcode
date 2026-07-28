import { fileURLToPath } from "node:url";

const REQUIRED_TEXT = [
  "YagCode",
  "受约束、可回档、可审计的本地 Coding Agent",
  "YagCode Desktop for macOS",
  "YagCode Desktop for Windows",
  "YagCode CLI for macOS",
  "YagCode CLI for Windows",
  "GitHub",
];

const FORBIDDEN = [
  /Bilibili/i,
  /<iframe/i,
  /<script/i,
  /\bfetch\s*\(/i,
  /WebSocket/i,
  /EventSource/i,
  /localStorage/i,
  /sessionStorage/i,
  /document\.cookie/i,
  /type=["']file["']/i,
  /<form\b/i,
];

export async function evaluateDeployedPages({ url, fetchImpl = globalThis.fetch } = {}) {
  if (!url) throw new Error("DEPLOYED_PAGES_URL_REQUIRED");
  const parsed = new URL(url);
  if (parsed.protocol !== "https:") throw new Error("DEPLOYED_PAGES_URL_REQUIRES_HTTPS");
  const htmlResponse = await fetchImpl(parsed.href);
  if (!htmlResponse.ok) throw new Error(`DEPLOYED_PAGES_HTML_UNAVAILABLE:${htmlResponse.status}`);
  const html = await htmlResponse.text();
  for (const pattern of FORBIDDEN) {
    if (pattern.test(html)) throw new Error("DEPLOYED_PAGE_FORBIDDEN_RUNTIME_SURFACE");
  }
  const found = REQUIRED_TEXT.filter((text) => html.includes(text));
  if (found.length !== REQUIRED_TEXT.length) throw new Error("DEPLOYED_PAGE_REQUIRED_TEXT_MISSING");
  const assets = collectSameOriginAssets(html, parsed);
  for (const asset of assets) {
    const response = await fetchImpl(asset);
    if (!response.ok) throw new Error(`DEPLOYED_PAGE_ASSET_UNAVAILABLE:${asset}`);
  }
  return {
    checked_url: parsed.href,
    linked_assets_checked: assets.length,
    required_text_found: found.length,
  };
}

export async function runCli(argv = process.argv.slice(2)) {
  try {
    const result = await evaluateDeployedPages({ url: argv[0] });
    console.log(JSON.stringify(result));
    return 0;
  } catch (error) {
    console.error(error.message);
    return 1;
  }
}

function collectSameOriginAssets(html, baseUrl) {
  const assets = new Set();
  for (const match of html.matchAll(/<link\b[^>]*\brel=["']stylesheet["'][^>]*\bhref=["']([^"']+)["'][^>]*>/gi)) {
    addSameOriginAsset(assets, match[1], baseUrl);
  }
  for (const match of html.matchAll(/<img\b[^>]*\bsrc=["']([^"']+)["'][^>]*>/gi)) {
    addSameOriginAsset(assets, match[1], baseUrl);
  }
  return [...assets].sort();
}

function addSameOriginAsset(assets, value, baseUrl) {
  if (!value) return;
  const assetUrl = new URL(value, baseUrl);
  if (assetUrl.origin !== baseUrl.origin) return;
  assets.add(assetUrl.href);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exitCode = await runCli();
