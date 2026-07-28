import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { canonicalJson, createCiEvidence, validateEvidenceShape } from './write-ci-evidence.mjs';

export function verifyEvidence({ evidence, status, commandIds }) {
  validateEvidenceShape(evidence);
  if (status && evidence.status !== status) throw new Error('CI_EVIDENCE_STATUS_MISMATCH');
  if (commandIds && canonicalJson(evidence.command_ids) !== canonicalJson(commandIds)) {
    throw new Error('CI_EVIDENCE_COMMANDS_MISMATCH');
  }
  return evidence;
}

export function promoteEvidence({ input, promote, status, commandIds }) {
  const evidence = verifyEvidence({
    evidence: JSON.parse(readFileSync(input, 'utf8')),
    status,
    commandIds,
  });
  writeFileSync(promote, canonicalJson(evidence), { encoding: 'utf8', flag: 'w' });
  return evidence;
}

export function ensureFinalEvidence({
  final,
  fallbackStatus,
  commandIds,
  env = process.env,
  now = () => new Date(),
} = {}) {
  if (existsSync(final)) {
    return verifyEvidence({ evidence: JSON.parse(readFileSync(final, 'utf8')), commandIds });
  }
  if (fallbackStatus === 'success') throw new Error('CI_EVIDENCE_SUCCESS_FINAL_MISSING');
  const pending = join(dirname(final), `${Date.now()}.pending.json`);
  const evidence = createCiEvidence({ env, status: normalizeStatus(fallbackStatus), commandIds, now });
  writeFileSync(pending, canonicalJson(evidence), { encoding: 'utf8', flag: 'w' });
  writeFileSync(final, canonicalJson(evidence), { encoding: 'utf8', flag: 'w' });
  return evidence;
}

export function runCli(argv = process.argv.slice(2), env = process.env) {
  try {
    const options = parseOptions(argv);
    const commandIds = arrayOption(argv, '--command-id');
    if (options['ensure-final']) {
      ensureFinalEvidence({
        final: options['ensure-final'],
        fallbackStatus: options['fallback-status'],
        commandIds,
        env,
      });
      return 0;
    }
    promoteEvidence({
      input: options.input,
      promote: options.promote,
      status: options.status,
      commandIds,
    });
    return 0;
  } catch (error) {
    console.error(error.message);
    return 1;
  }
}

function normalizeStatus(value) {
  if (value === 'success' || value === 'failed' || value === 'canceled') return value;
  throw new Error('CI_EVIDENCE_STATUS_INVALID');
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

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exitCode = runCli();
