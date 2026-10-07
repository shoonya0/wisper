// PreToolUse hook (matcher: Bash|PowerShell)
//
// Blocks a short list of destructive shell commands, in both POSIX and PowerShell
// spellings. Exit code 2 blocks the call; stderr is shown to the agent.
//
// This is a backstop for accidents, NOT a sandbox: regexes can be bypassed. Keep
// real protection in permissions (/permissions), sandboxing, branch protection and
// backups. Extend RULES for your project (e.g. production database hosts).

const RULES = [
  { re: /\brm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)[a-z]*\s+(\/|~|\$HOME|\.|\*)(\s|$)/i, why: 'recursive force-delete of a root, home, or whole directory' },
  { re: /\bRemove-Item\b(?=.*-Recurse)(?=.*-Force).*\s(\\|\/|[A-Z]:\\?|~|\.|\*)(\s|$)/i, why: 'recursive force-delete of a root, home, or whole directory' },
  { re: /\bgit\s+push\b.*(--force\b|-f\b|--force-with-lease\b).*\b(main|master|release[\w/-]*)\b/i, why: 'force-push to a protected branch' },
  { re: /\bgit\s+reset\s+--hard\b/i, why: 'discards uncommitted work — use git stash, or ask first' },
  { re: /\bgit\s+clean\s+-[a-z]*f/i, why: 'deletes untracked files — ask first' },
  { re: /\bgit\s+(commit|push)\b.*--no-verify\b/i, why: 'skips hooks — fix the failing hook instead' },
  { re: /\b(DROP\s+(TABLE|DATABASE|SCHEMA)|TRUNCATE\s+TABLE)\b/i, why: 'destructive SQL' },
  { re: /\b(npm|pnpm|yarn)\s+publish\b/i, why: 'publishes a package — must be done by a human' },
  // Wisper-specific: whisper.cpp/ is gitignored (1.3 GB build + models), so git can't restore it.
  { re: /\b(rm\s+-[a-z]*r|Remove-Item\b|rmdir\b|rd\b|del\b)[^|;&]*\bwhisper\.cpp\b/i, why: 'deletes the gitignored whisper.cpp build/models — git cannot restore them' },
];

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
  process.exit(0);
}

const command = String(input.tool_input?.command ?? '');
if (!command) process.exit(0);

const hit = RULES.find(({ re }) => re.test(command));
if (hit) {
  process.stderr.write(
    `Blocked by .claude/hooks/guard-shell.mjs (${hit.why}). Command: ${command.slice(0, 200)}\n` +
      'Use a safer alternative, or stop and ask the user to run it themselves.\n',
  );
  process.exit(2);
}

process.exit(0);
