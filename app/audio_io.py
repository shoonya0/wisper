"""Decode audio files to the 16 kHz mono float32 that whisper.cpp wants.

Uses miniaudio, which handles WAV / MP3 / FLAC / OGG with no ffmpeg dependency.
Video containers (mp4/mkv) are not decoded here — extract the audio first, or
point whisper-cli at them.
"""

from pathlib import Path

import numpy as np
import miniaudio

TARGET_SR = 16000

AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


def decode_to_16k_mono(path):
    """Return a float32 numpy array of the file resampled to 16 kHz mono."""
    path = Path(path)
    decoded = miniaudio.decode_file(
        str(path),
        output_format=miniaudio.SampleFormat.FLOAT32,
        nchannels=1,
        sample_rate=TARGET_SR,
    )
    return np.asarray(decoded.samples, dtype=np.float32)


def split_windows(audio, window_s=25.0, overlap_s=1.0):
    """Yield (start_sample, chunk) windows for long audio.

    Whisper's context is 30 s; 25 s windows with 1 s overlap keep each pass
    within that and avoid clipping words at the boundary. The caller trims the
    overlap when stitching text.
    """
    n = len(audio)
    win = int(window_s * TARGET_SR)
    hop = int((window_s - overlap_s) * TARGET_SR)
    if n <= win:
        yield 0, audio
        return
    start = 0
    while start < n:
        yield start, audio[start:start + win]
        start += hop
