"""Ear channels (spec _docs/specs/2026-10-15-ear-channels.md): hear each app in the left ear, the right
ear or both, through Windows' per-app channel volumes. No audio passes through Wisper.

C1: the pure core, no COM. `gains` is the §3.2 rule, `Selection` one ear's choice (rule 3.2.5),
`menu_items` the rows of one ear's menu (rule 3.2.7), `Journal` the restore file of §5.4: the
volumes each session had **before** Wisper's first change, so a crash can't leave them changed
(Windows remembers them, §4.2). Volumes are floats 0..1.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

ALL = "*all*"  # the "All apps (default)" choice; never a real app key (keys are exe paths)
ALL_LABEL = "All apps (default)"
NOT_RUNNING = " (not running)"
JOURNAL_NAME = "ear-channels-restore.json"


def _clamp(v):
    return min(1.0, max(0.0, float(v)))


@dataclass(frozen=True)
class Selection:
    """One ear's choice: All apps (no keys) or a set of app keys. Immutable, so it can be put on the
    router's queue as is; `toggle` and `choose_all` return a new one."""

    keys: frozenset[str] = frozenset()

    @property
    def is_all(self):
        return not self.keys

    def includes(self, key):
        return self.is_all or key in self.keys

    def toggle(self, key):
        """Rule 3.2.5: checking an app unchecks All apps, checking All apps unchecks the apps,
        unchecking the last app checks All apps again."""
        if key == ALL:
            return self.choose_all()
        return Selection(self.keys ^ {key})

    def choose_all(self):
        return Selection()


class App(NamedTuple):
    key: str      # exe path, lower case (§4.4)
    name: str     # what the menus show
    running: bool  # False: gone, but kept because an ear has it checked (rule 3.2.7)


class MenuItem(NamedTuple):
    key: str      # an App key, or ALL
    label: str
    checked: bool


def gains(app, left, right, left_vol, right_vol, app_vol=1.0):
    """§3.2: `app`'s (left, right) channel volumes. An ear plays the app at the ear's volume times the
    app's volume if it is All apps or has the app checked, else not at all (D4)."""
    a = _clamp(app_vol)
    return (_clamp(left_vol) * a if left.includes(app) else 0.0,
            _clamp(right_vol) * a if right.includes(app) else 0.0)


def untouched(left, right, left_vol, right_vol, app_vols):
    """Rule 3.2.1: both ears All apps and every volume 100 %. Then Wisper changes nothing and puts back
    what it changed (§5.4). `app_vols` is {key: volume} of the apps the user set."""
    return (left.is_all and right.is_all and _clamp(left_vol) == 1.0 and _clamp(right_vol) == 1.0
            and all(_clamp(v) == 1.0 for v in app_vols.values()))


def menu_items(apps, selection):
    """The rows of one ear's menu: All apps, a separator (None), then the apps sorted by name. A gone
    app stays while this ear has it checked, as "Name (not running)"; an unchecked gone one is left out."""
    rows: list[MenuItem | None] = [MenuItem(ALL, ALL_LABEL, selection.is_all), None]
    for app in sorted(apps, key=lambda a: (a.name.casefold(), a.key)):
        checked = app.key in selection.keys
        if app.running:
            rows.append(MenuItem(app.key, app.name, checked))
        elif checked:
            rows.append(MenuItem(app.key, app.name + NOT_RUNNING, True))
    return rows


def silent(apps, left, right):
    """Rule 3.2.2: names of the running apps that play in neither ear (the status line names them)."""
    return [a.name for a in sorted(apps, key=lambda a: a.name.casefold())
            if a.running and not left.includes(a.key) and not right.includes(a.key)]


def journal_path():
    """%LOCALAPPDATA%\\Wisper\\ear-channels-restore.json (D6): outside the repo, survives a crash."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Wisper" / JOURNAL_NAME


class Journal:
    """{session identifier: [left, right]} of the volumes a session had before Wisper's first change.
    Written before each change (`remember`), so a crash between the write and the change only restores
    what was already there. Every write is atomic (temp file + os.replace): a crash in the middle leaves
    the old file. The file is removed once empty. Not thread safe: the ear-channels thread only."""

    def __init__(self, path):
        self.path = Path(path)
        self._entries = self._load()

    def _load(self):
        """A missing file is an empty journal. A file that can't be read (locked, no access) raises, so it is
        never overwritten. A damaged one is moved aside to `<name>.bad` first, for the same reason."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            os.replace(self.path, self.path.with_name(self.path.name + ".bad"))
            return {}
        entries = {}
        for ident, vols in data.items():
            if (isinstance(vols, list) and len(vols) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vols)):
                entries[ident] = (_clamp(vols[0]), _clamp(vols[1]))
        return entries

    def entries(self):
        return dict(self._entries)

    def __contains__(self, ident):
        return ident in self._entries

    def remember(self, ident, left, right):
        """Keep the first volumes seen for `ident`; later calls don't overwrite them."""
        if ident in self._entries:
            return
        self._entries[ident] = (_clamp(left), _clamp(right))
        try:
            self._write()
        except OSError:
            del self._entries[ident]
            raise

    def forget(self, ident):
        if ident not in self._entries:
            return
        old = self._entries.pop(ident)
        try:
            self._write()
        except OSError:
            self._entries[ident] = old
            raise

    def _write(self):
        if not self._entries:
            self.path.unlink(missing_ok=True)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({k: list(v) for k, v in self._entries.items()}, f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
