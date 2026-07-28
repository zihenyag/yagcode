import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export function smokeCli({ executable, spawn = spawnSync } = {}) {
  if (!executable) throw new Error('CLI_SMOKE_EXECUTABLE_REQUIRED');
  const health = spawn(executable, ['health'], { shell: false, encoding: 'utf8' });
  if (health.error || health.signal || health.status !== 0 || !health.stdout.includes('"state": "ready"')) {
    throw new Error('CLI_HEALTH_FAILED');
  }
  return { state: 'passed' };
}

export function runCli(argv = process.argv.slice(2)) {
  try {
    smokeCli({ executable: argv[argv.indexOf('--executable') + 1] });
    return 0;
  } catch (error) {
    console.error(error.message);
    return 1;
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exitCode = runCli();
