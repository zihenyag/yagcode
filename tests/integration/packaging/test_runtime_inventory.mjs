import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { inventoryHash, readRuntimeInventory } from '../../../scripts/inventory-shipped-runtime.mjs';
import { runtimeHashes } from '../../../scripts/hash-artifacts.mjs';

test('runtime inventory covers desktop and cli products with notice anchors', () => {
  const inventory = readRuntimeInventory();
  assert.ok(inventory.products.cli.some(item => item.notice_anchor === 'yagcode-cli'));
  assert.ok(inventory.products.desktop.some(item => item.notice_anchor === 'electron'));
  assert.equal(inventoryHash().length, 64);
});

test('runtime and notice hashes are bound to manifest fields', () => {
  const hashes = runtimeHashes();
  assert.equal(hashes.runtime_inventory_sha256.length, 64);
  assert.equal(hashes.notices_sha256.length, 64);
  const notices = readFileSync('THIRD_PARTY_NOTICES.md', 'utf8');
  assert.ok(notices.includes('Electron'));
  assert.ok(notices.includes('CPython'));
});
