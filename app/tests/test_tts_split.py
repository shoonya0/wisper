"""tts.split_sentences: narration text -> short pieces (spec §5.2, test plan §1.1)."""

import pytest

from tts import FIRST_CHUNK_WORDS, MAX_CHARS, split_sentences

LONG_CLAUSES = ", ".join(f"clause number {i} keeps going with a few more words" for i in range(14))  # ~700 chars
LONG_WORDS = " ".join(f"word{i}" for i in range(110))                                                   # ~700 chars
SIXTEEN = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"


def test_simple():
    assert split_sentences("Hi. How are you? Fine!") == ["Hi.", "How are you?", "Fine!"]


def test_abbreviations_dont_split():
    assert split_sentences("Dr. Rao met Mr. Iyer.") == ["Dr. Rao met Mr. Iyer."]


def test_eg_ie_etc_dont_split():
    assert split_sentences("Use tools, e.g. ruff. Then test.") == ["Use tools, e.g. ruff.", "Then test."]


def test_decimal_doesnt_split():
    assert split_sentences("Pi is 3.14 today.") == ["Pi is 3.14 today."]


def test_ellipsis():
    assert split_sentences("Wait… what?") == ["Wait…", "what?"]


def test_hindi_danda():
    assert split_sentences("नमस्ते। आप कैसे हैं?") == ["नमस्ते।", "आप कैसे हैं?"]


def test_blank_line_splits():
    assert split_sentences("Title\n\nBody text.") == ["Title", "Body text."]


def test_closing_quote_stays_with_its_sentence():
    assert split_sentences('He said "Go." Then left.') == ['He said "Go."', "Then left."]


@pytest.mark.parametrize("text", ["", "  \n ", "\n\n\n"])
def test_empty(text):
    assert split_sentences(text) == []


def test_long_piece_splits_at_commas_first():
    pieces = split_sentences("Start. " + LONG_CLAUSES)
    rest = pieces[1:]
    assert len(rest) > 1
    assert all(len(p) <= MAX_CHARS for p in pieces)
    assert all(p.endswith(",") for p in rest[:-1]), rest


def test_long_text_without_punctuation_splits_at_spaces():
    pieces = split_sentences("Start. " + LONG_WORDS)
    assert len(pieces) > 2
    assert all(len(p) <= MAX_CHARS for p in pieces)
    assert all(w.startswith("word") for p in pieces[1:] for w in p.split()), "a word was cut"


def test_a_single_word_longer_than_max_is_kept_whole():
    word = "x" * (MAX_CHARS + 30)
    assert split_sentences(f"Ok. {word} end.") == ["Ok.", word, "end."]


def test_three_dots_split_like_an_ellipsis():
    assert split_sentences("Wait... what?") == ["Wait...", "what?"]


def test_first_chunk_cut_at_an_early_clause_mark():
    pieces = split_sentences("Hi everyone, thanks for joining the call today, let me walk you through it.")
    assert pieces == ["Hi everyone,", "thanks for joining the call today, let me walk you through it."]


def test_first_chunk_cut_at_the_first_of_two_early_clause_marks():
    pieces = split_sentences("Well, hi everyone, thanks for joining the call today.")
    assert pieces == ["Well,", "hi everyone, thanks for joining the call today."]


def test_first_chunk_without_clause_mark_cut_at_the_cap():
    words = SIXTEEN.split()
    assert split_sentences(SIXTEEN) == [" ".join(words[:FIRST_CHUNK_WORDS]), " ".join(words[FIRST_CHUNK_WORDS:])]


def test_first_chunk_ignores_a_late_clause_mark():
    words = SIXTEEN.split()
    words[10] += ","   # first comma after word 11
    pieces = split_sentences(" ".join(words))
    assert pieces[0] == " ".join(words[:FIRST_CHUNK_WORDS])


def test_first_chunk_already_short_is_unchanged():
    assert split_sentences("Okay. Let's begin the meeting now, everyone.") == \
        ["Okay.", "Let's begin the meeting now, everyone."]


def test_only_the_first_piece_is_shortened():
    text = f"{SIXTEEN}. {SIXTEEN}. {SIXTEEN}."
    pieces = split_sentences(text)
    assert len(pieces[0].split()) == FIRST_CHUNK_WORDS
    assert pieces[2:] == [f"{SIXTEEN}.", f"{SIXTEEN}."]


@pytest.mark.parametrize("text", [
    "Hi. How are you? Fine!",
    "Dr. Rao met Mr. Iyer.",
    'He said "Go." Then left.',
    "नमस्ते। आप कैसे हैं?",
    "Title\n\nBody text.\nSecond line of the body.",
    "Hi everyone, thanks for joining the call today, let me walk you through it.",
    "Start. " + LONG_CLAUSES,
    "Start. " + LONG_WORDS,
    f"{SIXTEEN}. {SIXTEEN}. {SIXTEEN}.",
])
def test_round_trip_keeps_every_word_in_order(text):
    pieces = split_sentences(text)
    assert " ".join(pieces).split() == text.split()
    assert all(p == p.strip() and p for p in pieces)
