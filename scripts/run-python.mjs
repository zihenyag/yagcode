import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

export function runPython({
  platform = process.platform,
  cwd = process.cwd(),
  argv = process.argv.slice(2),
  env = process.env,
  spawn = spawnSync,
  exists = existsSync,
  report = console.error,
} = {}) {
  let interpreter;
  if (platform === 'darwin' || platform === 'linux') {
    interpreter = join(cwd, '.venv', 'bin', 'python');
  } else if (platform === 'win32') {
    interpreter = join(cwd, '.venv', 'Scripts', 'python.exe');
  } else {
    report('UNSUPPORTED_RUNTIME_PLATFORM');
    return 2;
  }
  if (argv.length === 0) {
    report('PYTHON_ARGUMENT_REQUIRED');
    return 2;
  }
  if (!exists(interpreter)) {
    report('PYTHON_VENV_MISSING');
    return 2;
  }
  let result;
  try {
    result = spawn(interpreter, argv, { cwd, env, stdio: 'inherit', shell: false });
  } catch {
    report('PYTHON_CHILD_ABNORMAL_EXIT');
    return 2;
  }
  if (result.error || result.signal || result.status === null || result.status === undefined) {
    report('PYTHON_CHILD_ABNORMAL_EXIT');
    return 2;
  }
  return result.status;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exitCode = runPython();
