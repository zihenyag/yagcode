import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { assertVersionContract } from './check-version.mjs';

export function targetKey(platform, arch) {
  if (platform === 'mac' && arch === 'arm64') return 'darwin-arm64';
  if (platform === 'win' && arch === 'x64') return 'win32-x64';
  throw new Error('SIDECAR_TARGET_UNSUPPORTED');
}

export function sidecarExecutable(root, key) {
  const name = key.startsWith('win32') ? 'yagcode-sidecar.exe' : 'yagcode-sidecar';
  return join(root, 'dist', 'sidecar', key, 'yagcode-sidecar', name);
}

export function sidecarBuildPlan({ root = process.cwd(), platform, arch }) {
  const key = targetKey(platform, arch);
  const dataArgs = sidecarDataFiles(root, key).flatMap(({ source, destination }) => [
    '--add-data',
    pyinstallerDataArg(source, destination, key),
  ]);
  return {
    key,
    commands: [
      {
        command: pyinstallerExecutable(root, key),
        argv: [
          '--noconfirm',
          '--clean',
          '--name',
          'yagcode-sidecar',
          '--distpath',
          join(root, 'dist', 'sidecar', key),
          '--workpath',
          join(root, 'build', `pyinstaller-sidecar-${key}`),
          '--specpath',
          join(root, 'build', 'pyinstaller-specs'),
          ...dataArgs,
          '--paths',
          join(root, 'src'),
          join(root, 'src', 'yagcode', 'sidecar_cli.py'),
        ],
      },
      { command: sidecarExecutable(root, key), argv: ['health'] },
    ],
  };
}

export function sidecarDataFiles(root, key) {
  return [
    {
      source: join(root, 'src', 'yagcode', 'providers', 'official_endpoints.json'),
      destination: 'yagcode/providers',
    },
    {
      source: join(root, 'src', 'yagcode', 'onboarding', 'trusted_git_manifest.json'),
      destination: 'yagcode/onboarding',
    },
  ].map(item => ({ ...item, argument: pyinstallerDataArg(item.source, item.destination, key) }));
}

export function pyinstallerDataArg(source, destination, key) {
  return `${source}${key.startsWith('win32') ? ';' : ':'}${destination}`;
}

export function pyinstallerExecutable(root, key) {
  return key.startsWith('win32')
    ? join(root, '.venv', 'Scripts', 'pyinstaller.exe')
    : join(root, '.venv', 'bin', 'pyinstaller');
}

export function buildSidecar({ root = process.cwd(), platform, arch, spawn = spawnSync } = {}) {
  assertVersionContract();
  const plan = sidecarBuildPlan({ root, platform, arch });
  if (!existsSync(plan.commands[0].command)) throw new Error('PYINSTALLER_MISSING');
  for (const step of plan.commands) {
    const result = spawn(step.command, step.argv, {
      cwd: root,
      env: { ...process.env, PYINSTALLER_CONFIG_DIR: join(tmpdir(), 'yagcode-pyinstaller-cache') },
      stdio: 'inherit',
      shell: false,
    });
    if (result.error || result.signal || result.status !== 0) throw new Error('SIDECAR_BUILD_FAILED');
  }
  return plan;
}

export function runCli(argv = process.argv.slice(2)) {
  const options = parseArgs(argv);
  try {
    buildSidecar(options);
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
