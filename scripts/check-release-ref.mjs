import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { assertVersionContract, readVersionSnapshot } from './check-version.mjs';

const TAG_REF = /^refs\/tags\/v(\d+\.\d+\.\d+)$/;
const SHA = /^[0-9a-f]{40}$/;

export function evaluateReleaseContext({
  event = process.env.GITHUB_EVENT_NAME,
  ref = process.env.GITHUB_REF,
  sha = process.env.GITHUB_SHA,
  versionSnapshot = readVersionSnapshot(),
  spawn = spawnSync,
} = {}) {
  const appVersion = assertVersionContract(versionSnapshot);
  if (event === 'workflow_dispatch') {
    return { release_allowed: false, app_version: appVersion, reason: 'manual-build-only' };
  }
  if (event !== 'push') throw new Error('RELEASE_EVENT_INVALID');
  const match = TAG_REF.exec(ref ?? '');
  if (!match) throw new Error('RELEASE_REF_INVALID');
  if (match[1] !== appVersion) throw new Error('RELEASE_VERSION_MISMATCH');
  if (!SHA.test(sha ?? '')) throw new Error('RELEASE_SHA_INVALID');
  const resolved = spawn('git', ['rev-parse', `${ref}^{}`], { encoding: 'utf8', shell: false });
  if (resolved.error || resolved.signal || resolved.status !== 0) throw new Error('RELEASE_TAG_RESOLVE_FAILED');
  const peeled = resolved.stdout.trim();
  if (peeled !== sha) throw new Error('RELEASE_TAG_COMMIT_MISMATCH');
  return { release_allowed: true, app_version: appVersion, reason: 'tag-version-matched' };
}

export function runCli(argv = process.argv.slice(2)) {
  try {
    const options = parseOptions(argv);
    const result = evaluateReleaseContext({
      event: options.event,
      ref: options.ref,
      sha: options.sha,
    });
    console.log(JSON.stringify(result));
    return result.release_allowed ? 0 : 0;
  } catch (error) {
    console.error(error.message);
    return 1;
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

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exitCode = runCli();
