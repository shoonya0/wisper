"""Characterization tests for app.is_junk (Whisper's noise inventions)."""

import pytest

from app import is_junk


@pytest.mark.parametrize("text", ["Thank you.", "  you ", "[Music]", "(applause)", ".", "Thanks for watching!"])
def test_junk_is_dropped(text):
    assert is_junk(text)


@pytest.mark.parametrize("text", ["Thank you for coming today.", "you know what I mean", "[Music] and then"])
def test_real_speech_is_kept(text):
    assert not is_junk(text)
