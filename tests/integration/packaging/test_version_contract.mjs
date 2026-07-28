import assert from 'node:assert/strict';
import test from 'node:test';

import { assertVersionContract, pythonInterpreter, readVersionSnapshot } from '../../../scripts/check-version.mjs';

test('version contract accepts only exact matching semver triplet', () => {
  assert.equal(assertVersionContract({ root: '0.1.0', desktop: '0.1.0', python: '0.1.0' }), '0.1.0');
  assert.throws(() => assertVersionContract({ root: '0.1.0', desktop: '0.1.1', python: '0.1.0' }), /VERSION_MISMATCH/);
  assert.throws(() => assertVersionContract({ root: 'v0.1.0', desktop: 'v0.1.0', python: 'v0.1.0' }), /VERSION_FORMAT_INVALID/);
});

test('version reader uses the active platform python from the project venv', () => {
  assert.equal(pythonInterpreter({ root: '/repo', platform: 'linux' }), '/repo/.venv/bin/python');
  assert.equal(pythonInterpreter({ root: '/repo', platform: 'darwin' }), '/repo/.venv/bin/python');
  assert.equal(pythonInterpreter({ root: '/repo', platform: 'win32' }), '/repo/.venv/Scripts/python.exe');

  const calls = [];
  const snapshot = readVersionSnapshot({
    root: '/repo',
    platform: 'win32',
    readFile: path => {
      if (path === '/repo/package.json') return '{"version":"0.1.0"}';
      if (path === '/repo/apps/desktop/package.json') return '{"version":"0.1.0"}';
      throw new Error(`unexpected read ${path}`);
    },
    spawn: (...args) => {
      calls.push(args);
      return { status: 0, signal: null, error: null, stdout: '0.1.0\n' };
    },
  });
  assert.equal(snapshot.python, '0.1.0');
  assert.equal(calls[0][0], '/repo/.venv/Scripts/python.exe');
  assert.equal(calls[0][1][0], '/repo/scripts/read-python-project-version.py');
});
