import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { parse } from 'yaml';

import { cliBuildPlan, copyCliGuide } from '../../../scripts/build-cli.mjs';
import { desktopBuildPlan, rejectUpdaterMetadata, sanitizedEnv } from '../../../scripts/build-desktop.mjs';
import { sidecarBuildPlan } from '../../../scripts/build-sidecar.mjs';
import { createPlatformManifest, canonicalJson, mergeReleaseManifests, sha256File, verifyPlatformManifest, writeManifest } from '../../../scripts/hash-artifacts.mjs';
import { smokeCli } from '../../../scripts/smoke-cli.mjs';
import { parseOptions, smokeDesktopTree, smokeInstalledApp } from '../../../scripts/smoke-installed-app.mjs';

test('builder plans keep CLI, sidecar, and desktop products separate', () => {
  const root = '/repo';
  const sidecar = sidecarBuildPlan({ root, platform: 'mac', arch: 'arm64' });
  const winSidecar = sidecarBuildPlan({ root, platform: 'win', arch: 'x64' });
  const cli = cliBuildPlan({ root, platform: 'mac', arch: 'arm64' });
  const winCli = cliBuildPlan({ root, platform: 'win', arch: 'x64' });
  const desktop = desktopBuildPlan({ root, platform: 'mac', arch: 'arm64' });
  const winDesktop = desktopBuildPlan({ root, platform: 'win', arch: 'x64' });

  assert.equal(sidecar.key, 'darwin-arm64');
  assert.equal(cli.target.asset, 'yagcode-cli-mac-arm64.tar.gz');
  assert.equal(desktop.target.asset, 'yagcode-mac-arm64.dmg');
  assert.equal(cli.guide.source, '/repo/packaging/cli/CLI使用指南.md');
  assert.equal(cli.guide.destination, '/repo/dist/cli/darwin-arm64/yagcode-cli/CLI使用指南.md');
  assert.ok(cli.commands.flatMap(step => step.argv).includes('/repo/src/yagcode/cli.py'));
  assert.ok(sidecar.commands.flatMap(step => step.argv).includes('/repo/src/yagcode/sidecar_cli.py'));
  const guideStep = cli.commands.findIndex(step => step.kind === 'copyGuide');
  const archiveStep = cli.commands.findIndex(step => step.command === 'tar');
  assert.ok(guideStep > 0);
  assert.ok(archiveStep > guideStep);
  assert.equal(desktop.commands[1].command, process.execPath);
  assert.ok(desktop.commands[1].argv.includes('/repo/node_modules/electron-builder/cli.js'));
  assert.ok(desktop.commands[1].argv.includes('--publish'));
  assert.ok(desktop.commands[1].argv.includes('never'));
  assert.equal(winSidecar.commands[0].command, '/repo/.venv/Scripts/pyinstaller.exe');
  assert.equal(winCli.commands[0].command, '/repo/.venv/Scripts/pyinstaller.exe');
  assert.deepEqual(winDesktop.commands[0], {
    command: 'cmd.exe',
    argv: ['/d', '/s', '/c', 'npm.cmd run build --workspace apps/desktop'],
  });
});

test('cli package copies the Chinese usage guide into the release directory', () => {
  const root = join(tmpdir(), `yagcode-cli-guide-${Date.now()}`);
  mkdirSync(join(root, 'packaging', 'cli'), { recursive: true });
  const source = join(root, 'packaging', 'cli', 'CLI使用指南.md');
  writeFileSync(
    source,
    '# YagCode CLI 使用指南\n\n/provider add openai --base-url https://llm.example.invalid --docs-url https://llm.example.invalid/docs\n/diff\n/rollback checkpoint-1\n',
    'utf8',
  );
  const plan = cliBuildPlan({ root, platform: 'mac', arch: 'arm64' });

  copyCliGuide(plan.guide);

  const copied = readFileSync(plan.guide.destination, 'utf8');
  assert.match(copied, /YagCode CLI 使用指南/);
  assert.match(copied, /\/provider add openai/);
  assert.match(copied, /--base-url/);
  assert.match(copied, /--docs-url/);
  assert.match(copied, /\/rollback checkpoint-1/);
});

test('cli smoke requires the packaged Chinese usage guide', () => {
  const root = join(tmpdir(), `yagcode-cli-smoke-${Date.now()}`);
  mkdirSync(root, { recursive: true });
  const executable = join(root, 'yagcode-cli');
  writeFileSync(executable, 'fake executable', 'utf8');
  writeFileSync(
    join(root, 'CLI使用指南.md'),
    '/provider add\n--base-url\n--docs-url\n/thread\n/run\n/changes\n/diff\n/accept\n/reject\n/rollback\n/memory\n/audit\n',
    'utf8',
  );

  const result = smokeCli({
    executable,
    spawn(command, argv) {
      assert.equal(command, executable);
      assert.deepEqual(argv, ['health']);
      return { status: 0, stdout: '{"state":"ready","product":"yagcode-cli"}' };
    },
  });

  assert.equal(result.state, 'passed');
  assert.equal(result.guide, join(root, 'CLI使用指南.md'));
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

test('installed smoke requires bundled sidecar and desktop launch evidence', () => {
  const root = join(tmpdir(), `yagcode-win-smoke-${Date.now()}`);
  mkdirSync(join(root, 'resources', 'sidecar', 'win32-x64', 'yagcode-sidecar'), { recursive: true });
  writeFileSync(join(root, 'yagcode.exe'), 'fake desktop', 'utf8');
  writeFileSync(join(root, 'resources', 'sidecar', 'win32-x64', 'yagcode-sidecar', 'yagcode-sidecar.exe'), 'fake sidecar', 'utf8');
  const calls = [];
  const result = smokeInstalledApp({
    platform: 'win32-x64',
    root,
    spawn(command, argv, options) {
      calls.push({ command, argv, options });
      if (argv[0] === 'health') {
        return { status: 0, stdout: '{"product":"yagcode-sidecar","state":"ready","version":"0.1.0"}' };
      }
      return { status: 0, stdout: '' };
    },
  });

  assert.equal(result.state, 'passed');
  assert.equal(result.sidecar_health.product, 'yagcode-sidecar');
  assert.equal(result.desktop_launch.state, 'passed');
  assert.equal(calls[0].argv[0], 'health');
  assert.deepEqual(calls[1].argv, []);
  assert.equal(calls[1].options.env.YAGCODE_DESKTOP_SMOKE, '1');
});

test('installed smoke rejects root-only packages without packaged sidecar', () => {
  const appRoot = join(tmpdir(), `yagcode-mac-smoke-missing-sidecar-${Date.now()}`, 'yagcode.app');
  mkdirSync(join(appRoot, 'Contents', 'MacOS'), { recursive: true });
  writeFileSync(join(appRoot, 'Contents', 'MacOS', 'yagcode'), 'fake desktop', 'utf8');

  assert.throws(() => smokeDesktopTree({ platform: 'darwin-arm64', appRoot }), /PACKAGED_SIDECAR_MISSING/);
});

test('installed desktop smoke reports packaged launch stderr', () => {
  const appRoot = join(tmpdir(), `yagcode-mac-smoke-launch-failure-${Date.now()}`, 'yagcode.app');
  mkdirSync(join(appRoot, 'Contents', 'MacOS'), { recursive: true });
  mkdirSync(join(appRoot, 'Contents', 'Resources', 'sidecar', 'darwin-arm64', 'yagcode-sidecar'), { recursive: true });
  writeFileSync(join(appRoot, 'Contents', 'MacOS', 'yagcode'), 'fake desktop', 'utf8');
  writeFileSync(join(appRoot, 'Contents', 'Resources', 'sidecar', 'darwin-arm64', 'yagcode-sidecar', 'yagcode-sidecar'), 'fake sidecar', 'utf8');

  assert.throws(
    () =>
      smokeDesktopTree({
        platform: 'darwin-arm64',
        appRoot,
        spawn(_command, argv) {
          if (argv[0] === 'health') {
            return { status: 0, stdout: '{"product":"yagcode-sidecar","state":"ready","version":"0.1.0"}' };
          }
          return { status: 1, stderr: 'PYTHON_VENV_MISSING' };
        },
      }),
    /PYTHON_VENV_MISSING/,
  );
});

test('installed smoke accepts keyed and npm-stripped windows arguments', () => {
  assert.deepEqual(parseOptions(['--platform', 'win32-x64', '--root', 'dist/installed/win32-x64/yagcode']), {
    platform: 'win32-x64',
    root: 'dist/installed/win32-x64/yagcode',
  });
  assert.deepEqual(parseOptions(['win32-x64', 'dist/installed/win32-x64/yagcode']), {
    platform: 'win32-x64',
    root: 'dist/installed/win32-x64/yagcode',
  });
  assert.deepEqual(parseOptions(['darwin-arm64', 'dist/manifests/darwin-arm64.json', 'dist/release/yagcode-mac-arm64.dmg']), {
    platform: 'darwin-arm64',
    manifest: 'dist/manifests/darwin-arm64.json',
    asset: 'dist/release/yagcode-mac-arm64.dmg',
  });
  assert.throws(() => parseOptions(['win32-x64']), /ARGS_INVALID/);
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

test('release manifest merge rehashes downloaded release assets', () => {
  const root = join(tmpdir(), `yagcode-release-manifest-${Date.now()}`);
  const assetDir = join(root, 'dist', 'release');
  const manifestDir = join(root, 'dist', 'manifests');
  mkdirSync(join(root, 'packaging'), { recursive: true });
  mkdirSync(assetDir, { recursive: true });
  writeFileSync(join(root, 'packaging', 'shipped-runtime.json'), '{"ok":true}\n', 'utf8');
  writeFileSync(join(root, 'THIRD_PARTY_NOTICES.md'), 'notice\n', 'utf8');
  const assets = [
    ['desktop', 'darwin', 'arm64', 'yagcode-mac-arm64.dmg', 'darwin-arm64.json'],
    ['desktop', 'win32', 'x64', 'yagcode-win-x64.exe', 'win32-x64.json'],
    ['cli', 'darwin', 'arm64', 'yagcode-cli-mac-arm64.tar.gz', 'cli-darwin-arm64.json'],
    ['cli', 'win32', 'x64', 'yagcode-cli-win-x64.zip', 'cli-win32-x64.json'],
  ];
  const manifests = [];
  for (const [product, platform, arch, filename, manifestName] of assets) {
    const asset = join(assetDir, filename);
    const manifest = join(manifestDir, manifestName);
    writeFileSync(asset, `${filename}:original`, 'utf8');
    writeManifest({ output: manifest, manifest: createPlatformManifest({ product, platform, arch, asset, root }) });
    manifests.push(manifest);
  }
  const windowsAsset = join(assetDir, 'yagcode-win-x64.exe');
  writeFileSync(windowsAsset, 'yagcode-win-x64.exe:downloaded', 'utf8');
  const output = join(root, 'dist', 'release', 'release-manifest.json');
  const merged = mergeReleaseManifests({ manifests, assetDir, output, root });
  const windows = merged.assets.find(asset => asset.filename === 'yagcode-win-x64.exe');
  assert.equal(windows.sha256, sha256File(windowsAsset));
  assert.notEqual(canonicalJson(merged), readFileSync(manifests[1], 'utf8'));
});
