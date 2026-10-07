---
name: close-increment
description: Close out a finished increment by updating the phase status doc and current-state, recording lessons, writing the completion report, and making an atomic commit. Invoke manually after /verify-change and review pass.
disable-model-invocation: true
---

# Close increment

Run this only after `/verify-change` passed and review findings were addressed. `$ARGUMENTS`
may name the increment, e.g. `overlap-trim`.

## 1. Confirm the gate

- `/verify-change` evidence exists from **this** state of the tree. If anything changed since,
  rerun `/verify-change`.
- Every acceptance criterion in the spec is marked PASS with evidence.

## 2. Update the docs (same commit as the code)

1. `_docs/status/<YYYY-MM>.md` (Wisper has no roadmap phases yet; one status file per
   month): add or complete the increment section:
   - **Problem**: one or two sentences.
   - **Change**: files and modules, and behavior before vs after.
   - **Tests**: what was added, with suite names and counts.
   - **Evidence**: the verification table from `/verify-change`.
   - **Commit**: write `<pending>`. Fill in the hash after committing, in the next
     increment's commit or with a follow-up amend if the project allows it.
2. `_docs/current-state.md`: update only if the project's state changed (phase status,
   open decisions, baseline, next task). Update the snapshot SHA and date.
3. If a doc you read during this work turned out to be **wrong**, fix it now and name
   it in the report.

## 3. Lessons

Did a mistake happen that will happen again (a wrong command, a missed convention,
the wrong layer)?

- If yes, add **one** concise line to CLAUDE.md, *or* propose a hook if it must never
  happen, *or* a path rule in `.claude/rules/` if it only applies to some files.
- If no, change nothing. Don't add generic advice.

## 4. Completion report

```markdown
### Change summary
- Files changed / behavior changed / modules affected

### Validation
- Covered by automated tests: …
- Verified by agent UI check: …
- Tested physically on <OS/device>: …
- Reviewed but not executed: …
- Requires physical verification on <OS/device>: …

### Commands executed
- `…` → result

### Remaining risks
- …
```

## 5. Commit

- Stage **only** the files changed for this increment (`git add <paths>`, never
  `git add -A` blindly). Check with `git diff --cached --stat`.
- Message: `<type>(<scope>): <what>`, a blank line, then *why*. **No AI co-author or
  "Generated with" trailer**: in this repo, commits are authored by the git user only.
- Ask before committing.
- Don't push or open a PR unless the user asked to. If asked, put the completion report
  in the PR body.
