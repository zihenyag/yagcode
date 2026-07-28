import assert from 'node:assert/strict';
import test from 'node:test';

import { assertVersionContract } from '../../../scripts/check-version.mjs';

test('version contract accepts only exact matching semver triplet', () => {
  assert.equal(assertVersionContract({ root: '0.1.0', desktop: '0.1.0', python: '0.1.0' }), '0.1.0');
  assert.throws(() => assertVersionContract({ root: '0.1.0', desktop: '0.1.1', python: '0.1.0' }), /VERSION_MISMATCH/);
  assert.throws(() => assertVersionContract({ root: 'v0.1.0', desktop: 'v0.1.0', python: 'v0.1.0' }), /VERSION_FORMAT_INVALID/);
});
