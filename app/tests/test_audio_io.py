"""Characterization tests: pin audio_io's current behavior (including known issues)."""

import miniaudio
import numpy as np

import audio_io

SR = audio_io.TARGET_SR


def windows(seconds):
    audio = np.zeros(int(seconds * SR), np.float32)
    return [(start, len(chunk)) for start, chunk in audio_io.split_windows(audio)]


def test_short_audio_is_one_window():
    assert windows(10) == [(0, 10 * SR)]


def test_exactly_one_window_length_is_not_split():
    assert windows(25) == [(0, 25 * SR)]


def test_long_audio_uses_25s_windows_with_24s_hop():
    assert windows(60) == [(0, 25 * SR), (24 * SR, 25 * SR), (48 * SR, 12 * SR)]


def test_consecutive_windows_overlap_by_one_second():
    # TODO(known issue 1, _docs/current-state.md): the docstring says "the caller trims
    # the overlap", but App._transcribe_file doesn't, so ~1 s of speech is transcribed
    # twice at every boundary. Fixing it must keep this overlap and trim the text.
    (s1, n1), (s2, _), _ = windows(60)
    assert s1 + n1 - s2 == 1 * SR


def test_m4a_is_offered_but_miniaudio_cannot_decode_it():
    # TODO(known issue 2): .m4a appears in the file picker but miniaudio has no AAC decoder.
    assert ".m4a" in audio_io.AUDIO_EXTS
    assert "AAC" not in {f.name for f in miniaudio.FileFormat}


def test_decode_wav_returns_16k_mono_float32(tmp_path):
    import wave

    path = tmp_path / "tone.wav"
    stereo_44k = (np.sin(np.linspace(0, 2 * np.pi * 440, 44100)) * 12000).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(np.repeat(stereo_44k, 2).tobytes())

    out = audio_io.decode_to_16k_mono(path)

    assert out.dtype == np.float32
    assert out.ndim == 1
    assert abs(len(out) - SR) <= 16  # 1 s of audio, allowing for resampler edges
