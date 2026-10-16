"""Wisper — local speech-to-text for the AMD RX 580 (whisper.cpp + Vulkan).

Three modes over one GPU-resident model:
  • Dictation   — transcribe your microphone as you speak (low latency).
  • Live caption — transcribe desktop/meeting audio (WASAPI loopback).
  • File        — transcribe an audio file, text appearing progressively.

The text is typed into the DeepSeek terminal (the `deepseek` CLI in a pseudo-console) in the
left pane; Wisper never presses Enter (spec 2026-10-12-deepseek-terminal). Each answer
`deepseek` finishes comes back through a Stop hook (answers.py) and is narrated.

The Whisper model is loaded once and kept in GPU memory by a single worker
thread (whisper contexts are not thread safe, so only that thread touches it).
"""

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import numpy as np

import answers
import audio_io
import capture
import channels
import narrator
import playback
import priority
import terminal
import tts
from terminal_view import TerminalView
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
DEFAULT_MODE = "Live captions (desktop audio)"           # user decision, 2026-10-11
DEFAULT_MODEL = {
    "Dictation (microphone)": "small.en — balanced",
    "Live captions (desktop audio)": "small.en — balanced",   # user decision, 2026-10-11
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
PASS_ERROR = "Mic to call stopped"                       # TTS status only, no dialog (N8 rule 3.4)
STT_PAUSED = "Speech to text paused while narrating."   # D9: listening and narrating take turns
CABLE_SETUP = (
    "To let a call hear the narration (Only others / Both):\n\n"
    "1. Install VB-Audio Virtual Cable (free, vb-audio.com/Cable): run the setup as "
    "administrator, then reboot.\n"
    "2. In Wisper, choose \"CABLE Input (VB-Audio Virtual Cable)\" as Others. Wisper picks it "
    "by itself when it finds it at start-up.\n"
    "3. In Discord, Zoom or Meet, choose \"CABLE Output (VB-Audio Virtual Cable)\" as the "
    "microphone (Meet: ⋮ → Settings → Audio → Microphone; \"Default\" is your real mic). "
    "Restart the browser if CABLE Output isn't listed.\n\n"
    "Your voice: the call app now listens to the cable, not your microphone, so Wisper "
    "sends your microphone into the cable too while \"Send my mic to the call\" is ticked "
    "(on by default when a cable is found). Pick your microphone under Mic.\n\n"
    "Use headphones: with speakers, your mic also picks up the narration and the call hears "
    "it twice.")

# DeepSeek terminal (spec 2026-10-12-deepseek-terminal): the user's `deepseek` profile function,
# run as it is (D3) in a gitignored folder of the project (D4), walled off from Wisper's own files (D12).
WORKSPACE = Path(__file__).resolve().parent.parent / "AI_workspace"
HOOK_SCRIPT = Path(__file__).resolve().parent / "answers.py"
DEEPSEEK_ENDED = "DeepSeek ended. Press Enter to start it again."
DEEPSEEK_MISSING = "`deepseek` wasn't found: it's a function in your PowerShell profile."
NOT_RECOGNIZED = "is not recognized"                     # PowerShell's error for an unknown command
TERMINAL_MS = 16                                         # redraw timer: a key shows within ~16 ms (spec §7.4)
FILE_WORDS = 100                                         # File mode types this many words, then stops (D8)
FILE_LIMIT = f"File: typed the first {FILE_WORDS} words."
FILE_DONE = {"limit": FILE_LIMIT, "stopped": STT_PAUSED, None: "File transcription complete."}

# Ear channels (spec 2026-10-15-ear-channels §3.1, §5.5): each app in the left ear, the right ear or both.
EAR_STOPPED = "Ear channels stopped"                    # status line, no dialog (rule 3.2.9)
EAR_OFF = "Ear channels are off"                        # the router couldn't be made (journal unreadable)
EAR_SEND_MS = 50                                        # a dragged scale sends at most ~20 changes/s (§3.1)


def make_ear_router(on_update, on_error):
    """The real router (§5.5); tests replace it with a fake. Raises OSError when the journal can't be read."""
    return channels.Router(channels.WasapiAudio(), channels.Journal(channels.journal_path()), on_update, on_error)



def deepseek_argv(settings=None):
    """PowerShell runs the profile's `deepseek` function; each argument is single-quoted (§4.1)."""
    command = "deepseek"
    if settings is not None:
        command += " '--settings' '" + str(settings).replace("'", "''") + "'"
    return ["powershell.exe", "-NoLogo", "-Command", command]


def prepare_workspace(path):
    """Create the workspace as its own git repo (D12): Claude Code takes the git root as the project,
    so `deepseek` doesn't load Wisper's skills, agents, `.mcp.json` or git status. No git: it runs anyway."""
    path.mkdir(exist_ok=True)
    if not (path / ".git").exists():
        try:
            subprocess.run(["git", "init", "-q"], cwd=path, capture_output=True, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            pass


def claude_md_excludes(workspace):
    """`claudeMdExcludes` for every folder above the workspace (D12): Claude Code reads CLAUDE.md from
    each parent folder up to the drive, so without these it would read Wisper's. Its own still load."""
    patterns = []
    for folder in workspace.parents:
        base = folder.as_posix().rstrip("/")
        patterns += [f"{base}/CLAUDE.md", f"{base}/CLAUDE.local.md", f"{base}/.claude/CLAUDE.md",
                     f"{base}/.claude/rules/**"]
    return patterns


def hook_python():
    """python.exe for the hook: under pythonw.exe, the python.exe beside it (it reads stdin)."""
    exe = Path(sys.executable)
    console = exe.with_name("python.exe")
    return console if exe.name.lower() == "pythonw.exe" and console.exists() else exe


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
        self.last_text = ""               # prompt context for the next chunk (spec §4.3: unchanged)
        self.file_stop = threading.Event()  # D9: the narration started, the file job ends (§3.2)
        self.terminal = None              # the DeepSeek terminal (terminal.Terminal); None until started
        self._terminal_run = 0            # which start the "terminal_ended" results belong to

        # Worker owns the model. Jobs: ("model", path) | ("audio", arr, prompt)
        #                              | ("file", path) | ("stop",)
        self.jobs = queue.Queue()
        self.results = queue.Queue()     # ("ready"|"text"|"status"|"error"|"progress"|"done"
        #                                   | "terminal_ended" | "ai_answer", payload)
        self.loaded_model_path = None
        self.want_model_path = None

        # TTS worker owns the Kokoro engine (spec §5.4). Jobs: ("load",)
        # | ("speak", gen, text, voice, speed, devices) | ("stop",)
        self.tts_jobs = queue.Queue()
        self.tts_results = queue.Queue()  # ("tts_ready", voices) | ("tts_missing"|"tts_load_error", msg)
        #                                   | ("tts_done", gen, stopped) | ("tts_error", gen, msg)
        #                                   | ("tts_progress", gen, i, n) | ("pass_error", run_id, msg)
        self.speaking = False             # True from Speak until the narration ends, paused or not
        self.tts_paused = False           # N9: spec 2026-10-11-narration-pause.md
        self._tts_progress = ""           # " i/n" of the piece playing, for the paused status
        self._tts_spans = None            # N10: where each piece of the snapshot is in the box
        self._tts_snapshot = ""
        self.tts_gen = None               # generation of the narration the UI is showing
        self._narrating_gen = None        # TTS worker only
        self._device_error = None
        self.narrator = narrator.Narrator(
            self._tts_synth, self._tts_play, tts.split_sentences,
            on_done=lambda stopped: self.tts_results.put(("tts_done", self._narrating_gen, stopped)),
            on_error=lambda msg: self.tts_results.put(("tts_error", self._narrating_gen, msg)),
            on_progress=lambda i, n: self.tts_results.put(("tts_progress", self._narrating_gen, i, n)))
        self.player = playback.Player(lambda device: playback.PaStream(self.pa, device), self._on_device_error)
        # N8: the real mic into the cable on its own stream; Windows mixes it with the narration.
        self.passthrough = playback.Passthrough(
            lambda device: playback.PaInput(self.pa, device),
            lambda device: playback.PaStream(self.pa, device, block_s=playback.PASS_BLOCK_S),
            lambda name, e, run: self.tts_results.put(("pass_error", run, f"{PASS_ERROR}: {name}: {e}")))

        root.title("Wisper — local speech-to-text (RX 580 · Vulkan)")
        root.geometry("1440x780")
        root.minsize(STT_MIN_W + TTS_MIN_W + SASH_W, 520)   # +100 px for the ear channels strip

        # P4 (spec §4.4): `deepseek`'s Stop hook sends each final answer here; _poll narrates it.
        self.inbox = answers.Inbox(lambda text: self.results.put(("ai_answer", text)))
        self.hook_settings = self._write_hook_settings()

        self._apply_theme(root)
        self._build_ears(root)            # before the panes, so it keeps its rows at the bottom
        stt_pane, tts_pane = self._build_panes(root)
        self._build_controls(stt_pane)
        self._build_status(stt_pane)      # before the terminal so it keeps its row
        self._build_terminal(stt_pane)
        self._build_tts_pane(tts_pane)

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()
        self.tts_worker = threading.Thread(target=self._tts_worker_loop, daemon=True)
        self.tts_worker.start()
        self.tts_jobs.put(("load",))   # in the background: the window opens at once, STT doesn't wait
        if self.ear_router is not None:
            self.ear_router.start()
        self._on_mode_change()
        self._request_model()       # load the initial model
        self._start_terminal()
        self._poll()
        self._draw_terminal()

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

        style.configure("TCheckbutton", background=d["bg"], foreground=d["fg"],
                        indicatorbackground=d["field"], indicatorforeground=d["fg"])
        style.map("TCheckbutton", background=[("active", d["bg"])],
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
        self.stop_btn = ttk.Button(bar, text="⏹  Stop", width=8, state="disabled", command=self.tts_stop)
        self.stop_btn.pack(side="left", padx=(4, 0))

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
        # N10: pieces already played are dimmed, the one playing is highlighted; colour only.
        self.tts_text.tag_configure("narrated", foreground=DARK["muted"])
        self.tts_text.tag_configure("speaking", background=DARK["sel"])
        self.tts_text.tag_raise("sel")
        self.tts_text.bind("<Control-a>", self._select_all)
        self.tts_text.bind("<Control-Return>", self._speak_key)
        self.tts_text.bind("<KeyRelease-Return>", self._speak_key_released)
        self._speak_key_held = False

    def _speak_key(self, event):
        """Ctrl+Enter follows the Speak/Pause/Resume button (rule 3.3.4, N9), never a newline.

        Held down, Windows repeats the key press (without releases): only the first counts.
        """
        if not self._speak_key_held and self.speak_btn.instate(["!disabled"]):
            self._speak_key_held = True
            self.tts_toggle()
        return "break"

    def _speak_key_released(self, event):
        self._speak_key_held = False

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
        for name in ("Me:", "Others:", "Mic:"):
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

        # N8: the mic the call should hear (WASAPI, like the outputs; cables are left out).
        self.mics = playback.list_inputs(self.pa)
        self.pass_var = tk.BooleanVar(value=cable is not None and bool(self.mics))   # user decision, 2026-10-10
        self.pass_check = ttk.Checkbutton(rows["Mic:"], text="Send my mic to the call", variable=self.pass_var,
                                          command=self._on_passthrough_change)
        self.pass_check.pack(side="right")
        self.mic_box = ttk.Combobox(rows["Mic:"], values=[d["label"] for d in self.mics], state="readonly",
                                    width=20)
        self.mic_box.pack(side="left", padx=4, fill="x", expand=True)
        if self.mics:
            self.mic_box.current(0)       # list_sources puts the Windows default first
        self.mic_box.bind("<<ComboboxSelected>>", lambda e: self._update_passthrough())
        self.others_box.bind("<<ComboboxSelected>>", lambda e: self._update_passthrough(), add="+")
        self._on_output_change()
        self._update_passthrough()

    def _on_output_change(self):
        """A mode change stops the narration (rule 3.3.5)."""
        self._update_others_state()
        self.tts_stop()

    def _on_passthrough_change(self):
        self._update_others_state()
        self._update_passthrough()

    def _update_others_state(self):
        """Others is used by Only others, Both and the mic pass-through (N8)."""
        used = self.output_var.get() != "me" or self.pass_var.get()
        self.others_box.config(state="readonly" if used else "disabled")

    def _update_passthrough(self):
        """(Re)start the mic pass-through when it's on and both devices are chosen; else stop it."""
        self.passthrough.stop()
        if not self.pass_var.get():
            return
        mic = self.mics[self.mic_box.current()] if self.mic_box.current() >= 0 else None
        cable = self._chosen_output(self.others_box)
        if mic is not None and cable is not None:
            self.passthrough.start(mic, cable)

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
        self.mode_var = tk.StringVar(value=DEFAULT_MODE)
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

    def _build_terminal(self, parent):
        # The DeepSeek terminal takes the transcript box's place (D2): speech is typed into it.
        self.term_view = TerminalView(
            parent, {"fg": DARK["fg"], "bg": DARK["surface"], "sel": DARK["sel"], "border": DARK["border"]},
            on_key=self._terminal_key, on_paste=self._terminal_paste,
            on_scroll=lambda lines: self.terminal and self.terminal.scroll(lines),
            on_resize=lambda lines, columns: self.terminal and self.terminal.resize(lines, columns))
        self.term_view.widget.pack(fill="both", expand=True, padx=8, pady=(6, 0))

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

    # ------------------------------------------------------------ ear channels

    def _build_ears(self, root):
        """The ear channels strip across both panes (spec 2026-10-15-ear-channels §3.1). The router runs on its own
        thread; its updates come back through `ear_results`, drained by _poll (§5.2: no Tk call off this thread)."""
        self.ear_results = queue.Queue()  # ("ear_update", device, apps, warnings) | ("ear_error", msg)
        self.ear_sel = {channels.LEFT: channels.Selection(), channels.RIGHT: channels.Selection()}
        self.ear_apps = []                # channels.App rows from the last update
        self.ear_app_vols = {}            # app key -> 0..100, as the user set it (D9)
        self.ear_app_key = None           # the app the App scale is for
        self._ear_pending = {}            # ("volume", side) | ("app", key) -> 0..100, sent at the next tick
        self._ear_send_id = None
        self._ear_menu_vars = {}

        strip = ttk.Frame(root, padding=(8, 2, 8, 6))
        strip.pack(side="bottom", fill="x")
        tk.Frame(root, height=1, bg=DARK["border"]).pack(side="bottom", fill="x")
        self.ear_strip = strip

        head = ttk.Frame(strip)
        head.pack(fill="x")
        ttk.Label(head, text="Ear channels", style="Header.TLabel").pack(side="left")
        self.ear_device_var = tk.StringVar(value="Earphones: …")
        ttk.Label(head, textvariable=self.ear_device_var).pack(side="left", padx=(12, 0))
        self.ear_reset_btn = ttk.Button(head, text="Reset", command=self.ear_reset)
        self.ear_reset_btn.pack(side="right")
        self.ear_status_var = tk.StringVar()
        ttk.Label(head, textvariable=self.ear_status_var).pack(side="right", padx=8)

        self.ear_buttons, self.ear_menus, self.ear_scales, self.ear_vol_vars = {}, {}, {}, {}
        for side, label in ((channels.LEFT, "Left ear:"), (channels.RIGHT, "Right ear:")):
            row = ttk.Frame(strip)
            row.pack(fill="x", pady=(2, 0))
            ttk.Label(row, text=label, width=10).pack(side="left")
            menu = tk.Menu(row, tearoff=0, bg=DARK["surface"], fg=DARK["fg"], activebackground=DARK["sel"],
                           activeforeground=DARK["fg"], selectcolor=DARK["fg"])
            button = ttk.Menubutton(row, text=channels.ALL_LABEL, menu=menu, width=44)
            button.pack(side="left")
            self.ear_buttons[side], self.ear_menus[side] = button, menu
            self.ear_scales[side], self.ear_vol_vars[side] = self._ear_scale_row(row, ("volume", side))

        row = ttk.Frame(strip)
        row.pack(fill="x", pady=(2, 0))
        ttk.Label(row, text="App:", width=10).pack(side="left")
        self.ear_app_box = ttk.Combobox(row, state="readonly", width=44)
        self.ear_app_box.pack(side="left")
        self.ear_app_box.bind("<<ComboboxSelected>>", lambda e: self._ear_pick_app())
        self.ear_app_scale, self.ear_app_vol_var = self._ear_scale_row(row, ("app", None))

        try:
            self.ear_router = make_ear_router(lambda *update: self.ear_results.put(("ear_update", *update)),
                                              lambda msg: self.ear_results.put(("ear_error", msg)))
        except (OSError, ValueError) as e:
            self.ear_router = None        # e.g. the restore journal can't be read: never write over it
            self.ear_status_var.set(f"{EAR_OFF}: {e}")
            self._ear_enable(False, keep_reset=False)
        self._ear_rebuild()

    def _ear_enable(self, on, keep_reset=True):
        """Menus and scales on or off (§5.3: off while the earphones aren't stereo); Reset stays usable then."""
        for w in (*self.ear_buttons.values(), *self.ear_scales.values(), self.ear_app_box, self.ear_app_scale,
                  *([] if keep_reset else [self.ear_reset_btn])):
            w.state(["!disabled"] if on else ["disabled"])

    def _ear_scale_row(self, row, what):
        ttk.Label(row, text="  Volume").pack(side="left")
        var = tk.StringVar(value="100 %")
        scale = ttk.Scale(row, from_=0, to=100, value=100, length=180,
                          command=lambda value: self._ear_scale(what, value))
        scale.pack(side="left", padx=6)
        ttk.Label(row, textvariable=var, width=6).pack(side="left")
        return scale, var

    def _ear_scale(self, what, value):
        """A scale moved: show it at once, send it at most every EAR_SEND_MS (§3.1)."""
        v = round(float(value))
        if what[0] == "app":
            if self.ear_app_key is None:
                return
            what = ("app", self.ear_app_key)
            self.ear_app_vols[self.ear_app_key] = v
            self.ear_app_vol_var.set(f"{v} %")
        else:
            self.ear_vol_vars[what[1]].set(f"{v} %")
        self._ear_pending[what] = v
        if self._ear_send_id is None:
            self._ear_send_id = self.root.after(EAR_SEND_MS, self._ear_send)

    def _ear_send(self):
        self._ear_send_id = None
        pending, self._ear_pending = self._ear_pending, {}
        if self.ear_router is None:
            return
        for (kind, arg), v in pending.items():
            if kind == "volume":
                self.ear_router.volume(arg, v / 100)
            else:
                self.ear_router.app_volume(arg, v / 100)

    def _ear_pick_app(self):
        i = self.ear_app_box.current()
        if i < 0:
            return
        self.ear_app_key = self._ear_app_keys[i]
        v = self.ear_app_vols.get(self.ear_app_key, 100)
        self.ear_app_scale.set(v)
        self.ear_app_vol_var.set(f"{v} %")

    def _ear_toggle(self, side, key):
        """A menu item was clicked: rule 3.2.5 on this ear's choice, then tell the router."""
        self.ear_sel[side] = self.ear_sel[side].toggle(key)
        if self.ear_router is not None:
            self.ear_router.choose(side, self.ear_sel[side])
        self._ear_rebuild()

    def _ear_label(self, side):
        sel = self.ear_sel[side]
        if sel.is_all:
            return channels.ALL_LABEL
        names = {a.key: a.name for a in self.ear_apps}
        return ", ".join(sorted((names.get(k, k) for k in sel.keys), key=str.casefold))

    def _ear_rebuild(self):
        """Both menus from the last update and the current choices (rules 3.2.6, 3.2.7), and the App list."""
        for side, menu in self.ear_menus.items():
            menu.delete(0, "end")
            self._ear_menu_vars[side] = []    # the menu's check marks live as long as these do
            for item in channels.menu_items(self.ear_apps, self.ear_sel[side]):
                if item is None:
                    menu.add_separator()
                    continue
                var = tk.BooleanVar(value=item.checked)
                self._ear_menu_vars[side].append(var)
                menu.add_checkbutton(label=item.label, variable=var,
                                     command=lambda s=side, k=item.key: self._ear_toggle(s, k))
            self.ear_buttons[side].config(text=self._ear_label(side))
        apps = sorted(self.ear_apps, key=lambda a: (a.name.casefold(), a.key))
        self._ear_app_keys = [a.key for a in apps]
        self.ear_app_box.config(values=[a.name + ("" if a.running else channels.NOT_RUNNING) for a in apps])
        if self.ear_app_key in self._ear_app_keys:
            self.ear_app_box.current(self._ear_app_keys.index(self.ear_app_key))

    def ear_reset(self):
        """Both ears back to All apps at 100 %, every app at 100 %; the router puts every app back (§5.4)."""
        if self.ear_router is not None:
            self.ear_router.reset()
        self.ear_sel = {channels.LEFT: channels.Selection(), channels.RIGHT: channels.Selection()}
        self.ear_app_vols, self._ear_pending = {}, {}
        for scale, var in (*zip(self.ear_scales.values(), self.ear_vol_vars.values(), strict=True),
                           (self.ear_app_scale, self.ear_app_vol_var)):
            scale.set(100)
            var.set("100 %")
        self._ear_pending = {}            # scale.set may have queued a send; Reset already says it all
        self.ear_status_var.set("")
        self._ear_rebuild()

    def _poll_ears(self):
        while not self.ear_results.empty():
            kind, *payload = self.ear_results.get()
            if kind == "ear_update":
                device, apps, warnings = payload
                self.ear_device_var.set(f"Earphones: {device}")
                self.ear_apps = list(apps)
                self.ear_status_var.set(warnings[0] if warnings else "")
                self._ear_enable(channels.NOT_STEREO not in warnings)
                self._ear_rebuild()
            elif kind == "ear_error":     # rule 3.2.9: the status line, never a dialog
                self.ear_status_var.set(f"{EAR_STOPPED}: {payload[0]}")

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
            self._stop_capture()
        else:
            if not self.devices:
                messagebox.showerror("No device", "No audio device found for this mode.")
                return
            self._pause_narration()
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

    def _stop_capture(self):
        self.transcribing = False
        if self.capture:
            self.capture.stop()
            self.capture = None
        self.start_btn.config(text="▶  Start")

    def _stop_listening(self):
        """D9: the narration is about to start or resume, so speech to text stops (§3.2, §4.6).

        A file job ends at its next step; the words already typed stay."""
        if self.transcribing:
            self._stop_capture()
            self.flash(STT_PAUSED, 5)
        self.file_stop.set()              # read only by a file job; start_file clears it

    def _pause_narration(self):
        """D9: listening is about to start, so a playing narration pauses; ▶ Resume continues it."""
        if self.speaking and not self.tts_paused:
            self.tts_pause()

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
        self._pause_narration()
        self.file_stop.clear()
        self.start_btn.config(state="disabled")
        self.jobs.put(("file", self.selected_file))

    # --------------------------------------------------------------- DeepSeek terminal

    def _start_terminal(self):
        """Start `deepseek` in the terminal (at start-up, and on Enter after it ended)."""
        self._terminal_run += 1
        run = self._terminal_run
        lines, columns = self.term_view.size
        try:
            prepare_workspace(WORKSPACE)
            self.terminal = terminal.Terminal(
                deepseek_argv(self.hook_settings), str(WORKSPACE), lines=lines, columns=columns,
                on_exit=lambda: self.results.put(("terminal_ended", run)))
        except Exception as e:            # no powershell.exe, no pseudo-console: say so in its place
            self.terminal = None
            self.term_view.message(f"Couldn't start DeepSeek: {e}")

    def _write_hook_settings(self):
        """The `--settings` file with the Stop hook (§4.4), outside the workspace `deepseek` sees.

        Returns its path, or None if it can't be written: `deepseek` then runs without narration."""
        path = Path(tempfile.gettempdir()) / f"wisper-deepseek-hook-{os.getpid()}.json"
        settings = {**answers.hook_settings(hook_python(), HOOK_SCRIPT, self.inbox.port, self.inbox.token),
                    "claudeMdExcludes": claude_md_excludes(WORKSPACE)}
        try:
            path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        except OSError:
            return None
        return path

    def _narrate_answer(self, markdown):
        """A DeepSeek answer replaces the narration text and is spoken from the start (§4.5)."""
        text = answers.plain_text(markdown)
        if not text:
            return                        # e.g. an answer of only Markdown marks: the box is unchanged
        self.tts_stop()                   # playing or paused: it ends, the new answer wins
        self.tts_text.delete("1.0", "end")
        self.tts_text.insert("1.0", text)
        if self.speak_btn.instate(["!disabled"]):
            self.tts_toggle()
        else:                             # Kokoro missing or still loading: the text waits in the box
            self.tts_status_var.set("DeepSeek's answer is in the box; narration isn't ready.")

    def _terminal_ended(self, run):
        term = self.terminal
        if term is None or run != self._terminal_run:
            return                        # an older run, already replaced
        missing = any(NOT_RECOGNIZED in line and "deepseek" in line for line in term.text())
        term.notice(DEEPSEEK_MISSING if missing else DEEPSEEK_ENDED)

    def _terminal_key(self, keysym, char, state):
        term = self.terminal
        if term is not None and term.alive:
            data = terminal.key_bytes(keysym, char, state)
            if data:
                term.write(data)
        elif keysym == "Return":
            if term is not None:
                term.close()
            self._start_terminal()

    def _terminal_paste(self, text):
        if self.terminal is not None and self.terminal.alive:
            self.terminal.paste(text)

    def _type_speech(self, text):
        """Type a transcribed chunk at the end of `deepseek`'s input line, never Enter (D7)."""
        if self.terminal is not None and self.terminal.alive:
            self.terminal.type_text(text)
        else:
            self.flash("DeepSeek isn't running: press Enter in the terminal to start it.", 5)

    def _draw_terminal(self):
        if self.terminal is not None:
            self.term_view.draw(self.terminal.snapshot())
        self.root.after(TERMINAL_MS, self._draw_terminal)

    def tts_copy_all(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.tts_text.get("1.0", "end-1c"))
        self.tts_status_var.set("Copied narration text to clipboard.")

    def tts_clear(self):
        self.tts_stop()                   # rule 3.3.2: Clear stops the narration, then empties
        self.tts_text.delete("1.0", "end")

    def tts_toggle(self):
        """The main button: Speak, then Pause and Resume until the narration ends (N9)."""
        if self.speaking:
            (self.tts_resume if self.tts_paused else self.tts_pause)()
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
        self._stop_listening()
        self._tts_snapshot, self._tts_spans = text, tts.piece_spans(text)
        self._clear_marks()
        self.tts_gen = self.narrator.begin()
        self.player.resume()              # a pause left by a stopped narration never carries over
        self.tts_jobs.put(("speak", self.tts_gen, text, self.voice_var.get(),
                           float(self.speed_var.get()), devices))
        self.speaking = True
        self.tts_paused = False
        self._tts_progress = ""
        self.speak_btn.config(text="⏸  Pause")
        self.stop_btn.config(state="normal")
        self.tts_status_var.set("Speaking…")

    def tts_pause(self):
        """Silence every device within one block; Resume continues from there (N9)."""
        self.player.pause()
        self.tts_paused = True
        self.speak_btn.config(text="▶  Resume")
        self.tts_status_var.set(f"Paused{self._tts_progress}.")

    def tts_resume(self):
        self._stop_listening()
        self.player.resume()
        self.tts_paused = False
        self.speak_btn.config(text="⏸  Pause")
        self.tts_status_var.set(f"Speaking{self._tts_progress}…")

    def tts_stop(self):
        """Stop the narration, playing or paused (Stop, Clear, a voice/speed/mode/device change).

        Safe when nothing plays."""
        if not self.speaking:
            return
        self.narrator.stop()
        self.player.stop()                # silences every device within one block
        self._narration_ended("Narration stopped.")

    def _narration_ended(self, message):
        self.speaking = False
        self.tts_paused = False
        self.speak_btn.config(text="🔊  Speak")
        self.stop_btn.config(state="disabled")
        self.tts_status_var.set(message)
        self._clear_marks()               # back to the start (N10)

    def _mark_piece(self, i, n):
        """Mark pieces 1..i-1 narrated and piece i speaking, while the box matches the snapshot."""
        self._clear_marks()
        spans = self._tts_spans
        if not spans or len(spans) != n or self.tts_text.get("1.0", "end-1c") != self._tts_snapshot:
            self._tts_spans = None        # edited (or unmatched): stop marking this narration
            return
        if i > 1:                         # Tk's "+Nc" counts like Python offsets, emoji too (VERIFIED)
            self.tts_text.tag_add("narrated", "1.0", f"1.0 + {spans[i - 2][1]}c")
        start, end = spans[i - 1]
        self.tts_text.tag_add("speaking", f"1.0 + {start}c", f"1.0 + {end}c")

    def _clear_marks(self):
        for tag in ("narrated", "speaking"):
            self.tts_text.tag_remove(tag, "1.0", "end")

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
            typed = 0                     # words typed so far; the file stops after FILE_WORDS (D8)
            full = False

            def on_text(text):
                nonlocal typed, full
                text = text.strip()
                if full or not text or is_junk(text):
                    return
                words = text.split()
                if typed + len(words) > FILE_WORDS:   # a word past the limit: the file has more
                    full = True
                    words = words[:FILE_WORDS - typed]
                    if not words:
                        return
                typed += len(words)
                self.results.put(("text", " ".join(words) + " "))

            # One pass over the whole file: whisper.cpp seeks by its own timestamps, so
            # no words are cut or repeated at window edges (known issue 1).
            model.transcribe_long(audio, self.language, on_text,
                                  lambda pct: self.results.put(("progress", pct)),
                                  should_stop=lambda: full or self.file_stop.is_set())
            if full:
                self.results.put(("done", "limit"))
            elif self.file_stop.is_set():
                self.results.put(("done", "stopped"))
            else:
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
            elif kind == "pass_error":    # N8 rule 3.4: uncheck, status line, no dialog
                if payload[0] != self.passthrough.run_id:
                    continue              # from a run the user already replaced
                self.pass_var.set(False)
                self._update_others_state()
                self.passthrough.stop()
                self.tts_status_var.set(payload[1])
            elif payload[0] != self.tts_gen or not self.speaking:
                continue                  # a narration the user already stopped
            elif kind == "tts_progress":
                self._tts_progress = f" {payload[1]}/{payload[2]}"
                self._mark_piece(payload[1], payload[2])
                if self.tts_paused and self.tts_status_var.get().startswith("Paused"):
                    self.tts_status_var.set(f"Paused{self._tts_progress}.")   # the next piece waits
                    continue
                if not self.tts_status_var.get().startswith("Speaking"):
                    continue              # keep a message shown meanwhile (a mic error, N8; "Paused", N9)
                self.tts_status_var.set(f"Speaking{self._tts_progress}…")
            elif kind == "tts_done":      # a stopped narration was already ended by tts_stop()
                self._narration_ended("Narration complete.")
            elif kind == "tts_error":
                self._narration_ended(payload[1])
                if not payload[1].startswith(DEVICE_ERROR):
                    messagebox.showerror("Wisper", payload[1])

    def _poll(self):
        while not self.results.empty():
            kind, payload = self.results.get()
            if kind == "text":
                self._type_speech(payload)
            elif kind == "terminal_ended":
                self._terminal_ended(payload)
            elif kind == "ai_answer":
                self._narrate_answer(payload)
            elif kind == "ready":
                self.loaded_model_path = self.want_model_path
                self.start_btn.config(state="normal")
                self.flash("Model ready on GPU.", 2)
            elif kind == "progress":
                self.flash(f"Transcribing file… {payload}%", 60)
            elif kind == "done":
                self.start_btn.config(state="normal")
                self.flash(FILE_DONE[payload], 4)
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
        self._poll_ears()
        self.level_bar["value"] = self.capture.level if self.capture else 0
        self.root.after(100, self._poll)

    def on_close(self):
        if self.capture:
            self.capture.stop()
        if self.terminal is not None:
            self.terminal.close()         # ends `deepseek` and what it started in the pseudo-console
        if self.ear_router is not None:
            self.ear_router.close()       # puts every app back (§5.4); joined, 2 s cap
        self.inbox.close()
        if self.hook_settings is not None:
            self.hook_settings.unlink(missing_ok=True)
        self.jobs.put(("stop",))
        self.narrator.stop()
        self.player.stop()
        self.tts_jobs.put(("stop",))
        # The TTS worker closes its streams before the PyAudio they belong to goes away; a
        # synthesis in progress (at most ~3 s) isn't waited for beyond this.
        self.tts_worker.join(timeout=1)
        self.passthrough.close()          # waits for every run: its streams belong to the PyAudio below
        self.pa.terminate()
        self.root.destroy()


def main():
    priority.kill_children_with_me()     # D10: `deepseek` and all it starts end with Wisper, however it ends
    priority.boost_process()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
