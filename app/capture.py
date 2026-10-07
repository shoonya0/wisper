"""Audio capture and speech segmentation.

Enumerates microphone and desktop-loopback devices, records the chosen one, and
splits the stream into speech chunks at pauses. Chunks are emitted as 16 kHz
mono float32 arrays — exactly what whisper.cpp expects.

The segmenter is intentionally simple: an energy (RMS) gate finds pauses. It has
no ML dependency and adds no latency. Silero VAD would cut false triggers on
noisy input, but energy gating plus the hallucination filter in the app is a
good, dependency-light default.
"""

import queue
import threading

import numpy as np
import pyaudiowpatch as pyaudio
from scipy.signal import resample_poly

TARGET_SR = 16000


# --------------------------------------------------------------------- profiles

class Profile:
    """Segmentation timing. Shorter = lower latency, more (smaller) chunks."""

    def __init__(self, min_chunk_s, max_chunk_s, silence_cut_s,
                 silence_rms=0.006, min_speech_s=0.35):
        self.min_chunk_s = min_chunk_s
        self.max_chunk_s = max_chunk_s
        self.silence_cut_s = silence_cut_s
        self.silence_rms = silence_rms
        self.min_speech_s = min_speech_s


# Tuned for responsiveness: cut soon after a short pause.
DICTATION = Profile(min_chunk_s=1.0, max_chunk_s=8.0, silence_cut_s=0.4)
# Tuned for continuous speech (meetings/video): longer, more context per chunk.
CAPTIONS = Profile(min_chunk_s=2.0, max_chunk_s=12.0, silence_cut_s=0.6)


# ---------------------------------------------------------------- device lookup

def list_sources(pa, kind):
    """Return input devices for kind in {"mic", "loopback"}.

    Each item is the raw PyAudio device-info dict with a cleaned "label".
    The system default is placed first.
    """
    if kind == "loopback":
        devices = list(pa.get_loopback_device_info_generator())
        default_idx = _default_index(pa, output=True)
    else:
        devices = _input_devices(pa)
        default_idx = _default_index(pa, output=False)

    for d in devices:
        d["label"] = d["name"].replace(" [Loopback]", "")

    # Default device first, then stable order.
    devices.sort(key=lambda d: (d["index"] != default_idx, d["index"]))
    return devices


def _input_devices(pa):
    seen, out = set(), []
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d["maxInputChannels"] <= 0 or d.get("isLoopbackDevice", False):
            continue
        # Skip the generic mapper duplicates; keep real endpoints.
        name = d["name"]
        if name in seen:
            continue
        seen.add(name)
        out.append(d)
    return out


def _default_index(pa, output):
    try:
        wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        key = "defaultOutputDevice" if output else "defaultInputDevice"
        return wasapi[key]
    except OSError:
        return -1


# -------------------------------------------------------------------- capturing

class Capture:
    """Records one device and calls on_chunk(float32_16k) for each speech chunk."""

    def __init__(self, pa, device, profile, on_chunk):
        self.pa = pa
        self.device = device
        self.profile = profile
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
        p = self.profile
        chunk, chunk_len, silence_len, speech_len = [], 0, 0, 0
        min_n = int(p.min_chunk_s * self.sr)
        max_n = int(p.max_chunk_s * self.sr)
        cut_n = int(p.silence_cut_s * self.sr)
        speech_min_n = int(p.min_speech_s * self.sr)

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
                # Loopback delivers nothing while no app plays sound: treat as a pause.
                self.level = 0.0
                if chunk_len >= min_n:
                    flush()
                continue
            block = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
            block = block.reshape(-1, self.channels).mean(axis=1)
            rms = float(np.sqrt(np.mean(block ** 2))) if block.size else 0.0
            self.level = rms

            if rms < p.silence_rms:
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
