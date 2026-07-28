import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { assertVersionContract } from './check-version.mjs';

const PRODUCTS = new Set(['desktop', 'cli']);
const PLATFORMS = new Set(['darwin', 'win32']);
const ARCHES = new Set(['arm64', 'x64']);

export function canonicalJson(value) {
  return `${JSON.stringify(sortKeys(value), null, 2)}\n`;
}

export function sha256File(path, { readFile = readFileSync } = {}) {
  return createHash('sha256').update(readFile(path)).digest('hex');
}

export function runtimeHashes({ root = process.cwd(), readFile = readFileSync } = {}) {
  return {
    runtime_inventory_sha256: createHash('sha256').update(readFile(`${root}/packaging/shipped-runtime.json`)).digest('hex'),
    notices_sha256: createHash('sha256').update(readFile(`${root}/THIRD_PARTY_NOTICES.md`)).digest('hex'),
  };
}

export function createPlatformManifest({
  product,
  platform,
  arch,
  asset,
  root = process.cwd(),
  readFile = readFileSync,
  stat = statSync,
} = {}) {
  validateIdentity({ product, platform, arch });
  const info = stat(asset);
  if (!info.isFile() || info.size <= 0) throw new Error('ASSET_INVALID');
  const hashes = runtimeHashes({ root, readFile });
  return {
    schema_version: 1,
    app_version: assertVersionContract(),
    assets: [
      {
        product,
        platform,
        arch,
        filename: basename(asset),
        sha256: sha256File(asset, { readFile }),
        size_bytes: info.size,
        required: true,
        ...hashes,
      },
    ],
  };
}

export function verifyPlatformManifest({ manifest, asset, root = process.cwd() } = {}) {
  const data = JSON.parse(readFileSync(manifest, 'utf8'));
  if (data.schema_version !== 1 || !Array.isArray(data.assets) || data.assets.length !== 1) {
    throw new Error('MANIFEST_SCHEMA_INVALID');
  }
  const actual = createPlatformManifest({
    product: data.assets[0].product,
    platform: data.assets[0].platform,
    arch: data.assets[0].arch,
    asset,
    root,
  });
  if (canonicalJson(actual) !== canonicalJson(data)) throw new Error('MANIFEST_ASSET_MISMATCH');
  return actual;
}

export function writeManifest({ output, manifest }) {
  mkdirSync(dirname(output), { recursive: true });
  writeFileSync(output, canonicalJson(manifest), { encoding: 'utf8', flag: 'w' });
}

export function mergeReleaseManifests({ manifests, assetDir, output }) {
  const seen = new Set();
  const assets = [];
  let appVersion = null;
  for (const manifestPath of manifests) {
    const data = JSON.parse(readFileSync(manifestPath, 'utf8'));
    if (data.schema_version !== 1 || !Array.isArray(data.assets) || data.assets.length !== 1) {
      throw new Error('MANIFEST_SCHEMA_INVALID');
    }
    appVersion = appVersion ?? data.app_version;
    if (data.app_version !== appVersion) throw new Error('MANIFEST_VERSION_MISMATCH');
    const asset = data.assets[0];
    const key = `${asset.product}:${asset.platform}:${asset.arch}`;
    if (seen.has(key)) throw new Error('MANIFEST_DUPLICATE_ASSET');
    seen.add(key);
    verifyPlatformManifest({ manifest: manifestPath, asset: join(assetDir, asset.filename) });
    assets.push(asset);
  }
  const required = new Set(['desktop:darwin:arm64', 'desktop:win32:x64', 'cli:darwin:arm64', 'cli:win32:x64']);
  if (seen.size !== required.size || [...required].some(key => !seen.has(key))) {
    throw new Error('MANIFEST_REQUIRED_ASSETS_MISSING');
  }
  const merged = { schema_version: 1, app_version: appVersion, assets };
  writeManifest({ output, manifest: merged });
  return merged;
}

export function runCli(argv = process.argv.slice(2)) {
  try {
    const command = argv[0];
    const options = parseOptions(argv.slice(1));
    if (command === 'platform') {
      writeManifest({
        output: options.output,
        manifest: createPlatformManifest({
          product: options.product,
          platform: options.platform,
          arch: options.arch,
          asset: options.asset,
        }),
      });
      return 0;
    }
    if (command === 'verify-platform') {
      verifyPlatformManifest({ manifest: options.manifest, asset: options.asset });
      return 0;
    }
    if (command === 'merge') {
      mergeReleaseManifests({
        manifests: arrayOption(argv.slice(1), '--manifest'),
        assetDir: options['asset-dir'],
        output: options.output,
      });
      return 0;
    }
    throw new Error('MANIFEST_COMMAND_INVALID');
  } catch (error) {
    console.error(error.message);
    return 1;
  }
}

function validateIdentity({ product, platform, arch }) {
  if (!PRODUCTS.has(product) || !PLATFORMS.has(platform) || !ARCHES.has(arch)) {
    throw new Error('ASSET_IDENTITY_INVALID');
  }
}

function parseOptions(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    if (!argv[index]?.startsWith('--') || argv[index + 1] === undefined) throw new Error('ARGS_INVALID');
    result[argv[index].slice(2)] = argv[index + 1];
  }
  return result;
}

function arrayOption(argv, name) {
  const values = [];
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === name) values.push(argv[index + 1]);
  }
  return values;
}

function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, nested]) => [key, sortKeys(nested)]));
  }
  return value;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exitCode = runCli();
