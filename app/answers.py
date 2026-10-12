"""DeepSeek's answers, read aloud (spec 2026-10-12-deepseek-terminal §4.4–4.5, P4).

Claude Code (`deepseek`) runs this file as its `Stop` hook at the end of every answered turn:
`python answers.py <port> <token>`, with the hook input as JSON on stdin. The script sends the
final reply (`last_assistant_message`) to Wisper's `Inbox`, a listener on 127.0.0.1 that
ignores anything without this run's token. `plain_text()` turns the reply's Markdown into
text Kokoro can read without saying the symbols.

A leaf: stdlib only. app.py starts the Inbox and builds the hook settings.
"""

import hmac
import json
import re
import secrets
import socket
import sys
import threading
from pathlib import Path

MAX_BYTES = 1 << 20          # an answer bigger than 1 MB is cut there
HOOK_TIMEOUT_S = 2.0         # the hook never holds up `deepseek` for longer than this


def extract_answer(hook_input):
    """The final reply in a Stop hook's input (JSON text), or "" when there's none."""
    try:
        data = json.loads(hook_input)
    except ValueError:
        return ""
    answer = data.get("last_assistant_message") if isinstance(data, dict) else None
    return answer if isinstance(answer, str) else ""


def hook_settings(python, script, port, token):
    """The `--settings` JSON for `deepseek`: one Stop hook that runs this script.

    Claude Code runs hook commands through Git Bash, so paths use forward slashes."""
    command = f'"{Path(python).as_posix()}" "{Path(script).as_posix()}" {port} {token}'
    return {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": command}]}]}}


# ---------------------------------------------------------------- Markdown → speech

# Line patterns use [ \t], not \s: \s would match the newline before the line too.
_FENCE      = re.compile(r"^[ \t]*(```|~~~).*(\n|$)", re.M)                  # the whole line goes
_RULE       = re.compile(r"^[ \t]*([-*_])([ \t]*\1){2,}[ \t]*(\n|$)", re.M)  # ---, ***, ___
_TABLE_RULE = re.compile(r"^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(\|[ \t]*:?-{3,}:?[ \t]*)*\|?[ \t]*(\n|$)", re.M)
_HEADING    = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.*?)[ \t]*#*[ \t]*$", re.M)
_QUOTE      = re.compile(r"^[ \t]*>[ \t]?", re.M)
_BULLET     = re.compile(r"^([ \t]*)[-*+][ \t]+(\[[ xX]\][ \t]+)?", re.M)
_IMAGE      = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK       = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_CODE       = re.compile(r"`([^`]*)`")
_BOLD       = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_ITALIC     = re.compile(r"(?<![\w*])([*_])(?=\S)(.+?)(?<=\S)\1(?![\w*])")
_STRIKE     = re.compile(r"~~(.+?)~~")
_END        = ".!?:;,…"


def _with_stop(line):
    """A heading or list item said on its own: add a full stop so Kokoro pauses after it."""
    line = line.rstrip()
    return line if not line or line[-1] in _END else line + "."


def plain_text(markdown):
    """Markdown → text to narrate: the marks go, the words stay.

    Bold, italics, headings, bullets, quotes, code fences and backticks, link and image
    targets and table rules are removed; table cells are joined with commas. Headings and
    list items end with a full stop, so each is said as its own sentence.
    """
    text = markdown.replace("\r\n", "\n")
    text = _FENCE.sub("", text)
    text = _TABLE_RULE.sub("", text)
    text = _RULE.sub("", text)
    text = _HEADING.sub(lambda m: _with_stop(m.group(1)), text)
    text = _QUOTE.sub("", text)
    text = _BULLET.sub(lambda m: "\0" + m.group(1), text)                # mark list items for the stop
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _CODE.sub(r"\1", text)
    text = _STRIKE.sub(r"\1", text)
    text = _BOLD.sub(r"\2", text)
    text = _ITALIC.sub(r"\2", text)
    lines = []
    for line in text.split("\n"):
        if "|" in line and line.strip().startswith("|"):                 # a table row
            line = ", ".join(c.strip() for c in line.strip().strip("|").split("|") if c.strip())
        if line.lstrip().startswith("\0"):
            line = _with_stop(line.replace("\0", "", 1).strip())
        lines.append(line.rstrip())
    text = "\n".join(lines).replace("\0", "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------- the listener

class Inbox:
    """Accepts answers on 127.0.0.1 from the hook; on_answer(text) runs on the listener thread.

    One message per connection: JSON {"token": ..., "text": ...}. A wrong token, bad JSON or a
    connection that sends nothing in time is dropped silently.
    """

    def __init__(self, on_answer):
        self.on_answer = on_answer
        self.token = secrets.token_hex(16)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, name="answers-inbox", daemon=True)
        self._thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:                      # close() closed the socket
                return
            with conn:
                try:
                    conn.settimeout(HOOK_TIMEOUT_S)
                    self._handle(_read_all(conn))
                except Exception:                # one bad connection never ends the listener
                    continue

    def _handle(self, raw):
        try:
            message = json.loads(raw.decode("utf-8"))
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        token, text = message.get("token"), message.get("text")
        if not isinstance(token, str) or not hmac.compare_digest(token, self.token):
            return
        if isinstance(text, str):
            self.on_answer(text)

    def close(self):
        self._sock.close()
        self._thread.join(timeout=1)


def _read_all(conn):
    chunks, size = [], 0
    while size < MAX_BYTES:
        chunk = conn.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)[:MAX_BYTES]


# ---------------------------------------------------------------- the hook

def send(port, token, text):
    """Send one answer to the Inbox. Returns False when Wisper isn't listening."""
    message = json.dumps({"token": token, "text": text}).encode("utf-8")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=HOOK_TIMEOUT_S) as conn:
            conn.sendall(message)
    except OSError:
        return False
    return True


def main(argv, stdin):
    """The Stop hook. Always exits 0 and prints nothing: a failure must never block `deepseek`."""
    try:
        port, token = int(argv[1]), argv[2]
        answer = extract_answer(stdin.buffer.read().decode("utf-8", "replace"))
        if answer.strip():
            send(port, token, answer)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv, sys.stdin))
