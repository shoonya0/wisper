// PreToolUse hook (matcher: Edit|Write|NotebookEdit)
//
// Blocks the agent from editing files that must never be hand-edited by an agent:
// secrets, lockfiles, generated output, applied migrations. Exit code 2 blocks the
// tool call and stderr is shown to the agent as the reason (Claude Code hooks docs).
//
// Cross-platform: Node built-ins only; paths are normalised with node:path and
// matched against both separators, so it behaves the same on Windows and macOS.
//
// Customise PROTECTED / ALLOWED for your project. This is a guardrail against
// accidents, not a security boundary — the agent can still run shell commands,
// which guard-shell.mjs covers separately.

import path from 'node:path';

const PROTECTED = [
  { re: /(^|[\\/])\.env(\.[^\\/]+)?$/i, why: 'secrets file' },
  {
    re: /(^|[\\/])(package-lock\.json|npm-shrinkwrap\.json|pnpm-lock\.yaml|yarn\.lock|bun\.lockb?|poetry\.lock|uv\.lock|Cargo\.lock|Gemfile\.lock|go\.sum)$/i,
    why: 'lockfile — change it with the package manager, not by editing',
  },
  { re: /(^|[\\/])(dist|dist-[^\\/]+|generated|__generated__|__pycache__)[\\/]/i, why: 'generated output — change the source instead' },
  { re: /(^|[\\/])\.git[\\/]/, why: 'git internals' },
  // Wisper-specific
  {
    re: /^whisper\.cpp[\\/]/i,
    why: 'upstream whisper.cpp clone (gitignored, pinned at 6e4ab85); app/whisper_native.py mirrors its structs — change our binding instead, or ask the user',
  },
  { re: /^app[\\/]\.venv[\\/]/i, why: 'virtualenv — change it with pip and app/requirements*.txt' },
  { re: /\.bin$/i, why: 'model weights — download them, never edit' },
];

const ALLOWED = [/(^|[\\/])\.env\.example$/i, /(^|[\\/])\.env\.sample$/i];

function readStdin() {
  return new Promise((resolve) => {
    let raw = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => (raw += chunk));
    process.stdin.on('end', () => resolve(raw));
    process.stdin.on('error', () => resolve(raw));
  });
}

const raw = await readStdin();
let input = {};
try {
  input = JSON.parse(raw || '{}');
} catch {
  process.exit(0); // malformed input: don't block, let the normal permission flow apply
}

const toolInput = input.tool_input ?? {};
const target = toolInput.file_path ?? toolInput.notebook_path ?? '';
if (!target) process.exit(0);

const projectDir = process.env.CLAUDE_PROJECT_DIR || input.cwd || process.cwd();
const absolute = path.resolve(projectDir, target);
const relative = path.relative(projectDir, absolute) || path.basename(absolute);

if (ALLOWED.some((re) => re.test(relative))) process.exit(0);

const hit = PROTECTED.find(({ re }) => re.test(relative));
if (hit) {
  process.stderr.write(
    `Blocked by .claude/hooks/protect-files.mjs: "${relative}" is protected (${hit.why}). ` +
      'If this edit is truly required, stop and ask the user to make it or to change the hook.\n',
  );
  process.exit(2);
}

process.exit(0);
