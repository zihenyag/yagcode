import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { buildSidecar } from './build-sidecar.mjs';
import { assertVersionContract } from './check-version.mjs';
import { createPlatformManifest, writeManifest } from './hash-artifacts.mjs';

export function desktopTarget(platform, arch) {
  if (platform === 'mac' && arch === 'arm64') return { platformId: 'darwin', archId: 'arm64', key: 'darwin-arm64', asset: 'yagcode-mac-arm64.dmg', builder: ['--mac', 'dmg', '--arm64'] };
  if (platform === 'win' && arch === 'x64') return { platformId: 'win32', archId: 'x64', key: 'win32-x64', asset: 'yagcode-win-x64.exe', builder: ['--win', 'nsis', '--x64'] };
  throw new Error('DESKTOP_TARGET_UNSUPPORTED');
}

export function desktopBuildPlan({ root = process.cwd(), platform, arch }) {
  const target = desktopTarget(platform, arch);
  const electronDist = localElectronDist(root);
  return {
    target,
    asset: join(root, 'dist', 'release', target.asset),
    manifest: join(root, 'dist', 'manifests', `${target.key}.json`),
    commands: [
      npmStep(target.platformId, ['run', 'build', '--workspace', 'apps/desktop']),
      {
        command: process.execPath,
        argv: [
          join(root, 'node_modules', 'electron-builder', 'cli.js'),
          '--config',
          join(root, 'packaging', 'electron-builder.yml'),
          '--publish',
          'never',
          ...(electronDist === null ? [] : [`--config.electronDist=${electronDist}`]),
          ...target.builder,
        ],
      },
    ],
    env: {
      CSC_IDENTITY_AUTO_DISCOVERY: 'false',
      ELECTRON_CACHE: join(tmpdir(), 'yagcode-electron-cache'),
      ELECTRON_BUILDER_CACHE: join(tmpdir(), 'yagcode-electron-builder-cache'),
    },
  };
}

export function localElectronDist(root) {
  const electronDist = join(root, 'node_modules', 'electron', 'dist');
  return existsSync(electronDist) ? electronDist : null;
}

export function npmStep(platformId, argv) {
  if (platformId === 'win32') return { command: 'cmd.exe', argv: ['/d', '/s', '/c', `npm.cmd ${argv.join(' ')}`] };
  return { command: 'npm', argv };
}

export function buildDesktop({ root = process.cwd(), platform, arch, spawn = spawnSync } = {}) {
  assertVersionContract();
  buildSidecar({ root, platform, arch, spawn });
  const plan = desktopBuildPlan({ root, platform, arch });
  mkdirSync(join(root, 'dist', 'release'), { recursive: true });
  for (const step of plan.commands) {
    const result = spawn(step.command, step.argv, {
      cwd: root,
      env: sanitizedEnv(process.env, plan.env),
      stdio: 'inherit',
      shell: false,
    });
    if (result.error || result.signal || result.status !== 0) throw new Error('DESKTOP_BUILD_FAILED');
  }
  rejectUpdaterMetadata(join(root, 'dist', 'release'));
  const manifest = createPlatformManifest({
    product: 'desktop',
    platform: plan.target.platformId,
    arch: plan.target.archId,
    asset: plan.asset,
    root,
  });
  writeManifest({ output: plan.manifest, manifest });
  return plan;
}

export function sanitizedEnv(base, extra = {}) {
  const copy = { ...base, ...extra };
  for (const key of ['CSC_LINK', 'CSC_KEY_PASSWORD', 'CSC_NAME', 'WIN_CSC_LINK', 'WIN_CSC_KEY_PASSWORD']) {
    delete copy[key];
  }
  copy.CSC_IDENTITY_AUTO_DISCOVERY = 'false';
  copy.ELECTRON_CACHE = extra.ELECTRON_CACHE ?? join(tmpdir(), 'yagcode-electron-cache');
  copy.ELECTRON_BUILDER_CACHE = extra.ELECTRON_BUILDER_CACHE ?? join(tmpdir(), 'yagcode-electron-builder-cache');
  return copy;
}

export function rejectUpdaterMetadata(directory) {
  const forbidden = [/\.blockmap$/i, /^latest.*\.ya?ml$/i, /^app-update\.ya?ml$/i];
  for (const name of readdirSync(directory, { recursive: true })) {
    if (forbidden.some(pattern => pattern.test(String(name)))) {
      throw new Error('UPDATER_METADATA_FORBIDDEN');
    }
  }
}

export function runCli(argv = process.argv.slice(2)) {
  try {
    buildDesktop(parseArgs(argv));
    return 0;
  } catch (error) {
    console.error(error.message);
    return 1;
  }
}

function parseArgs(argv) {
  const result = { root: process.cwd() };
  for (let index = 0; index < argv.length; index += 2) {
    if (!argv[index]?.startsWith('--') || argv[index + 1] === undefined) throw new Error('ARGS_INVALID');
    result[argv[index].slice(2)] = argv[index + 1];
  }
  return result;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exitCode = runCli();
