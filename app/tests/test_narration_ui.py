"""Narration wired into the window (spec §3.2, §3.3, §4, §5.3, §5.5; N5, N6): Speak/Stop, Clear,
output modes and devices, mic pass-through (N8), errors.

Real Tk window and real Narrator/Player, with a fake Kokoro engine and fake output streams
(conftest.py), so nothing is heard and no model is loaded.
"""

import time

import pytest
from conftest import CABLE, MIC, SPEAKERS, FakeEngine, FakeInput, FakeOutput, pump

import app

PARAGRAPH = "First sentence here. Second one follows. And a third."


def ready(make_window, mics=(), outputs=None, **engine_kw):
    engine = FakeEngine(**engine_kw)
    win = make_window(engine, mics=mics, **({"outputs": outputs} if outputs else {}))
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


# ---------------------------------------------------------------- mic pass-through (N8)

def cable_blocks():
    return sum(o.blocks for o in FakeOutput.instances if o.name == CABLE["label"])


def test_pass_through_is_on_by_default_with_a_cable_and_reaches_the_cable(make_window):
    win, _ = ready(make_window, mics=(MIC,))
    assert win.pass_var.get() is True
    assert list(win.mic_box.cget("values")) == [MIC["label"]] and win.mic_box.get() == MIC["label"]
    pump(win, lambda: cable_blocks() >= 3)                        # the mic is heard in the call
    assert win.passthrough.running


def test_pass_through_is_off_without_a_cable(make_window):
    win = make_window(FakeEngine(), outputs=(SPEAKERS,), mics=(MIC,))
    assert win.pass_var.get() is False
    assert not win.passthrough.running and not FakeInput.instances


def test_unchecking_stops_the_pass_through(make_window):
    win, _ = ready(make_window, mics=(MIC,))
    pump(win, lambda: FakeInput.instances and FakeInput.instances[-1].reads)
    win.pass_check.invoke()
    assert win.pass_var.get() is False
    assert not win.passthrough.running and FakeInput.instances[-1].closed
    win.pass_check.invoke()                                        # and back on
    pump(win, lambda: win.passthrough.running and FakeInput.instances[-1].reads)


def test_only_me_keeps_others_enabled_while_passing_the_mic(make_window):
    win, _ = ready(make_window, mics=(MIC,))
    choose_output(win, "me")
    assert win.others_box.instate(["!disabled"]), "pass-through still needs Others"
    win.pass_check.invoke()
    assert win.others_box.instate(["disabled"])


def test_changing_the_mic_or_others_restarts_the_pass_through(make_window):
    win, _ = ready(make_window, mics=(MIC,))
    pump(win, lambda: FakeInput.instances)
    for box in (win.mic_box, win.others_box):
        before = FakeInput.instances[-1]
        box.event_generate("<<ComboboxSelected>>")
        assert before.closed and FakeInput.instances[-1] is not before
        pump(win, lambda: win.passthrough.running)


def test_narration_and_the_mic_reach_the_call_together(make_window):
    win, _ = ready(make_window, mics=(MIC,))
    win.tts_text.insert("end", PARAGRAPH)
    win.tts_toggle()
    pump(win, lambda: win.tts_status_var.get() == "Narration complete.")
    cable_streams = [o for o in FakeOutput.instances if o.name == CABLE["label"] and o.blocks]
    assert len(cable_streams) == 2, "one stream for the mic, one for the narration (Windows mixes them)"
    assert win.passthrough.running, "the mic keeps going after the narration ends"


def test_a_mic_error_unchecks_the_box_without_a_dialog(make_window, monkeypatch):
    win, _ = ready(make_window, mics=(MIC,))
    dialogs = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda title, msg: dialogs.append(msg))
    pump(win, lambda: FakeInput.instances and FakeInput.instances[-1].reads)
    FakeInput.failing = OSError("mic unplugged")
    pump(win, lambda: win.pass_var.get() is False)
    status = win.tts_status_var.get()
    assert status.startswith(app.PASS_ERROR) and MIC["label"] in status and "mic unplugged" in status
    assert not win.passthrough.running and dialogs == []


def test_an_error_from_a_replaced_run_leaves_the_new_run_alone(make_window):
    win, _ = ready(make_window, mics=(MIC,))
    pump(win, lambda: win.passthrough.running)
    old_run = win.passthrough.run_id
    win.mic_box.event_generate("<<ComboboxSelected>>")             # restart: a new run
    assert win.passthrough.run_id != old_run
    win.tts_results.put(("pass_error", old_run, f"{app.PASS_ERROR}: old mic: gone"))
    settle = time.monotonic() + 0.3
    pump(win, lambda: time.monotonic() > settle)
    assert win.pass_var.get() is True and win.passthrough.running
    assert not win.tts_status_var.get().startswith(app.PASS_ERROR)


# ---------------------------------------------------------------- polish (N7)

def test_status_shows_which_piece_is_speaking(make_window):
    win, _ = ready(make_window, piece_s=0.4)
    win.tts_text.insert("end", PARAGRAPH)                         # 3 pieces
    win.tts_toggle()
    seen = set()

    def watch():
        seen.add(win.tts_status_var.get())
        return win.tts_status_var.get() == "Narration complete."

    pump(win, watch, timeout=5)
    assert {"Speaking 1/3…", "Speaking 2/3…", "Speaking 3/3…"} <= seen


def press_ctrl_enter(win, release=True):
    """Call the key handlers directly: Tk drops generated key events unless the window has
    the desktop's keyboard focus, and taking it (focus_force) would steal it from the user
    on every verify run. test_ctrl_enter_is_bound checks the bindings themselves."""
    assert win._speak_key(None) == "break", "\"break\" stops Tk's own newline"
    if release:
        win._speak_key_released(None)


def test_ctrl_enter_is_bound_in_the_narration_box(window):
    assert "_speak_key" in window.tts_text.bind("<Control-Return>")
    assert "_speak_key_released" in window.tts_text.bind("<KeyRelease-Return>")


def test_ctrl_enter_toggles_speak_and_stop(make_window):
    win, _ = ready(make_window, piece_s=1.0)
    win.tts_text.insert("end", PARAGRAPH)
    press_ctrl_enter(win)
    assert win.speaking
    press_ctrl_enter(win)
    assert not win.speaking and win.tts_status_var.get() == "Narration stopped."


def test_holding_ctrl_enter_toggles_only_once(make_window):
    win, _ = ready(make_window, piece_s=1.0)
    win.tts_text.insert("end", PARAGRAPH)
    for _ in range(4):                     # Windows key repeat: presses only (even: toggling would end stopped)
        press_ctrl_enter(win, release=False)
    assert win.speaking, "a held Ctrl+Enter must act like one button press"
    win._speak_key_released(None)
    press_ctrl_enter(win)
    assert not win.speaking


def test_ctrl_enter_does_nothing_while_kokoro_is_missing(make_window):
    win = make_window(None)
    pump(win, lambda: win.tts_status_var.get() == app.tts.MISSING_MESSAGE)
    win.tts_text.insert("end", PARAGRAPH)
    press_ctrl_enter(win)
    assert not win.speaking and win.tts_status_var.get() == app.tts.MISSING_MESSAGE


def test_after_a_device_error_speak_works_on_another_device(make_window, monkeypatch):
    headphones = {**SPEAKERS, "index": 9, "name": "Headphones (USB)", "label": "Headphones (USB)"}
    win, _ = ready(make_window, outputs=(headphones, SPEAKERS, CABLE))
    real_write = FakeOutput.write

    def unplugged(self, block):
        if self.name == headphones["label"]:
            raise OSError("device unplugged")
        real_write(self, block)

    monkeypatch.setattr(FakeOutput, "write", unplugged)
    choose_output(win, "me")
    win.tts_text.insert("end", PARAGRAPH)
    win.tts_toggle()
    pump(win, lambda: not win.speaking)
    assert win.tts_status_var.get().startswith(app.DEVICE_ERROR)
    win.me_box.current(1)                                          # the user picks the speakers
    win.me_box.event_generate("<<ComboboxSelected>>")
    win.tts_toggle()
    pump(win, lambda: win.tts_status_var.get() == "Narration complete.")


@pytest.mark.parametrize("captured, output, warned", [
    (SPEAKERS, "me", True), (SPEAKERS, "both", True), (SPEAKERS, "others", False),
    (CABLE, "others", True), (CABLE, "me", False),
])
def test_speak_warns_that_live_captions_will_transcribe_it(make_window, captured, output, warned):
    win, _ = ready(make_window)
    win.mode_var.set("Live captions (desktop audio)")
    win.devices = [dict(captured)]                                 # the loopback device Live captions uses
    win.device_box.config(values=[captured["label"]])
    win.device_box.current(0)
    win.transcribing = True                                        # a capture is running
    choose_output(win, output)
    win.tts_text.insert("end", PARAGRAPH)
    win.tts_toggle()
    assert (app.FEEDBACK_HINT in win.tts_status_var.get()) is warned
    win.transcribing = False
    win.tts_toggle()


def test_progress_keeps_a_mic_error_visible(make_window):
    win, _ = ready(make_window, mics=(MIC,), piece_s=0.4)
    pump(win, lambda: win.passthrough.running)
    win.tts_text.insert("end", PARAGRAPH)
    win.tts_toggle()
    pump(win, lambda: win.tts_status_var.get() == "Speaking 1/3…")
    win.tts_results.put(("pass_error", win.passthrough.run_id, f"{app.PASS_ERROR}: Microphone: gone"))
    pump(win, lambda: win.tts_status_var.get().startswith(app.PASS_ERROR))
    settle = time.monotonic() + 0.6                                # the next piece starts meanwhile
    pump(win, lambda: time.monotonic() > settle)
    assert win.tts_status_var.get().startswith(app.PASS_ERROR), "progress erased the mic error"
    pump(win, lambda: not win.speaking, timeout=5)
