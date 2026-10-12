"""D10: whatever Wisper starts dies with it, however Wisper ends (spec 2026-10-12-deepseek-terminal §4.7, P5).

A real parent process puts itself in the kill-on-close Job Object (`priority.kill_children_with_me`)
and starts a child; the parent is then killed with `taskkill /F`. Without the job the child
survives, which shows the test can tell the difference. pytest itself is never put in a job.
"""

import ctypes as C
import ctypes.wintypes as W
import subprocess
import sys
from pathlib import Path

import pytest

import priority

APP = Path(__file__).resolve().parent.parent
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0

PARENT = """
import os, subprocess, sys, time
sys.path.insert(0, sys.argv[1])
import priority
joined = priority.kill_children_with_me() if sys.argv[2] == "job" else False
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print(os.getpid(), child.pid, joined, flush=True)
time.sleep(60)
"""

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
k32.CloseHandle.argtypes = [W.HANDLE]


def test_the_limit_structure_has_windows_size():
    assert C.sizeof(priority._ExtendedLimit) == (144 if C.sizeof(C.c_void_p) == 8 else 112)


@pytest.mark.parametrize("job, dies", [("job", True), ("none", False)])
def test_a_child_dies_with_its_parent_only_under_the_job(job, dies):
    parent = subprocess.Popen([sys.executable, "-c", PARENT, str(APP), job], stdout=subprocess.PIPE, text=True)
    child_handle = None
    try:
        parent_pid, child_pid, joined = parent.stdout.readline().split()     # type: ignore[union-attr]
        assert joined == str(job == "job")
        child_handle = k32.OpenProcess(SYNCHRONIZE, False, int(child_pid))
        assert child_handle, f"couldn't open the child: {C.get_last_error()}"
        subprocess.run(["taskkill", "/F", "/PID", parent_pid], check=True, capture_output=True)
        ended = k32.WaitForSingleObject(child_handle, 5000) == WAIT_OBJECT_0
        assert ended is dies
        if not dies:
            subprocess.run(["taskkill", "/F", "/T", "/PID", child_pid], capture_output=True)
    finally:
        if child_handle:
            k32.CloseHandle(child_handle)
        parent.kill()
        parent.wait(timeout=5)
