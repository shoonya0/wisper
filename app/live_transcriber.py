"""Live desktop-audio transcriber.

Captures whatever is playing on a speaker (WASAPI loopback), splits it into
chunks at pauses in speech, and transcribes each chunk with whisper.cpp
(large-v3-turbo on the GPU via Vulkan), loaded in-process through whisper.dll.
"""

import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import numpy as np
import pyaudiowpatch as pyaudio
from scipy.signal import resample_poly

from whisper_native import Whisper

WHISPER_DIR = Path(__file__).resolve().parent.parent / "whisper.cpp"
DLL_DIR = WHISPER_DIR / "build" / "bin" / "Release"
MODEL = WHISPER_DIR / "models" / "ggml-large-v3-turbo-q5_0.bin"

TARGET_SR = 16000
MIN_CHUNK_S = 2.0        # don't cut a chunk shorter than this
MAX_CHUNK_S = 12.0       # always cut once a chunk gets this long
SILENCE_CUT_S = 0.6      # a pause this long ends a chunk
SILENCE_RMS = 0.006      # below this a block counts as silence
MIN_SPEECH_S = 0.4       # chunks with less loud audio than this are dropped

LANGUAGES = ["auto", "en", "hi", "es", "fr", "de", "ja", "zh", "ru", "pt", "it", "ko", "ar"]

# Whisper tends to invent these on music/noise; drop them when they are the whole chunk.
HALLUCINATIONS = {
    "thank you.", "thanks for watching!", "thank you for watching.",
    "thanks for watching.", "you", "bye.", ".",
}


# --------------------------------------------------------------------------- audio

def list_loopback_devices(pa):
    """Return loopback devices, with the default speaker's loopback first."""
    devices = list(pa.get_loopback_device_info_generator())
    try:
        wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_name = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])["name"]
        devices.sort(key=lambda d: not d["name"].startswith(default_name))
    except OSError:
        pass
    return devices


class LoopbackCapture:
    """Records a loopback device and emits speech chunks (16 kHz mono float32)."""

    def __init__(self, pa, device, on_chunk):
        self.pa = pa
        self.device = device
        self.on_chunk = on_chunk
        self.sr = int(device["defaultSampleRate"])
        self.channels = max(1, device["maxInputChannels"])
        self.blocks = queue.Queue()
        self.stream = None
        self.running = False
        self.thread = None
        self.level = 0.0

    def start(self):
        self.running = True
        self.stream = self.pa.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sr,
            input=True,
            input_device_index=self.device["index"],
            frames_per_buffer=int(self.sr * 0.05),
            stream_callback=self._callback,
        )
        self.thread = threading.Thread(target=self._segment_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        if self.thread:
            self.thread.join(timeout=2)

    def _callback(self, in_data, frame_count, time_info, status):
        self.blocks.put(in_data)
        return (None, pyaudio.paContinue)

    def _segment_loop(self):
        chunk, chunk_len, silence_len, speech_len = [], 0, 0, 0
        min_n, max_n = int(MIN_CHUNK_S * self.sr), int(MAX_CHUNK_S * self.sr)
        cut_n, speech_min_n = int(SILENCE_CUT_S * self.sr), int(MIN_SPEECH_S * self.sr)

        def flush():
            nonlocal chunk, chunk_len, silence_len, speech_len
            if chunk and speech_len >= speech_min_n:
                audio = np.concatenate(chunk)
                self.on_chunk(resample_poly(audio, TARGET_SR, self.sr).astype(np.float32))
            chunk, chunk_len, silence_len, speech_len = [], 0, 0, 0

        while self.running:
            try:
                raw = self.blocks.get(timeout=0.2)
            except queue.Empty:
                # Loopback delivers nothing while no app is playing sound: treat as a pause.
                self.level = 0.0
                if chunk_len >= min_n:
                    flush()
                continue
            block = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
            block = block.reshape(-1, self.channels).mean(axis=1)
            rms = float(np.sqrt(np.mean(block ** 2))) if block.size else 0.0
            self.level = rms

            if rms < SILENCE_RMS:
                if not chunk:
                    continue  # skip leading silence
                silence_len += len(block)
            else:
                silence_len = 0
                speech_len += len(block)
            chunk.append(block)
            chunk_len += len(block)

            if (chunk_len >= min_n and silence_len >= cut_n) or chunk_len >= max_n:
                flush()
        flush()


# --------------------------------------------------------------------------- GUI

class App:
    def __init__(self, root):
        self.root = root
        self.pa = pyaudio.PyAudio()
        self.capture = None
        self.chunks = queue.Queue()
        self.results = queue.Queue()
        self.transcribing = False
        self.model_ready = False
        self.busy = False
        self.last_text = ""
        self.flash_until = 0.0

        root.title("Live Desktop Transcriber — Whisper large-v3-turbo")
        root.geometry("900x620")
        root.minsize(600, 400)

        bar = ttk.Frame(root, padding=8)
        bar.pack(fill="x")

        self.toggle_btn = ttk.Button(bar, text="▶  Start", width=12, command=self.toggle, state="disabled")
        self.toggle_btn.pack(side="left")

        ttk.Label(bar, text="  Device:").pack(side="left")
        self.devices = list_loopback_devices(self.pa)
        self.device_var = tk.StringVar()
        self.device_box = ttk.Combobox(
            bar, textvariable=self.device_var, state="readonly", width=38,
            values=[d["name"].replace(" [Loopback]", "") for d in self.devices],
        )
        if self.devices:
            self.device_box.current(0)
        self.device_box.pack(side="left", padx=4)

        ttk.Label(bar, text="  Language:").pack(side="left")
        self.lang_var = tk.StringVar(value="auto")
        self.language = "auto"  # plain copy for the worker thread (Tk isn't thread safe)
        self.lang_var.trace_add("write", lambda *_: setattr(self, "language", self.lang_var.get().strip() or "auto"))
        ttk.Combobox(bar, textvariable=self.lang_var, values=LANGUAGES, width=6).pack(side="left", padx=4)

        ttk.Button(bar, text="Save…", command=self.save).pack(side="right")
        ttk.Button(bar, text="Clear", command=self.clear).pack(side="right", padx=4)
        ttk.Button(bar, text="Copy all", command=self.copy_all).pack(side="right")

        self.text = ScrolledText(root, wrap="word", font=("Segoe UI", 12), undo=True, padx=10, pady=10)
        self.text.pack(fill="both", expand=True, padx=8)
        self.text.bind("<Control-a>", self._select_all)
        self.text.bind("<Button-3>", self._context_menu)
        self.menu = tk.Menu(root, tearoff=0)
        self.menu.add_command(label="Copy", command=lambda: self.text.event_generate("<<Copy>>"))
        self.menu.add_command(label="Select all", command=lambda: self._select_all())
        self.menu.add_command(label="Copy all", command=self.copy_all)

        status = ttk.Frame(root, padding=(8, 4))
        status.pack(fill="x")
        self.status_var = tk.StringVar(value="Loading Whisper large-v3-turbo onto the GPU…")
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        self.level_bar = ttk.Progressbar(status, length=120, maximum=0.2)
        self.level_bar.pack(side="right")
        ttk.Label(status, text="Level ").pack(side="right")

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.worker = threading.Thread(target=self._transcribe_loop, daemon=True)
        self.worker.start()
        self._poll()

    # ---- worker thread (owns the model; whisper contexts are not thread safe)

    def _transcribe_loop(self):
        try:
            model = Whisper(DLL_DIR, MODEL)
            # Warm-up run: the first inference compiles GPU pipelines and is slow.
            model.transcribe(np.zeros(TARGET_SR, np.float32), "en")
        except Exception as e:
            self.results.put(("error", f"Could not load the model: {e}"))
            return
        self.results.put(("ready", None))

        while True:
            audio = self.chunks.get()
            if audio is None:
                break
            self.busy = True
            try:
                text = model.transcribe(audio, self.language, self.last_text[-200:])
                if text and not self._is_junk(text):
                    self.last_text += " " + text
                    self.results.put(("text", text))
            except Exception as e:
                self.results.put(("status", f"Transcription error: {e}"))
            finally:
                self.busy = False
        model.close()

    @staticmethod
    def _is_junk(text):
        t = text.strip().lower()
        return t in HALLUCINATIONS or (t.startswith("[") and t.endswith("]")) or (t.startswith("(") and t.endswith(")"))

    # ---- UI actions

    def toggle(self):
        if self.transcribing:
            self.transcribing = False
            self.capture.stop()
            self.capture = None
            self.toggle_btn.config(text="▶  Start")
            self.device_box.config(state="readonly")
        else:
            if not self.devices:
                messagebox.showerror("No device", "No loopback (speaker) device found.")
                return
            device = self.devices[self.device_box.current()]
            try:
                self.capture = LoopbackCapture(self.pa, device, self.chunks.put)
                self.capture.start()
            except Exception as e:
                messagebox.showerror("Audio error", str(e))
                self.capture = None
                return
            self.transcribing = True
            self.toggle_btn.config(text="⏸  Pause")
            self.device_box.config(state="disabled")

    def copy_all(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.text.get("1.0", "end-1c"))
        self.flash("Copied transcript to clipboard.")

    def clear(self):
        self.text.delete("1.0", "end")
        self.last_text = ""

    def save(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if path:
            Path(path).write_text(self.text.get("1.0", "end-1c"), encoding="utf-8")
            self.flash(f"Saved to {path}")

    def flash(self, message, seconds=3):
        self.status_var.set(message)
        self.flash_until = time.time() + seconds

    def _select_all(self, event=None):
        self.text.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _context_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    # ---- UI loop

    def _append(self, text):
        at_bottom = self.text.yview()[1] >= 0.999
        existing = self.text.get("1.0", "end-1c")
        sep = "" if not existing or existing.endswith(("\n", " ")) else " "
        self.text.insert("end", sep + text)
        if at_bottom:
            self.text.see("end")

    def _poll(self):
        while not self.results.empty():
            kind, payload = self.results.get()
            if kind == "text":
                self._append(payload)
            elif kind == "ready":
                self.model_ready = True
                self.toggle_btn.config(state="normal")
            elif kind == "error":
                self.status_var.set(payload)
                messagebox.showerror("Whisper", payload)
            elif kind == "status":
                self.flash(payload)

        if self.model_ready and time.time() > self.flash_until:
            pending = self.chunks.qsize() + (1 if self.busy else 0)
            state = "Listening" if self.transcribing else "Paused"
            self.status_var.set(f"{state}  •  GPU model ready  •  chunks pending: {pending}")

        self.level_bar["value"] = self.capture.level if self.capture else 0
        self.root.after(100, self._poll)

    def on_close(self):
        if self.capture:
            self.capture.stop()
        self.chunks.put(None)
        self.pa.terminate()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
