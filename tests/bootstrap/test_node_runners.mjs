import assert from 'node:assert/strict';
import test from 'node:test';

const COMMANDS = [
  'test:runners',
  'test:python',
  'lint:python',
  'typecheck:python',
  'check:landing',
  'scan:framework-boundary',
  'scan:secrets',
];

function pythonPath(cwd, platform) {
  const suffix = platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
  return `${cwd}/${suffix}`;
}

function normalizePath(value) {
  return value.replaceAll('\\', '/');
}

function fixturePythonRunner({ platform, cwd, argv, env, exists, spawn }) {
  const interpreter = pythonPath(cwd, platform);
  if (!exists(interpreter)) return { status: 2, interpreter };
  const result = spawn(interpreter, argv, { cwd, env, stdio: 'inherit', shell: false });
  return { status: result.status, interpreter };
}

function runnerOracle({ cwd, platform, statuses = COMMANDS.map(() => 0) }) {
  if (!['darwin', 'linux', 'win32'].includes(platform)) return { code: 2, calls: [] };
  const calls = [];
  for (const [index, status] of statuses.entries()) {
    calls.push(['npm', ['run', COMMANDS[index]]]);
    if (status !== 0) return { code: 1, calls };
  }
  return { code: 0, calls };
}

function constantSuccessRunner() {
  return { code: 0, calls: COMMANDS.map(name => ['npm', ['run', name]]) };
}

test('test_owned_runner_fixture_and_oracle', () => {
  for (const platform of ['darwin', 'linux', 'win32']) assert.equal(pythonPath('/fixture', platform).startsWith('/'), true);
  assert.equal(pythonPath('/fixture', 'darwin'), '/fixture/.venv/bin/python');
  assert.equal(pythonPath('/fixture', 'linux'), '/fixture/.venv/bin/python');
  assert.equal(pythonPath('/fixture', 'win32'), '/fixture/.venv/Scripts/python.exe');
  const fixtureEnv = { FIXTURE: '1' };
  for (const [platform, expected] of [['darwin', '/fixture/.venv/bin/python'], ['linux', '/fixture/.venv/bin/python'], ['win32', '/fixture/.venv/Scripts/python.exe']]) {
    const existsCalls = [];
    const spawnCalls = [];
    const result = fixturePythonRunner({ platform, cwd: '/fixture', argv: ['-m', 'pytest'], env: fixtureEnv,
      exists: path => (existsCalls.push(path), true),
      spawn: (...args) => (spawnCalls.push(args), { status: 7 }) });
    assert.equal(result.status, 7);
    assert.equal(result.interpreter, expected);
    assert.deepEqual(existsCalls, [expected]);
    assert.deepEqual(spawnCalls, [[expected, ['-m', 'pytest'], {
      cwd: '/fixture', env: fixtureEnv, stdio: 'inherit', shell: false,
    }]]);
  }
  assert.deepEqual(runnerOracle({ cwd: '/fixture', platform: 'linux' }).calls, COMMANDS.map(name => ['npm', ['run', name]]));
  assert.deepEqual(runnerOracle({ cwd: '/fixture', platform: 'linux', statuses: [0, 7, 0, 0] }).calls,
    [['npm', ['run', 'test:runners']], ['npm', ['run', 'test:python']]]);
  const expectedFailure = runnerOracle({ cwd: '/fixture', platform: 'linux', statuses: [0, 7, 0, 0] });
  assert.equal(expectedFailure.code, 1);
  assert.equal(expectedFailure.calls.length, 2);
  assert.notDeepEqual(constantSuccessRunner(), expectedFailure);
  assert.equal(runnerOracle({ cwd: '/fixture', platform: 'freebsd' }).code, 2);
  assert.notDeepEqual(runnerOracle({ cwd: '/fixture', platform: 'linux', statuses: [0, 0, 0, 0] }).calls, []);
  assert.notDeepEqual(runnerOracle({ cwd: '/fixture', platform: 'linux', statuses: COMMANDS.slice(0, -1).map(() => 0) }).calls,
    COMMANDS.map(name => ['npm', ['run', name]]));
});

async function loadBootstrapRunners() {
  try {
    const [python, all] = await Promise.all([
      import(new URL('../../scripts/run-python.mjs', import.meta.url)),
      import(new URL('../../scripts/test-all.mjs', import.meta.url)),
    ]);
    return { python, all };
  } catch {
    throw new Error('BOOTSTRAP_RUNNERS_MISSING');
  }
}

test('bootstrap runners obey runtime contracts', async () => {
  let runners;
  try { runners = await loadBootstrapRunners(); } catch (error) { assert.fail(error.message); }
  const cwd = '/fixture/repository';
  const env = { FIXTURE: '1' };
  const reports = [];
  const pythonCalls = [];
  assert.equal(runners.python.runPython({ platform: 'linux', cwd, env, argv: ['-m', 'pytest'], report: value => reports.push(value),
    exists: path => normalizePath(path) === '/fixture/repository/.venv/bin/python',
    spawn: (...args) => (pythonCalls.push(args), { status: 0 }) }), 0);
  assert.equal(normalizePath(pythonCalls[0][0]), '/fixture/repository/.venv/bin/python');
  assert.deepEqual(pythonCalls[0].slice(1), [['-m', 'pytest'], { cwd, env, stdio: 'inherit', shell: false }]);
  for (const [platform, expected] of [['darwin', '/fixture/repository/.venv/bin/python'], ['linux', '/fixture/repository/.venv/bin/python'], ['win32', '/fixture/repository/.venv/Scripts/python.exe']]) {
    const calls = [];
    assert.equal(runners.python.runPython({ platform, cwd, argv: ['-V'], exists: () => true, spawn: (...args) => (calls.push(args), { status: 9 }) }), 9);
    assert.equal(normalizePath(calls[0][0]), expected);
  }
  for (const result of [{ error: new Error('x') }, { signal: 'SIGTERM', status: null }, { status: null }, { status: undefined }]) {
    const localReports = [];
    assert.equal(runners.python.runPython({ platform: 'linux', cwd, argv: ['-V'], exists: () => true, spawn: () => result, report: x => localReports.push(x) }), 2);
    assert.deepEqual(localReports, ['PYTHON_CHILD_ABNORMAL_EXIT']);
  }
  const throwReports = [];
  assert.equal(runners.python.runPython({ platform: 'linux', cwd, argv: ['-V'], exists: () => true,
    spawn: () => { throw new Error('spawn throw'); }, report: x => throwReports.push(x) }), 2);
  assert.deepEqual(throwReports, ['PYTHON_CHILD_ABNORMAL_EXIT']);
  assert.equal(runners.python.runPython({ platform: 'linux', cwd, argv: [], exists: () => true, report: x => reports.push(x) }), 2);
  assert.equal(runners.python.runPython({ platform: 'linux', cwd, argv: ['-V'], exists: () => false, report: x => reports.push(x) }), 2);
  assert.equal(runners.python.runPython({ platform: 'freebsd', cwd, argv: ['-V'], exists: () => true, report: x => reports.push(x) }), 2);
  assert.deepEqual(reports, ['PYTHON_ARGUMENT_REQUIRED', 'PYTHON_VENV_MISSING', 'UNSUPPORTED_RUNTIME_PLATFORM']);

  const allCalls = [];
  assert.equal(runners.all.runAll({ nodeVersion: '22.14.0', platform: 'linux', cwd, env, report: x => reports.push(x), spawn: (...args) => (allCalls.push(args), { status: 0 }) }), 0);
  assert.deepEqual(allCalls, COMMANDS.map(name => ['npm', ['run', name], { cwd, env, stdio: 'inherit', shell: false }]));
  const windowsCalls = [];
  assert.equal(runners.all.runAll({ nodeVersion: '22.14.0', platform: 'win32', cwd, env, spawn: (...args) => (windowsCalls.push(args), { status: 0 }) }), 0);
  assert.deepEqual(windowsCalls, COMMANDS.map(name => [
    'cmd.exe', ['/d', '/s', '/c', `npm.cmd run ${name}`], { cwd, env, stdio: 'inherit', shell: false },
  ]));
  for (const nodeVersion of ['22.13.0', '23.0.0', '26.0.0']) {
    const calls = [];
    const localReports = [];
    assert.equal(runners.all.runAll({ nodeVersion, platform: 'linux', spawn: (...args) => (calls.push(args), { status: 0 }), report: x => localReports.push(x) }), 2);
    assert.equal(calls.length, 0);
    assert.deepEqual(localReports, ['NODE_VERSION_UNSUPPORTED']);
  }
  for (const result of [{ error: new Error('x') }, { signal: 'SIGTERM', status: null }, { status: null }, { status: undefined }, { status: 3 }]) {
    const calls = [];
    assert.equal(runners.all.runAll({ nodeVersion: '22.14.0', platform: 'linux', spawn: (...args) => (calls.push(args), result) }), 1);
    assert.equal(calls.length, 1);
  }
  const thrownCalls = [];
  assert.equal(runners.all.runAll({ nodeVersion: '22.14.0', platform: 'linux',
    spawn: (...args) => { thrownCalls.push(args); throw new Error('spawn throw'); } }), 1);
  assert.equal(thrownCalls.length, 1);
  const secondFailureCalls = [];
  assert.equal(runners.all.runAll({ nodeVersion: '22.14.0', platform: 'linux', spawn: (...args) => (secondFailureCalls.push(args), { status: secondFailureCalls.length === 2 ? 5 : 0 }) }), 1);
  assert.equal(secondFailureCalls.length, 2);
  const unsupportedReports = [];
  assert.equal(runners.all.runAll({ nodeVersion: '22.14.0', platform: 'freebsd', spawn: () => { throw new Error('must not spawn'); }, report: x => unsupportedReports.push(x) }), 2);
  assert.deepEqual(unsupportedReports, ['UNSUPPORTED_RUNTIME_PLATFORM']);
});
