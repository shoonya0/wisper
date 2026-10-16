"""The ear channels strip (spec 2026-10-15-ear-channels §3.1, §3.2, §5.5; step C4) with a fake router.

The real Tk window (invisible, conftest.make_window); FakeRouter records what the strip asks for and plays the
router thread's updates and errors. No audio device and no real journal: the one test with a real
channels.Router (the start-up replay) gives it test_channels.FakeAudio and a journal in tmp_path.
"""

import json
import time

import pytest
from conftest import FakeRouter, pump
from test_channels import FakeAudio

import app
import channels
from channels import ALL_LABEL, LEFT, RIGHT, App, Selection

DISCORD = r"c:\apps\discord\discord.exe"
ZOOM    = r"c:\program files\zoom\bin\zoom.exe"
CHROME  = r"c:\program files\google\chrome\application\chrome.exe"
APPS = [App(DISCORD, "Discord", True), App(ZOOM, "Zoom Meetings", True), App(CHROME, "Google Chrome", True)]


def router():
    r = FakeRouter.last
    assert r is not None
    return r


def rows(win, side):
    """(label, checked) of each menu row; None for the separator."""
    menu = win.ear_menus[side]
    out = []
    for i in range(menu.index("end") + 1):
        if menu.type(i) == "separator":
            out.append(None)
        else:
            out.append((menu.entrycget(i, "label"), bool(win.root.getvar(menu.entrycget(i, "variable")))))
    return out


def click(win, side, label):
    menu = win.ear_menus[side]
    for i in range(menu.index("end") + 1):
        if menu.type(i) != "separator" and menu.entrycget(i, "label") == label:
            menu.invoke(i)
            return
    raise AssertionError(f"no {label!r} in the {side} menu: {rows(win, side)}")


def updated(win, apps=APPS, warnings=(), device="Speakers (High Definition Audio Device)"):
    router().update(device, apps, warnings)
    pump(win, lambda: win.ear_results.empty())
    win.root.update()


def test_start_up_state(window):  # D2: All apps, 100 %, the router started
    assert router().calls == [("start",)]
    for side in (LEFT, RIGHT):
        assert window.ear_buttons[side].cget("text") == ALL_LABEL
        assert window.ear_scales[side].get() == 100 and window.ear_vol_vars[side].get() == "100 %"
        assert rows(window, side) == [(ALL_LABEL, True), None]
    assert window.ear_status_var.get() == ""
    assert window.ear_device_var.get() == "Earphones: …"


def test_update_fills_the_menus_and_the_device(window):  # rule 3.2.6
    updated(window)
    assert window.ear_device_var.get() == "Earphones: Speakers (High Definition Audio Device)"
    for side in (LEFT, RIGHT):
        assert rows(window, side) == [(ALL_LABEL, True), None, ("Discord", False), ("Google Chrome", False),
                                      ("Zoom Meetings", False)]
    assert list(window.ear_app_box.cget("values")) == ["Discord", "Google Chrome", "Zoom Meetings"]


def test_choosing_apps_follows_rule_3_2_5(window):
    updated(window)
    click(window, LEFT, "Discord")
    assert router().calls[-1] == ("choose", LEFT, Selection(frozenset({DISCORD})))
    assert window.ear_buttons[LEFT].cget("text") == "Discord"
    assert rows(window, LEFT)[0] == (ALL_LABEL, False) and ("Discord", True) in rows(window, LEFT)
    assert window.ear_buttons[RIGHT].cget("text") == ALL_LABEL           # the other ear doesn't change
    click(window, LEFT, "Zoom Meetings")                                 # D5: several apps per ear
    assert window.ear_buttons[LEFT].cget("text") == "Discord, Zoom Meetings"
    click(window, LEFT, ALL_LABEL)                                       # All apps unchecks the apps
    assert router().calls[-1] == ("choose", LEFT, Selection())
    assert rows(window, LEFT)[0] == (ALL_LABEL, True)
    click(window, RIGHT, "Zoom Meetings")
    click(window, RIGHT, "Zoom Meetings")                                # unchecking the last app: All apps
    assert router().calls[-1] == ("choose", RIGHT, Selection())
    assert window.ear_buttons[RIGHT].cget("text") == ALL_LABEL


def test_update_keeps_the_choice_and_shows_a_closed_app_as_not_running(window):  # rules 3.2.6, 3.2.7
    updated(window)
    click(window, LEFT, "Discord")
    edge = App(r"c:\edge\msedge.exe", "Microsoft Edge", True)
    updated(window, [App(DISCORD, "Discord", False), APPS[1], edge], ["Microsoft Edge plays in neither ear."])
    assert rows(window, LEFT) == [(ALL_LABEL, False), None, ("Discord (not running)", True), ("Microsoft Edge", False),
                                  ("Zoom Meetings", False)]
    assert rows(window, RIGHT) == [(ALL_LABEL, True), None, ("Microsoft Edge", False), ("Zoom Meetings", False)]
    assert window.ear_buttons[LEFT].cget("text") == "Discord"
    assert window.ear_status_var.get() == "Microsoft Edge plays in neither ear."
    updated(window)                                                      # Discord is back, Edge gone
    assert ("Discord", True) in rows(window, LEFT)
    assert window.ear_status_var.get() == ""


def test_error_shows_in_the_status_line_without_a_dialog(window, monkeypatch):  # rule 3.2.9
    shown = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda *a: shown.append(a))
    router().error("device gone")
    pump(window, lambda: window.ear_status_var.get() == f"{app.EAR_STOPPED}: device gone")
    assert shown == []


def test_reset_puts_the_strip_back_and_tells_the_router(window):
    updated(window)
    click(window, LEFT, "Discord")
    window._ear_scale(("volume", RIGHT), "40")
    window.ear_scales[RIGHT].set(40)
    window.ear_reset_btn.invoke()
    assert ("reset",) in router().calls
    assert window.ear_buttons[LEFT].cget("text") == ALL_LABEL and rows(window, LEFT)[0] == (ALL_LABEL, True)
    assert window.ear_scales[RIGHT].get() == 100 and window.ear_vol_vars[RIGHT].get() == "100 %"
    time.sleep(app.EAR_SEND_MS / 1000 + 0.05)
    window.root.update()
    assert router().calls[-1] == ("reset",)                              # the dragged 40 % isn't sent after it


def test_ear_volume_is_sent_throttled(window):  # §3.1: ~20 changes/s while dragging
    for v in ("90", "70.4", "50"):
        window._ear_scale(("volume", LEFT), v)
    assert window.ear_vol_vars[LEFT].get() == "50 %"                     # shown at once
    assert not [c for c in router().calls if c[0] == "volume"]           # sent at the next tick
    pump(window, lambda: any(c[0] == "volume" for c in router().calls))
    assert [c for c in router().calls if c[0] == "volume"] == [("volume", LEFT, 0.5)]


def test_app_volume(window):  # D9
    updated(window)
    window._ear_scale(("app", None), "30")                               # no app chosen: nothing
    window.ear_app_box.current(0)
    window._ear_pick_app()
    window._ear_scale(("app", None), "30")
    pump(window, lambda: any(c[0] == "app_volume" for c in router().calls))
    assert [c for c in router().calls if c[0] == "app_volume"] == [("app_volume", DISCORD, 0.3)]
    window.ear_app_box.current(2)
    window._ear_pick_app()
    assert window.ear_app_vol_var.get() == "100 %"                       # Zoom is still at 100 %
    window.ear_app_box.current(0)
    window._ear_pick_app()
    assert window.ear_app_scale.get() == pytest.approx(30) and window.ear_app_vol_var.get() == "30 %"


def test_router_that_cant_start_leaves_the_strip_off(make_window, monkeypatch):
    def unreadable(self, on_update, on_error):
        raise PermissionError("ear-channels-restore.json is locked")
    monkeypatch.setattr(FakeRouter, "__init__", unreadable)
    win = make_window()
    assert win.ear_router is None
    assert win.ear_status_var.get() == f"{app.EAR_OFF}: ear-channels-restore.json is locked"
    assert win.ear_buttons[LEFT].instate(["disabled"]) and win.ear_reset_btn.instate(["disabled"])
    assert win.start_btn is not None                                     # the rest of Wisper still works


# ---- C5: lifetime (spec §5.3, §5.4; acceptance A5) ----------------------------------------------------------------

def test_not_stereo_disables_the_menus_and_scales(window):  # §5.3
    updated(window, warnings=[channels.NOT_STEREO])
    assert window.ear_status_var.get() == channels.NOT_STEREO
    controls = [*window.ear_buttons.values(), *window.ear_scales.values(), window.ear_app_box, window.ear_app_scale]
    assert all(w.instate(["disabled"]) for w in controls)
    assert window.ear_reset_btn.instate(["!disabled"])                  # Reset still puts everything back
    updated(window)                                                      # stereo earphones again
    assert all(w.instate(["!disabled"]) for w in controls)
    assert window.ear_app_box.instate(["readonly"])


def test_on_close_puts_the_apps_back_before_pyaudio_goes_away(window):  # §5.4: router.close() before pa.terminate()
    order = []
    router().close = lambda timeout=2.0: order.append("ears restored")
    window.pa.terminate = lambda: order.append("pyaudio terminated")
    window.root.destroy = lambda: order.append("window destroyed")      # the fixture's teardown destroys it
    try:
        window.on_close()
    finally:
        del window.root.destroy
    assert order == ["ears restored", "pyaudio terminated", "window destroyed"]


def test_leftover_journal_is_put_back_at_start_up(make_window, tmp_path):  # §5.4, A5: after a crash or a kill
    path = tmp_path / "ear-channels-restore.json"
    path.write_text(json.dumps({"id-chrome": [1.0, 1.0]}), encoding="utf-8")
    chrome = channels.Session(CHROME, "Google Chrome", 5, "id-chrome", 2, channels.STATE_ACTIVE, (1.0, 0.0))
    audio = FakeAudio(sessions=[chrome])                                 # Windows kept the killed run's (1, 0)

    def real_router(on_update, on_error):
        return channels.Router(audio, channels.Journal(path), on_update, on_error, poll_s=0.05)

    win = make_window(ear_router=real_router)
    pump(win, lambda: chrome.volumes == (1.0, 1.0) and not path.exists())
    pump(win, lambda: "Google Chrome" in win.ear_app_box.cget("values"))
    assert win.ear_buttons[LEFT].cget("text") == ALL_LABEL              # every start is All apps (§2 non-goal)
