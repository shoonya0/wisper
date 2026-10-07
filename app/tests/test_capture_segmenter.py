"""Characterization tests for capture.Capture's energy-gate segmenter (no audio device)."""

import threading
import time

import numpy as np

import capture

SR = capture.TARGET_SR  # same rate in and out, so resampling is the identity
BLOCK = int(SR * 0.05)  # 50 ms, like the real stream


def run_segmenter(profile, signal):
    chunks = []
    cap = capture.Capture(
        pa=None,
        device={"defaultSampleRate": SR, "maxInputChannels": 1, "index": 0},
        profile=profile,
        on_chunk=chunks.append,
    )
    for i in range(0, len(signal), BLOCK):
        cap.blocks.put((signal[i : i + BLOCK] * 32767).astype(np.int16).tobytes())
    cap.running = True
    thread = threading.Thread(target=cap._segment_loop)
    thread.start()
    deadline = time.time() + 5
    while not cap.blocks.empty() and time.time() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)
    cap.running = False
    thread.join(timeout=2)
    return chunks


def tone(seconds, amp=0.2):
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def silence(seconds):
    return np.zeros(int(seconds * SR), np.float32)


def test_pause_after_speech_cuts_a_chunk():
    chunks = run_segmenter(capture.DICTATION, np.concatenate([tone(1.5), silence(0.5), tone(1.5), silence(0.5)]))
    assert len(chunks) == 2
    assert all(c.dtype == np.float32 for c in chunks)


def test_leading_silence_is_skipped():
    (chunk,) = run_segmenter(capture.DICTATION, np.concatenate([silence(1.0), tone(1.5), silence(0.5)]))
    assert len(chunk) < 2.1 * SR  # 1.5 s speech + ~0.4 s trailing pause, no leading second


def test_long_speech_is_cut_at_max_chunk():
    chunks = run_segmenter(capture.DICTATION, tone(20))
    assert [round(len(c) / SR) for c in chunks] == [8, 8, 4]


def test_too_little_speech_is_dropped():
    assert run_segmenter(capture.DICTATION, np.concatenate([tone(0.2), silence(1.5)])) == []
