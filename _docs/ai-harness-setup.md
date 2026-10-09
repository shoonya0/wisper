# AI harness setup log

This is the setup agent's record and resume point. If the setup is interrupted, start
the agent again with the same prompt and it continues from the first step that isn't
DONE or SKIPPED.

| Field | Value |
|---|---|
| Started | 2026-10-07 |
| Target | `D:\projects\wisper` |
| Playbook | `D:\projects\wisper\stepsForCreatingApp` (removed from Wisper 2026-10-07; its edits were merged into `D:\projects\stepsForCreatingApp`) |
| OS / shell | `win32` (x64, Windows 11) / Bash (Git Bash) |
| Mode | EXISTING+AI (merge: keep `.claude/skills/optimized-app-research`) |
| Stack | Python 3.14 (Tkinter, ctypes → whisper.dll); whisper.cpp (C/C++, Vulkan) is an upstream clone, not project code |
| Platforms (CI matrix) | Windows desktop → `windows-latest` |
| Depth | Full |
| Methodology plugin | none (playbook loop) |
| Hosting | GitHub (`gh` not installed yet) |
| Setup branch | `chore/ai-harness` (from `master` @ `b48a3ff`) |
| Verify command | `node tools/verify.mjs` (`--full` for CI) |

Status values: `TODO` · `DONE` · `SKIPPED` (with consequence) · `DEFERRED` (with
re-enable condition) · `BLOCKED` (with reason)

## Tools

| Tool | Needed? | Status | Version / evidence | Who installed |
|---|---|---|---|---|
| git | yes | DONE | 2.55.0.windows.3 | pre-installed |
| node ≥ 20 | yes | DONE | v24.19.0 | pre-installed |
| gh (+ auth) | yes (GitHub) | DONE | `gh --version` → 2.102.0; `gh auth status` → logged in as shoonya0 (scopes repo, workflow) | agent (winget, user OK); auth by user |
| uv / pipx / pip | no | SKIPPED | code-review-graph already installed; venv pip used for dev tools | — |
| code-review-graph | yes | DONE | 2.3.9 | pre-installed |
| agent-browser (+ Chrome) | no | SKIPPED | Tkinter UI, no web renderer → UI verification is manual | — |
| stack toolchain | yes | DONE | app/.venv Python 3.12.10; ruff 0.16.10, pytest 9.1.1, pyright 1.1.414, pre-commit 4.6.2 (`app/requirements-dev.txt`); import-linter 2.15 installed but unused (needs packages) | agent (pip, user OK) |

## Steps

| ID | Step | Status | Evidence (command → result) / decision |
|---|---|---|---|
| P1 | Target confirmed | DONE | session cwd `D:\projects\wisper`; user asked to set up "current project" |
| P2 | Platform + Node | DONE | `node -p ...` → win32 x64 node v24.19.0; git 2.55.0.windows.3 |
| P3 | Project inspected | DONE | inspect-project.mjs → git repo, 0 commits, all untracked; AI artifacts: .claude/skills, graph cache; no CI/pre-commit/env files |
| P4 | Mode chosen | DONE | EXISTING+AI: existing files are restructured, not deleted (user) |
| P5 | Scope answers | DONE | Windows desktop · Full · none · GitHub |
| P6 | Setup log created | DONE | this file (in `_docs/`, per user) |
| T1–T8 | Tools (see table) | DONE | check-tools.mjs: gh missing → installed; `claude doctor` not run (interactive); marketplaces incl. claude-plugins-official present |
| N1 / E1 | Git + safety (branch) | DONE | 0 commits → baseline `b48a3ff` (author shoonya0 only, per user) → `git switch -c chore/ai-harness`; `.gitignore` += `/whisper.cpp/`, `/stepsForCreatingApp/` |
| N2 / E2 | Vision interview / secrets check | DONE | staged file names + diff grep → no secret files, no key-like strings |
| N3 / E3 | Stack ADR / graph build | DONE | `code-review-graph build` → 6 files, 85 nodes, 644 edges (python only) |
| N4 / E4 | Architecture doc + review / architecture tour | DONE | architecture/large-functions/flows + reading entry points; 6 communities, 17 flows |
| N5 / E5 | Roadmap + test plans / architecture-overview + current-state | DONE | `_docs/README.md`, `architecture-overview.md`, `current-state.md`, `performance.md`; root README restructured to short entry point (all facts moved); one root `_docs/` (small project) |
| N6 / E6 | Scaffold + deps / checks found | DONE | none existed (no tests, lint, CI, scripts) |
| — / E7 | Baseline at `<sha>` | DONE | at `b48a3ff`: ruff 3× I001 (+8 E501 at width 100 → width set to 120 to match code), pyright 1 error in legacy `live_transcriber.py:245`, no tests |
| — / E8 | Verify command | DONE | `tools/verify.mjs` (not `scripts/`: `/scripts/` is gitignored). Imports sorted in `a1dc6b3`, legacy excluded from pyright → `verify passed (3 steps)` |
| — / E9 | Characterization tests | DONE | `app/tests/` 25 tests incl. TODO-pinned known issues 1–2; import-boundary test replaces import-linter |
| H1 | .gitignore + .claude tracking | DONE | appended AI-harness local-state block (+ .pytest_cache, .ruff_cache); `git check-ignore` → settings.json/hooks/skills/agents NOT ignored, local files ignored |
| H2 | Verify command | DONE | `node tools/verify.mjs` → verify passed (3 steps); `--full` = same (no formatter by choice) |
| H3 | Hook scripts copied, adapted, stdin-tested | DONE | protect-files (+ whisper.cpp/, app/.venv/, *.bin, __pycache__; − migrations), guard-shell (+ deleting whisper.cpp), stop-verify. 8/8 Node stdin cases + stop-verify exit 0. format-on-edit SKIPPED (no formatter); graph-update SKIPPED (user-level ~/.claude/settings.json already runs `code-review-graph update`) |
| H4 | .claude/settings.json | DONE | new file, exec-form hooks: SessionStart (prints current-state), PreToolUse protect+guard, Stop verify; env CLAUDE_VERIFY_CMD; JSON parses |
| H5 | Skills + reviewer agent | DONE | verify-change (Wisper rungs: fast / engine smoke / binding smoke / manual app), close-increment (no AI trailer, `_docs/status/<YYYY-MM>.md`), code-reviewer (threading + ctypes-struct checks). Existing `optimized-app-research` kept, linked from CLAUDE.md |
| H6 | CLAUDE.md | DONE | 64 lines; every command run in this setup (verify, single pytest) |
| H7 | Docs skeleton | DONE | done in E5; 51 links/paths + 9 file:line refs checked → all resolve |
| H8 | Formatter + linter | DONE | ruff check (E,F,W,I,B,UP; width 120) → 0 findings. Formatter SKIPPED by user (keeps hand-aligned style) |
| H9 | Architecture rules | DONE | import-linter can't handle top-level modules → `app/tests/test_architecture.py` (AST). Probe: illegal `import capture` in priority.py → fails with fix message; file restored via git |
| H10 | Pre-commit | DONE | `.pre-commit-config.yaml` (verify + advisory graph detect-changes); `pre-commit install`; `run --all-files` → Passed |
| H11 | CI | DONE | `.github/workflows/verify.yml`: windows-latest, py3.12, node 22, `verify --full`; branches [master, main]; YAML parses. First run 2026-10-09 (`workflow_dispatch` on `chore/ai-harness`, run 37918351584) → verify passed, 28 passed + 1 skipped (the minimum-window-size layout test skips on the narrower runner screen, by design) |
| H12 | Plugins | DONE | context7 + security-guidance @claude-plugins-official, scope project, enabled=true. Cost: context7 = 1 MCP server (schemas at runtime), security-guidance = 5 hooks (no model context). pyright-lsp DEFERRED (needs global pyright-langserver) |
| H13 | code-review-graph MCP | DONE | `install --platform claude-code --no-instructions --no-hooks --no-skills` (CLAUDE.md/.gitignore unchanged, diffed); `.mcp.json` rewritten to portable `code-review-graph serve`; `claude mcp list` → Pending approval |
| H14 | Agent UI access | SKIPPED | Tkinter native UI: no agent UI access; 'UI verification is manual' in CLAUDE.md + verify-change |
| H15 | Optional extras | DEFERRED | `/install-github-app` needs `gh auth login` + repo admin (user); PR template; offered in handoff |
| V1 | Restart | DONE | new session 2026-10-07; SessionStart hook printed current-state.md; gh on PATH (`gh --version` → 2.102.0) |
| V2 | Registration checks | DONE | session lists skills verify-change/close-increment/optimized-app-research + agent code-reviewer; `claude mcp list` → code-review-graph ✔ Connected, context7 ! Needs authentication; `claude plugin list` → context7 + security-guidance enabled (project) |
| V3 | Live probes | DONE | 1 protect: Write `probe-hook.bin` → blocked by protect-files.mjs. 2 guard: a `git reset` with a bogus flag → blocked by guard-shell.mjs (2026-10-09). 3 format: SKIPPED (no formatter). 4 graph MCP: `list_graph_stats` → 85 nodes, 644 edges, head matches build. 5 `/verify-change` → rung 1 pass, 25/25 pytest. 6 Stop hook: no "Verification failed" block after turns that edited `_docs/`. 7 UI: SKIPPED (H14) |
| V4 | Context budget | DONE | CLAUDE.md 64 lines / 488 words (~0.7k tokens, under 3k). Project skills: 3 (close-increment has `disable-model-invocation: true`; verify-change and optimized-app-research have no side effects). Unused by this project, user-scope: `postman` MCP (~40 deferred tools) and `vibe-prospecting` plugin → suggest disabling for this project via `/mcp` and `/plugin` |
| V5 | Log finalized | DONE | this file |
| V6 | Completion report | DONE | below |
| V7 | Commit / first task | TODO | |

## Test baseline (EXISTING)

At `a1dc6b3` + harness tests:

| Command | Duration | Result | Failing tests (by name) |
|---|---|---|---|
| `node tools/verify.mjs` | 6.1 s | pass | none (25/25 pytest) |

## Decisions made by the user

- Don't delete existing README/AI files. Restructure them into `_docs/` and keep the root README as a short entry point.
- All docs go in `_docs/` (not `docs/`). Large projects can have per-area `<area>/_docs/`. Wisper is small, so it gets one root `_docs/`.
- The `_docs/` convention was added to the playbook itself (agent/00-START.md rule 10 + §0.6, 01-preflight P6, 04-existing E5, all templates). Backup of the playbook before the change: session scratchpad.
- Full harness, GitHub hosting, Windows-only platform, no methodology plugin.
- Commits: author = git user only, no AI co-author trailer.
- Ignore `whisper.cpp/` and `stepsForCreatingApp/` in git.
- Baseline fix: sort imports (own commit `a1dc6b3`) + exclude legacy `live_transcriber.py` from pyright.
- No auto-formatter (keep hand-aligned style): no format hook, no format check.
- Plugins: agent's recommendation → context7 + security-guidance; pyright-lsp deferred (needs global pyright-langserver).

## Deferred items (and what re-enables them)

- pyright-lsp plugin: install a global `pyright-langserver` (e.g. `npm i -g pyright`) → then `claude plugin install pyright-lsp@claude-plugins-official --scope project`.
- `live_transcriber.py` excluded from pyright: re-include after open decision 1 (current-state.md).
- context7 shows "Needs authentication" in `claude mcp list`: authenticate via `/mcp` if lookups fail.

## Completion report

### Change summary

- Files added: `CLAUDE.md`, `_docs/` (README, current-state, architecture-overview,
  performance, this log), `.claude/settings.json`, `.claude/hooks/` (protect-files,
  guard-shell, stop-verify), `.claude/skills/verify-change`, `.claude/skills/close-increment`,
  `.claude/agents/code-reviewer.md`, `.mcp.json`, `.pre-commit-config.yaml`,
  `.github/workflows/verify.yml`, `pyproject.toml`, `tools/verify.mjs`,
  `app/requirements-dev.txt`, `app/tests/` (25 tests).
- Files changed: `.gitignore` (+ whisper.cpp, playbook, AI local state, caches),
  `README.md` (short entry point; details moved to `_docs/`). Earlier commit `a1dc6b3`: sorted imports.
- Harness pieces: verify command, 3 hooks + SessionStart, 2 skills + reviewer agent,
  architecture test, pre-commit, CI, code-review-graph MCP, plugins context7 + security-guidance.

### Validation

- Covered by automated checks: hook stdin tests (H3, 8/8), `node tools/verify.mjs` (H2,
  V3), JSON/YAML parse (H4, H11), architecture-rule probe (H9).
- Verified live in Claude Code on Windows 11: protect hook blocks, graph MCP connected
  (85 nodes), `/verify-change` evidence table, SessionStart output, Stop hook with no pending block.
- Verified later (2026-10-09): guard-shell live block; CI on GitHub (PRs #1, #2 and `master`).
- Not verified: macOS/Linux (Windows-only project, not run there).
- Requires user action: optional `/install-github-app`; context7 auth via `/mcp`.

### Commands executed (this session)

- `node tools/verify.mjs` → verify passed (3 steps), 25/25 pytest
- `gh auth status` → logged in as shoonya0; `claude mcp list`; `claude plugin list`

### Remaining risks / next steps

- `live_transcriber.py` is excluded from pyright (open decision 1 in current-state.md).
- Known issues 1–2 are pinned by TODO tests; they are the natural first tasks.
- CI branch filter is `[master, main]`. The base branch is `master` (user decision 2026-10-09: no `main`).
