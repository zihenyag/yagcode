import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { parse } from 'yaml';

import { cliBuildPlan } from '../../../scripts/build-cli.mjs';
import { desktopBuildPlan, rejectUpdaterMetadata, sanitizedEnv } from '../../../scripts/build-desktop.mjs';
import { sidecarBuildPlan } from '../../../scripts/build-sidecar.mjs';
import { createPlatformManifest, canonicalJson, verifyPlatformManifest, writeManifest } from '../../../scripts/hash-artifacts.mjs';
import { smokeInstalledApp } from '../../../scripts/smoke-installed-app.mjs';

test('builder plans keep CLI, sidecar, and desktop products separate', () => {
  const root = '/repo';
  const sidecar = sidecarBuildPlan({ root, platform: 'mac', arch: 'arm64' });
  const winSidecar = sidecarBuildPlan({ root, platform: 'win', arch: 'x64' });
  const cli = cliBuildPlan({ root, platform: 'mac', arch: 'arm64' });
  const winCli = cliBuildPlan({ root, platform: 'win', arch: 'x64' });
  const desktop = desktopBuildPlan({ root, platform: 'mac', arch: 'arm64' });

  assert.equal(sidecar.key, 'darwin-arm64');
  assert.equal(cli.target.asset, 'yagcode-cli-mac-arm64.tar.gz');
  assert.equal(desktop.target.asset, 'yagcode-mac-arm64.dmg');
  assert.ok(cli.commands.flatMap(step => step.argv).includes('/repo/src/yagcode/cli.py'));
  assert.ok(sidecar.commands.flatMap(step => step.argv).includes('/repo/src/yagcode/sidecar_cli.py'));
  assert.equal(desktop.commands[1].command, process.execPath);
  assert.ok(desktop.commands[1].argv.includes('/repo/node_modules/electron-builder/cli.js'));
  assert.ok(desktop.commands[1].argv.includes('--publish'));
  assert.ok(desktop.commands[1].argv.includes('never'));
  assert.equal(winSidecar.commands[0].command, '/repo/.venv/Scripts/pyinstaller.exe');
  assert.equal(winCli.commands[0].command, '/repo/.venv/Scripts/pyinstaller.exe');
});

test('desktop builder strips signing secrets and rejects updater metadata', () => {
  const env = sanitizedEnv({ CSC_LINK: 'secret', WIN_CSC_KEY_PASSWORD: 'secret', KEEP: '1' });
  assert.equal(env.CSC_LINK, undefined);
  assert.equal(env.WIN_CSC_KEY_PASSWORD, undefined);
  assert.equal(env.CSC_IDENTITY_AUTO_DISCOVERY, 'false');
  assert.equal(env.ELECTRON_CACHE, join(tmpdir(), 'yagcode-electron-cache'));
  assert.equal(env.ELECTRON_BUILDER_CACHE, join(tmpdir(), 'yagcode-electron-builder-cache'));
  assert.equal(env.KEEP, '1');

  const directory = join(tmpdir(), `yagcode-updater-${Date.now()}`);
  mkdirSync(directory, { recursive: true });
  writeFileSync(join(directory, 'latest.yml'), 'bad', 'utf8');
  assert.throws(() => rejectUpdaterMetadata(directory), /UPDATER_METADATA_FORBIDDEN/);
});

test('electron builder config disables dmg update metadata', () => {
  const config = parse(readFileSync('packaging/electron-builder.yml', 'utf8'));
  assert.equal(config.dmg.writeUpdateInfo, false);
  assert.equal(config.generateUpdatesFilesForAllChannels, false);
  assert.equal(config.win.signAndEditExecutable, false);
  assert.equal(config.nsis.differentialPackage, false);
});

test('installed smoke rejects missing roots before launch evidence', () => {
  assert.throws(() => smokeInstalledApp({ platform: 'linux-x64', root: '/definitely/missing/yagcode' }), /INSTALLED_APP_ROOT_REQUIRED/);
  assert.throws(() => smokeInstalledApp({ platform: 'darwin-arm64' }), /DARWIN_SMOKE_ARGS_REQUIRED/);
});

test('manifest creation hashes real asset bytes and detects tampering', () => {
  const root = join(tmpdir(), `yagcode-manifest-${Date.now()}`);
  mkdirSync(join(root, 'packaging'), { recursive: true });
  writeFileSync(join(root, 'packaging', 'shipped-runtime.json'), '{"ok":true}\n', 'utf8');
  writeFileSync(join(root, 'THIRD_PARTY_NOTICES.md'), 'notice\n', 'utf8');
  const asset = join(root, 'asset.tar.gz');
  writeFileSync(asset, 'asset-v1', 'utf8');
  const manifest = createPlatformManifest({
    product: 'cli',
    platform: 'darwin',
    arch: 'arm64',
    asset,
    root,
  });
  const manifestPath = join(root, 'manifest.json');
  writeManifest({ output: manifestPath, manifest });
  assert.deepEqual(verifyPlatformManifest({ manifest: manifestPath, asset, root }), manifest);
  writeFileSync(asset, 'asset-v2', 'utf8');
  assert.throws(() => verifyPlatformManifest({ manifest: manifestPath, asset, root }), /MANIFEST_ASSET_MISMATCH/);
  assert.ok(canonicalJson(manifest).endsWith('\n'));
});
