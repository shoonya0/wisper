"""Wisper — local speech-to-text for the AMD RX 580 (whisper.cpp + Vulkan).

Three modes over one GPU-resident model:
  • Dictation   — transcribe your microphone as you speak (low latency).
  • Live caption — transcribe desktop/meeting audio (WASAPI loopback).
  • File        — transcribe an audio file, text appearing progressively.

The Whisper model is loaded once and kept in GPU memory by a single worker
thread (whisper contexts are not thread safe, so only that thread touches it).
"""

import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import numpy as np

import audio_io
import capture
import narrator
import playback
import priority
import tts
from whisper_native import Whisper

WHISPER_DIR = Path(__file__).resolve().parent.parent / "whisper.cpp"
DLL_DIR = WHISPER_DIR / "build" / "bin" / "Release"
MODEL_DIR = WHISPER_DIR / "models"

# label -> (filename, english_only). Ordered fastest → most accurate.
MODELS = [
    ("base.en — fastest",            "ggml-base.en-q5_1.bin",        True),
    ("small.en — balanced",          "ggml-small.en-q5_1.bin",       True),
    ("large-v3-turbo — most accurate", "ggml-large-v3-turbo-q5_0.bin", False),
]
MODEL_BY_LABEL = {label: (MODEL_DIR / fn, en_only) for label, fn, en_only in MODELS}

MODES = ["Dictation (microphone)", "Live captions (desktop audio)", "File"]
DEFAULT_MODEL = {
    "Dictation (microphone)": "small.en — balanced",
    "Live captions (desktop audio)": "large-v3-turbo — most accurate",
    "File": "large-v3-turbo — most accurate",
}
PROFILE = {
    "Dictation (microphone)": capture.DICTATION,
    "Live captions (desktop audio)": capture.CAPTIONS,
}
SOURCE_KIND = {
    "Dictation (microphone)": "mic",
    "Live captions (desktop audio)": "loopback",
}

SPEEDS = ["0.8", "0.9", "1.0", "1.1", "1.25", "1.5"]     # narration speed (spec §3.2)
DEVICE_ERROR = "Audio device failed"                     # TTS status only, no dialog (rule 3.3.9)
OUTPUT_MODES = [("me", "Only me"), ("others", "Only others"), ("both", "Both")]   # playback.MODES
DEFAULT_OUTPUT = "both"                                  # user decision, 2026-10-10
CABLE_SETUP = (
    "To let a call hear the narration (Only others / Both):\n\n"
    "1. Install VB-Audio Virtual Cable (free, vb-audio.com/Cable): run the setup as "
    "administrator, then reboot.\n"
    "2. In Wisper, choose \"CABLE Input (VB-Audio Virtual Cable)\" as Others. Wisper picks it "
    "by itself when it finds it at start-up.\n"
    "3. In Discord, Zoom or Meet, choose \"CABLE Output (VB-Audio Virtual Cable)\" as the "
    "microphone (Meet: ⋮ → Settings → Audio → Microphone; \"Default\" is your real mic). "
    "Restart the browser if CABLE Output isn't listed.\n\n"
    "Your real microphone then no longer reaches the call. To talk too: Windows Sound "
    "settings → More sound settings → Recording → your microphone → Properties → Listen → "
    "tick \"Listen to this device\" and play it through CABLE Input.")

LANGUAGES = ["auto", "en", "hi", "es", "fr", "de", "ja", "zh", "ru", "pt", "it", "ko", "ar"]

# Whisper invents these on music/noise; drop them when they are the whole chunk.
HALLUCINATIONS = {
    "thank you.", "thanks for watching!", "thank you for watching.",
    "thanks for watching.", "you", "bye.", ".",
}


# Dark theme palette (VS Code "Dark+" inspired).
DARK = {
    "bg":        "#1e1e1e",   # window / panels
    "surface":   "#252526",   # raised surface (transcript area)
    "fg":        "#d4d4d4",   # primary text
    "muted":     "#8a8f98",   # disabled / secondary text
    "border":    "#3c3c3c",
    "accent":    "#0e639c",   # primary button
    "accent_hi": "#1177bb",   # hover
    "sel":       "#264f78",   # selection
    "field":     "#2d2d2d",   # input field background
}


# Split window (narration spec §3.1): minimum pane widths keep every control visible.
STT_MIN_W = 700   # Start + Mode + Model + Lang row
TTS_MIN_W = 420
SASH_W    = 6


def is_junk(text):
    t = text.strip().lower()
    return (t in HALLUCINATIONS
            or (t.startswith("[") and t.endswith("]"))
            or (t.startswith("(") and t.endswith(")")))


class App:
    def __init__(self, root):
        self.root = root
        self.pa = capture.pyaudio.PyAudio()
        self.capture = None
        self.transcribing = False        # a live capture session is running
        self.busy = False                # worker mid-inference
        self.last_text = ""

        # Worker owns the model. Jobs: ("model", path) | ("audio", arr, prompt)
        #                              | ("file", path) | ("stop",)
        self.jobs = queue.Queue()
        self.results = queue.Queue()     # ("ready"|"text"|"status"|"error"|"progress"|"done", payload)
        self.loaded_model_path = None
        self.want_model_path = None

        # TTS worker owns the Kokoro engine (spec §5.4). Jobs: ("load",)
        # | ("speak", gen, text, voice, speed, devices) | ("stop",)
        self.tts_jobs = queue.Queue()
        self.tts_results = queue.Queue()  # ("tts_ready", voices) | ("tts_missing"|"tts_load_error", msg)
        #                                   | ("tts_done", gen, stopped) | ("tts_error", gen, msg)
        self.speaking = False
        self.tts_gen = None               # generation of the narration the UI is showing
        self._narrating_gen = None        # TTS worker only
        self._device_error = None
        self.narrator = narrator.Narrator(
            self._tts_synth, self._tts_play, tts.split_sentences,
            on_done=lambda stopped: self.tts_results.put(("tts_done", self._narrating_gen, stopped)),
            on_error=lambda msg: self.tts_results.put(("tts_error", self._narrating_gen, msg)))
        self.player = playback.Player(lambda device: playback.PaStream(self.pa, device), self._on_device_error)

        root.title("Wisper — local speech-to-text (RX 580 · Vulkan)")
        root.geometry("1440x680")
        root.minsize(STT_MIN_W + TTS_MIN_W + SASH_W, 420)

        self._apply_theme(root)
        stt_pane, tts_pane = self._build_panes(root)
        self._build_controls(stt_pane)
        self._build_status(stt_pane)      # before the transcript so it keeps its row
        self._build_transcript(stt_pane)
        self._build_tts_pane(tts_pane)

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()
        self.tts_worker = threading.Thread(target=self._tts_worker_loop, daemon=True)
        self.tts_worker.start()
        self.tts_jobs.put(("load",))   # in the background: the window opens at once, STT doesn't wait
        self._on_mode_change()
        self._request_model()       # load the initial model
        self._poll()

    # ------------------------------------------------------------------ theme

    def _apply_theme(self, root):
        d = DARK
        root.configure(bg=d["bg"])
        style = ttk.Style(root)
        style.theme_use("clam")  # the only built-in theme that honors these colors

        style.configure(".", background=d["bg"], foreground=d["fg"],
                        fieldbackground=d["field"], bordercolor=d["border"],
                        lightcolor=d["bg"], darkcolor=d["bg"],
                        troughcolor=d["field"], focuscolor=d["accent"])
        style.configure("TFrame", background=d["bg"])
        style.configure("TLabel", background=d["bg"], foreground=d["fg"])
        style.configure("Header.TLabel", foreground=d["muted"], font=("Segoe UI", 10, "bold"))

        style.configure("TButton", background=d["field"], foreground=d["fg"],
                        bordercolor=d["border"], focuscolor=d["bg"], padding=6)
        style.map("TButton",
                  background=[("active", d["accent_hi"]), ("pressed", d["accent"]),
                              ("disabled", d["bg"])],
                  foreground=[("disabled", d["muted"])])

        # Primary action button (Start / Transcribe).
        style.configure("Accent.TButton", background=d["accent"],
                        foreground="#ffffff", bordercolor=d["accent"])
        style.map("Accent.TButton",
                  background=[("active", d["accent_hi"]), ("pressed", d["accent"]),
                              ("disabled", d["field"])],
                  foreground=[("disabled", d["muted"])])

        style.configure("TCombobox", fieldbackground=d["field"],
                        background=d["field"], foreground=d["fg"],
                        arrowcolor=d["fg"], bordercolor=d["border"],
                        selectbackground=d["sel"], selectforeground=d["fg"], padding=3)
        style.map("TCombobox",
                  fieldbackground=[("readonly", d["field"]), ("disabled", d["bg"])],
                  foreground=[("disabled", d["muted"])],
                  arrowcolor=[("disabled", d["muted"])])

        style.configure("TRadiobutton", background=d["bg"], foreground=d["fg"],
                        indicatorbackground=d["field"], indicatorforeground=d["fg"])
        style.map("TRadiobutton", background=[("active", d["bg"])],
                  indicatorbackground=[("selected", d["accent"]), ("active", d["border"])])

        style.configure("TProgressbar", background=d["accent"],
                        troughcolor=d["field"], bordercolor=d["border"])
        style.configure("Vertical.TScrollbar", background=d["field"],
                        troughcolor=d["bg"], bordercolor=d["border"],
                        arrowcolor=d["fg"])

        # Combobox drop-down list is a classic tk Listbox — theme it via options.
        root.option_add("*TCombobox*Listbox.background", d["surface"])
        root.option_add("*TCombobox*Listbox.foreground", d["fg"])
        root.option_add("*TCombobox*Listbox.selectBackground", d["sel"])
        root.option_add("*TCombobox*Listbox.selectForeground", d["fg"])

        self._dark_titlebar(root)

    @staticmethod
    def _dark_titlebar(root):
        """Best-effort dark Windows title bar (Win10 2004+/Win11)."""
        try:
            import ctypes
            root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
        except Exception:
            pass

    # ---------------------------------------------------------------- UI build

    def _build_panes(self, root):
        """Left pane: speech to text (the original app). Right pane: text to speech."""
        panes = tk.PanedWindow(root, orient="horizontal", sashwidth=SASH_W, sashrelief="flat",
                               bg=DARK["border"], borderwidth=0)
        panes.pack(fill="both", expand=True)
        stt_pane = ttk.Frame(panes)
        tts_pane = ttk.Frame(panes)
        # minsize keeps every control of a pane visible however far the sash is dragged.
        panes.add(stt_pane, minsize=STT_MIN_W, width=720, stretch="always")
        panes.add(tts_pane, minsize=TTS_MIN_W, width=720, stretch="always")
        ttk.Label(stt_pane, text="Speech to text", style="Header.TLabel",
                  padding=(8, 6, 8, 0)).pack(anchor="w")
        ttk.Label(tts_pane, text="Text to speech", style="Header.TLabel",
                  padding=(8, 6, 8, 0)).pack(anchor="w")
        return stt_pane, tts_pane

    def _build_tts_pane(self, parent):
        # Speak stays disabled until Kokoro has loaded (or for good if its files are missing).
        bar = ttk.Frame(parent, padding=8)
        bar.pack(fill="x")
        self.speak_btn = ttk.Button(bar, text="🔊  Speak", width=11, state="disabled",
                                    command=self.tts_toggle, style="Accent.TButton")
        self.speak_btn.pack(side="left")

        ttk.Label(bar, text="  Voice:").pack(side="left")
        self.voice_var = tk.StringVar(value=tts.DEFAULT_VOICE)
        self.voice_box = ttk.Combobox(bar, textvariable=self.voice_var, values=[tts.DEFAULT_VOICE],
                                      state="readonly", width=12)
        self.voice_box.pack(side="left", padx=4)
        ttk.Label(bar, text="  Speed:").pack(side="left")
        self.speed_var = tk.StringVar(value="1.0")
        self.speed_box = ttk.Combobox(bar, textvariable=self.speed_var, values=SPEEDS,
                                      state="readonly", width=5)
        self.speed_box.pack(side="left", padx=4)
        # Rule 3.3.5: changing voice or speed while speaking stops; it applies to the next Speak.
        for box in (self.voice_box, self.speed_box):
            box.bind("<<ComboboxSelected>>", lambda e: self.tts_stop())

        self._build_outputs(parent)

        actions = ttk.Frame(parent, padding=(8, 6))
        actions.pack(fill="x")
        ttk.Button(actions, text="Copy all", command=self.tts_copy_all).pack(side="right")
        ttk.Button(actions, text="Clear", command=self.tts_clear).pack(side="right", padx=4)
        ttk.Button(actions, text="Save…", command=self.tts_save).pack(side="right")

        status = ttk.Frame(parent, padding=(8, 4))
        status.pack(side="bottom", fill="x")    # before the box so it keeps its row
        self.tts_status_var = tk.StringVar(value="Loading Kokoro…")
        ttk.Label(status, textvariable=self.tts_status_var).pack(side="left")

        # Editable: the user types or pastes the text to narrate.
        self.tts_text = self._make_text_box(parent)
        self.tts_text.bind("<Control-a>", self._select_all)

    def _build_outputs(self, parent):
        """Output mode and the Me / Others devices (spec §3.2, §4, §5.3; N6)."""
        modes = ttk.Frame(parent, padding=(8, 0))
        modes.pack(fill="x")
        ttk.Label(modes, text="Output:", width=7).pack(side="left")
        self.output_var = tk.StringVar(value=DEFAULT_OUTPUT)
        self.output_radios = []
        for value, label in OUTPUT_MODES:
            radio = ttk.Radiobutton(modes, text=label, value=value, variable=self.output_var,
                                    command=self._on_output_change)
            radio.pack(side="left", padx=(4, 8))
            self.output_radios.append(radio)

        # PortAudio lists devices once, at PyAudio start-up, so one lookup here is enough.
        self.tts_outputs = playback.list_outputs(self.pa)
        labels = [d["label"] for d in self.tts_outputs]
        rows = {}
        for name in ("Me:", "Others:"):
            rows[name] = ttk.Frame(parent, padding=(8, 4, 8, 0))
            rows[name].pack(fill="x")
            ttk.Label(rows[name], text=name, width=7).pack(side="left")
        self.setup_btn = ttk.Button(rows["Others:"], text="How to set up…", command=self.show_cable_setup)
        self.setup_btn.pack(side="right")
        self.me_box = ttk.Combobox(rows["Me:"], values=labels, state="readonly", width=20)
        self.others_box = ttk.Combobox(rows["Others:"], values=labels, state="readonly", width=20)
        for box in (self.me_box, self.others_box):
            box.pack(side="left", padx=4, fill="x", expand=True)
            box.bind("<<ComboboxSelected>>", lambda e: self.tts_stop())   # rule 3.3.5
        if self.tts_outputs:
            self.me_box.current(0)        # list_outputs puts the Windows default first
        cable = playback.find_virtual_cable(self.tts_outputs)
        if cable is not None:
            self.others_box.current(self.tts_outputs.index(cable))
        self._on_output_change()

    def _on_output_change(self):
        """Others is only used by Only others and Both; a mode change stops (rule 3.3.5)."""
        self.others_box.config(state="disabled" if self.output_var.get() == "me" else "readonly")
        self.tts_stop()

    def show_cable_setup(self):
        messagebox.showinfo("How to set up narration into a call", CABLE_SETUP)

    def _chosen_output(self, box):
        i = box.current()
        return self.tts_outputs[i] if i >= 0 else None

    def _build_controls(self, parent):
        bar = ttk.Frame(parent, padding=8)
        bar.pack(fill="x")

        self.start_btn = ttk.Button(bar, text="▶  Start", width=11,
                                     command=self.toggle, state="disabled",
                                     style="Accent.TButton")
        self.start_btn.pack(side="left")

        ttk.Label(bar, text="  Mode:").pack(side="left")
        self.mode_var = tk.StringVar(value=MODES[0])
        mode_box = ttk.Combobox(bar, textvariable=self.mode_var, values=MODES,
                                state="readonly", width=24)
        mode_box.pack(side="left", padx=4)
        mode_box.bind("<<ComboboxSelected>>", lambda e: self._on_mode_change())

        ttk.Label(bar, text="  Model:").pack(side="left")
        self.model_var = tk.StringVar()
        self.model_box = ttk.Combobox(bar, textvariable=self.model_var,
                                      values=[m[0] for m in MODELS],
                                      state="readonly", width=24)
        self.model_box.pack(side="left", padx=4)
        self.model_box.bind("<<ComboboxSelected>>", lambda e: self._request_model())

        ttk.Label(bar, text="  Lang:").pack(side="left")
        self.lang_var = tk.StringVar(value="auto")
        self.language = "auto"
        self.lang_box = ttk.Combobox(bar, textvariable=self.lang_var,
                                     values=LANGUAGES, width=6)
        self.lang_box.pack(side="left", padx=4)
        self.lang_var.trace_add("write", lambda *_: setattr(
            self, "language", self.lang_var.get().strip() or "auto"))

        # Second row: device picker / file picker (swapped per mode).
        row2 = ttk.Frame(parent, padding=(8, 0))
        row2.pack(fill="x")
        self.device_label = ttk.Label(row2, text="Device:")
        self.device_var = tk.StringVar()
        self.device_box = ttk.Combobox(row2, textvariable=self.device_var,
                                       state="readonly", width=52)
        self.file_btn = ttk.Button(row2, text="Choose audio file…", command=self.pick_file)
        self.file_label = ttk.Label(row2, text="No file selected.")
        self._row2 = row2

        actions = ttk.Frame(parent, padding=(8, 6))
        actions.pack(fill="x")
        ttk.Button(actions, text="Copy all", command=self.copy_all).pack(side="right")
        ttk.Button(actions, text="Clear", command=self.clear).pack(side="right", padx=4)
        ttk.Button(actions, text="Save…", command=self.save).pack(side="right")

    @staticmethod
    def _make_text_box(parent):
        box = ScrolledText(
            parent, wrap="word", font=("Segoe UI", 12), padx=10, pady=10,
            bg=DARK["surface"], fg=DARK["fg"], insertbackground=DARK["fg"],
            selectbackground=DARK["sel"], selectforeground=DARK["fg"],
            borderwidth=0, highlightthickness=1,
            highlightbackground=DARK["border"], highlightcolor=DARK["border"])
        box.pack(fill="both", expand=True, padx=8)
        # ScrolledText's scrollbar is a classic tk.Scrollbar; tint it to match.
        try:
            box.vbar.configure(
                background=DARK["field"], troughcolor=DARK["bg"],
                activebackground=DARK["accent"], borderwidth=0,
                highlightthickness=0)
        except Exception:
            pass
        return box

    def _build_transcript(self, parent):
        # Read-only for the user: starts disabled; only the app writes to it
        # (via _write_locked). Text stays selectable so Ctrl+C / Copy still work.
        self.text = self._make_text_box(parent)
        self.text.configure(state="disabled")
        self.text.bind("<Control-a>", self._select_all)
        self.text.bind("<Control-c>", lambda e: self.text.event_generate("<<Copy>>"))

    def _build_status(self, parent):
        status = ttk.Frame(parent, padding=(8, 4))
        # Packed at the bottom before the transcript: the transcript's requested height
        # used to push this row off the window (status and level meter never showed).
        status.pack(side="bottom", fill="x")
        self.status_var = tk.StringVar(value="Loading model onto the GPU…")
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        self.level_bar = ttk.Progressbar(status, length=120, maximum=0.15)
        self.level_bar.pack(side="right")
        ttk.Label(status, text="Level ").pack(side="right")

    # --------------------------------------------------------------- mode swap

    def _on_mode_change(self):
        if self.transcribing:
            self.toggle()  # stop any running capture
        mode = self.mode_var.get()
        self.model_var.set(DEFAULT_MODEL[mode])
        self._request_model()

        for w in (self.device_label, self.device_box, self.file_btn, self.file_label):
            w.pack_forget()

        if mode == "File":
            self.file_btn.pack(side="left")
            self.file_label.pack(side="left", padx=8)
            self.selected_file = None
            self.start_btn.config(text="▶  Transcribe")
        else:
            self.device_label.pack(side="left")
            self.device_box.pack(side="left", padx=6, fill="x", expand=True)
            self._populate_devices(SOURCE_KIND[mode])
            self.start_btn.config(text="▶  Start")

    def _populate_devices(self, kind):
        self.devices = capture.list_sources(self.pa, kind)
        self.device_box.config(values=[d["label"] for d in self.devices])
        if self.devices:
            self.device_box.current(0)

    # --------------------------------------------------------------- model swap

    def _request_model(self):
        label = self.model_var.get() or DEFAULT_MODEL[self.mode_var.get()]
        path, en_only = MODEL_BY_LABEL[label]
        # English-only models: pin language to en and lock the box.
        if en_only:
            self.lang_var.set("en")
            self.lang_box.config(state="disabled")
        else:
            self.lang_box.config(state="normal")
        self.want_model_path = path
        if path != self.loaded_model_path:
            self.start_btn.config(state="disabled")
            self.status_var.set(f"Loading {label} onto the GPU…")
            self.jobs.put(("model", path))

    # --------------------------------------------------------------- UI actions

    def toggle(self):
        mode = self.mode_var.get()
        if mode == "File":
            self.start_file()
            return
        if self.transcribing:
            self.transcribing = False
            if self.capture:
                self.capture.stop()
                self.capture = None
            self.start_btn.config(text="▶  Start")
        else:
            if not self.devices:
                messagebox.showerror("No device", "No audio device found for this mode.")
                return
            device = self.devices[self.device_box.current()]
            try:
                self.capture = capture.Capture(
                    self.pa, device, PROFILE[mode], self._on_audio_chunk)
                self.capture.start()
            except Exception as e:
                messagebox.showerror("Audio error", str(e))
                self.capture = None
                return
            self.transcribing = True
            self.start_btn.config(text="⏸  Stop")

    def _on_audio_chunk(self, audio):
        # Called from the capture thread; hand off to the worker.
        self.jobs.put(("audio", audio, self.last_text[-200:]))

    def pick_file(self):
        exts = " ".join("*" + e for e in sorted(audio_io.AUDIO_EXTS))
        path = filedialog.askopenfilename(
            filetypes=[("Audio", exts), ("All files", "*.*")])
        if path:
            self.selected_file = path
            self.file_label.config(text=Path(path).name)

    def start_file(self):
        if not getattr(self, "selected_file", None):
            messagebox.showinfo("Choose a file", "Pick an audio file first.")
            return
        self.start_btn.config(state="disabled")
        self.jobs.put(("file", self.selected_file))

    def copy_all(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.text.get("1.0", "end-1c"))
        self.flash("Copied transcript to clipboard.")

    def clear(self):
        self._write_locked(lambda: self.text.delete("1.0", "end"))
        self.last_text = ""

    def save(self):
        path = self._save_text(self.text)
        if path:
            self.flash(f"Saved to {path}")

    def tts_copy_all(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.tts_text.get("1.0", "end-1c"))
        self.tts_status_var.set("Copied narration text to clipboard.")

    def tts_clear(self):
        self.tts_stop()                   # rule 3.3.2: Clear stops the narration, then empties
        self.tts_text.delete("1.0", "end")

    def tts_toggle(self):
        if self.speaking:
            self.tts_stop()
            return
        text = self.tts_text.get("1.0", "end-1c")      # snapshot: later edits don't change it
        if not text.strip():
            self.tts_status_var.set("Nothing to narrate.")
            return
        me = self._chosen_output(self.me_box)
        if me is None:
            self.tts_status_var.set("No audio output device found.")
            return
        try:
            devices = playback.targets_for(self.output_var.get(), me, self._chosen_output(self.others_box))
        except ValueError as e:           # Only others / Both without an Others device (spec §5.3)
            self.tts_status_var.set(str(e))
            return
        self.tts_gen = self.narrator.begin()
        self.tts_jobs.put(("speak", self.tts_gen, text, self.voice_var.get(),
                           float(self.speed_var.get()), devices))
        self.speaking = True
        self.speak_btn.config(text="⏹  Stop")
        self.tts_status_var.set("Speaking…")

    def tts_stop(self):
        """Stop the narration (Stop, Clear, a voice/speed/mode/device change). Safe when nothing plays."""
        if not self.speaking:
            return
        self.narrator.stop()
        self.player.stop()                # silences every device within one block
        self._narration_ended("Narration stopped.")

    def _narration_ended(self, message):
        self.speaking = False
        self.speak_btn.config(text="🔊  Speak")
        self.tts_status_var.set(message)

    def tts_save(self):
        path = self._save_text(self.tts_text)
        if path:
            self.tts_status_var.set(f"Saved narration text to {path}")

    @staticmethod
    def _save_text(box):
        """Ask for a .txt path and write box's text as UTF-8. Returns the path, or "" if cancelled."""
        path = filedialog.asksaveasfilename(defaultextension=".txt",
                                            filetypes=[("Text", "*.txt")])
        if path:
            Path(path).write_text(box.get("1.0", "end-1c"), encoding="utf-8")
        return path

    def flash(self, message, seconds=3):
        self.status_var.set(message)
        self.flash_until = time.time() + seconds

    def _select_all(self, event):
        event.widget.tag_add("sel", "1.0", "end-1c")
        return "break"

    # --------------------------------------------------------------- worker

    def _worker_loop(self):
        priority.boost_thread()
        model = None
        while True:
            job = self.jobs.get()
            kind = job[0]

            if kind == "stop":
                break

            if kind == "model":
                path = job[1]
                if path == self.loaded_model_path:
                    self.results.put(("ready", None))
                    continue
                try:
                    if model:
                        model.close()
                    model = Whisper(DLL_DIR, path)
                    model.transcribe(np.zeros(capture.TARGET_SR, np.float32), "en")  # warm-up
                    self.loaded_model_path = path
                    self.results.put(("ready", None))
                except Exception as e:
                    model = None
                    self.results.put(("error", f"Could not load model: {e}"))
                continue

            if model is None:
                continue  # ignore audio/file jobs until a model is loaded

            if kind == "audio":
                _, audio, prompt = job
                self.busy = True
                try:
                    text = model.transcribe(audio, self.language, prompt)
                    if text and not is_junk(text):
                        self.last_text += " " + text
                        self.results.put(("text", text))
                except Exception as e:
                    self.results.put(("status", f"Transcription error: {e}"))
                finally:
                    self.busy = False

            elif kind == "file":
                self._transcribe_file(model, job[1])

        if model:
            model.close()

    def _transcribe_file(self, model, path):
        self.busy = True
        try:
            self.results.put(("status", f"Decoding {Path(path).name}…"))
            audio = audio_io.decode_to_16k_mono(path)
            self.results.put(("text", f"\n\n--- {Path(path).name} ---\n"))

            def on_text(text):
                text = text.strip()
                if text and not is_junk(text):
                    self.results.put(("text", text + " "))

            # One pass over the whole file: whisper.cpp seeks by its own timestamps, so
            # no words are cut or repeated at window edges (known issue 1).
            model.transcribe_long(audio, self.language, on_text,
                                  lambda pct: self.results.put(("progress", pct)))
            self.results.put(("progress", 100))
            self.results.put(("done", None))
        except Exception as e:
            self.results.put(("error", f"File transcription failed: {e}"))
        finally:
            self.busy = False

    # --------------------------------------------------------------- UI loop

    # --------------------------------------------------------------- TTS worker

    def _tts_worker_loop(self):
        """The only thread that touches the Kokoro engine (spec §5.4)."""
        while True:
            job = self.tts_jobs.get()
            if job[0] == "stop":
                self.player.close()
                return
            if job[0] == "load":
                self._tts_load()
            elif job[0] == "speak":
                _, gen, text, voice, speed, devices = job
                self._narrating_gen = gen
                self._device_error = None
                try:
                    self.player.start(devices)
                    self.narrator.speak(gen, text, voice=voice, speed=speed)
                except Exception as e:    # never let the worker die: later Speaks need it
                    self.tts_results.put(("tts_error", gen, f"Narration failed: {e}"))
                finally:
                    self.player.close()

    def _tts_load(self):
        try:
            self._engine = tts.load()
            self._engine.synthesize("Ready.")   # warm-up: the first real Speak is ~2 s faster (N0)
            voices = self._engine.voices()
        except FileNotFoundError as e:
            self.tts_results.put(("tts_missing", str(e)))
            return
        except Exception as e:
            self.tts_results.put(("tts_load_error", f"Couldn't load Kokoro: {e}"))
            return
        self.tts_results.put(("tts_ready", voices))

    def _tts_synth(self, piece, voice, speed):
        return self._engine.synthesize(piece, voice, speed)

    def _tts_play(self, samples, stop_event):
        if not self.player.play(samples) and self._device_error and not stop_event.is_set():
            raise RuntimeError(self._device_error)

    def _on_device_error(self, name, error):
        self._device_error = f"{DEVICE_ERROR}: {name}: {error}"

    def _poll_tts(self):
        while not self.tts_results.empty():
            kind, *payload = self.tts_results.get()
            if kind == "tts_ready":
                voices = payload[0]
                self.voice_box.config(values=voices)
                if self.voice_var.get() not in voices and voices:
                    self.voice_var.set(voices[0])
                self.speak_btn.config(state="normal")
                self.tts_status_var.set("Narration ready.")
            elif kind == "tts_missing":
                self.tts_status_var.set(payload[0])
            elif kind == "tts_load_error":
                self.tts_status_var.set(payload[0])
                messagebox.showerror("Wisper", payload[0])
            elif payload[0] != self.tts_gen or not self.speaking:
                continue                  # a narration the user already stopped
            elif kind == "tts_done":      # a stopped narration was already ended by tts_stop()
                self._narration_ended("Narration complete.")
            elif kind == "tts_error":
                self._narration_ended(payload[1])
                if not payload[1].startswith(DEVICE_ERROR):
                    messagebox.showerror("Wisper", payload[1])

    def _write_locked(self, fn):
        """Run a mutation on the (normally disabled) transcript, then re-lock it."""
        self.text.configure(state="normal")
        try:
            fn()
        finally:
            self.text.configure(state="disabled")

    def _append(self, text):
        at_bottom = self.text.yview()[1] >= 0.999
        existing = self.text.get("1.0", "end-1c")
        sep = "" if not existing or existing.endswith(("\n", " ")) else " "
        self._write_locked(lambda: self.text.insert("end", sep + text))
        if at_bottom:
            self.text.see("end")

    def _poll(self):
        while not self.results.empty():
            kind, payload = self.results.get()
            if kind == "text":
                self._append(payload)
            elif kind == "ready":
                self.loaded_model_path = self.want_model_path
                self.start_btn.config(state="normal")
                self.flash("Model ready on GPU.", 2)
            elif kind == "progress":
                self.flash(f"Transcribing file… {payload}%", 60)
            elif kind == "done":
                self.start_btn.config(state="normal")
                self.flash("File transcription complete.", 4)
            elif kind == "error":
                self.status_var.set(payload)
                messagebox.showerror("Wisper", payload)
            elif kind == "status":
                self.flash(payload, 5)

        if getattr(self, "flash_until", 0) < time.time() and self.loaded_model_path:
            pending = self.jobs.qsize() + (1 if self.busy else 0)
            if self.mode_var.get() == "File":
                state = "Working" if self.busy else "Ready"
            else:
                state = "Listening" if self.transcribing else "Ready"
            self.status_var.set(f"{state}  •  {self.model_var.get()}  •  queue: {pending}")

        self._poll_tts()
        self.level_bar["value"] = self.capture.level if self.capture else 0
        self.root.after(100, self._poll)

    def on_close(self):
        if self.capture:
            self.capture.stop()
        self.jobs.put(("stop",))
        self.narrator.stop()
        self.player.stop()
        self.tts_jobs.put(("stop",))
        # The TTS worker closes its streams before the PyAudio they belong to goes away; a
        # synthesis in progress (at most ~3 s) isn't waited for beyond this.
        self.tts_worker.join(timeout=1)
        self.pa.terminate()
        self.root.destroy()


def main():
    priority.boost_process()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
