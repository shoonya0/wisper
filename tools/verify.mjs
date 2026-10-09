#!/usr/bin/env node
// tools/verify.mjs — the one "verify" entry point (Stop hook, pre-commit, CI).
// Runs the fast checks in order and stops at the first failure; `--full` adds the
// slow ones.
//
//   node tools/verify.mjs          # fast: what the Stop hook runs
//   node tools/verify.mjs --full   # fast + slow: what CI runs
//
// Uses app/.venv's Python when it exists (local), otherwise `python` on PATH (CI).
// Tools are run as `python -m <tool>` with no shell, so it behaves the same on
// Windows and macOS.

import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const venvPython = process.platform === 'win32'
  ? path.join(root, 'app', '.venv', 'Scripts', 'python.exe')
  : path.join(root, 'app', '.venv', 'bin', 'python');
const python = existsSync(venvPython) ? venvPython : 'python';

const FAST = [
  { name: 'lint', args: ['-m', 'ruff', 'check', '.'] },
  { name: 'typecheck', args: ['-m', 'pyright'] },
  { name: 'unit + architecture tests', args: ['-m', 'pytest'] },
];

// No formatter check: the code is hand-formatted (aligned tables), by choice.
const SLOW = [
  // { name: 'GPU smoke test', args: ['-m', 'pytest', '-m', 'gpu'] },
];

const steps = process.argv.includes('--full') ? [...FAST, ...SLOW] : FAST;
const summary = [];

for (const step of steps) {
  const started = Date.now();
  process.stdout.write(`\n▶ ${step.name}: python ${step.args.join(' ')}\n`);
  const r = spawnSync(python, step.args, { cwd: root, stdio: 'inherit', windowsHide: true });
  const seconds = ((Date.now() - started) / 1000).toFixed(1);
  const ok = r.status === 0 && !r.error;
  summary.push(`${ok ? '✔' : '✘'} ${step.name} (${seconds}s)${r.error ? ` — ${r.error.message}` : ''}`);
  if (!ok) {
    process.stdout.write(`\n${summary.join('\n')}\nverify FAILED at "${step.name}"\n`);
    process.exit(r.status || 1);
  }
}

process.stdout.write(`\n${summary.join('\n')}\nverify passed (${steps.length} steps)\n`);
