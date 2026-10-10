"""playback: device lookup, output-mode targets, resampling, and the stoppable Player.

Fake streams and a fake PyAudio: no audio device is touched. Test plan §1.2.
"""

import threading
import time

import numpy as np
import pytest

import playback
from playback import (
    MAX_BACKLOG_BLOCKS,
    NO_OTHERS_MESSAGE,
    LinearResampler,
    Passthrough,
    Player,
    find_virtual_cable,
    is_virtual_cable,
    resample_to,
    targets_for,
)

BLOCK_S = 0.02


def dev(index, name, rate=48000):
    return {"index": index, "name": name, "label": name, "defaultSampleRate": rate, "maxOutputChannels": 2}


SPEAKERS = dev(0, "Speakers (Realtek(R) Audio)")
CABLE = dev(1, "CABLE Input (VB-Audio Virtual Cable)")


# ---------------------------------------------------------------- device lookup

@pytest.mark.parametrize("name", [
    "CABLE Input (VB-Audio Virtual Cable)",
    "VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)",
    "Line 1 (Virtual Audio Cable)",
    "cable input (vb-audio virtual cable)",
])
def test_find_virtual_cable(name):
    cable = dev(3, name)
    assert find_virtual_cable([SPEAKERS, cable]) is cable


def test_find_virtual_cable_none_without_a_cable():
    assert find_virtual_cable([SPEAKERS]) is None
    assert find_virtual_cable([]) is None


class FakePa:
    WASAPI = {"index": 2, "defaultOutputDevice": 7}

    def __init__(self, devices):
        self.devices = devices

    def get_host_api_info_by_type(self, kind):
        return self.WASAPI

    def get_device_count(self):
        return len(self.devices)

    def get_device_info_by_index(self, i):
        return dict(self.devices[i])


def test_list_outputs_wasapi_outputs_only_default_first():
    devices = [
        {"index": 3, "name": "Speakers (MME)", "hostApi": 0, "maxOutputChannels": 2},
        {"index": 5, "name": "Microphone", "hostApi": 2, "maxOutputChannels": 0},
        {"index": 6, "name": "CABLE Input", "hostApi": 2, "maxOutputChannels": 2},
        {"index": 7, "name": "Headphones", "hostApi": 2, "maxOutputChannels": 2},
        {"index": 8, "name": "Headphones [Loopback]", "hostApi": 2, "maxOutputChannels": 2,
         "isLoopbackDevice": True},
    ]
    outputs = playback.list_outputs(FakePa(devices))
    assert [d["label"] for d in outputs] == ["Headphones", "CABLE Input"]


# ---------------------------------------------------------------- output modes

def test_targets_only_me():
    assert targets_for("me", SPEAKERS, CABLE) == [SPEAKERS]
    assert targets_for("me", SPEAKERS, None) == [SPEAKERS]


def test_targets_only_others():
    assert targets_for("others", SPEAKERS, CABLE) == [CABLE]


def test_targets_both():
    assert targets_for("both", SPEAKERS, CABLE) == [SPEAKERS, CABLE]


def test_targets_both_on_the_same_device_plays_once():
    assert targets_for("both", SPEAKERS, dict(SPEAKERS)) == [SPEAKERS]


@pytest.mark.parametrize("mode", ["others", "both"])
def test_targets_without_others_device_asks_for_one(mode):
    with pytest.raises(ValueError, match="Choose the device the call should hear"):
        targets_for(mode, SPEAKERS, None)
    assert NO_OTHERS_MESSAGE.startswith("Choose the device the call should hear")


def test_targets_unknown_mode():
    with pytest.raises(ValueError, match="Unknown output mode"):
        targets_for("everyone", SPEAKERS, CABLE)


# ---------------------------------------------------------------- resampling

def test_resample_24k_to_48k():
    x = np.sin(np.linspace(0, 200, 24000)).astype(np.float32)
    y = resample_to(x, 48000)
    assert abs(len(y) - 2 * len(x)) <= 1
    assert y.dtype == np.float32
    assert not np.isnan(y).any()


def test_resample_24k_to_44k1():
    x = np.zeros(24000, dtype=np.float32)
    y = resample_to(x, 44100)
    assert abs(len(y) - 44100) <= 1 and y.dtype == np.float32


def test_resample_same_rate_returns_the_input():
    x = np.ones(100, dtype=np.float32)
    assert resample_to(x, 24000) is x


# ---------------------------------------------------------------- player

class FakeStream:
    """Records writes; optionally sleeps one block per write (real time) or fails on write n."""

    def __init__(self, device, realtime=False, fail_on=None):
        self.name = device["label"]
        self.rate = int(device["defaultSampleRate"])
        self.realtime = realtime
        self.fail_on = fail_on
        self.writes = []
        self.write_times = []
        self.closed = False

    def write(self, block):
        if self.closed:
            raise AssertionError("write after close")
        if self.fail_on is not None and len(self.writes) == self.fail_on:
            raise OSError("device unplugged")
        if self.realtime:
            time.sleep(len(block) / self.rate)
        self.writes.append(np.array(block))
        self.write_times.append(time.perf_counter())

    def close(self):
        self.closed = True


def make_player(block_s=BLOCK_S, **stream_kw):
    streams, errors = [], []

    def factory(device):
        s = FakeStream(device, **stream_kw.get(device["label"], {}))
        streams.append(s)
        return s

    player = Player(factory, lambda name, e: errors.append((name, e)), block_s=block_s)
    return player, streams, errors


def at_24k(name, index):
    return dev(index, name, rate=24000)


def test_both_streams_get_identical_blocks_equal_to_the_input_padded():
    me, others = at_24k("me", 0), at_24k("others", 1)
    player, streams, errors = make_player()
    player.start([me, others])
    samples = np.arange(1000, dtype=np.float32)      # 2.08 blocks of 480 frames
    assert player.play(samples) is True
    a, b = streams
    assert len(a.writes) == len(b.writes) == 3
    assert all(np.array_equal(x, y) for x, y in zip(a.writes, b.writes, strict=True))
    played = np.concatenate(a.writes)
    assert len(played) == 3 * 480
    assert np.array_equal(played[:1000], samples) and not played[1000:].any()
    assert not errors


def test_streams_stay_open_between_sentences():
    player, streams, _ = make_player()
    player.start([at_24k("me", 0)])
    assert player.play(np.ones(480, dtype=np.float32))
    assert player.play(np.ones(480, dtype=np.float32))
    assert len(streams) == 1 and not streams[0].closed
    player.close()
    assert streams[0].closed


def test_each_device_gets_audio_at_its_own_rate():
    player, streams, _ = make_player()
    player.start([dev(0, "48k", 48000), dev(1, "44k1", 44100)])
    assert player.play(np.zeros(24000, dtype=np.float32))         # 1 s
    s48, s441 = streams
    assert len(s48.writes) == len(s441.writes) == 50
    assert sum(map(len, s48.writes)) == 48000 and sum(map(len, s441.writes)) == 44100


def test_stop_from_another_thread_silences_both_devices_within_a_block():
    # Real streams buffer in parallel, so only one fake paces in real time; 50 ms blocks keep
    # Windows' ~16 ms sleep granularity small next to the 2-block budget (spec: < 2 blocks).
    block_s = 0.05
    me, others = at_24k("me", 0), at_24k("others", 1)
    player, streams, errors = make_player(block_s, me={"realtime": True})
    player.start([me, others])
    samples = np.ones(24000 * 5, dtype=np.float32)               # 5 s
    stopped_at = []

    def stop_soon():
        time.sleep(0.325)   # mid-block: a stop on a block boundary is the jitter-prone case
        stopped_at.append(time.perf_counter())
        player.stop()

    threading.Thread(target=stop_soon).start()
    t0 = time.perf_counter()
    assert player.play(samples) is False
    returned = time.perf_counter()
    assert returned - t0 < 1.0, "play() didn't return soon after stop()"
    for s in streams:
        assert s.closed
        late = [t for t in s.write_times if t > stopped_at[0] + block_s]
        assert not late, f"{s.name}: {len(late)} write(s) after the block in progress"
    assert returned - stopped_at[0] < 2 * block_s
    assert not errors


def test_play_after_stop_does_nothing_until_the_next_start():
    player, streams, _ = make_player()
    player.start([at_24k("me", 0)])
    player.stop()
    assert player.play(np.ones(480, dtype=np.float32)) is False
    assert not any(s.writes for s in streams)
    player.start([at_24k("me", 0)])
    assert player.play(np.ones(480, dtype=np.float32)) is True


def test_write_error_reports_the_device_once_and_closes_the_other_stream():
    me, others = at_24k("me", 0), at_24k("others", 1)
    player, streams, errors = make_player(others={"fail_on": 2})
    player.start([me, others])
    assert player.play(np.ones(480 * 5, dtype=np.float32)) is False    # no exception escapes
    assert [name for name, _ in errors] == ["others"]
    assert isinstance(errors[0][1], OSError)
    assert all(s.closed for s in streams)


def test_rounded_block_size_never_cuts_the_tail():
    player, streams, _ = make_player(block_s=0.05)
    player.start([dev(0, "22k", 22050)])                      # 1102.5 frames per block -> 1102
    assert player.play(np.ones(24000, dtype=np.float32))
    played = np.concatenate(streams[0].writes)
    assert len(played) >= 22050 and len(played) % 1102 == 0


def test_pa_stream_interleaves_mono_into_every_channel():
    opened = {}

    class FakeOutput:
        def __init__(self, **kw):
            opened.update(kw)
            self.data = b""

        def write(self, data):
            self.data += data

    class Pa:
        def open(self, **kw):
            self.out = FakeOutput(**kw)
            return self.out

    pa = Pa()
    stream = playback.PaStream(pa, {**dev(4, "5.1 speakers"), "maxOutputChannels": 6})
    stream.write(np.array([0.25, -0.5], dtype=np.float32))
    assert opened["channels"] == 6 and opened["rate"] == 48000 and opened["output_device_index"] == 4
    assert np.frombuffer(pa.out.data, dtype=np.float32).tolist() == [0.25] * 6 + [-0.5] * 6


def test_open_error_reports_the_device_and_closes_streams_already_open():
    errors, opened = [], []

    def factory(device):
        if device["label"] == "others":
            raise OSError("Invalid sample rate")
        s = FakeStream(device)
        opened.append(s)
        return s

    player = Player(factory, lambda name, e: errors.append(name), block_s=BLOCK_S)
    player.start([at_24k("me", 0), at_24k("others", 1)])
    assert player.play(np.ones(480, dtype=np.float32)) is False
    assert errors == ["others"]
    assert opened[0].closed and not opened[0].writes


# ---------------------------------------------------------------- mic pass-through (N8)

@pytest.mark.parametrize("name, cable", [
    ("CABLE Output (VB-Audio Virtual Cable)", True),
    ("CABLE Input (VB-Audio Virtual Cable)", True),
    ("VoiceMeeter Output (VB-Audio VoiceMeeter VAIO)", True),
    ("Line 1 (Virtual Audio Cable)", True),
    ("Microphone (4- High Definition Audio Device)", False),
    ("Headset Microphone (Realtek(R) Audio)", False),
])
def test_is_virtual_cable_covers_both_sides(name, cable):
    assert is_virtual_cable(name) is cable


def test_list_inputs_wasapi_mics_only_no_cables_default_first():
    devices = [
        {"index": 3, "name": "Microsoft Sound Mapper - Input", "hostApi": 0, "maxInputChannels": 2},
        {"index": 5, "name": "Speakers", "hostApi": 2, "maxInputChannels": 0},
        {"index": 6, "name": "CABLE Output (VB-Audio Virtual Cable)", "hostApi": 2, "maxInputChannels": 2},
        {"index": 7, "name": "Headset Microphone", "hostApi": 2, "maxInputChannels": 1},
        {"index": 8, "name": "Microphone (Realtek)", "hostApi": 2, "maxInputChannels": 2},
        {"index": 9, "name": "Speakers [Loopback]", "hostApi": 2, "maxInputChannels": 2, "isLoopbackDevice": True},
    ]

    class FakeInputPa(FakePa):
        WASAPI = {"index": 2, "defaultInputDevice": 8}

    assert [d["label"] for d in playback.list_inputs(FakeInputPa(devices))] == [
        "Microphone (Realtek)", "Headset Microphone"]


def test_linear_resampler_same_rate_returns_the_block():
    block = np.ones(480, dtype=np.float32)
    assert LinearResampler(48000, 48000)(block) is block


def test_linear_resampler_44k1_to_48k_is_continuous_across_blocks():
    t = np.arange(44100) / 44100
    sine = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    rs = LinearResampler(44100, 48000)
    out = np.concatenate([rs(sine[i:i + 441]) for i in range(0, len(sine), 441)])
    assert out.dtype == np.float32
    assert abs(len(out) - 48000) <= 2
    expected = np.sin(2 * np.pi * 440 * np.arange(len(out)) / 48000)
    assert np.abs(out - expected).max() < 0.01, "a jump at a block boundary"


class FakeMic:
    """Endless mic: block k is filled with k. Counts frames waiting since the last read."""

    def __init__(self, device, backlog=0, fail_on=None, read_s=0.002):
        self.name, self.rate = device["label"], int(device["defaultSampleRate"])
        self.backlog, self.fail_on, self.read_s = backlog, fail_on, read_s
        self.reads, self.dropped, self.closed = 0, 0, False

    def available(self):
        return self.backlog

    def read(self, frames):
        if self.closed:
            raise AssertionError("read after close")
        if self.fail_on is not None and self.reads == self.fail_on:
            raise OSError("mic unplugged")
        if self.backlog:                          # the first read after a backlog drops it
            self.dropped, self.backlog = frames, 0
            return np.zeros(frames, dtype=np.float32)
        time.sleep(self.read_s)
        self.reads += 1
        return np.full(frames, self.reads, dtype=np.float32)

    def close(self):
        self.closed = True


def make_passthrough(mic_kw=None, cable_kw=None, open_error=None):
    made, errors = {}, []

    def open_input(device):
        made["mic"] = FakeMic(device, **(mic_kw or {}))
        return made["mic"]

    def open_output(device):
        if open_error:
            raise open_error
        made["cable"] = FakeStream(device, **(cable_kw or {}))
        return made["cable"]

    pt = Passthrough(open_input, open_output, lambda name, e, run: errors.append((name, e, run)), block_s=0.01)
    return pt, made, errors


MIC = dev(5, "Microphone (Realtek)")


def wait_for(cond, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.005)


def test_passthrough_copies_mic_blocks_to_the_cable_in_order():
    pt, made, errors = make_passthrough()
    pt.start(MIC, CABLE)
    wait_for(lambda: "cable" in made and len(made["cable"].writes) >= 5)
    pt.stop()
    firsts = [int(w[0]) for w in made["cable"].writes]
    assert firsts == list(range(1, len(firsts) + 1))
    assert all(len(w) == 480 for w in made["cable"].writes)       # 10 ms at 48 kHz
    assert not errors


def test_passthrough_stop_ends_the_thread_and_closes_both_streams():
    pt, made, errors = make_passthrough()
    pt.start(MIC, CABLE)
    wait_for(lambda: pt.running and "cable" in made)
    pt.stop()
    assert not pt.running
    assert made["mic"].closed and made["cable"].closed
    writes = len(made["cable"].writes)
    time.sleep(0.05)
    assert len(made["cable"].writes) == writes
    pt.stop()                                                        # idempotent
    assert not errors


def test_passthrough_drops_a_backlog_so_the_delay_cannot_grow():
    pt, made, _ = make_passthrough(mic_kw={"backlog": (MAX_BACKLOG_BLOCKS + 5) * 480})
    pt.start(MIC, CABLE)
    wait_for(lambda: "cable" in made and made["cable"].writes)
    pt.stop()
    assert made["mic"].dropped == 5 * 480, "only the frames beyond the allowed backlog are dropped"


def test_passthrough_restart_switches_devices():
    pt, made, _ = make_passthrough()
    pt.start(MIC, CABLE)
    wait_for(lambda: "cable" in made)
    first_mic = made["mic"]
    pt.start(dev(6, "Headset Microphone"), CABLE)
    assert first_mic.closed
    wait_for(lambda: made["mic"] is not first_mic and made["mic"].reads)
    assert made["mic"].name == "Headset Microphone"
    pt.stop()


def test_passthrough_mic_error_is_reported_once_and_closes_both_streams():
    pt, made, errors = make_passthrough(mic_kw={"fail_on": 3})
    pt.start(MIC, CABLE)
    wait_for(lambda: not pt.running)
    assert [name for name, _, _ in errors] == [MIC["label"]]
    assert isinstance(errors[0][1], OSError)
    assert made["mic"].closed and made["cable"].closed


def test_passthrough_cable_write_error_names_the_cable():
    pt, made, errors = make_passthrough(cable_kw={"fail_on": 2})
    pt.start(MIC, CABLE)
    wait_for(lambda: not pt.running)
    assert [name for name, _, _ in errors] == [CABLE["label"]]
    assert made["mic"].closed


def test_passthrough_cable_open_error_closes_the_mic():
    pt, made, errors = make_passthrough(open_error=OSError("device busy"))
    pt.start(MIC, CABLE)
    wait_for(lambda: not pt.running)
    assert [name for name, _, _ in errors] == [CABLE["label"]]
    assert made["mic"].closed


def test_passthrough_error_while_stopping_is_not_reported():
    reading = threading.Event()

    class ClosingMic(FakeMic):
        def read(self, frames):
            reading.set()
            time.sleep(0.05)                     # stop() arrives during this read ...
            raise OSError("stream closed")      # ... which then fails, as a closing device does

    errors = []
    pt = Passthrough(lambda d: ClosingMic(d), lambda d: FakeStream(d), lambda n, e, run: errors.append(n), block_s=0.01)
    pt.start(MIC, CABLE)
    reading.wait(1)
    pt.stop()
    assert not pt.running and errors == []


def test_a_slow_old_run_never_keeps_running_after_a_restart():
    # Opening a mic can take seconds (a Bluetooth headset switching profile); stop() only
    # waits join_s. The old run must still end, write nothing and report nothing.
    mics, errors = [], []

    def open_input(device):
        if not mics:
            time.sleep(0.3)                      # longer than join_s below
        mics.append(FakeMic(device))
        return mics[-1]

    cables = []

    def open_output(device):
        cables.append(FakeStream(device))
        return cables[-1]

    pt = Passthrough(open_input, open_output, lambda name, e, run: errors.append(name), block_s=0.01, join_s=0.05)
    pt.start(MIC, CABLE)
    time.sleep(0.02)                             # the first run is still opening the mic
    pt.start(dev(6, "Headset Microphone"), CABLE)
    wait_for(lambda: len(mics) == 2 and all(m.closed for m in mics[:1]) and mics[1].reads >= 3)
    old = [m for m in mics if m.name == MIC["label"]]
    assert old and old[0].reads == 0, "the old run read the mic after it was replaced"
    writers = [c for c in cables if c.writes]
    assert len(writers) == 1, "two runs wrote to the cable"
    pt.close()
    assert not pt.running and all(m.closed for m in mics) and errors == []


def test_close_waits_for_a_run_that_outlived_stop():
    opened = threading.Event()

    def open_input(device):
        time.sleep(0.2)
        opened.set()
        return FakeMic(device)

    pt = Passthrough(open_input, lambda d: FakeStream(d), lambda name, e, run: None, block_s=0.01, join_s=0.02)
    pt.start(MIC, CABLE)
    pt.stop()                                    # returns before the open finishes
    pt.close()                                   # must wait for it: PyAudio is terminated next
    assert opened.is_set()
    assert not any(t.name == "mic-passthrough" and t.is_alive() for t in threading.enumerate())


def test_errors_carry_the_run_they_belong_to():
    pt, made, errors = make_passthrough(mic_kw={"fail_on": 1})
    pt.start(MIC, CABLE)
    wait_for(lambda: not pt.running)
    assert [run for _, _, run in errors] == [pt.run_id]


def test_pa_input_returns_mono_float32_blocks():
    class FakeRawStream:
        def read(self, frames, exception_on_overflow=True):
            assert exception_on_overflow is False
            return np.tile(np.array([0.2, 0.4], dtype=np.float32), frames).tobytes()

        def get_read_available(self):
            return 7

        def close(self):
            pass

    class FakeOpenPa:
        def open(self, **kw):
            self.kw = kw
            return FakeRawStream()

    pa = FakeOpenPa()
    mic = playback.PaInput(pa, {**MIC, "maxInputChannels": 2, "defaultSampleRate": 48000})
    assert pa.kw["input"] and pa.kw["channels"] == 2 and pa.kw["frames_per_buffer"] == 480
    block = mic.read(480)
    assert block.shape == (480,) and np.allclose(block, 0.3)
    assert mic.available() == 7
