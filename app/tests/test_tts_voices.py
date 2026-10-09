"""tts.lang_for_voice: Kokoro voice prefix -> espeak-ng language (test plan, test_tts_voices.py)."""

import re

import pytest

from tts import lang_for_voice


@pytest.mark.parametrize(("voice", "lang"), [
    ("af_heart",  "en-us"),
    ("am_adam",   "en-us"),
    ("bm_george", "en-gb"),
    ("ef_dora",   "es"),
    ("ff_siwis",  "fr-fr"),
    ("hf_alpha",  "hi"),
    ("if_sara",   "it"),
    ("pf_dora",   "pt-br"),
])
def test_lang_for_voice(voice, lang):
    assert lang_for_voice(voice) == lang


@pytest.mark.parametrize("voice", ["jf_alpha", "zf_xiaobei", "", "xx_unknown"])
def test_unsupported_prefix_raises_naming_the_voice(voice):
    with pytest.raises(ValueError, match=re.escape(repr(voice))):
        lang_for_voice(voice)
