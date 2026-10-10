"""Narration wired into the window (spec §3.2, §3.3, §4, §5.3, §5.5; N5, N6): Speak/Stop, Clear,
output modes and devices, errors.

Real Tk window and real Narrator/Player, with a fake Kokoro engine and fake output streams
(conftest.py), so nothing is heard and no model is loaded.
"""

import time

import pytest
from conftest import CABLE, SPEAKERS, FakeEngine, FakeOutput, pump

import app

PARAGRAPH = "First sentence here. Second one follows. And a third."


def ready(make_window, **engine_kw):
    engine = FakeEngine(**engine_kw)
    win = make_window(engine)
    pump(win, lambda: win.speak_btn.instate(["!disabled"]))
    return win, engine


def test_missing_model_shows_the_setup_message_and_stt_still_works(make_window):
    win = make_window(None)
    pump(win, lambda: win.tts_status_var.get() == app.tts.MISSING_MESSAGE)
    assert win.speak_btn.instate(["disabled"])
    pump(win, lambda: win.start_btn.instate(["!disabled"]))     # the (fake) Whisper model loaded


def test_ready_lists_voices_and_enables_speak(make_window):
    win, _ = ready(make_window)
    assert win.tts_status_var.get() == "Narration ready."
    assert list(win.voice_box.cget("values")) == ["af_heart", "bf_emma", "hf_alpha"]
    assert win.voice_var.get() == "af_heart"


def test_speak_reads_every_sentence_in_order_then_completes(make_window):
    win, engine = ready(make_window)
    win.tts_text.insert("end", PARAGRAPH)
    win.voice_var.set("bf_emma")
    win.speed_var.set("1.25")
    win.tts_toggle()
    assert win.speak_btn.cget("text") == "⏹  Stop"
    pump(win, lambda: win.tts_status_var.get() == "Narration complete.")
    assert win.speak_btn.cget("text") == "🔊  Speak"
    spoken = [text for text, _, _ in engine.calls[1:]]          # calls[0] is the warm-up
    assert " ".join(spoken).split() == PARAGRAPH.split()
    assert {(voice, speed) for _, voice, speed in engine.calls[1:]} == {("bf_emma", 1.25)}
    assert FakeOutput.instances and FakeOutput.instances[-1].closed


def test_empty_box_says_nothing_to_narrate(make_window):
    win, engine = ready(make_window)
    win.tts_text.insert("end", "  \n ")
    win.tts_toggle()
    assert win.tts_status_var.get() == "Nothing to narrate."
    assert not win.speaking and len(engine.calls) == 1


def test_clear_during_narration_stops_it_and_empties_the_box(make_window):
    win, engine = ready(make_window, piece_s=1.0)
    win.tts_text.insert("end", PARAGRAPH)
    win.tts_toggle()
    pump(win, lambda: any(o.blocks for o in FakeOutput.instances))   # audio is playing
    win.tts_clear()
    assert win.tts_text.get("1.0", "end-1c") == ""
    assert win.tts_status_var.get() == "Narration stopped."
    assert win.speak_btn.cget("text") == "🔊  Speak"
    # AC5: silence within ~200 ms (one 50 ms block plus the worker closing the stream),
    # not at the end of the 1 s sentence that was playing.
    pump(win, lambda: all(o.closed for o in FakeOutput.instances), timeout=0.25)
    blocks = sum(o.blocks for o in FakeOutput.instances)
    settle = time.monotonic() + 0.3                               # let any late audio/result arrive
    pump(win, lambda: time.monotonic() > settle)
    assert sum(o.blocks for o in FakeOutput.instances) == blocks, "audio kept playing after Clear"
    assert win.tts_status_var.get() == "Narration stopped."       # the late "done" is ignored


def test_stop_keeps_the_text_and_a_new_speak_starts_over(make_window):
    win, engine = ready(make_window, piece_s=1.0)
    win.tts_text.insert("end", PARAGRAPH)
    win.tts_toggle()
    pump(win, lambda: any(o.blocks for o in FakeOutput.instances))
    win.tts_toggle()                                              # the button is Stop now
    assert win.tts_text.get("1.0", "end-1c") == PARAGRAPH
    assert win.tts_status_var.get() == "Narration stopped."
    first = len(engine.calls)
    win.tts_toggle()
    pump(win, lambda: len(engine.calls) > first)
    assert engine.calls[first][0].startswith("First"), "a new Speak reads from the beginning"
    settle = time.monotonic() + 0.3     # the first narration's late "done" arrives meanwhile ...
    pump(win, lambda: time.monotonic() > settle)
    assert win.speaking and win.speak_btn.cget("text") == "⏹  Stop", "... and must not end this one"
    win.tts_toggle()


def test_changing_the_voice_while_speaking_stops(make_window):
    win, _ = ready(make_window, piece_s=1.0)
    win.tts_text.insert("end", PARAGRAPH)
    win.tts_toggle()
    win.voice_var.set("hf_alpha")
    win.voice_box.event_generate("<<ComboboxSelected>>")
    assert not win.speaking
    assert win.tts_status_var.get() == "Narration stopped."


def test_synthesis_error_shows_status_and_one_dialog(make_window, monkeypatch):
    win, engine = ready(make_window)
    dialogs = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda title, msg: dialogs.append(msg))

    def broken(text, voice="af_heart", speed=1.0):
        raise RuntimeError("phonemizer failed")

    engine.synthesize = broken
    win.tts_text.insert("end", PARAGRAPH)
    win.tts_toggle()
    pump(win, lambda: not win.speaking)
    assert win.tts_status_var.get() == "phonemizer failed"
    assert dialogs == ["phonemizer failed"]


def test_device_error_shows_status_without_a_dialog(make_window, monkeypatch):
    win, _ = ready(make_window)
    dialogs = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda title, msg: dialogs.append(msg))

    def unplugged(self, block):
        raise OSError("device unplugged")

    monkeypatch.setattr(FakeOutput, "write", unplugged)
    win.tts_text.insert("end", PARAGRAPH)
    win.tts_toggle()
    pump(win, lambda: not win.speaking)
    assert win.tts_status_var.get().startswith(app.DEVICE_ERROR)
    assert "Speakers" in win.tts_status_var.get() and "device unplugged" in win.tts_status_var.get()
    assert dialogs == []


def test_an_unexpected_worker_error_is_reported_and_the_next_speak_works(make_window, monkeypatch):
    win, engine = ready(make_window)
    monkeypatch.setattr(app.messagebox, "showerror", lambda title, msg: None)
    real_start = win.player.start
    calls = []

    def start_once_broken(devices):
        calls.append(devices)
        if len(calls) == 1:
            raise RuntimeError("boom")
        real_start(devices)

    monkeypatch.setattr(win.player, "start", start_once_broken)
    win.tts_text.insert("end", "One. Two.")
    win.tts_toggle()
    pump(win, lambda: not win.speaking)
    assert win.tts_status_var.get() == "Narration failed: boom"
    win.tts_toggle()
    pump(win, lambda: win.tts_status_var.get() == "Narration complete.")


# ---------------------------------------------------------------- output modes (N6)

def played_on():
    """Labels of the fake outputs that received audio."""
    return {o.name for o in FakeOutput.instances if o.blocks}


def choose_output(win, mode):
    win.output_var.set(mode)
    win.output_radios[[m for m, _ in app.OUTPUT_MODES].index(mode)].invoke()


def test_default_is_both_with_the_cable_preselected_as_others(make_window):
    win, _ = ready(make_window)
    assert win.output_var.get() == "both"
    assert win.me_box.get() == SPEAKERS["label"]
    assert win.others_box.get() == CABLE["label"]
    assert win.others_box.instate(["!disabled"])


def test_both_plays_the_same_narration_on_me_and_others(make_window):
    win, _ = ready(make_window)
    win.tts_text.insert("end", PARAGRAPH)
    win.tts_toggle()
    pump(win, lambda: win.tts_status_var.get() == "Narration complete.")
    assert played_on() == {SPEAKERS["label"], CABLE["label"]}
    blocks = {o.name: 0 for o in FakeOutput.instances}
    for o in FakeOutput.instances:
        blocks[o.name] += o.blocks
    assert blocks[SPEAKERS["label"]] == blocks[CABLE["label"]] > 0


def test_only_others_plays_on_the_cable_only(make_window):
    win, _ = ready(make_window)
    choose_output(win, "others")
    win.tts_text.insert("end", PARAGRAPH)
    win.tts_toggle()
    pump(win, lambda: win.tts_status_var.get() == "Narration complete.")
    assert played_on() == {CABLE["label"]}


def test_only_me_disables_others_and_plays_on_me_only(make_window):
    win, _ = ready(make_window)
    choose_output(win, "me")
    assert win.others_box.instate(["disabled"])
    win.tts_text.insert("end", PARAGRAPH)
    win.tts_toggle()
    pump(win, lambda: win.tts_status_var.get() == "Narration complete.")
    assert played_on() == {SPEAKERS["label"]}
    choose_output(win, "both")
    assert win.others_box.instate(["!disabled"])


def test_without_a_cable_nothing_is_preselected_and_speak_asks_for_others(make_window):
    win = make_window(FakeEngine(), outputs=(SPEAKERS,))
    pump(win, lambda: win.speak_btn.instate(["!disabled"]))
    assert win.output_var.get() == "both"
    assert win.others_box.get() == ""
    win.tts_text.insert("end", PARAGRAPH)
    win.tts_toggle()
    assert win.tts_status_var.get() == app.playback.NO_OTHERS_MESSAGE
    assert not win.speaking and not FakeOutput.instances
    win.others_box.current(0)                                     # the user picks a device
    win.tts_toggle()
    pump(win, lambda: win.tts_status_var.get() == "Narration complete.")


@pytest.mark.parametrize("change", ["mode", "me", "others"])
def test_changing_the_mode_or_a_device_while_speaking_stops(make_window, change):
    win, _ = ready(make_window, piece_s=1.0)
    win.tts_text.insert("end", PARAGRAPH)
    win.tts_toggle()
    pump(win, lambda: any(o.blocks for o in FakeOutput.instances))
    if change == "mode":
        choose_output(win, "me")
    else:
        box = win.me_box if change == "me" else win.others_box
        box.event_generate("<<ComboboxSelected>>")
    assert not win.speaking
    assert win.tts_status_var.get() == "Narration stopped."
    pump(win, lambda: all(o.closed for o in FakeOutput.instances), timeout=0.25)


def test_how_to_set_up_opens_the_cable_steps(make_window, monkeypatch):
    win, _ = ready(make_window)
    shown = []
    monkeypatch.setattr(app.messagebox, "showinfo", lambda title, msg: shown.append(msg))
    win.setup_btn.invoke()
    assert len(shown) == 1
    assert "VB-Audio Virtual Cable" in shown[0] and "CABLE Output" in shown[0] and "CABLE Input" in shown[0]
