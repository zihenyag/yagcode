import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const REQUIRED = [
  'index.html',
  'docs/landing/landing.css',
  'docs/landing/assets/screenshots/setup-agent.png',
  'docs/landing/assets/screenshots/ready-workbench.png',
  'docs/landing/assets/screenshots/finished-diff.png',
  'docs/landing/assets/screenshots/permission-panel.png',
];

const FORBIDDEN = [
  /Bilibili/i,
  /<iframe/i,
  /docs\/landing\/landing\.js/,
  /\bfetch\s*\(/i,
  /WebSocket/i,
  /EventSource/i,
  /localStorage/i,
  /sessionStorage/i,
  /document\.cookie/i,
];

export function buildPages({ root = process.cwd(), output = 'dist/pages' } = {}) {
  const absoluteOutput = join(root, output);
  const html = readFileSync(join(root, 'index.html'), 'utf8');
  for (const pattern of FORBIDDEN) {
    if (pattern.test(html)) throw new Error('PAGES_FORBIDDEN_RUNTIME_SURFACE');
  }
  for (const relative of REQUIRED) {
    if (!existsSync(join(root, relative))) throw new Error(`PAGES_REQUIRED_FILE_MISSING:${relative}`);
  }
  rmSync(absoluteOutput, { recursive: true, force: true });
  for (const relative of REQUIRED) {
    const target = join(absoluteOutput, relative);
    mkdirSync(dirname(target), { recursive: true });
    cpSync(join(root, relative), target, { recursive: true });
  }
  writeFileSync(join(absoluteOutput, '.nojekyll'), '', 'utf8');
  return { output: absoluteOutput, files: REQUIRED.length + 1 };
}

export function runCli(argv = process.argv.slice(2)) {
  try {
    const options = parseOptions(argv);
    console.log(JSON.stringify(buildPages({ output: options.output ?? 'dist/pages' })));
    return 0;
  } catch (error) {
    console.error(error.message);
    return 1;
  }
}

function parseOptions(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    if (!argv[index]?.startsWith('--') || argv[index + 1] === undefined) throw new Error('ARGS_INVALID');
    result[argv[index].slice(2)] = argv[index + 1];
  }
  return result;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exitCode = runCli();
