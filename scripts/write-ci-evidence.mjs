import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const STATUS = new Set(['success', 'failed', 'canceled']);
const SHA = /^[0-9a-f]{40}$/;
const FORBIDDEN = /(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|github_pat_[A-Za-z0-9_]{80,}|-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----)/;

export function canonicalJson(value) {
  return `${JSON.stringify(sortKeys(value), null, 2)}\n`;
}

export function createCiEvidence({
  env = process.env,
  status,
  commandIds,
  now = () => new Date(),
} = {}) {
  if (!STATUS.has(status)) throw new Error('CI_EVIDENCE_STATUS_INVALID');
  if (!Array.isArray(commandIds) || commandIds.length === 0 || commandIds.some(command => typeof command !== 'string' || command.length === 0)) {
    throw new Error('CI_EVIDENCE_COMMANDS_INVALID');
  }
  const evidence = {
    schema_version: 1,
    commit_sha: first(env.CI_COMMIT_SHA, env.GITHUB_SHA),
    pipeline_id: first(env.CI_PIPELINE_ID, env.GITHUB_RUN_ID, 'local-pipeline'),
    job_id: first(env.CI_JOB_ID, env.GITHUB_JOB, 'local-job'),
    job_url: first(env.CI_JOB_URL, env.GITHUB_SERVER_URL && env.GITHUB_REPOSITORY && env.GITHUB_RUN_ID
      ? `${env.GITHUB_SERVER_URL}/${env.GITHUB_REPOSITORY}/actions/runs/${env.GITHUB_RUN_ID}`
      : 'local'),
    status,
    command_ids: commandIds,
    recorded_at_utc: now().toISOString(),
  };
  validateEvidenceShape(evidence);
  const serialized = canonicalJson(evidence);
  if (FORBIDDEN.test(serialized)) throw new Error('CI_EVIDENCE_SECRET_CANARY');
  return evidence;
}

export function writePendingEvidence({ output, evidence }) {
  if (!output || !output.endsWith('.pending.json')) throw new Error('CI_EVIDENCE_PENDING_PATH_REQUIRED');
  validateEvidenceShape(evidence);
  mkdirSync(dirname(output), { recursive: true });
  writeFileSync(output, canonicalJson(evidence), { encoding: 'utf8', flag: 'w' });
}

export function validateEvidenceShape(evidence) {
  const keys = Object.keys(evidence);
  const expected = ['schema_version', 'commit_sha', 'pipeline_id', 'job_id', 'job_url', 'status', 'command_ids', 'recorded_at_utc'];
  if (keys.length !== expected.length || expected.some(key => !Object.hasOwn(evidence, key))) {
    throw new Error('CI_EVIDENCE_SCHEMA_INVALID');
  }
  if (evidence.schema_version !== 1) throw new Error('CI_EVIDENCE_SCHEMA_INVALID');
  if (!SHA.test(evidence.commit_sha)) throw new Error('CI_EVIDENCE_COMMIT_INVALID');
  if (!STATUS.has(evidence.status)) throw new Error('CI_EVIDENCE_STATUS_INVALID');
  if (!Array.isArray(evidence.command_ids) || evidence.command_ids.length === 0) throw new Error('CI_EVIDENCE_COMMANDS_INVALID');
  if (Number.isNaN(Date.parse(evidence.recorded_at_utc))) throw new Error('CI_EVIDENCE_TIME_INVALID');
}

export function runCli(argv = process.argv.slice(2), env = process.env) {
  try {
    const options = parseOptions(argv);
    const commandIds = arrayOption(argv, '--command-id');
    const evidence = createCiEvidence({ env, status: options.status, commandIds });
    writePendingEvidence({ output: options.output, evidence });
    return 0;
  } catch (error) {
    console.error(error.message);
    return 1;
  }
}

function first(...values) {
  const value = values.find(candidate => typeof candidate === 'string' && candidate.length > 0);
  if (!value) throw new Error('CI_EVIDENCE_METADATA_MISSING');
  return value;
}

function parseOptions(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const name = argv[index];
    if (!name.startsWith('--')) throw new Error('ARGS_INVALID');
    if (name === '--command-id') {
      index += 1;
      continue;
    }
    if (argv[index + 1] === undefined) throw new Error('ARGS_INVALID');
    result[name.slice(2)] = argv[index + 1];
    index += 1;
  }
  return result;
}

function arrayOption(argv, name) {
  const values = [];
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === name) values.push(argv[index + 1]);
  }
  return values;
}

function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, nested]) => [key, sortKeys(nested)]));
  }
  return value;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exitCode = runCli();
