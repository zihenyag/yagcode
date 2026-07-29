import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export function smokeCli({ executable, spawn = spawnSync } = {}) {
  if (!executable) throw new Error('CLI_SMOKE_EXECUTABLE_REQUIRED');
  const health = spawn(executable, ['health'], { shell: false, encoding: 'utf8' });
  if (health.error || health.signal || health.status !== 0) {
    throw new Error('CLI_HEALTH_FAILED');
  }
  assertHealthPayload(health.stdout);
  const guide = join(dirname(executable), 'CLI使用指南.md');
  assertGuide(guide);
  return { state: 'passed', guide };
}

function assertHealthPayload(stdout) {
  let payload;
  try {
    payload = JSON.parse(String(stdout ?? ''));
  } catch {
    throw new Error('CLI_HEALTH_JSON_INVALID');
  }
  if (payload.state !== 'ready' || payload.product !== 'yagcode-cli') throw new Error('CLI_HEALTH_PAYLOAD_INVALID');
}

function assertGuide(guide) {
  if (!existsSync(guide)) throw new Error('CLI_GUIDE_MISSING');
  const text = readFileSync(guide, 'utf8');
  for (const expected of ['/provider add', '/thread', '/run', '/changes', '/diff', '/accept', '/reject', '/rollback', '/memory', '/audit']) {
    if (!text.includes(expected)) throw new Error('CLI_GUIDE_INCOMPLETE');
  }
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
