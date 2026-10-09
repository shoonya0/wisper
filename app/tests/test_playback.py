"""playback: device lookup, output-mode targets, resampling, and the stoppable Player.

Fake streams and a fake PyAudio: no audio device is touched. Test plan §1.2.
"""

import threading
import time

import numpy as np
import pytest

import playback
from playback import NO_OTHERS_MESSAGE, Player, find_virtual_cable, resample_to, targets_for

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
