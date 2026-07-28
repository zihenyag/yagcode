import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export function readRuntimeInventory({ root = process.cwd(), readFile = readFileSync } = {}) {
  const data = JSON.parse(readFile(`${root}/packaging/shipped-runtime.json`, 'utf8'));
  for (const product of ['cli', 'desktop']) {
    if (!Array.isArray(data.products?.[product]) || data.products[product].length === 0) {
      throw new Error('RUNTIME_INVENTORY_PRODUCT_MISSING');
    }
    for (const item of data.products[product]) {
      for (const key of ['name', 'version', 'source', 'license', 'notice_anchor']) {
        if (typeof item[key] !== 'string' || item[key].trim() === '') {
          throw new Error('RUNTIME_INVENTORY_ITEM_INVALID');
        }
      }
    }
  }
  return data;
}

export function inventoryHash({ root = process.cwd(), readFile = readFileSync } = {}) {
  readRuntimeInventory({ root, readFile });
  return createHash('sha256').update(readFile(`${root}/packaging/shipped-runtime.json`)).digest('hex');
}

export function runCli() {
  try {
    console.log(inventoryHash());
    return 0;
  } catch (error) {
    console.error(error.message);
    return 1;
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exitCode = runCli();
