"""DeepSeek's answers: the hook input, Markdown → speech, the Inbox and the hook script (spec P4).

The hook inputs are the ones recorded in P0 (`fixtures/deepseek-hook/`). The Inbox and the hook
script run for real on 127.0.0.1; `deepseek` never runs.
"""

import io
import json
import queue
import socket
import subprocess
import sys
from pathlib import Path

import pytest

import answers

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "deepseek-hook"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- extract_answer

@pytest.mark.parametrize(("name", "answer"), [
    ("stop-short-answer.json", "OK"),
    ("stop-answer-from-memory.json", "Teal."),
    ("stop-markdown-answer.json", "**Fruits**\n\n- Apple\n- Banana\n- Cherry"),
])
def test_extract_answer_from_the_recorded_hook_inputs(name, answer):
    assert answers.extract_answer(fixture(name)) == answer


@pytest.mark.parametrize("hook_input", [
    "",                                                       # nothing on stdin
    "not json",
    "[1, 2]",
    json.dumps({"hook_event_name": "Stop"}),                  # the field is missing
    json.dumps({"last_assistant_message": None}),
    json.dumps({"last_assistant_message": 42}),
])
def test_extract_answer_gives_nothing_without_a_reply(hook_input):
    assert answers.extract_answer(hook_input) == ""


# ---------------------------------------------------------------- plain_text

@pytest.mark.parametrize(("markdown", "spoken"), [
    ("**Fruits**\n\n- Apple\n- Banana\n- Cherry", "Fruits\n\nApple.\nBanana.\nCherry."),   # the P0 answer
    ("Teal.", "Teal."),
    ("# Plan\nFirst *this*, then __that__.", "Plan.\nFirst this, then that."),
    ("## Done!", "Done!"),                                   # already ends a sentence
    ("1. One\n2. Two", "1. One\n2. Two"),                    # numbers are read out as they are
    ("* star item\n+ plus item", "star item.\nplus item."),
    ("- [x] tested\n- [ ] shipped", "tested.\nshipped."),
    ("See [the docs](https://example.com/x_y) and ![a cat](cat.png).", "See the docs and a cat."),
    ("Run `pip install` now.", "Run pip install now."),
    ("```python\nprint('hi')\n```", "print('hi')"),
    ("> quoted line", "quoted line"),
    ("above\n\n---\n\nbelow", "above\n\nbelow"),
    ("| Name | Age |\n|---|---:|\n| Ann | 30 |", "Name, Age\nAnn, 30"),
    ("~~old~~ new", "old new"),
    ("snake_case_name and 2 * 3 * 4", "snake_case_name and 2 * 3 * 4"),  # not italics
    ("a\n\n\n\nb", "a\n\nb"),
    ("Line one\r\nLine two", "Line one\nLine two"),
    ("", ""),
])
def test_plain_text(markdown, spoken):
    assert answers.plain_text(markdown) == spoken


# ---------------------------------------------------------------- hook settings

def test_hook_settings_run_this_script_with_the_port_and_token():
    settings = answers.hook_settings(r"C:\Py 3\python.exe", r"D:\w\app\answers.py", 50123, "abc")
    (stop,) = settings["hooks"]["Stop"]
    assert stop["hooks"] == [{"type": "command", "command": '"C:/Py 3/python.exe" "D:/w/app/answers.py" 50123 abc'}]


# ---------------------------------------------------------------- Inbox

@pytest.fixture
def inbox():
    got = queue.Queue()
    box = answers.Inbox(got.put)
    yield box, got
    box.close()


def raw_send(port, data):
    with socket.create_connection(("127.0.0.1", port), timeout=2) as conn:
        conn.sendall(data)


def test_inbox_takes_an_answer_with_the_token(inbox):
    box, got = inbox
    assert answers.send(box.port, box.token, "Teal. Café ✓")
    assert got.get(timeout=2) == "Teal. Café ✓"


def test_inbox_ignores_a_wrong_token_and_junk_then_still_works(inbox):
    box, got = inbox
    assert answers.send(box.port, "wrong", "spoofed")
    raw_send(box.port, b"not json")
    raw_send(box.port, json.dumps([box.token, "x"]).encode())
    raw_send(box.port, json.dumps({"token": box.token}).encode())         # no text
    assert answers.send(box.port, box.token, "real")
    assert got.get(timeout=2) == "real"                                     # the junk gave nothing
    assert got.empty()


def test_inbox_listens_on_localhost_only_with_a_fresh_token():
    a, b = answers.Inbox(lambda text: None), answers.Inbox(lambda text: None)
    try:
        assert a._sock.getsockname()[0] == "127.0.0.1"
        assert a.token != b.token and len(a.token) == 32
    finally:
        a.close()
        b.close()


def test_inbox_close_stops_the_listener():
    box = answers.Inbox(lambda text: None)
    box.close()
    assert not box._thread.is_alive()
    assert not answers.send(box.port, box.token, "late")                   # nobody listens


# ---------------------------------------------------------------- the hook script

def run_hook(port, token, stdin):
    script = Path(answers.__file__)
    return subprocess.run([sys.executable, str(script), str(port), token], input=stdin.encode("utf-8"),
                          capture_output=True, timeout=10)


def test_the_hook_script_sends_the_answer(inbox):
    box, got = inbox
    done = run_hook(box.port, box.token, fixture("stop-answer-from-memory.json"))
    assert (done.returncode, done.stdout, done.stderr) == (0, b"", b"")
    assert got.get(timeout=2) == "Teal."


def test_the_hook_script_never_fails_deepseek():
    with socket.socket() as s:                    # a port nobody listens on
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    done = run_hook(port, "t", fixture("stop-short-answer.json"))
    assert (done.returncode, done.stdout) == (0, b"")
    assert answers.main(["answers.py"], io.TextIOWrapper(io.BytesIO(b""))) == 0      # no arguments


def test_the_hook_sends_nothing_for_an_empty_answer(inbox):
    box, got = inbox
    run_hook(box.port, box.token, json.dumps({"last_assistant_message": "  "}))
    assert answers.send(box.port, box.token, "next")
    assert got.get(timeout=2) == "next"
