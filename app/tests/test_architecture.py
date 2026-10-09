"""Import boundaries from _docs/architecture-overview.md ("Layers and allowed imports").

app.py is the only module that wires the others together; capture, audio_io,
whisper_native, priority, tts and playback are independent leaves; nothing imports the legacy
live_transcriber.py. Each failure message says how to fix the violation.
"""

import ast
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
PROJECT_MODULES = {"app", "capture", "audio_io", "whisper_native", "priority", "tts", "playback", "live_transcriber"}
LEAVES = {"capture", "audio_io", "whisper_native", "priority", "tts", "playback"}

ALLOWED = {
    "app": LEAVES,
    **{leaf: set() for leaf in LEAVES},
}

FIX = {
    "app": "app.py may import only capture, audio_io, whisper_native, priority, tts and playback. "
    "Move the code you need out of live_transcriber.py into one of those modules.",
    "leaf": "Leaf modules must stay independent. Pass what you need in from app.py "
    "(a callback or an argument), or move the shared code into the module that owns it.",
}


def project_imports(module):
    tree = ast.parse((APP_DIR / f"{module}.py").read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        found.update(n.split(".")[0] for n in names if n.split(".")[0] in PROJECT_MODULES)
    return found


@pytest.mark.parametrize("module", sorted(ALLOWED))
def test_imports_follow_the_layer_table(module):
    illegal = project_imports(module) - ALLOWED[module]
    fix = FIX["app"] if module == "app" else FIX["leaf"]
    assert not illegal, (
        f"{module}.py imports {sorted(illegal)}, which _docs/architecture-overview.md forbids. {fix}"
    )


def test_every_module_is_classified():
    on_disk = {p.stem for p in APP_DIR.glob("*.py")}
    unknown = on_disk - PROJECT_MODULES
    assert not unknown, (
        f"New module(s) {sorted(unknown)} aren't in the layer table. Add them to "
        "_docs/architecture-overview.md and to ALLOWED/PROJECT_MODULES in this test."
    )
