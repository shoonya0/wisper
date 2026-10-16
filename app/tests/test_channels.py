"""channels: the pure core of ear channels (spec 2026-10-15-ear-channels §3.2, §5.1, §5.4; step C1)."""

import json
import os

import pytest

from channels import (
    ALL,
    ALL_LABEL,
    App,
    Journal,
    MenuItem,
    Selection,
    gains,
    journal_path,
    menu_items,
    silent,
    untouched,
)

DISCORD = r"c:\users\u\appdata\local\discord\app-1.0\discord.exe"
ZOOM    = r"c:\program files\zoom\bin\zoom.exe"
CHROME  = r"c:\program files\google\chrome\application\chrome.exe"
WISPER  = r"c:\python312\python.exe"

APPS = [App(ZOOM, "Zoom Meetings", True), App(DISCORD, "Discord", True), App(CHROME, "Google Chrome", True)]


def only(*keys):
    return Selection(frozenset(keys))


# ---- §3.2: the rule ----------------------------------------------------------------------------------------------

def test_start_up_state_changes_nothing():  # rule 3.2.1
    left, right = Selection(), Selection()
    assert left.is_all and right.is_all
    assert untouched(left, right, 1.0, 1.0, {})
    assert all(gains(a.key, left, right, 1.0, 1.0) == (1.0, 1.0) for a in APPS)


def test_users_example_discord_left_zoom_right():  # rule 3.2.2
    left, right = only(DISCORD), only(ZOOM)
    assert gains(DISCORD, left, right, 1.0, 1.0) == (1.0, 0.0)
    assert gains(ZOOM, left, right, 1.0, 1.0) == (0.0, 1.0)
    assert gains(CHROME, left, right, 1.0, 1.0) == (0.0, 0.0)  # D4: neither ear → silent
    assert silent(APPS, left, right) == ["Google Chrome"]
    assert not untouched(left, right, 1.0, 1.0, {})


def test_one_app_left_all_apps_right():  # rule 3.2.3
    left, right = only(DISCORD), Selection()
    assert gains(DISCORD, left, right, 1.0, 1.0) == (1.0, 1.0)
    assert gains(ZOOM, left, right, 1.0, 1.0) == (0.0, 1.0)
    assert silent(APPS, left, right) == []


def test_same_app_in_both_ears_at_each_ears_volume():  # rule 3.2.4
    both = only(DISCORD)
    assert gains(DISCORD, both, both, 0.8, 0.4) == (0.8, 0.4)


def test_ear_volume_applies_to_all_apps_too():
    assert gains(ZOOM, Selection(), Selection(), 0.5, 1.0) == (0.5, 1.0)
    assert not untouched(Selection(), Selection(), 0.5, 1.0, {})


def test_app_volume_multiplies_the_ear_volume():  # D9
    left, right = only(DISCORD), Selection()
    assert gains(DISCORD, left, right, 0.5, 1.0, app_vol=0.6) == pytest.approx((0.3, 0.6))
    assert gains(ZOOM, left, right, 0.5, 1.0, app_vol=0.6) == pytest.approx((0.0, 0.6))
    assert not untouched(Selection(), Selection(), 1.0, 1.0, {DISCORD: 0.6})
    assert untouched(Selection(), Selection(), 1.0, 1.0, {DISCORD: 1.0})  # set back to 100 %: untouched again


def test_volumes_are_clamped_to_0_1():
    assert gains(ZOOM, Selection(), Selection(), 1.5, -0.2, app_vol=2.0) == (1.0, 0.0)


# ---- rule 3.2.5: Selection ---------------------------------------------------------------------------------------

def test_checking_an_app_unchecks_all_apps():
    s = Selection().toggle(DISCORD)
    assert not s.is_all and s.keys == {DISCORD}
    assert s.includes(DISCORD) and not s.includes(ZOOM)


def test_several_apps_per_ear():  # D5
    s = Selection().toggle(ZOOM).toggle(CHROME)
    assert s.keys == {ZOOM, CHROME}


def test_checking_all_apps_unchecks_the_apps():
    s = only(ZOOM, CHROME).toggle(ALL)
    assert s.is_all and s == Selection()


def test_unchecking_the_last_app_checks_all_apps_again():
    s = only(ZOOM, CHROME).toggle(ZOOM)
    assert s.keys == {CHROME}
    assert s.toggle(CHROME).is_all


def test_selection_is_immutable():
    s = only(ZOOM)
    s.toggle(DISCORD)
    assert s.keys == {ZOOM}


# ---- rules 3.2.6 / 3.2.7: menu rows ------------------------------------------------------------------------------

def test_menu_all_apps_then_separator_then_apps_by_name():
    rows = menu_items(APPS, Selection())
    assert rows[0] == MenuItem(ALL, ALL_LABEL, True)
    assert rows[1] is None
    assert [r.label for r in rows[2:] if r] == ["Discord", "Google Chrome", "Zoom Meetings"]
    assert not any(r.checked for r in rows[2:] if r)


def test_menu_shows_the_checked_apps():
    rows = menu_items(APPS, only(ZOOM))
    assert rows[0] == MenuItem(ALL, ALL_LABEL, False)
    assert [r.key for r in rows[2:] if r and r.checked] == [ZOOM]


def test_new_app_is_listed_unchecked_and_starts_silent():  # rule 3.2.6
    left, right = only(DISCORD), only(ZOOM)
    edge = App(r"c:\edge\msedge.exe", "Microsoft Edge", True)
    rows = menu_items([*APPS, edge], left)
    assert MenuItem(edge.key, "Microsoft Edge", False) in rows
    assert gains(edge.key, left, right, 1.0, 1.0) == (0.0, 0.0)
    assert "Microsoft Edge" in silent([*APPS, edge], left, right)


def test_checked_app_that_closed_stays_as_not_running():  # rule 3.2.7
    apps = [App(DISCORD, "Discord", False), App(ZOOM, "Zoom Meetings", True)]
    rows = menu_items(apps, only(DISCORD))
    assert MenuItem(DISCORD, "Discord (not running)", True) in rows
    assert silent(apps, Selection(), only(ZOOM)) == []  # a gone app isn't named in the status line


def test_unchecked_app_that_closed_is_removed():  # rule 3.2.7
    apps = [App(DISCORD, "Discord", False), App(ZOOM, "Zoom Meetings", True)]
    assert [r.key for r in menu_items(apps, only(ZOOM))[2:] if r] == [ZOOM]
    assert [r.key for r in menu_items(apps, Selection())[2:] if r] == [ZOOM]


def test_wisper_follows_the_same_rules():  # rule 3.2.8
    apps = [*APPS, App(WISPER, "Wisper (narration)", True)]
    assert gains(WISPER, only(DISCORD), only(ZOOM), 1.0, 1.0) == (0.0, 0.0)
    assert "Wisper (narration)" in [r.label for r in menu_items(apps, Selection())[2:] if r]


# ---- §5.4: the restore journal -----------------------------------------------------------------------------------

ID_A = r"{0.0.0.00000000}.{guid}|\Device\HarddiskVolume3\Discord.exe%b{00000000-0000-0000-0000-000000000000}"
ID_B = r"{0.0.0.00000000}.{guid}|\Device\HarddiskVolume3\Zoom.exe%b{00000000-0000-0000-0000-000000000000}"
ID_C = r"{0.0.0.00000000}.{guid}|\Device\HarddiskVolume3\chrome.exe%b{00000000-0000-0000-0000-000000000000}"


def test_journal_starts_empty_without_a_file(tmp_path):
    j = Journal(tmp_path / "x.json")
    assert j.entries() == {}
    assert not (tmp_path / "x.json").exists()


def test_journal_writes_and_reads_back(tmp_path):
    path = tmp_path / "Wisper" / "ear.json"  # the folder doesn't exist yet
    j = Journal(path)
    j.remember(ID_A, 1.0, 0.5)
    j.remember(ID_B, 0.25, 1.0)
    assert path.exists()
    assert Journal(path).entries() == {ID_A: (1.0, 0.5), ID_B: (0.25, 1.0)}  # a new run (after a crash) sees them


def test_journal_keeps_the_volumes_from_before_the_first_change(tmp_path):
    j = Journal(tmp_path / "ear.json")
    j.remember(ID_A, 1.0, 1.0)
    j.remember(ID_A, 0.0, 1.0)  # Wisper's own later change must not replace the original
    assert ID_A in j
    assert Journal(tmp_path / "ear.json").entries() == {ID_A: (1.0, 1.0)}


def test_journal_forget_and_file_removed_when_empty(tmp_path):
    path = tmp_path / "ear.json"
    j = Journal(path)
    j.remember(ID_A, 1.0, 1.0)
    j.remember(ID_B, 1.0, 1.0)
    j.forget(ID_A)
    assert Journal(path).entries() == {ID_B: (1.0, 1.0)}
    j.forget(ID_B)
    j.forget(ID_B)  # twice is fine
    assert not path.exists()
    assert j.entries() == {}


def test_journal_crash_in_the_middle_leaves_the_old_file(tmp_path, monkeypatch):
    path = tmp_path / "ear.json"
    j = Journal(path)
    j.remember(ID_A, 1.0, 1.0)
    j.remember(ID_B, 1.0, 0.5)  # two entries, so forget(ID_A) below rewrites the file instead of removing it
    before = path.read_bytes()

    def crash(src, dst):
        raise OSError("disk gone")
    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError):
        j.remember(ID_C, 0.5, 0.5)
    assert path.read_bytes() == before
    assert ID_C not in j  # memory matches the file, so the next remember tries again
    with pytest.raises(OSError):
        j.forget(ID_A)
    assert ID_A in j
    monkeypatch.undo()
    assert Journal(path).entries() == {ID_A: (1.0, 1.0), ID_B: (1.0, 0.5)}


@pytest.mark.parametrize("damaged", ["{not json", "[1, 2]"])
def test_journal_moves_a_damaged_file_aside_before_writing(tmp_path, damaged):
    path = tmp_path / "ear.json"
    path.write_text(damaged, encoding="utf-8")
    j = Journal(path)
    assert j.entries() == {}
    j.remember(ID_A, 1.0, 1.0)
    assert (tmp_path / "ear.json.bad").read_text(encoding="utf-8") == damaged  # kept for a person to look at
    assert Journal(path).entries() == {ID_A: (1.0, 1.0)}


def test_journal_that_cant_be_read_raises_and_is_left_alone(tmp_path, monkeypatch):
    path = tmp_path / "ear.json"
    path.write_text(json.dumps({ID_A: [1.0, 0.0]}), encoding="utf-8")
    before = path.read_bytes()

    def locked(self, *args, **kwargs):
        raise PermissionError("locked by another process")
    monkeypatch.setattr(type(path), "read_text", locked)
    with pytest.raises(PermissionError):
        Journal(path)  # not an empty journal that the next remember() would write over
    monkeypatch.undo()
    assert path.read_bytes() == before


def test_journal_failed_remove_of_the_last_entry_keeps_it(tmp_path, monkeypatch):
    path = tmp_path / "ear.json"
    j = Journal(path)
    j.remember(ID_A, 1.0, 0.5)

    def locked(self, *args, **kwargs):
        raise PermissionError("locked")
    monkeypatch.setattr(type(path), "unlink", locked)
    with pytest.raises(PermissionError):
        j.forget(ID_A)
    assert ID_A in j
    monkeypatch.undo()
    assert Journal(path).entries() == {ID_A: (1.0, 0.5)}


def test_journal_drops_bad_entries_and_clamps(tmp_path):
    path = tmp_path / "ear.json"
    path.write_text(json.dumps({ID_A: [1.5, -1], ID_B: [1], "c": "x", "d": [True, 1.0]}), encoding="utf-8")
    assert Journal(path).entries() == {ID_A: (1.0, 0.0)}


def test_journal_path_is_in_local_app_data(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert journal_path() == tmp_path / "Wisper" / "ear-channels-restore.json"
