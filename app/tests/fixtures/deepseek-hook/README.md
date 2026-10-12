# DeepSeek Stop-hook fixtures

Recorded by the P0 spike on 2026-10-12 (`_docs/specs/2026-10-12-deepseek-terminal.md` §7):
the JSON that Claude Code 2.1.296 (`deepseek`, model DeepSeek Flash) writes to a `Stop` hook's
stdin at the end of a turn. The user name in paths is replaced by `USER`. No keys or tokens.

| File | Turn | `last_assistant_message` |
|---|---|---|
| `stop-short-answer.json` | "My favourite colour is teal. Reply with just OK." | `OK` |
| `stop-answer-from-memory.json` | "What is my favourite colour?" (next turn) | `Teal.` |
| `stop-markdown-answer.json` | "List three fruits as a markdown bullet list…" | Markdown (`**Fruits**`, `- Apple`…), raw |

The hook doesn't fire for `/clear` or for a turn interrupted with Esc, so there's no
fixture for those: they narrate nothing.
