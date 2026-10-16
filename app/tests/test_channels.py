"""channels: ear channels (spec 2026-10-15-ear-channels). The pure core (§3.2, §5.1, §5.4; step C1) and the COM
layer (step C2: fast tests with a fake, one slow test on the real default output)."""

import inspect
import json
import os
import subprocess
import sys
import time

import comtypes
import pytest

import channels
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


# ---- C2: the COM layer ---------------------------------------------------------------------------------------------

class FakeAudio:
    """Stands in for WasapiAudio (same public methods): sessions on named devices, volumes kept in memory."""

    def __init__(self, device=("dev-1", "Speakers"), sessions=(), journal=None):
        self.device = device
        self.by_device = {device[0]: list(sessions)}
        self.calls = []
        self.fail: Exception | None = None  # an exception sessions() raises
        self.journal = journal    # when given, set() records whether the session was journaled first
        self.journaled_first = []

    def default_output(self):
        return self.device

    def sessions(self, device_id):
        if self.fail:
            raise self.fail
        return [channels.Session(s.key, s.name, s.pid, s.identifier, s.channels, s.state, s.volumes, handle=s)
                for s in self.by_device.get(device_id, [])]

    def get(self, session):
        return session.handle.volumes

    def set(self, session, left, right):
        if session.channels != 2:
            raise ValueError("not stereo")
        if self.journal is not None:
            self.journaled_first.append(session.identifier in self.journal)
        self.calls.append((session.identifier, left, right))
        session.handle.volumes = (left, right)

    def close(self):
        self.calls.append("close")


def public_methods(cls):
    return {n: list(inspect.signature(f).parameters) for n, f in vars(cls).items()
            if callable(f) and not n.startswith("_")}


def test_fake_audio_has_the_real_methods():  # so C3's router tests use the API the router really gets
    assert public_methods(FakeAudio) == public_methods(channels.WasapiAudio)


def test_fake_audio_set_and_get():
    s = channels.Session(DISCORD, "Discord", 7, ID_A, 2, channels.STATE_ACTIVE, (1.0, 1.0))
    audio = FakeAudio(sessions=[s])
    [listed] = audio.sessions("dev-1")
    audio.set(listed, 1.0, 0.0)
    assert audio.get(audio.sessions("dev-1")[0]) == (1.0, 0.0)
    mono = channels.Session(ZOOM, "Zoom", 8, ID_B, 1, channels.STATE_ACTIVE, (1.0,))
    with pytest.raises(ValueError):
        FakeAudio(sessions=[mono]).set(mono, 1.0, 0.0)


@pytest.mark.parametrize(("pid", "path", "system", "description", "expected"), [
    (0, "", True, "", (channels.SYSTEM_KEY, "System sounds")),
    (7, r"C:\Apps\Discord\Discord.exe", False, "Discord", (r"c:\apps\discord\discord.exe", "Discord")),
    (7, r"C:\Apps\Tool\tool.EXE", False, "", (r"c:\apps\tool\tool.exe", "tool")),  # no FileDescription
    (7, "", False, "", ("pid:7", "Process 7")),                                     # path can't be read
    (99, r"C:\Python312\python.exe", False, "Python", (r"c:\python312\python.exe", "Wisper (narration)")),
])
def test_describe_names_and_groups_apps_by_exe(pid, path, system, description, expected):  # §4.4
    assert channels.describe(pid, path, system, own_pid=99, description=description) == expected


def test_set_refuses_a_session_that_isnt_stereo():  # §5.3: a device with != 2 channels is left alone
    s = channels.Session(ZOOM, "Zoom", 8, ID_B, 6, channels.STATE_ACTIVE, (1.0,) * 6)
    with pytest.raises(ValueError, match="not stereo"):
        channels.WasapiAudio().set(s, 1.0, 0.0)


# The child plays silence on the default output and prints its own PID: the venv's python.exe is a launcher, so
# Popen.pid isn't the process that plays (C0, spec §4.1).
SILENCE = """
import os, sys, time
import pyaudiowpatch as pa
p = pa.PyAudio()
info = p.get_device_info_by_index(p.get_host_api_info_by_type(pa.paWASAPI)["defaultOutputDevice"])
ch, sr = int(info["maxOutputChannels"]), int(info["defaultSampleRate"])
s = p.open(format=pa.paFloat32, channels=ch, rate=sr, output=True, output_device_index=info["index"])
print(os.getpid(), flush=True)
end = time.time() + float(sys.argv[1])
while time.time() < end:
    s.write(bytes(4 * ch * sr // 20))
s.close()
p.terminate()
"""


def _play_silence(seconds):
    child = subprocess.Popen([sys.executable, "-c", SILENCE, str(seconds)], stdout=subprocess.PIPE, text=True)
    assert child.stdout is not None
    return child, int(child.stdout.readline())


def _wait_session(audio, device_id, pid, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        found = [s for s in audio.sessions(device_id) if s.pid == pid]
        if found:
            return found[0]
        time.sleep(0.1)
    raise AssertionError(f"no session for pid {pid}")


@pytest.fixture
def real_audio():
    audio = channels.WasapiAudio()
    try:
        device_id, _ = audio.default_output()
    except (comtypes.COMError, OSError) as e:
        pytest.skip(f"no default audio output: {e}")  # CI runners have no sound device
    return audio, device_id


@pytest.mark.slow
def test_wasapi_sets_reads_and_restores_a_childs_channel_volumes(real_audio):  # C2 done-when
    audio, device_id = real_audio
    child, pid = _play_silence(4)
    session, before = None, None
    try:
        session = _wait_session(audio, device_id, pid)
        before = session.volumes
        assert before == (1.0, 1.0), f"python.exe is remembered at {before}: reset it in Windows' Volume Mixer"
        assert session.channels == 2 and session.key.endswith("python.exe")
        assert session.identifier and session.state in (channels.STATE_INACTIVE, channels.STATE_ACTIVE)
        audio.set(session, 1.0, 0.0)
        assert audio.get(session) == (1.0, 0.0)
        assert _wait_session(audio, device_id, pid).volumes == (1.0, 0.0)  # a fresh listing sees it too
        audio.set(session, 1.0, 1.0)
        assert audio.get(session) == (1.0, 1.0)
    finally:
        try:
            if session is not None and before is not None and len(before) == 2:
                audio.set(session, *before)  # Windows remembers python.exe's volumes (§4.2): leave them as found
        finally:
            child.wait()
    time.sleep(0.5)
    child, pid = _play_silence(2)
    try:
        assert _wait_session(audio, device_id, pid).volumes == (1.0, 1.0)  # the restore outlived the process
    finally:
        child.wait()


# ---- C3: the router (§5.2, §5.4, rules 3.2.1-3.2.9) ---------------------------------------------------------------

def sess(key, name, ident, volumes=(1.0, 1.0), pid=1, chans=2):
    return channels.Session(key, name, pid, ident, chans, channels.STATE_ACTIVE, volumes)


def three():
    return [sess(DISCORD, "Discord", ID_A), sess(ZOOM, "Zoom Meetings", ID_B), sess(CHROME, "Google Chrome", ID_C)]


class Rig:
    """A router on FakeAudio, its journal in tmp_path, and what it reported."""

    def __init__(self, tmp_path, sessions=None, journal=None):
        self.path = tmp_path / "ear.json"
        if journal is not None:
            self.path.write_text(json.dumps(journal), encoding="utf-8")
        self.journal = Journal(self.path)
        self.audio = FakeAudio(sessions=three() if sessions is None else sessions, journal=self.journal)
        self.updates, self.errors = [], []
        self.router = channels.Router(self.audio, self.journal, lambda *a: self.updates.append(a), self.errors.append)

    def do(self, *cmd):
        self.router._command(cmd)
        self.router.step()

    def vols(self, device="dev-1"):
        return {s.identifier: s.volumes for s in self.audio.by_device[device]}


def test_router_start_up_changes_nothing(tmp_path):  # rule 3.2.1, D2
    rig = Rig(tmp_path)
    rig.router.step()
    rig.router.step()
    assert rig.audio.calls == []
    assert not rig.path.exists()
    [(device, apps, warnings)] = rig.updates  # once: the second step showed nothing new
    assert device == "Speakers" and warnings == []
    assert {a.name for a in apps} == {"Discord", "Google Chrome", "Zoom Meetings"}


def test_router_journals_each_session_before_changing_it(tmp_path):  # §5.2 step 2, rule 3.2.2
    rig = Rig(tmp_path, sessions=[sess(DISCORD, "Discord", ID_A, (0.8, 0.8)), sess(ZOOM, "Zoom Meetings", ID_B),
                                  sess(CHROME, "Google Chrome", ID_C)])
    rig.router._command(("choose", channels.LEFT, only(DISCORD)))
    rig.do("choose", channels.RIGHT, only(ZOOM))
    assert rig.vols() == {ID_A: (1.0, 0.0), ID_B: (0.0, 1.0), ID_C: (0.0, 0.0)}
    assert rig.audio.journaled_first == [True, True, True]
    assert Journal(rig.path).entries() == {ID_A: (0.8, 0.8), ID_B: (1.0, 1.0), ID_C: (1.0, 1.0)}
    assert rig.updates[-1][2] == ["Google Chrome plays in neither ear."]


def test_router_back_to_all_apps_restores_and_empties_the_journal(tmp_path):  # rule 3.2.1, §5.4
    rig = Rig(tmp_path, sessions=[sess(DISCORD, "Discord", ID_A, (0.8, 0.6)), sess(ZOOM, "Zoom Meetings", ID_B)])
    rig.do("choose", channels.LEFT, only(DISCORD))
    assert rig.vols() == {ID_A: (1.0, 1.0), ID_B: (0.0, 1.0)}  # rule 3.2.3: Right is still All apps
    rig.do("choose", channels.LEFT, Selection())
    assert rig.vols() == {ID_A: (0.8, 0.6), ID_B: (1.0, 1.0)}  # what each had before Wisper, not 100 %
    assert rig.journal.entries() == {} and not rig.path.exists()
    assert rig.router.applied == {}


def test_router_reapplies_only_what_a_command_changed(tmp_path):
    rig = Rig(tmp_path)
    rig.do("choose", channels.LEFT, only(DISCORD))
    rig.audio.calls.clear()
    rig.router.step()
    assert rig.audio.calls == []  # nothing changed: nothing set
    rig.do("volume", channels.LEFT, 0.5)
    assert rig.audio.calls == [(ID_A, 0.5, 1.0)]  # Zoom and Chrome are (0, 1) either way


def test_router_reapplies_volumes_someone_else_changed(tmp_path):  # §5.2: drift (an app, the Volume Mixer)
    rig = Rig(tmp_path)
    rig.do("choose", channels.LEFT, only(DISCORD))
    rig.audio.by_device["dev-1"][1].volumes = (1.0, 1.0)  # Zoom reset its own volumes
    rig.audio.calls.clear()
    rig.router.step()
    assert rig.audio.calls == [(ID_B, 0.0, 1.0)]
    assert rig.journal.entries()[ID_B] == (1.0, 1.0)  # the journal still has the volumes from before Wisper


def test_router_app_volume(tmp_path):  # D9
    rig = Rig(tmp_path)
    rig.router._command(("choose", channels.LEFT, only(DISCORD)))
    rig.do("app_volume", DISCORD, 0.5)
    assert rig.vols()[ID_A] == (0.5, 0.5)
    rig.do("volume", channels.RIGHT, 0.4)
    assert rig.vols()[ID_A] == pytest.approx((0.5, 0.2))
    assert rig.vols()[ID_B] == pytest.approx((0.0, 0.4))


def test_router_app_gone_and_back(tmp_path):  # rules 3.2.6, 3.2.7
    rig = Rig(tmp_path)
    rig.router._command(("choose", channels.LEFT, only(DISCORD)))
    rig.do("choose", channels.RIGHT, only(ZOOM))
    dev = rig.audio.by_device["dev-1"]
    discord = dev.pop(0)
    dev.pop()  # Chrome (unchecked) closes too
    rig.router.step()
    _, apps, _ = rig.updates[-1]
    assert App(DISCORD, "Discord", False) in apps           # checked: stays, "(not running)"
    assert all(a.key != CHROME for a in apps)               # unchecked: removed
    discord.volumes = (1.0, 0.0)                             # back; Windows remembered what Wisper set
    dev.append(discord)
    rig.audio.calls.clear()
    rig.router.step()
    assert rig.audio.calls == []
    assert App(DISCORD, "Discord", True) in rig.updates[-1][1]
    edge = sess(r"c:\edge\msedge.exe", "Microsoft Edge", "id-edge")
    dev.append(edge)                                        # a new app: listed unchecked, starts silent
    rig.router.step()
    assert edge.volumes == (0.0, 0.0)
    assert App(edge.key, "Microsoft Edge", True) in rig.updates[-1][1]
    assert rig.updates[-1][2] == ["Microsoft Edge plays in neither ear."]
    assert rig.router.left == only(DISCORD)                 # the selection didn't change


def test_router_device_change_restores_the_old_device_first(tmp_path):  # §5.3, §5.4
    rig = Rig(tmp_path)
    rig.router._command(("choose", channels.LEFT, only(DISCORD)))
    rig.do("choose", channels.RIGHT, only(ZOOM))
    new = [sess(DISCORD, "Discord", "dev2-discord")]
    rig.audio.by_device["dev-2"] = new
    rig.audio.device = ("dev-2", "Headphones")
    rig.router.step()
    assert rig.vols("dev-1") == {ID_A: (1.0, 1.0), ID_B: (1.0, 1.0), ID_C: (1.0, 1.0)}
    assert new[0].volumes == (1.0, 0.0)
    assert set(rig.journal.entries()) == {"dev2-discord"}
    assert rig.updates[-1][0] == "Headphones"


def test_router_leftover_journal_restores_each_session_when_it_appears(tmp_path):  # §5.4: after a crash
    dev = [sess(ZOOM, "Zoom Meetings", ID_B, (0.0, 1.0))]   # Windows remembered the crashed run's volumes
    rig = Rig(tmp_path, sessions=dev, journal={ID_A: [1.0, 1.0], ID_B: [0.9, 0.9]})
    dev = rig.audio.by_device["dev-1"]
    rig.router.step()
    assert dev[0].volumes == (0.9, 0.9)
    assert rig.journal.entries() == {ID_A: (1.0, 1.0)}      # Discord isn't running yet: kept
    dev.append(sess(DISCORD, "Discord", ID_A, (1.0, 0.0)))
    rig.router.step()
    assert dev[1].volumes == (1.0, 1.0)
    assert not rig.path.exists()


def test_router_leftover_journal_keeps_the_original_while_changing(tmp_path):
    dev = [sess(DISCORD, "Discord", ID_A, (1.0, 0.0))]      # left over from a crash: (1, 0) isn't the original
    rig = Rig(tmp_path, sessions=dev, journal={ID_A: [1.0, 1.0]})
    rig.do("choose", channels.LEFT, only(ZOOM))
    assert dev[0].volumes == (0.0, 1.0)
    assert rig.journal.entries() == {ID_A: (1.0, 1.0)}      # not overwritten with (1, 0)


def test_router_reset_restores_everything(tmp_path):
    rig = Rig(tmp_path)
    rig.router._command(("choose", channels.LEFT, only(DISCORD)))
    rig.router._command(("volume", channels.RIGHT, 0.3))
    rig.do("app_volume", ZOOM, 0.5)
    rig.do("reset")
    assert rig.vols() == {ID_A: (1.0, 1.0), ID_B: (1.0, 1.0), ID_C: (1.0, 1.0)}
    assert rig.router.untouched() and not rig.path.exists()


def test_router_device_not_stereo_changes_nothing(tmp_path):  # §5.3
    rig = Rig(tmp_path, sessions=[sess(DISCORD, "Discord", ID_A, (1.0,) * 6, chans=6)])
    rig.do("choose", channels.LEFT, only(DISCORD))
    assert rig.audio.calls == []
    assert rig.updates[-1][2] == [channels.NOT_STEREO]


def test_router_error_reported_once_restores_and_reset_retries(tmp_path):  # rule 3.2.9
    rig = Rig(tmp_path)
    rig.router._command(("choose", channels.LEFT, only(DISCORD)))
    rig.do("choose", channels.RIGHT, only(ZOOM))
    rig.audio.fail = OSError("device gone")
    rig.router.step()  # doesn't raise
    rig.router.step()
    assert rig.errors == ["device gone"]
    rig.audio.fail = None
    before = list(rig.audio.calls)
    rig.router.step()
    assert rig.router.stopped and rig.audio.calls == before  # stopped: changes nothing until Reset
    assert rig.vols()[ID_A] == (1.0, 0.0)                     # the restore failed too; the journal still has it
    assert ID_A in rig.journal
    rig.do("reset")
    assert not rig.router.stopped
    assert rig.vols() == {ID_A: (1.0, 1.0), ID_B: (1.0, 1.0), ID_C: (1.0, 1.0)} and not rig.path.exists()


def test_router_error_while_applying_restores_what_it_can(tmp_path):
    rig = Rig(tmp_path)
    real_set = rig.audio.set

    def set_fails_for_chrome(session, left, right):
        if session.identifier == ID_C and (left, right) == (0.0, 0.0):
            raise OSError("Chrome said no")
        real_set(session, left, right)
    rig.audio.set = set_fails_for_chrome
    rig.router._command(("choose", channels.LEFT, only(DISCORD)))
    rig.do("choose", channels.RIGHT, only(ZOOM))
    assert rig.errors == ["Chrome said no"]
    assert rig.vols() == {ID_A: (1.0, 1.0), ID_B: (1.0, 1.0), ID_C: (1.0, 1.0)}
    assert not rig.path.exists()


def test_router_restores_every_process_of_one_app(tmp_path):  # C3 review: the identifier has no pid (§4.1)
    sessions = [sess(DISCORD, "Discord", ID_A, (0.7, 0.7), pid=1), sess(DISCORD, "Discord", ID_A, (0.7, 0.7), pid=2),
                sess(ZOOM, "Zoom Meetings", ID_B)]
    rig = Rig(tmp_path, sessions=sessions)
    rig.do("choose", channels.LEFT, only(ZOOM))
    assert [s.volumes for s in rig.audio.by_device["dev-1"]] == [(0.0, 1.0), (0.0, 1.0), (1.0, 1.0)]
    rig.do("reset")
    assert [s.volumes for s in rig.audio.by_device["dev-1"]] == [(0.7, 0.7), (0.7, 0.7), (1.0, 1.0)]
    assert not rig.path.exists()


def test_router_a_mono_stream_doesnt_switch_the_strip_off(tmp_path):  # C3 review: channels are per stream
    rig = Rig(tmp_path)
    rig.router._command(("choose", channels.LEFT, only(DISCORD)))
    rig.do("choose", channels.RIGHT, only(ZOOM))
    mono = sess(r"c:\old\beeper.exe", "Beeper", "id-mono", (1.0,), chans=1)
    rig.audio.by_device["dev-1"].append(mono)
    rig.router.step()
    assert rig.updates[-1][2] != [channels.NOT_STEREO]
    assert rig.vols()[ID_A] == (1.0, 0.0) and mono.volumes == (1.0,)  # stereo apps still routed, the mono one alone
    rig.do("reset")
    assert {k: v for k, v in rig.vols().items() if k != "id-mono"} == {ID_A: (1.0, 1.0), ID_B: (1.0, 1.0),
                                                                        ID_C: (1.0, 1.0)}
    assert not rig.path.exists()


def test_router_bad_command_is_reported_not_fatal(tmp_path):  # C3 review: rule 3.2.9 for commands too
    rig = Rig(tmp_path)
    rig.router.poll_s = 0.01
    rig.router.start()
    try:
        rig.router.volume(channels.LEFT, "")  # what float() rejects
        end = time.time() + 2
        while not rig.errors and time.time() < end:
            time.sleep(0.01)
        assert len(rig.errors) == 1
        assert rig.router._thread is not None and rig.router._thread.is_alive()
        rig.router.reset()
        rig.router.choose(channels.LEFT, only(DISCORD))
        rig.router.choose(channels.RIGHT, only(ZOOM))
        while rig.vols()[ID_A] != (1.0, 0.0) and time.time() < end:
            time.sleep(0.01)
        assert rig.vols()[ID_A] == (1.0, 0.0)  # Reset brought it back
    finally:
        rig.router.close()


def test_neither_message():
    assert channels.neither_message([]) == ""
    assert channels.neither_message(["Chrome"]) == "Chrome plays in neither ear."
    assert channels.neither_message(["A", "B", "C"]) == "A, B and C play in neither ear."


def test_router_thread_applies_commands_and_close_restores(tmp_path):  # the real thread, FakeAudio
    rig = Rig(tmp_path)
    rig.router.poll_s = 0.01
    rig.router.start()
    try:
        rig.router.choose(channels.LEFT, only(DISCORD))
        rig.router.choose(channels.RIGHT, only(ZOOM))
        end = time.time() + 2
        while rig.vols()[ID_A] != (1.0, 0.0) and time.time() < end:
            time.sleep(0.01)
        assert rig.vols()[ID_A] == (1.0, 0.0)
    finally:
        rig.router.close()
    assert rig.router._thread is not None and not rig.router._thread.is_alive()
    assert rig.vols() == {ID_A: (1.0, 1.0), ID_B: (1.0, 1.0), ID_C: (1.0, 1.0)}
    assert not rig.path.exists()
    assert "close" in rig.audio.calls  # WasapiAudio.close() ran on the thread
