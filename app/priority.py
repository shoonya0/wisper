"""Raise CPU and GPU scheduling priority for this process on Windows.

Whisper's GPU work is bursty: the encoder is one big batch, but decoding is
token-by-token, with the CPU submitting a small GPU job, waiting on it, then
sampling. Any delay on the CPU side (a busy machine, or Windows EcoQoS
throttling a background window) leaves the GPU idle between tokens. This
module removes those stalls; every call is best-effort and never raises.
"""

import ctypes as C
import ctypes.wintypes as W
import sys

HIGH_PRIORITY_CLASS = 0x80
THREAD_PRIORITY_HIGHEST = 2
D3DKMT_SCHEDULINGPRIORITYCLASS_HIGH = 4  # REALTIME (5) needs admin and can starve the desktop

ProcessPowerThrottling = 4
ThreadPowerThrottling = 3
POWER_THROTTLING_EXECUTION_SPEED = 0x1
POWER_THROTTLING_IGNORE_TIMER_RESOLUTION = 0x4


class _PowerThrottlingState(C.Structure):
    _fields_ = [("Version", W.ULONG), ("ControlMask", W.ULONG), ("StateMask", W.ULONG)]


def _no_throttling(control_mask):
    # Control bit set + state bit clear = "never throttle this", i.e. opt out of EcoQoS.
    return _PowerThrottlingState(1, control_mask, 0)


def boost_process():
    """High CPU priority, high GPU scheduling priority, no EcoQoS. Returns what applied."""
    if sys.platform != "win32":
        return []
    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = W.HANDLE
    proc = k32.GetCurrentProcess()
    applied = []

    k32.SetPriorityClass.argtypes = [W.HANDLE, W.DWORD]
    if k32.SetPriorityClass(proc, HIGH_PRIORITY_CLASS):
        applied.append("cpu-high")

    state = _no_throttling(POWER_THROTTLING_EXECUTION_SPEED | POWER_THROTTLING_IGNORE_TIMER_RESOLUTION)
    k32.SetProcessInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
    if k32.SetProcessInformation(proc, ProcessPowerThrottling, C.byref(state), C.sizeof(state)):
        applied.append("no-ecoqos")

    try:
        gdi = C.WinDLL("gdi32")
        gdi.D3DKMTSetProcessSchedulingPriorityClass.argtypes = [W.HANDLE, C.c_int]
        if gdi.D3DKMTSetProcessSchedulingPriorityClass(proc, D3DKMT_SCHEDULINGPRIORITYCLASS_HIGH) == 0:
            applied.append("gpu-high")
    except (OSError, AttributeError):
        pass
    return applied


def boost_thread():
    """Call from the inference thread: highest thread priority, no EcoQoS."""
    if sys.platform != "win32":
        return []
    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentThread.restype = W.HANDLE
    thread = k32.GetCurrentThread()
    applied = []

    k32.SetThreadPriority.argtypes = [W.HANDLE, C.c_int]
    if k32.SetThreadPriority(thread, THREAD_PRIORITY_HIGHEST):
        applied.append("thread-highest")

    state = _no_throttling(POWER_THROTTLING_EXECUTION_SPEED)
    k32.SetThreadInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
    if k32.SetThreadInformation(thread, ThreadPowerThrottling, C.byref(state), C.sizeof(state)):
        applied.append("thread-no-ecoqos")
    return applied
