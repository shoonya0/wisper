"""Characterization tests: pin audio_io's current behavior (including known issues)."""

import miniaudio
import numpy as np
import pytest

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


def test_file_picker_only_offers_formats_miniaudio_can_decode():
    # Known issue 2: .m4a used to be offered, but miniaudio has no AAC decoder.
    ext_to_format = {".wav": "WAV", ".mp3": "MP3", ".flac": "FLAC", ".ogg": "VORBIS"}
    decodable = {f.name for f in miniaudio.FileFormat}
    assert audio_io.AUDIO_EXTS <= ext_to_format.keys()
    assert all(ext_to_format[e] in decodable for e in audio_io.AUDIO_EXTS)


def test_undecodable_file_raises_error_naming_supported_formats(tmp_path):
    path = tmp_path / "voice.m4a"
    path.write_bytes(b"\x00\x00\x00\x20ftypM4A " + bytes(64))

    with pytest.raises(ValueError, match=r"voice\.m4a.*WAV, MP3, FLAC, OGG"):
        audio_io.decode_to_16k_mono(path)


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
