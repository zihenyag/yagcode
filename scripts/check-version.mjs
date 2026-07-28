import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const SEMVER = /^\d+\.\d+\.\d+$/;

export function readVersionSnapshot({
  root = process.cwd(),
  spawn = spawnSync,
  readFile = readFileSync,
} = {}) {
  const rootPackage = JSON.parse(readFile(`${root}/package.json`, 'utf8'));
  const desktopPackage = JSON.parse(readFile(`${root}/apps/desktop/package.json`, 'utf8'));
  const python = spawn(
    `${root}/.venv/bin/python`,
    [`${root}/scripts/read-python-project-version.py`, root],
    { cwd: root, encoding: 'utf8', shell: false },
  );
  if (python.error || python.signal || python.status !== 0) {
    throw new Error('PYTHON_VERSION_READ_FAILED');
  }
  return {
    root: rootPackage.version,
    desktop: desktopPackage.version,
    python: python.stdout.trim(),
  };
}

export function assertVersionContract(snapshot = readVersionSnapshot()) {
  const versions = [snapshot.root, snapshot.desktop, snapshot.python];
  if (!versions.every(version => SEMVER.test(version))) {
    throw new Error('VERSION_FORMAT_INVALID');
  }
  if (!(snapshot.root === snapshot.desktop && snapshot.root === snapshot.python)) {
    throw new Error('VERSION_MISMATCH');
  }
  return snapshot.root;
}

export function runCli() {
  try {
    console.log(assertVersionContract());
    return 0;
  } catch (error) {
    console.error(error.message);
    return 1;
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exitCode = runCli();
