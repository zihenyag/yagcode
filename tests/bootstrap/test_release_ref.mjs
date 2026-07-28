import assert from 'node:assert/strict';
import test from 'node:test';

function fakeSpawnFor({ peeledSha = 'a'.repeat(40), status = 0, signal = null, error = null } = {}) {
  const calls = [];
  const spawn = (...args) => {
    calls.push(args);
    return { status, signal, error, stdout: `${peeledSha}\n`, stderr: '' };
  };
  return { spawn, calls };
}

test('test_owned_release_ref_oracle_accepts_only_version_tags', () => {
  assert.match('refs/tags/v0.1.0', /^refs\/tags\/v\d+\.\d+\.\d+$/);
  assert.doesNotMatch('refs/heads/main', /^refs\/tags\/v\d+\.\d+\.\d+$/);
  assert.doesNotMatch('refs/tags/0.1.0', /^refs\/tags\/v\d+\.\d+\.\d+$/);
  assert.doesNotMatch('refs/tags/v0.1', /^refs\/tags\/v\d+\.\d+\.\d+$/);
});

test('manual dispatch checks version but never allows release', async () => {
  const release = await import(new URL('../../scripts/check-release-ref.mjs', import.meta.url));
  const result = release.evaluateReleaseContext({
    event: 'workflow_dispatch',
    ref: 'refs/heads/main',
    sha: 'a'.repeat(40),
    versionSnapshot: { root: '0.1.0', desktop: '0.1.0', python: '0.1.0' },
    spawn: () => { throw new Error('git must not be called'); },
  });
  assert.deepEqual(result, { release_allowed: false, app_version: '0.1.0', reason: 'manual-build-only' });
});

test('push tag allows release only when tag version and peeled commit match', async () => {
  const release = await import(new URL('../../scripts/check-release-ref.mjs', import.meta.url));
  const sha = 'a'.repeat(40);
  const fake = fakeSpawnFor({ peeledSha: sha });
  const result = release.evaluateReleaseContext({
    event: 'push',
    ref: 'refs/tags/v0.1.0',
    sha,
    versionSnapshot: { root: '0.1.0', desktop: '0.1.0', python: '0.1.0' },
    spawn: fake.spawn,
  });
  assert.equal(result.release_allowed, true);
  assert.equal(result.app_version, '0.1.0');
  assert.deepEqual(fake.calls[0][0], 'git');
  assert.deepEqual(fake.calls[0][1], ['rev-parse', 'refs/tags/v0.1.0^{}']);
});

test('release ref rejects branch, version mismatch, commit mismatch, and git failure', async () => {
  const release = await import(new URL('../../scripts/check-release-ref.mjs', import.meta.url));
  const sha = 'a'.repeat(40);
  assert.throws(() => release.evaluateReleaseContext({
    event: 'push',
    ref: 'refs/heads/main',
    sha,
    versionSnapshot: { root: '0.1.0', desktop: '0.1.0', python: '0.1.0' },
  }), /RELEASE_REF_INVALID/);
  assert.throws(() => release.evaluateReleaseContext({
    event: 'push',
    ref: 'refs/tags/v0.2.0',
    sha,
    versionSnapshot: { root: '0.1.0', desktop: '0.1.0', python: '0.1.0' },
    spawn: fakeSpawnFor({ peeledSha: sha }).spawn,
  }), /RELEASE_VERSION_MISMATCH/);
  assert.throws(() => release.evaluateReleaseContext({
    event: 'push',
    ref: 'refs/tags/v0.1.0',
    sha,
    versionSnapshot: { root: '0.1.0', desktop: '0.1.0', python: '0.1.0' },
    spawn: fakeSpawnFor({ peeledSha: 'b'.repeat(40) }).spawn,
  }), /RELEASE_TAG_COMMIT_MISMATCH/);
  assert.throws(() => release.evaluateReleaseContext({
    event: 'push',
    ref: 'refs/tags/v0.1.0',
    sha,
    versionSnapshot: { root: '0.1.0', desktop: '0.1.0', python: '0.1.0' },
    spawn: fakeSpawnFor({ status: 1 }).spawn,
  }), /RELEASE_TAG_RESOLVE_FAILED/);
});
