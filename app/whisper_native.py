"""Minimal ctypes binding for whisper.cpp's whisper.dll (Vulkan build).

Loads the model once and keeps it on the GPU. Struct layouts mirror
whisper.cpp/include/whisper.h and must be updated if that header changes.
"""

import ctypes as C
import os
from pathlib import Path

import numpy as np

WHISPER_SAMPLING_GREEDY = 0


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

        rc = self.lib.whisper_full(
            self.ctx, p, audio.ctypes.data_as(C.POINTER(C.c_float)), len(audio)
        )
        if rc != 0:
            raise RuntimeError(f"whisper_full failed ({rc})")

        # Join raw bytes first: a multi-byte character can be split across segments.
        parts = []
        for i in range(self.lib.whisper_full_n_segments(self.ctx)):
            if self.lib.whisper_full_get_segment_no_speech_prob(self.ctx, i) > no_speech_max:
                continue
            parts.append(self.lib.whisper_full_get_segment_text(self.ctx, i))
        return b"".join(parts).decode("utf-8", "replace").strip()

    def close(self):
        if self.ctx:
            self.lib.whisper_free(self.ctx)
            self.ctx = None
