"""Narration output: WASAPI output devices, virtual-cable detection, and a stoppable player.

Narration spec _docs/specs/2026-10-07-kokoro-narration.md §4, §5.2, §5.3. A leaf module: it
imports no other project module. The player writes the same samples to one or two output
streams ("Only me", "Only others", "Both") in short blocks and checks a stop Event between
blocks, so Stop/Clear silences every device within about one block. Passthrough (N8,
_docs/specs/2026-10-10-mic-passthrough.md) copies the real microphone into the cable on its
own stream; Windows' shared-mode mixer sums it with the narration.
"""

import math
import threading

import numpy as np
import pyaudiowpatch as pyaudio
from scipy.signal import resample_poly

SAMPLE_RATE = 24000      # Kokoro output (tts.SAMPLE_RATE; not imported: leaves stay independent)
BLOCK_S     = 0.05       # stop latency is about one block
PASS_BLOCK_S       = 0.01   # mic pass-through block: the voice delay Wisper adds is about one block
MAX_BACKLOG_BLOCKS = 3      # mic frames waiting beyond this are dropped: the delay can't grow

MODES = ("me", "others", "both")
NO_OTHERS_MESSAGE = "Choose the device the call should hear (Others)."

# Playback side of the common virtual cables (spec §5.3), matched case-insensitively.
CABLE_NAMES = ("cable input", "vb-audio", "voicemeeter input", "virtual audio cable", "line 1 (virtual")
# Recording side too: a cable must never be offered as the mic (it would feed itself).
CABLE_RECORD_NAMES = ("cable output", "voicemeeter out")


# ---------------------------------------------------------------- device lookup

def list_outputs(pa):
    """WASAPI output devices (raw PyAudio dicts with a "label"), the Windows default first."""
    try:
        wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    except OSError:
        return []
    devices = []
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if (d["hostApi"] != wasapi["index"] or d["maxOutputChannels"] <= 0
                or d.get("isLoopbackDevice", False)):
            continue
        d["label"] = d["name"]
        devices.append(d)
    devices.sort(key=lambda d: (d["index"] != wasapi["defaultOutputDevice"], d["index"]))
    return devices


def list_inputs(pa):
    """WASAPI microphones without virtual cables (they'd feed themselves), the Windows default first."""
    try:
        wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    except OSError:
        return []
    devices = []
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if (d["hostApi"] != wasapi["index"] or d["maxInputChannels"] <= 0
                or d.get("isLoopbackDevice", False) or is_virtual_cable(d["name"])):
            continue
        d["label"] = d["name"]
        devices.append(d)
    devices.sort(key=lambda d: (d["index"] != wasapi["defaultInputDevice"], d["index"]))
    return devices


def is_virtual_cable(name):
    """True for either side of a virtual cable (case insensitive)."""
    name = name.casefold()
    return any(c in name for c in CABLE_NAMES + CABLE_RECORD_NAMES)


def find_virtual_cable(devices):
    """The first output device that looks like a virtual cable's playback side, or None."""
    for d in devices:
        name = d["name"].casefold()
        if any(c in name for c in CABLE_NAMES):
            return d
    return None


def targets_for(mode, me, others):
    """Devices to play on for an output mode. Raises ValueError(NO_OTHERS_MESSAGE) without Others."""
    if mode not in MODES:
        raise ValueError(f"Unknown output mode {mode!r}: expected one of {', '.join(MODES)}")
    if mode != "me" and others is None:
        raise ValueError(NO_OTHERS_MESSAGE)
    if mode == "me":
        return [me]
    if mode == "others" or others["index"] == me["index"]:   # same device twice would double-play
        return [others]
    return [me, others]


def resample_to(samples, rate, src_rate=SAMPLE_RATE):
    """Resample mono float32 audio to rate. Returns the input itself when the rates match."""
    if rate == src_rate:
        return samples
    g = math.gcd(int(rate), int(src_rate))
    return resample_poly(samples, int(rate) // g, int(src_rate) // g).astype(np.float32)


# ---------------------------------------------------------------- player

class PaStream:
    """A blocking PyAudio output stream that takes mono float32 blocks (the real stream_factory)."""

    def __init__(self, pa, device, block_s=BLOCK_S):
        self.name = device.get("label", device["name"])
        self.rate = int(device["defaultSampleRate"])   # WASAPI shared mode needs the device rate
        # Shared mode wants the mix format's channel count (2, or 6/8 on a 5.1/7.1 or 8-channel cable).
        self.channels = max(1, int(device["maxOutputChannels"]))
        self._stream = pa.open(format=pyaudio.paFloat32, channels=self.channels, rate=self.rate,
                               output=True, output_device_index=device["index"],
                               frames_per_buffer=round(self.rate * block_s))

    def write(self, block):
        if self.channels > 1:
            block = np.repeat(block, self.channels)    # interleave mono into every channel
        self._stream.write(block.astype(np.float32).tobytes())

    def close(self):
        self._stream.close()                            # discards anything still buffered


class Player:
    """Plays mono samples on 1-2 devices at once, block by block.

    start(devices), play() and close() must never overlap: in the app the TTS worker calls
    start/close and the narration-player thread calls play in between (joined before
    close). stop() is the only call that is safe at any time from another thread (it just
    sets an Event). Streams stay open
    between play() calls, so sentences follow each other without reopening devices.
    stream_factory(device) returns an object with name, rate, write(mono_block), close().
    start() clears the stop Event, so a stop() that races ahead of the next start() is lost:
    the narrator must also drop stale work by its own generation id (spec §5.4).
    """

    def __init__(self, stream_factory, on_error, block_s=BLOCK_S):
        self._factory = stream_factory
        self._on_error = on_error          # on_error(device_name, exception), called once per failure
        self._block_s = block_s
        self._stop = threading.Event()
        self._devices = []
        self._streams = []

    def start(self, devices):
        """Begin a narration on these devices (opened on the first play)."""
        self.close()
        self._stop.clear()
        self._devices = list(devices)

    def stop(self):
        self._stop.set()

    @property
    def stopped(self):
        return self._stop.is_set()

    def play(self, samples, src_rate=SAMPLE_RATE):
        """Play samples to the end on every device. False if stopped or a device failed."""
        if self._stop.is_set() or not self._open():
            self.close()
            return False
        samples = np.asarray(samples, dtype=np.float32)
        n_blocks = math.ceil(len(samples) / round(src_rate * self._block_s))
        tracks = []
        for s in self._streams:
            frames = round(s.rate * self._block_s)
            audio = resample_to(samples, s.rate, src_rate)
            n_blocks = max(n_blocks, math.ceil(len(audio) / frames))   # rounding never cuts the tail
            tracks.append((s, audio, frames))
        # Same block count on every device keeps them in step (within one block).
        tracks = [(s, np.pad(a, (0, n_blocks * f - len(a))), f) for s, a, f in tracks]

        for i in range(n_blocks):
            if self._stop.is_set():
                self.close()
                return False
            for s, audio, frames in tracks:
                try:
                    s.write(audio[i * frames:(i + 1) * frames])
                except Exception as e:
                    self._fail(s.name, e)
                    return False
        return True

    def close(self):
        streams, self._streams = self._streams, []
        for s in streams:
            try:
                s.close()
            except Exception:
                pass

    def _open(self):
        if self._streams:
            return True
        for d in self._devices:
            try:
                self._streams.append(self._factory(d))
            except Exception as e:
                self._fail(d.get("label", d["name"]), e)
                return False
        return bool(self._streams)

    def _fail(self, name, error):
        self.close()
        self._on_error(name, error)


# ---------------------------------------------------------------- mic pass-through (N8)

class PaInput:
    """A blocking PyAudio mic stream that returns mono float32 blocks (the real open_input)."""

    def __init__(self, pa, device, block_s=PASS_BLOCK_S):
        self.name = device.get("label", device["name"])
        self.rate = int(device["defaultSampleRate"])   # shared mode: the device's own format
        self.channels = max(1, int(device["maxInputChannels"]))
        self._stream = pa.open(format=pyaudio.paFloat32, channels=self.channels, rate=self.rate,
                               input=True, input_device_index=device["index"],
                               frames_per_buffer=round(self.rate * block_s))

    def available(self):
        return self._stream.get_read_available()

    def read(self, frames):
        raw = self._stream.read(frames, exception_on_overflow=False)
        return np.frombuffer(raw, np.float32).reshape(-1, self.channels).mean(axis=1)

    def close(self):
        self._stream.close()


class LinearResampler:
    """Block-by-block linear resampling that stays continuous across blocks."""

    def __init__(self, src_rate, dst_rate):
        self.step = src_rate / dst_rate   # input samples per output sample
        self._pos = 0.0                   # next output position, relative to _prev
        self._prev = None                 # the last input sample of the previous block

    def __call__(self, block):
        if self.step == 1.0:
            return block
        x = block if self._prev is None else np.concatenate(([self._prev], block))
        start = 0.0 if self._prev is None else self._pos
        positions = np.arange(start, len(x) - 1, self.step)
        out = np.interp(positions, np.arange(len(x)), x).astype(np.float32)
        nxt = positions[-1] + self.step if len(positions) else start
        self._pos = nxt - (len(x) - 1)
        self._prev = x[-1]
        return out


class Passthrough:
    """Copies the mic into the cable on its own thread, so a call hears the user's voice.

    start(mic, cable), stop() and close() are called from one thread (the UI); the
    pass-through thread only touches its own two streams. Each run has its own stop Event
    and run_id: a run that outlives stop() (an open or read slower than join_s) still ends
    on its own Event, never reports an error, and close() waits for it before PyAudio is
    terminated. open_input(device) returns an object with name, rate, available(),
    read(frames) -> mono float32, close(); open_output(device) one with name, rate,
    write(mono_block), close() (PaStream).
    """

    def __init__(self, open_input, open_output, on_error, block_s=PASS_BLOCK_S, join_s=1.0):
        self._open_input = open_input
        self._open_output = open_output
        self._on_error = on_error          # on_error(device_name, exception, run_id), once per failure
        self._block_s = block_s
        self._join_s = join_s
        self._stop = threading.Event()
        self._thread = None
        self._lingering = []               # runs that outlived stop(); close() joins them
        self.run_id = 0

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, mic, cable):
        self.stop()
        self.run_id += 1
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(mic, cable, self._stop, self.run_id),
                                        name="mic-passthrough", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._join_s)
            if self._thread.is_alive():
                self._lingering.append(self._thread)
            self._thread = None
        self._lingering = [t for t in self._lingering if t.is_alive()]

    def close(self, timeout=5.0):
        """stop(), then wait for every run to end: their streams must close before pa.terminate()."""
        self.stop()
        for t in self._lingering:
            t.join(timeout=timeout)
        self._lingering = [t for t in self._lingering if t.is_alive()]

    def _run(self, mic, cable, stop, run_id):
        streams, name = [], mic.get("label", mic["name"])
        try:
            src = self._open_input(mic)
            streams.append(src)
            if stop.is_set():
                return
            name = cable.get("label", cable["name"])
            dst = self._open_output(cable)
            streams.append(dst)
            frames = round(src.rate * self._block_s)
            resample = LinearResampler(src.rate, dst.rate)
            while not stop.is_set():
                name = src.name
                extra = src.available() - MAX_BACKLOG_BLOCKS * frames
                if extra > 0:
                    src.read(extra)           # drop the backlog: the voice stays on time
                block = src.read(frames)
                if stop.is_set():
                    break
                name = dst.name
                dst.write(resample(block))
        except Exception as e:
            if not stop.is_set():
                self._on_error(name, e, run_id)
        finally:
            for st in streams:
                try:
                    st.close()
                except Exception:
                    pass
