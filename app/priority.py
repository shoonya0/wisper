"""Raise CPU and GPU scheduling priority for this process on Windows, and tie its children's
lifetime to it (a kill-on-close Job Object).

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

JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

_job = None  # kept open for the life of the process: Windows closes it when the process ends


class _PowerThrottlingState(C.Structure):
    _fields_ = [("Version", W.ULONG), ("ControlMask", W.ULONG), ("StateMask", W.ULONG)]


class _BasicLimit(C.Structure):
    _fields_ = [("PerProcessUserTimeLimit", C.c_int64), ("PerJobUserTimeLimit", C.c_int64),
                ("LimitFlags",              W.DWORD),   ("MinimumWorkingSetSize", C.c_size_t),
                ("MaximumWorkingSetSize",   C.c_size_t), ("ActiveProcessLimit",   W.DWORD),
                ("Affinity",                C.c_size_t), ("PriorityClass",        W.DWORD),
                ("SchedulingClass",         W.DWORD)]


class _ExtendedLimit(C.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimit),   ("IoInfo",                C.c_uint64 * 6),
                ("ProcessMemoryLimit",    C.c_size_t),    ("JobMemoryLimit",        C.c_size_t),
                ("PeakProcessMemoryUsed", C.c_size_t),    ("PeakJobMemoryUsed",     C.c_size_t)]


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


def kill_children_with_me():
    """Put this process in a kill-on-close Job Object; returns True if it's in one.

    Every process it starts from then on, and theirs, joins the job. When this process ends,
    however it ends (a normal exit, a crash, `taskkill /F`), Windows closes the job's last
    handle and kills them all. Call it once, first thing in main(), never from tests: it would
    tie pytest's children to pytest.
    """
    global _job
    if sys.platform != "win32":
        return False
    if _job:
        return True
    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = W.HANDLE
    k32.CreateJobObjectW.argtypes = [C.c_void_p, W.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
    k32.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
    k32.GetCurrentProcess.restype = W.HANDLE
    k32.CloseHandle.argtypes = [W.HANDLE]
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return False
    info = _ExtendedLimit()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not (k32.SetInformationJobObject(job, JobObjectExtendedLimitInformation, C.byref(info), C.sizeof(info))
            and k32.AssignProcessToJobObject(job, k32.GetCurrentProcess())):
        k32.CloseHandle(job)
        return False
    _job = job
    return True
