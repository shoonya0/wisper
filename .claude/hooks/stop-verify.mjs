// Stop hook
//
// Runs the project's fast check (default `npm run verify`) when the agent tries to
// finish a turn, and BLOCKS the stop (exit code 2, stderr shown to the agent) if
// the check fails. This turns "run the tests before saying done" from advice into
// a deterministic gate.
//
// Guards against wasted runs and endless loops:
// - Skips when the working tree has no changes since the last passing run
//   (fingerprint of `git status --porcelain` + `git diff HEAD`), so Q&A turns are free.
// - Blocks at most CLAUDE_VERIFY_MAX_BLOCKS times in a row per session (default 3),
//   then lets the turn end and tells the user. Claude Code also has its own cap
//   (8 consecutive stop-hook continuations, reset whenever Claude calls a tool).
//
// Cross-platform: the verify command is a fixed string run through the platform
// shell (cmd.exe on Windows, /bin/sh on macOS) — required to launch npm's .cmd shim
// on Windows. Never interpolate untrusted input into CLAUDE_VERIFY_CMD.

import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const VERIFY_CMD = process.env.CLAUDE_VERIFY_CMD || 'npm run verify';
const MAX_BLOCKS = Number.parseInt(process.env.CLAUDE_VERIFY_MAX_BLOCKS || '3', 10);
const TIMEOUT_MS = 14 * 60 * 1000; // keep below the hook's "timeout": 900 (seconds)
const TAIL_LINES = 80;

function readStdin() {
  return new Promise((resolve) => {
    let raw = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => (raw += chunk));
    process.stdin.on('end', () => resolve(raw));
    process.stdin.on('error', () => resolve(raw));
  });
}

function git(args, cwd) {
  const r = spawnSync('git', args, { cwd, encoding: 'utf8', maxBuffer: 256 * 1024 * 1024, windowsHide: true });
  return r.status === 0 ? r.stdout : null;
}

function loadState(file) {
  try {
    return JSON.parse(readFileSync(file, 'utf8'));
  } catch {
    return { blocks: 0, lastPass: null };
  }
}

function saveState(file, state) {
  try {
    writeFileSync(file, JSON.stringify(state));
  } catch {
    // state is an optimisation; never fail the hook over it
  }
}

const raw = await readStdin();
let input = {};
try {
  input = JSON.parse(raw || '{}');
} catch {
  process.exit(0);
}

const projectDir = process.env.CLAUDE_PROJECT_DIR || input.cwd || process.cwd();
const sessionId = String(input.session_id || 'nosession').replace(/[^A-Za-z0-9_-]/g, '_');
const stateFile = path.join(os.tmpdir(), `claude-stop-verify-${sessionId}.json`);
const state = loadState(stateFile);

// 1. Nothing changed since the last passing run? Let the turn end.
const status = git(['status', '--porcelain'], projectDir);
if (status !== null && status.trim() === '') {
  rmSync(stateFile, { force: true });
  process.exit(0);
}
const fingerprint =
  status === null
    ? null
    : createHash('sha1')
        .update(status)
        .update(git(['diff', 'HEAD'], projectDir) ?? '')
        .digest('hex');
if (fingerprint && state.lastPass === fingerprint) process.exit(0);

// 2. Run the check.
if (!existsSync(path.join(projectDir, 'package.json')) && !process.env.CLAUDE_VERIFY_CMD) process.exit(0);
const result = spawnSync(VERIFY_CMD, {
  cwd: projectDir,
  shell: true,
  encoding: 'utf8',
  timeout: TIMEOUT_MS,
  maxBuffer: 64 * 1024 * 1024,
  windowsHide: true,
});

if (result.status === 0) {
  saveState(stateFile, { blocks: 0, lastPass: fingerprint });
  process.exit(0);
}

// 3. Failed. Block, unless we've already blocked MAX_BLOCKS times in a row.
const blocks = (state.blocks || 0) + 1;
if (blocks > MAX_BLOCKS) {
  saveState(stateFile, { blocks: 0, lastPass: state.lastPass ?? null });
  // Exit 0 lets the turn end; systemMessage is shown to the user, not the agent.
  process.stdout.write(
    JSON.stringify({
      systemMessage: `stop-verify: "${VERIFY_CMD}" still fails after ${MAX_BLOCKS} attempts. Handing back to you.`,
    }),
  );
  process.exit(0);
}
saveState(stateFile, { blocks, lastPass: state.lastPass ?? null });

const output = `${result.stdout ?? ''}\n${result.stderr ?? ''}`.trim().split(/\r?\n/);
const reason = result.error
  ? `could not run (${result.error.code || result.error.message})`
  : `exit code ${result.status}`;
process.stderr.write(
  `Verification failed: "${VERIFY_CMD}" ${reason} (attempt ${blocks}/${MAX_BLOCKS}).\n` +
    'Fix the root cause before finishing. Do not skip, delete or weaken tests. ' +
    'If a failure is pre-existing (in the recorded baseline), say so with evidence.\n' +
    `--- last ${TAIL_LINES} lines ---\n${output.slice(-TAIL_LINES).join('\n')}\n`,
);
process.exit(2);
