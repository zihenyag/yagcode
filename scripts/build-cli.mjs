import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { assertVersionContract } from './check-version.mjs';
import { pyinstallerDataArg, sidecarDataFiles } from './build-sidecar.mjs';
import { createPlatformManifest, writeManifest } from './hash-artifacts.mjs';

export function cliTarget(platform, arch) {
  if (platform === 'mac' && arch === 'arm64') return { platformId: 'darwin', archId: 'arm64', key: 'darwin-arm64', asset: 'yagcode-cli-mac-arm64.tar.gz' };
  if (platform === 'win' && arch === 'x64') return { platformId: 'win32', archId: 'x64', key: 'win32-x64', asset: 'yagcode-cli-win-x64.zip' };
  throw new Error('CLI_TARGET_UNSUPPORTED');
}

export function cliExecutable(root, key) {
  const name = key.startsWith('win32') ? 'yagcode-cli.exe' : 'yagcode-cli';
  return join(root, 'dist', 'cli', key, 'yagcode-cli', name);
}

export function cliGuidePaths(root, key) {
  return {
    source: join(root, 'packaging', 'cli', 'CLI使用指南.md'),
    destination: join(root, 'dist', 'cli', key, 'yagcode-cli', 'CLI使用指南.md'),
  };
}

export function cliBuildPlan({ root = process.cwd(), platform, arch }) {
  const target = cliTarget(platform, arch);
  const dataArgs = sidecarDataFiles(root, target.key).flatMap(({ source, destination }) => [
    '--add-data',
    pyinstallerDataArg(source, destination, target.key),
  ]);
  const dist = join(root, 'dist', 'cli', target.key);
  const asset = join(root, 'dist', 'release', target.asset);
  const guide = cliGuidePaths(root, target.key);
  const archiveCommand = target.platformId === 'darwin'
    ? { command: 'tar', argv: ['-czf', asset, '-C', dist, 'yagcode-cli'] }
    : { command: 'powershell.exe', argv: ['-NoProfile', '-Command', `Compress-Archive -Path "${dist}\\yagcode-cli" -DestinationPath "${asset}" -Force`] };
  return {
    target,
    asset,
    guide,
    manifest: join(root, 'dist', 'manifests', `cli-${target.key}.json`),
    commands: [
      {
        kind: 'spawn',
        command: pyinstallerExecutable(root, target.key),
        argv: [
          '--noconfirm',
          '--clean',
          '--name',
          'yagcode-cli',
          '--distpath',
          dist,
          '--workpath',
          join(root, 'build', `pyinstaller-cli-${target.key}`),
          '--specpath',
          join(root, 'build', 'pyinstaller-specs'),
          ...dataArgs,
          '--paths',
          join(root, 'src'),
          join(root, 'src', 'yagcode', 'cli.py'),
        ],
      },
      { kind: 'copyGuide', ...guide, argv: [] },
      { kind: 'spawn', command: cliExecutable(root, target.key), argv: ['health'] },
      { kind: 'spawn', ...archiveCommand },
    ],
  };
}

export function pyinstallerExecutable(root, key) {
  return key.startsWith('win32')
    ? join(root, '.venv', 'Scripts', 'pyinstaller.exe')
    : join(root, '.venv', 'bin', 'pyinstaller');
}

export function buildCli({ root = process.cwd(), platform, arch, spawn = spawnSync } = {}) {
  assertVersionContract();
  const plan = cliBuildPlan({ root, platform, arch });
  mkdirSync(join(root, 'dist', 'release'), { recursive: true });
  for (const step of plan.commands) {
    if (step.kind === 'copyGuide') {
      copyCliGuide(step);
      continue;
    }
    const result = spawn(step.command, step.argv, {
      cwd: root,
      env: { ...process.env, PYINSTALLER_CONFIG_DIR: join(tmpdir(), 'yagcode-pyinstaller-cache') },
      stdio: 'inherit',
      shell: false,
    });
    if (result.error || result.signal || result.status !== 0) throw new Error('CLI_BUILD_FAILED');
  }
  const manifest = createPlatformManifest({
    product: 'cli',
    platform: plan.target.platformId,
    arch: plan.target.archId,
    asset: plan.asset,
    root,
  });
  writeManifest({ output: plan.manifest, manifest });
  return plan;
}

export function copyCliGuide({ source, destination }) {
  if (!existsSync(source)) throw new Error('CLI_GUIDE_MISSING');
  mkdirSync(dirname(destination), { recursive: true });
  copyFileSync(source, destination);
}

export function runCli(argv = process.argv.slice(2)) {
  try {
    buildCli(parseArgs(argv));
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
