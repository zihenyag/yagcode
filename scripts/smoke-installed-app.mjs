import { createHash } from 'node:crypto';
import { cpSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, readlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { sha256File, verifyPlatformManifest } from './hash-artifacts.mjs';

const DESKTOP_SMOKE_TIMEOUT_MS = 30_000;

export function smokeInstalledApp({ platform, asset, manifest, root, spawn = spawnSync } = {}) {
  if (platform === 'darwin-arm64') {
    return smokeDarwinDmg({ asset, manifest, spawn });
  }
  if (!root || !existsSync(root)) throw new Error('INSTALLED_APP_ROOT_REQUIRED');
  if (platform === 'win32-x64') {
    const runtime = smokeDesktopTree({ platform, appRoot: root, spawn });
    return {
      state: 'passed',
      platform,
      root,
      installed_tree_sha256: hashTree(root),
      ...runtime,
    };
  }
  throw new Error('INSTALLED_APP_PLATFORM_UNSUPPORTED');
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
    copyInstalledApp(join(mountPoint, apps[0]), copiedApp);
  } finally {
    const detach = spawn('hdiutil', ['detach', mountPoint], { encoding: 'utf8', shell: false });
    if (detach.error || detach.signal || detach.status !== 0) throw new Error('DMG_DETACH_FAILED');
  }
  if (existsSync(join(mountPoint, basename(copiedApp)))) throw new Error('DMG_MOUNT_STILL_ACCESSIBLE');
  const runtime = smokeDesktopTree({ platform: 'darwin-arm64', appRoot: copiedApp, spawn });
  return {
    state: 'passed',
    platform: 'darwin-arm64',
    asset_sha256: sha256File(asset),
    installed_root: installRoot,
    installed_tree_sha256: hashTree(copiedApp),
    ...runtime,
  };
}

export function smokeDesktopTree({ platform, appRoot, spawn = spawnSync } = {}) {
  if (!appRoot || !existsSync(appRoot)) throw new Error('INSTALLED_APP_ROOT_REQUIRED');
  const desktopExecutable = packagedDesktopExecutable(platform, appRoot);
  const sidecarExecutable = packagedSidecarExecutable(platform, appRoot);
  if (!existsSync(desktopExecutable)) throw new Error('INSTALLED_APP_EXECUTABLE_MISSING');
  if (!existsSync(sidecarExecutable)) throw new Error('PACKAGED_SIDECAR_MISSING');
  const sidecarHealth = smokeSidecarExecutable({ executable: sidecarExecutable, spawn });
  const desktopLaunch = smokeDesktopExecutable({ executable: desktopExecutable, spawn });
  return {
    desktop_executable: desktopExecutable,
    desktop_launch: desktopLaunch,
    sidecar_executable: sidecarExecutable,
    sidecar_health: sidecarHealth,
  };
}

export function copyInstalledApp(source, destination) {
  cpSync(source, destination, { recursive: true, dereference: false, verbatimSymlinks: true });
}

export function packagedDesktopExecutable(platform, appRoot) {
  if (platform === 'darwin-arm64') return join(appRoot, 'Contents', 'MacOS', 'yagcode');
  if (platform === 'win32-x64') return join(appRoot, 'yagcode.exe');
  throw new Error('INSTALLED_APP_PLATFORM_UNSUPPORTED');
}

export function packagedSidecarExecutable(platform, appRoot) {
  if (platform === 'darwin-arm64') {
    return join(appRoot, 'Contents', 'Resources', 'sidecar', 'darwin-arm64', 'yagcode-sidecar', 'yagcode-sidecar');
  }
  if (platform === 'win32-x64') {
    return join(appRoot, 'resources', 'sidecar', 'win32-x64', 'yagcode-sidecar', 'yagcode-sidecar.exe');
  }
  throw new Error('INSTALLED_APP_PLATFORM_UNSUPPORTED');
}

function smokeSidecarExecutable({ executable, spawn }) {
  const result = spawn(executable, ['health'], { encoding: 'utf8', shell: false, windowsHide: true });
  assertCommandSucceeded('SIDECAR_HEALTH_FAILED', result);
  let payload;
  try {
    payload = JSON.parse(String(result.stdout ?? ''));
  } catch {
    throw new Error('SIDECAR_HEALTH_JSON_INVALID');
  }
  if (payload.state !== 'ready' || payload.product !== 'yagcode-sidecar') {
    throw new Error('SIDECAR_HEALTH_PAYLOAD_INVALID');
  }
  return { state: payload.state, product: payload.product, version: payload.version };
}

function smokeDesktopExecutable({ executable, spawn }) {
  const result = spawn(executable, [], {
    encoding: 'utf8',
    env: { ...process.env, YAGCODE_DESKTOP_SMOKE: '1' },
    shell: false,
    timeout: DESKTOP_SMOKE_TIMEOUT_MS,
    windowsHide: true,
  });
  assertCommandSucceeded('DESKTOP_SMOKE_FAILED', result);
  return { state: 'passed' };
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

function assertCommandSucceeded(reason, result) {
  if (result?.error || result?.signal || result?.status !== 0) {
    throw new Error(commandFailureMessage(reason, result));
  }
}

function commandFailureMessage(reason, result) {
  const details = [reason];
  if (result?.error?.message) details.push(result.error.message);
  if (result?.signal) details.push(`signal=${result.signal}`);
  if (result?.status !== undefined && result?.status !== null) details.push(`status=${result.status}`);
  const stderr = String(result?.stderr ?? '').trim();
  const stdout = String(result?.stdout ?? '').trim();
  if (stderr) details.push(stderr);
  if (stdout) details.push(stdout);
  return details.join('\n').slice(0, 4000);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exitCode = runCli();
