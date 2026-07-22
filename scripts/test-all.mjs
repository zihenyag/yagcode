import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export const TEST_COMMANDS = Object.freeze(['test:runners', 'test:python', 'lint:python', 'typecheck:python']);

function supportsNode22(version) {
  const match = /^(\d+)\.(\d+)\.\d+$/.exec(version);
  return match !== null && Number(match[1]) === 22 && Number(match[2]) >= 14;
}

export function runAll({
  nodeVersion = process.versions.node,
  platform = process.platform,
  cwd = process.cwd(),
  env = process.env,
  spawn = spawnSync,
  report = console.error,
} = {}) {
  if (!supportsNode22(nodeVersion)) {
    report('NODE_VERSION_UNSUPPORTED');
    return 2;
  }
  if (!['darwin', 'linux', 'win32'].includes(platform)) {
    report('UNSUPPORTED_RUNTIME_PLATFORM');
    return 2;
  }
  const windows = platform === 'win32';
  for (const name of TEST_COMMANDS) {
    const command = windows ? 'cmd.exe' : 'npm';
    const argv = windows ? ['/d', '/s', '/c', `npm.cmd run ${name}`] : ['run', name];
    let result;
    try {
      result = spawn(command, argv, { cwd, env, stdio: 'inherit', shell: false });
    } catch {
      return 1;
    }
    if (result.error || result.signal || result.status === null || result.status === undefined || result.status !== 0) {
      return 1;
    }
  }
  return 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exitCode = runAll();
