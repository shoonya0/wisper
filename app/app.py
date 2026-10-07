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
import priority
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

        root.title("Wisper — local speech-to-text (RX 580 · Vulkan)")
        root.geometry("940x640")
        root.minsize(640, 420)

        self._apply_theme(root)
        self._build_controls(root)
        self._build_transcript(root)
        self._build_status(root)

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()
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

    def _build_controls(self, root):
        bar = ttk.Frame(root, padding=8)
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
        row2 = ttk.Frame(root, padding=(8, 0))
        row2.pack(fill="x")
        self.device_label = ttk.Label(row2, text="Device:")
        self.device_var = tk.StringVar()
        self.device_box = ttk.Combobox(row2, textvariable=self.device_var,
                                       state="readonly", width=52)
        self.file_btn = ttk.Button(row2, text="Choose audio file…", command=self.pick_file)
        self.file_label = ttk.Label(row2, text="No file selected.")
        self._row2 = row2

        actions = ttk.Frame(root, padding=(8, 6))
        actions.pack(fill="x")
        ttk.Button(actions, text="Copy all", command=self.copy_all).pack(side="right")
        ttk.Button(actions, text="Clear", command=self.clear).pack(side="right", padx=4)
        ttk.Button(actions, text="Save…", command=self.save).pack(side="right")

    def _build_transcript(self, root):
        # Read-only for the user: starts disabled; only the app writes to it
        # (via _write_locked). Text stays selectable so Ctrl+C / Copy still work.
        self.text = ScrolledText(
            root, wrap="word", font=("Segoe UI", 12), padx=10, pady=10,
            bg=DARK["surface"], fg=DARK["fg"], insertbackground=DARK["fg"],
            selectbackground=DARK["sel"], selectforeground=DARK["fg"],
            borderwidth=0, highlightthickness=1,
            highlightbackground=DARK["border"], highlightcolor=DARK["border"])
        self.text.pack(fill="both", expand=True, padx=8)
        self.text.configure(state="disabled")
        # ScrolledText's scrollbar is a classic tk.Scrollbar; tint it to match.
        try:
            self.text.vbar.configure(
                background=DARK["field"], troughcolor=DARK["bg"],
                activebackground=DARK["accent"], borderwidth=0,
                highlightthickness=0)
        except Exception:
            pass
        self.text.bind("<Control-a>", self._select_all)
        self.text.bind("<Control-c>", lambda e: self.text.event_generate("<<Copy>>"))

    def _build_status(self, root):
        status = ttk.Frame(root, padding=(8, 4))
        status.pack(fill="x")
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
        path = filedialog.asksaveasfilename(defaultextension=".txt",
                                            filetypes=[("Text", "*.txt")])
        if path:
            Path(path).write_text(self.text.get("1.0", "end-1c"), encoding="utf-8")
            self.flash(f"Saved to {path}")

    def flash(self, message, seconds=3):
        self.status_var.set(message)
        self.flash_until = time.time() + seconds

    def _select_all(self, event=None):
        self.text.tag_add("sel", "1.0", "end-1c")
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
            total = len(audio)
            windows = list(audio_io.split_windows(audio))
            self.results.put(("text", f"\n\n--- {Path(path).name} ---\n"))
            for start, chunk in windows:
                text = model.transcribe(chunk, self.language)
                if text and not is_junk(text):
                    self.results.put(("text", text + " "))
                pct = min(100, int(100 * (start + len(chunk)) / total))
                self.results.put(("progress", pct))
            self.results.put(("done", None))
        except Exception as e:
            self.results.put(("error", f"File transcription failed: {e}"))
        finally:
            self.busy = False

    # --------------------------------------------------------------- UI loop

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

        self.level_bar["value"] = self.capture.level if self.capture else 0
        self.root.after(100, self._poll)

    def on_close(self):
        if self.capture:
            self.capture.stop()
        self.jobs.put(("stop",))
        self.pa.terminate()
        self.root.destroy()


def main():
    priority.boost_process()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
