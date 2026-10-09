"""Minimal ctypes binding for whisper.cpp's whisper.dll (Vulkan build).

Loads the model once and keeps it on the GPU. Struct layouts mirror
whisper.cpp/include/whisper.h and must be updated if that header changes.
"""

import codecs
import ctypes as C
import os
from pathlib import Path

import numpy as np

WHISPER_SAMPLING_GREEDY = 0

# whisper_new_segment_callback / whisper_progress_callback in whisper.h:
# (whisper_context *, whisper_state *, int n_new | progress, void * user_data)
SegmentCallback = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_int, C.c_void_p)
ProgressCallback = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_int, C.c_void_p)

# Fast speech is about 30 characters/s. On a short tail of audio, long-form decoding can
# "hear" a whole earlier sentence in a fraction of a second (measured: 108 chars in 0.62 s).
MAX_CHARS_PER_S = 60
MIN_SEGMENT_S = 0.5  # floor for the rate, so a short real word ("Yes.") is never too dense


def is_too_dense(text, t0_s, t1_s):
    """True when a segment has far more text than its duration can hold (a hallucination)."""
    return len(text.strip()) > MAX_CHARS_PER_S * max(t1_s - t0_s, MIN_SEGMENT_S)


class WhisperAhead(C.Structure):
    _fields_ = [("n_text_layer", C.c_int), ("n_head", C.c_int)]


class WhisperAheads(C.Structure):
    _fields_ = [("n_heads", C.c_size_t), ("heads", C.POINTER(WhisperAhead))]


class WhisperContextParams(C.Structure):
    _fields_ = [
        ("use_gpu", C.c_bool),
        ("flash_attn", C.c_bool),
        ("gpu_device", C.c_int),
        ("dtw_token_timestamps", C.c_bool),
        ("dtw_aheads_preset", C.c_int),
        ("dtw_n_top", C.c_int),
        ("dtw_aheads", WhisperAheads),
        ("dtw_mem_size", C.c_size_t),
    ]


class WhisperVadParams(C.Structure):
    _fields_ = [
        ("threshold", C.c_float),
        ("min_speech_duration_ms", C.c_int),
        ("min_silence_duration_ms", C.c_int),
        ("max_speech_duration_s", C.c_float),
        ("speech_pad_ms", C.c_int),
        ("samples_overlap", C.c_float),
    ]


class Greedy(C.Structure):
    _fields_ = [("best_of", C.c_int)]


class BeamSearch(C.Structure):
    _fields_ = [("beam_size", C.c_int), ("patience", C.c_float)]


class WhisperFullParams(C.Structure):
    _fields_ = [
        ("strategy", C.c_int),
        ("n_threads", C.c_int),
        ("n_max_text_ctx", C.c_int),
        ("offset_ms", C.c_int),
        ("duration_ms", C.c_int),
        ("translate", C.c_bool),
        ("no_context", C.c_bool),
        ("no_timestamps", C.c_bool),
        ("single_segment", C.c_bool),
        ("print_special", C.c_bool),
        ("print_progress", C.c_bool),
        ("print_realtime", C.c_bool),
        ("print_timestamps", C.c_bool),
        ("token_timestamps", C.c_bool),
        ("thold_pt", C.c_float),
        ("thold_ptsum", C.c_float),
        ("max_len", C.c_int),
        ("split_on_word", C.c_bool),
        ("max_tokens", C.c_int),
        ("debug_mode", C.c_bool),
        ("audio_ctx", C.c_int),
        ("tdrz_enable", C.c_bool),
        ("suppress_regex", C.c_char_p),
        ("initial_prompt", C.c_char_p),
        ("carry_initial_prompt", C.c_bool),
        ("prompt_tokens", C.POINTER(C.c_int32)),
        ("prompt_n_tokens", C.c_int),
        ("language", C.c_char_p),
        ("detect_language", C.c_bool),
        ("suppress_blank", C.c_bool),
        ("suppress_nst", C.c_bool),
        ("temperature", C.c_float),
        ("max_initial_ts", C.c_float),
        ("length_penalty", C.c_float),
        ("temperature_inc", C.c_float),
        ("entropy_thold", C.c_float),
        ("logprob_thold", C.c_float),
        ("no_speech_thold", C.c_float),
        ("greedy", Greedy),
        ("beam_search", BeamSearch),
        ("new_segment_callback", C.c_void_p),
        ("new_segment_callback_user_data", C.c_void_p),
        ("progress_callback", C.c_void_p),
        ("progress_callback_user_data", C.c_void_p),
        ("encoder_begin_callback", C.c_void_p),
        ("encoder_begin_callback_user_data", C.c_void_p),
        ("abort_callback", C.c_void_p),
        ("abort_callback_user_data", C.c_void_p),
        ("logits_filter_callback", C.c_void_p),
        ("logits_filter_callback_user_data", C.c_void_p),
        ("grammar_rules", C.c_void_p),
        ("n_grammar_rules", C.c_size_t),
        ("i_start_rule", C.c_size_t),
        ("grammar_penalty", C.c_float),
        ("vad", C.c_bool),
        ("vad_model_path", C.c_char_p),
        ("vad_params", WhisperVadParams),
    ]


class Whisper:
    """One loaded model. Not thread safe: call transcribe() from one thread at a time."""

    def __init__(self, dll_dir, model_path, use_gpu=True):
        dll_dir = Path(dll_dir)
        self._dll_dir_handle = os.add_dll_directory(str(dll_dir))
        lib = C.CDLL(str(dll_dir / "whisper.dll"))

        lib.whisper_context_default_params_by_ref.restype = C.POINTER(WhisperContextParams)
        lib.whisper_init_from_file_with_params.argtypes = [C.c_char_p, WhisperContextParams]
        lib.whisper_init_from_file_with_params.restype = C.c_void_p
        lib.whisper_full_default_params_by_ref.argtypes = [C.c_int]
        lib.whisper_full_default_params_by_ref.restype = C.POINTER(WhisperFullParams)
        lib.whisper_full.argtypes = [C.c_void_p, WhisperFullParams, C.POINTER(C.c_float), C.c_int]
        lib.whisper_full.restype = C.c_int
        lib.whisper_full_n_segments.argtypes = [C.c_void_p]
        lib.whisper_full_n_segments.restype = C.c_int
        lib.whisper_full_get_segment_text.argtypes = [C.c_void_p, C.c_int]
        lib.whisper_full_get_segment_text.restype = C.c_char_p
        lib.whisper_full_get_segment_no_speech_prob.argtypes = [C.c_void_p, C.c_int]
        lib.whisper_full_get_segment_no_speech_prob.restype = C.c_float
        lib.whisper_full_get_segment_t0.argtypes = [C.c_void_p, C.c_int]
        lib.whisper_full_get_segment_t0.restype = C.c_int64
        lib.whisper_full_get_segment_t1.argtypes = [C.c_void_p, C.c_int]
        lib.whisper_full_get_segment_t1.restype = C.c_int64
        lib.whisper_free.argtypes = [C.c_void_p]
        lib.whisper_free_params.argtypes = [C.c_void_p]
        lib.whisper_free_context_params.argtypes = [C.c_void_p]
        self.lib = lib

        cparams_p = lib.whisper_context_default_params_by_ref()
        cparams = WhisperContextParams.from_buffer_copy(cparams_p.contents)
        lib.whisper_free_context_params(cparams_p)
        cparams.use_gpu = use_gpu
        cparams.flash_attn = False  # RX 580 has no fp16 support; keep the safe path

        self.ctx = lib.whisper_init_from_file_with_params(str(model_path).encode(), cparams)
        if not self.ctx:
            raise RuntimeError(f"Failed to load model {model_path}")

        fparams_p = lib.whisper_full_default_params_by_ref(WHISPER_SAMPLING_GREEDY)
        self._defaults = WhisperFullParams.from_buffer_copy(fparams_p.contents)
        lib.whisper_free_params(fparams_p)

    def transcribe(self, audio16k, language="auto", prompt="", translate=False, no_speech_max=0.6):
        """Transcribe 16 kHz mono float32 audio and return the text."""
        self._full(audio16k, language, prompt, translate)

        # Join raw bytes first: a multi-byte character can be split across segments.
        parts = []
        for i in range(self.lib.whisper_full_n_segments(self.ctx)):
            if self.lib.whisper_full_get_segment_no_speech_prob(self.ctx, i) > no_speech_max:
                continue
            parts.append(self.lib.whisper_full_get_segment_text(self.ctx, i))
        return b"".join(parts).decode("utf-8", "replace").strip()

    def transcribe_long(self, audio16k, language, on_text, on_progress=None, no_speech_max=0.6):
        """Transcribe a whole file in one whisper_full call, streaming text as it's decoded.

        whisper.cpp walks long audio in 30 s steps and seeks by its own timestamps, so
        nothing is cut mid-word and nothing is stitched here. on_text(str) gets each new
        segment and on_progress(percent) the progress. Both run on the calling thread,
        inside whisper_full. An exception in either is re-raised after whisper_full returns.
        """
        decoder = codecs.getincrementaldecoder("utf-8")("replace")  # a character can span segments
        errors = []

        @SegmentCallback
        def segment_cb(ctx, state, n_new, user_data):
            try:
                n = self.lib.whisper_full_n_segments(self.ctx)
                for i in range(n - n_new, n):
                    if self.lib.whisper_full_get_segment_no_speech_prob(self.ctx, i) > no_speech_max:
                        continue
                    raw = self.lib.whisper_full_get_segment_text(self.ctx, i)
                    t0 = self.lib.whisper_full_get_segment_t0(self.ctx, i) / 100  # 10 ms units → s
                    t1 = self.lib.whisper_full_get_segment_t1(self.ctx, i) / 100
                    if is_too_dense(raw.decode("utf-8", "replace"), t0, t1):  # characters, not bytes
                        continue
                    text = decoder.decode(raw)
                    if text:
                        on_text(text)
            except Exception as e:  # an exception can't cross the C frame: keep it for later
                errors.append(e)

        @ProgressCallback
        def progress_cb(ctx, state, progress, user_data):
            try:
                if on_progress:
                    on_progress(progress)
            except Exception as e:
                errors.append(e)

        self._full(audio16k, language, "", False, segment_cb, progress_cb)
        tail = decoder.decode(b"", final=True)
        if tail:
            on_text(tail)
        if errors:
            raise errors[0]

    def _full(self, audio16k, language, prompt, translate, segment_cb=None, progress_cb=None):
        """Run whisper_full with Wisper's settings. The callbacks must stay alive until it returns."""
        audio = np.ascontiguousarray(audio16k, dtype=np.float32)
        p = WhisperFullParams.from_buffer_copy(self._defaults)
        p.n_threads = min(4, os.cpu_count() or 4)
        p.no_context = True
        p.single_segment = False
        p.print_progress = p.print_realtime = p.print_timestamps = p.print_special = False
        p.suppress_nst = True
        p.temperature = 0.0
        p.translate = translate
        lang = (language or "auto").encode()
        prompt_b = prompt.encode() if prompt else None
        p.language = lang
        p.initial_prompt = prompt_b
        if segment_cb:
            p.new_segment_callback = C.cast(segment_cb, C.c_void_p).value
        if progress_cb:
            p.progress_callback = C.cast(progress_cb, C.c_void_p).value

        rc = self.lib.whisper_full(
            self.ctx, p, audio.ctypes.data_as(C.POINTER(C.c_float)), len(audio)
        )
        if rc != 0:
            raise RuntimeError(f"whisper_full failed ({rc})")

    def close(self):
        if self.ctx:
            self.lib.whisper_free(self.ctx)
            self.ctx = None
