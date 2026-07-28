import { createHash } from 'node:crypto';
import { cpSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, readlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { sha256File, verifyPlatformManifest } from './hash-artifacts.mjs';

export function smokeInstalledApp({ platform, asset, manifest, root, spawn = spawnSync } = {}) {
  if (platform === 'darwin-arm64') {
    return smokeDarwinDmg({ asset, manifest, spawn });
  }
  if (!root || !existsSync(root)) throw new Error('INSTALLED_APP_ROOT_REQUIRED');
  return { state: 'root-present', root, installed_tree_sha256: hashTree(root) };
}

export function smokeDarwinDmg({ asset, manifest, spawn = spawnSync } = {}) {
  if (!asset || !manifest) throw new Error('DARWIN_SMOKE_ARGS_REQUIRED');
  verifyPlatformManifest({ manifest, asset });
  const context = mkdtempSync(join(tmpdir(), 'yagcode-dmg-smoke-'));
  const mountPoint = join(context, 'mount');
  const installRoot = join(context, 'install');
  mkdirSync(mountPoint);
  mkdirSync(installRoot);
  const attach = spawn('hdiutil', ['attach', '-readonly', '-nobrowse', '-mountpoint', mountPoint, asset], {
    encoding: 'utf8',
    shell: false,
  });
  if (attach.error || attach.signal || attach.status !== 0) throw new Error('DMG_ATTACH_FAILED');
  let copiedApp = '';
  try {
    const apps = readdirSync(mountPoint).filter(name => name.endsWith('.app'));
    if (apps.length !== 1) throw new Error('DMG_APP_COUNT_INVALID');
    copiedApp = join(installRoot, apps[0]);
    cpSync(join(mountPoint, apps[0]), copiedApp, { recursive: true, dereference: false });
  } finally {
    const detach = spawn('hdiutil', ['detach', mountPoint], { encoding: 'utf8', shell: false });
    if (detach.error || detach.signal || detach.status !== 0) throw new Error('DMG_DETACH_FAILED');
  }
  if (existsSync(join(mountPoint, basename(copiedApp)))) throw new Error('DMG_MOUNT_STILL_ACCESSIBLE');
  return {
    state: 'passed',
    platform: 'darwin-arm64',
    asset_sha256: sha256File(asset),
    installed_root: installRoot,
    installed_tree_sha256: hashTree(copiedApp),
  };
}

export function runCli(argv = process.argv.slice(2)) {
  try {
    const options = parseOptions(argv);
    console.log(JSON.stringify(smokeInstalledApp(options), null, 2));
    return 0;
  } catch (error) {
    console.error(error.message);
    return 1;
  }
}

export function parseOptions(argv) {
  if (argv[0] && !argv[0].startsWith('--')) {
    if (argv[0] === 'win32-x64' && argv.length === 2) return { platform: argv[0], root: argv[1] };
    if (argv[0] === 'darwin-arm64' && argv.length === 3) return { platform: argv[0], manifest: argv[1], asset: argv[2] };
    throw new Error('ARGS_INVALID');
  }
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    if (!argv[index]?.startsWith('--') || argv[index + 1] === undefined) throw new Error('ARGS_INVALID');
    result[argv[index].slice(2)] = argv[index + 1];
  }
  return result;
}

function hashTree(root) {
  const hash = createHash('sha256');
  const visit = path => {
    const stat = lstatSync(path);
    hash.update(basename(path));
    hash.update(String(stat.mode));
    if (stat.isSymbolicLink()) {
      hash.update('symlink');
      hash.update(readlinkSync(path));
      return;
    }
    if (stat.isDirectory()) {
      for (const name of readdirSync(path).sort()) visit(join(path, name));
      return;
    }
    if (stat.isFile()) hash.update(readFileSync(path));
  };
  visit(root);
  return hash.digest('hex');
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exitCode = runCli();
