"""Characterization tests: pin audio_io's current behavior (including known issues)."""

import miniaudio
import numpy as np
import pytest

import audio_io

SR = audio_io.TARGET_SR


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
