import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

function parseJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

function testOwnedCanonicalJson(value) {
  return `${JSON.stringify(sortKeys(value), null, 2)}\n`;
}

function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => [a, sortKeys(b)]));
  }
  return value;
}

test('test_owned_ci_evidence_oracle_rejects_secret_values', () => {
  const evidence = {
    schema_version: 1,
    commit_sha: 'a'.repeat(40),
    pipeline_id: '123',
    job_id: '456',
    job_url: 'https://github.example/zihenyag/yagcode/actions/runs/123',
    status: 'success',
    command_ids: ['test:all'],
    recorded_at_utc: '2026-07-28T00:00:00.000Z',
  };
  assert.equal(testOwnedCanonicalJson(evidence).endsWith('\n'), true);
  assert.equal(testOwnedCanonicalJson(evidence).includes('sk-'), false);
  const canary = `sk-${'test-owned-secret-canary-000000'}`;
  const contaminated = { ...evidence, job_url: `https://example.invalid/${canary}` };
  assert.notEqual(testOwnedCanonicalJson(contaminated).includes(canary), false);
});

test('ci evidence writer and verifier produce redacted final artifacts', async () => {
  const writer = await import(new URL('../../scripts/write-ci-evidence.mjs', import.meta.url));
  const verifier = await import(new URL('../../scripts/verify-ci-evidence.mjs', import.meta.url));
  const root = mkdtempSync(join(tmpdir(), 'yagcode-ci-evidence-'));
  const pending = join(root, 'offline-checks.pending.json');
  const final = join(root, 'offline-checks.json');
  const env = {
    GITHUB_SHA: 'b'.repeat(40),
    GITHUB_RUN_ID: 'run-7',
    GITHUB_JOB: 'offline-checks',
    GITHUB_SERVER_URL: 'https://github.example',
    GITHUB_REPOSITORY: 'zihenyag/yagcode',
    SECRET_CANARY: `sk-${'should-not-appear-in-output-000000'}`,
  };
  const now = () => new Date('2026-07-28T01:02:03.004Z');
  const evidence = writer.createCiEvidence({ env, status: 'success', commandIds: ['test:all'], now });
  assert.deepEqual(Object.keys(evidence), [
    'schema_version',
    'commit_sha',
    'pipeline_id',
    'job_id',
    'job_url',
    'status',
    'command_ids',
    'recorded_at_utc',
  ]);
  assert.equal(JSON.stringify(evidence).includes('should-not-appear'), false);
  writer.writePendingEvidence({ output: pending, evidence });
  assert.deepEqual(parseJson(pending), evidence);
  assert.equal(verifier.verifyEvidence({ evidence, status: 'success', commandIds: ['test:all'] }).status, 'success');
  verifier.promoteEvidence({ input: pending, promote: final, status: 'success', commandIds: ['test:all'] });
  assert.deepEqual(parseJson(final), evidence);
  assert.throws(() => verifier.verifyEvidence({ evidence: { ...evidence, status: 'weird' }, status: 'success', commandIds: ['test:all'] }), /CI_EVIDENCE_STATUS_INVALID/);
  assert.throws(() => verifier.verifyEvidence({ evidence: { ...evidence, command_ids: ['other'] }, status: 'success', commandIds: ['test:all'] }), /CI_EVIDENCE_COMMANDS_MISMATCH/);
});

test('ensureFinal records failure when a failed job has no final evidence', async () => {
  const verifier = await import(new URL('../../scripts/verify-ci-evidence.mjs', import.meta.url));
  const root = mkdtempSync(join(tmpdir(), 'yagcode-ci-ensure-'));
  const final = join(root, 'offline-checks.json');
  const env = {
    GITHUB_SHA: 'c'.repeat(40),
    GITHUB_RUN_ID: 'run-8',
    GITHUB_JOB: 'offline-checks',
    GITHUB_SERVER_URL: 'https://github.example',
    GITHUB_REPOSITORY: 'zihenyag/yagcode',
  };
  verifier.ensureFinalEvidence({ final, fallbackStatus: 'failed', commandIds: ['offline-checks'], env, now: () => new Date('2026-07-28T02:00:00.000Z') });
  assert.equal(parseJson(final).status, 'failed');
  assert.equal(parseJson(final).command_ids[0], 'offline-checks');
});

test('ensureFinal rejects missing success evidence', async () => {
  const verifier = await import(new URL('../../scripts/verify-ci-evidence.mjs', import.meta.url));
  const root = mkdtempSync(join(tmpdir(), 'yagcode-ci-missing-success-'));
  const final = join(root, 'offline-checks.json');
  assert.equal(existsSync(final), false);
  assert.throws(() => verifier.ensureFinalEvidence({
    final,
    fallbackStatus: 'success',
    commandIds: ['offline-checks'],
    env: {
      GITHUB_SHA: 'd'.repeat(40),
      GITHUB_RUN_ID: '1',
      GITHUB_JOB: 'offline-checks',
      GITHUB_SERVER_URL: 'https://github.example',
      GITHUB_REPOSITORY: 'zihenyag/yagcode',
    },
  }), /CI_EVIDENCE_SUCCESS_FINAL_MISSING/);
});
