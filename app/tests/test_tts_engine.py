"""tts.load / Engine against the real Kokoro model (slow, ~4 s; test plan, test_tts_engine.py).

Runs in `node tools/verify.mjs --full`. Skipped when models/kokoro/ is missing, as on CI.
"""

import numpy as np
import pytest

import tts

needs_model = pytest.mark.skipif(bool(tts.missing_files()), reason="models/kokoro/ missing: see current-state.md")


@pytest.fixture(scope="module")
def engine():
    return tts.load()


@pytest.mark.slow
@needs_model
def test_voices_include_the_default_and_only_supported_languages(engine):
    voices = engine.voices()
    assert tts.DEFAULT_VOICE in voices
    assert all(v[:1] in tts.LANG_BY_PREFIX for v in voices)


@pytest.mark.slow
@needs_model
def test_synthesize_hello_world(engine):
    samples = engine.synthesize("Hello world.")
    assert samples.dtype == np.float32 and samples.ndim == 1
    assert 0.4 <= len(samples) / tts.SAMPLE_RATE <= 3.0
    assert 0.01 < float(np.abs(samples).max()) <= 1.0


def test_missing_files_raise_the_setup_message(tmp_path):  # fast: no model needed
    with pytest.raises(FileNotFoundError, match="Narration setup"):
        tts.load(tmp_path)
