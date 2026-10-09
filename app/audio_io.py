"""Decode audio files to the 16 kHz mono float32 that whisper.cpp wants.

Uses miniaudio, which handles WAV / MP3 / FLAC / OGG with no ffmpeg dependency.
Video containers (mp4/mkv) are not decoded here — extract the audio first, or
point whisper-cli at them.
"""

from pathlib import Path

import miniaudio
import numpy as np

TARGET_SR = 16000

# Only what miniaudio can decode: it has no AAC decoder, so no .m4a/.aac.
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg"}


def decode_to_16k_mono(path):
    """Return a float32 numpy array of the file resampled to 16 kHz mono."""
    path = Path(path)
    try:
        decoded = miniaudio.decode_file(
            str(path),
            output_format=miniaudio.SampleFormat.FLOAT32,
            nchannels=1,
            sample_rate=TARGET_SR,
        )
    except miniaudio.DecodeError as e:
        raise ValueError(
            f"Can't decode {path.name}: supported formats are WAV, MP3, FLAC, OGG (Vorbis)") from e
    return np.asarray(decoded.samples, dtype=np.float32)

