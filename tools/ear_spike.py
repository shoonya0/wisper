"""Per-app left/right volumes on the default output, from Python (comtypes).

Spike C0 of _docs/specs/2026-10-15-ear-channels.md. Not part of the app; results go into
the spec (§4.1, §4.4) and _docs/performance.md.

    app\\.venv\\Scripts\\python.exe tools/ear_spike.py list           # sessions on the default output
    app\\.venv\\Scripts\\python.exe tools/ear_spike.py check          # set/read/loopback/restore/persist/timing
    app\\.venv\\Scripts\\python.exe tools/ear_spike.py watch 120      # print session changes for 120 s
    app\\.venv\\Scripts\\python.exe tools/ear_spike.py set PID L R    # set a process's sessions (e.g. restore 1 1)

`check` plays a quiet 440 Hz tone (amplitude 0.005) from a child process and records the
speakers' loopback; every volume it changes is set back to (1, 1) before it exits.
"""

import ctypes
import os
import subprocess
import sys
import threading
import time
from ctypes import POINTER, Structure, byref, c_float, c_uint, c_ushort, c_void_p, wstring_at
from ctypes.wintypes import BOOL, DWORD, HANDLE, LPCWSTR, LPVOID, UINT

import comtypes
from comtypes import CLSCTX_ALL, GUID, HRESULT, STDMETHOD, IUnknown

# ---- COM interfaces (mmdeviceapi.h, audiopolicy.h, audioclient.h) -------------------------------------------------


class PROPERTYKEY(Structure):
    _fields_ = [("fmtid", GUID), ("pid", DWORD)]


class PROPVARIANT(Structure):  # only the VT_LPWSTR case is read
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                ("data", c_void_p), ("pad", c_void_p)]


class IPropertyStore(IUnknown):
    _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    _methods_ = [
        STDMETHOD(HRESULT, "GetCount", [POINTER(DWORD)]),
        STDMETHOD(HRESULT, "GetAt", [DWORD, POINTER(PROPERTYKEY)]),
        STDMETHOD(HRESULT, "GetValue", [POINTER(PROPERTYKEY), POINTER(PROPVARIANT)]),
        STDMETHOD(HRESULT, "SetValue", [POINTER(PROPERTYKEY), POINTER(PROPVARIANT)]),
        STDMETHOD(HRESULT, "Commit", []),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        STDMETHOD(HRESULT, "Activate", [POINTER(GUID), DWORD, c_void_p, POINTER(POINTER(IUnknown))]),
        STDMETHOD(HRESULT, "OpenPropertyStore", [DWORD, POINTER(POINTER(IPropertyStore))]),
        STDMETHOD(HRESULT, "GetId", [POINTER(c_void_p)]),
        STDMETHOD(HRESULT, "GetState", [POINTER(DWORD)]),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        STDMETHOD(HRESULT, "EnumAudioEndpoints", [UINT, DWORD, POINTER(c_void_p)]),
        STDMETHOD(HRESULT, "GetDefaultAudioEndpoint", [UINT, UINT, POINTER(POINTER(IMMDevice))]),
    ]


class IAudioSessionControl2(IUnknown):  # IAudioSessionControl's 9 methods, then its own 5
    _iid_ = GUID("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")
    _methods_ = [
        STDMETHOD(HRESULT, "GetState", [POINTER(c_uint)]),
        STDMETHOD(HRESULT, "GetDisplayName", [POINTER(c_void_p)]),
        STDMETHOD(HRESULT, "SetDisplayName", [LPCWSTR, c_void_p]),
        STDMETHOD(HRESULT, "GetIconPath", [POINTER(c_void_p)]),
        STDMETHOD(HRESULT, "SetIconPath", [LPCWSTR, c_void_p]),
        STDMETHOD(HRESULT, "GetGroupingParam", [POINTER(GUID)]),
        STDMETHOD(HRESULT, "SetGroupingParam", [POINTER(GUID), c_void_p]),
        STDMETHOD(HRESULT, "RegisterAudioSessionNotification", [c_void_p]),
        STDMETHOD(HRESULT, "UnregisterAudioSessionNotification", [c_void_p]),
        STDMETHOD(HRESULT, "GetSessionIdentifier", [POINTER(c_void_p)]),
        STDMETHOD(HRESULT, "GetSessionInstanceIdentifier", [POINTER(c_void_p)]),
        STDMETHOD(HRESULT, "GetProcessId", [POINTER(DWORD)]),
        STDMETHOD(HRESULT, "IsSystemSoundsSession", []),
        STDMETHOD(HRESULT, "SetDuckingPreference", [BOOL]),
    ]


class IAudioSessionEnumerator(IUnknown):
    _iid_ = GUID("{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}")
    _methods_ = [
        STDMETHOD(HRESULT, "GetCount", [POINTER(ctypes.c_int)]),
        STDMETHOD(HRESULT, "GetSession", [ctypes.c_int, POINTER(POINTER(IUnknown))]),
    ]


class IAudioSessionManager2(IUnknown):
    _iid_ = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
    _methods_ = [
        STDMETHOD(HRESULT, "GetAudioSessionControl", [c_void_p, DWORD, POINTER(c_void_p)]),
        STDMETHOD(HRESULT, "GetSimpleAudioVolume", [c_void_p, DWORD, POINTER(c_void_p)]),
        STDMETHOD(HRESULT, "GetSessionEnumerator", [POINTER(POINTER(IAudioSessionEnumerator))]),
    ]


class IChannelAudioVolume(IUnknown):
    _iid_ = GUID("{1C158861-B533-4B30-B1CF-E853E51C59B8}")
    _methods_ = [
        STDMETHOD(HRESULT, "GetChannelCount", [POINTER(c_uint)]),
        STDMETHOD(HRESULT, "SetChannelVolume", [c_uint, c_float, c_void_p]),
        STDMETHOD(HRESULT, "GetChannelVolume", [c_uint, POINTER(c_float)]),
        STDMETHOD(HRESULT, "SetAllVolumes", [c_uint, POINTER(c_float), c_void_p]),
        STDMETHOD(HRESULT, "GetAllVolumes", [c_uint, POINTER(c_float)]),
    ]


CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
PKEY_Device_FriendlyName = PROPERTYKEY(GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14)
E_RENDER, E_MULTIMEDIA, VT_LPWSTR = 0, 1, 31
STATES = {0: "inactive", 1: "active", 2: "expired"}

ole32, kernel32, version = ctypes.windll.ole32, ctypes.windll.kernel32, ctypes.windll.version
kernel32.OpenProcess.restype = HANDLE
kernel32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [HANDLE, DWORD, ctypes.c_wchar_p, POINTER(DWORD)]
kernel32.CloseHandle.argtypes = [HANDLE]
version.GetFileVersionInfoSizeW.argtypes = [LPCWSTR, POINTER(DWORD)]
version.GetFileVersionInfoW.argtypes = [LPCWSTR, DWORD, DWORD, LPVOID]
version.VerQueryValueW.argtypes = [LPVOID, LPCWSTR, POINTER(LPVOID), POINTER(UINT)]
ole32.CoTaskMemFree.argtypes = [c_void_p]


def _take_string(p: c_void_p) -> str:
    """A CoTaskMem string from an out parameter, freed."""
    s = wstring_at(p.value) if p.value else ""
    ole32.CoTaskMemFree(p)
    return s


# ---- helpers ------------------------------------------------------------------------------------------------------


def exe_path(pid: int) -> str:
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf, n = ctypes.create_unicode_buffer(1024), DWORD(1024)
        return buf.value if kernel32.QueryFullProcessImageNameW(h, 0, buf, byref(n)) else ""
    finally:
        kernel32.CloseHandle(h)


def file_description(path: str) -> str:
    size = version.GetFileVersionInfoSizeW(path, None)
    if not size:
        return ""
    data = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(path, 0, size, data):
        return ""
    p, n = LPVOID(), UINT()
    if not version.VerQueryValueW(data, "\\VarFileInfo\\Translation", byref(p), byref(n)) or n.value < 4:
        return ""
    lang, cp = ctypes.cast(p, POINTER(c_ushort))[0], ctypes.cast(p, POINTER(c_ushort))[1]
    if not version.VerQueryValueW(data, f"\\StringFileInfo\\{lang:04x}{cp:04x}\\FileDescription", byref(p), byref(n)):
        return ""
    return ctypes.wstring_at(p.value or 0, max(n.value - 1, 0)).strip() if n.value else ""


def default_output():
    """(IMMDevice, id, friendly name) of the Windows default output (eRender, eMultimedia)."""
    en = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL)
    dev = POINTER(IMMDevice)()
    en.GetDefaultAudioEndpoint(E_RENDER, E_MULTIMEDIA, byref(dev))
    raw = c_void_p()
    dev.GetId(byref(raw))
    store = POINTER(IPropertyStore)()
    dev.OpenPropertyStore(0, byref(store))  # STGM_READ
    pv = PROPVARIANT()
    store.GetValue(byref(PKEY_Device_FriendlyName), byref(pv))
    name = wstring_at(pv.data) if pv.vt == VT_LPWSTR and pv.data else "?"
    ole32.PropVariantClear(byref(pv))
    return dev, _take_string(raw), name


def sessions(dev):
    """Every session on the device: dicts with pid, exe, name, identifier, state, system, channels, volumes, vol."""
    unk = POINTER(IUnknown)()
    dev.Activate(byref(IAudioSessionManager2._iid_), CLSCTX_ALL, None, byref(unk))
    mgr = unk.QueryInterface(IAudioSessionManager2)
    en = POINTER(IAudioSessionEnumerator)()
    mgr.GetSessionEnumerator(byref(en))
    n = ctypes.c_int()
    en.GetCount(byref(n))
    out = []
    for i in range(n.value):
        s = POINTER(IUnknown)()
        en.GetSession(i, byref(s))
        c2, vol = s.QueryInterface(IAudioSessionControl2), s.QueryInterface(IChannelAudioVolume)
        pid, state, cc, raw = DWORD(), c_uint(), c_uint(), c_void_p()
        c2.GetProcessId(byref(pid))
        c2.GetState(byref(state))
        c2.GetSessionIdentifier(byref(raw))
        vol.GetChannelCount(byref(cc))
        vols = []
        for k in range(cc.value):
            v = c_float()
            vol.GetChannelVolume(k, byref(v))
            vols.append(round(v.value, 4))
        path = exe_path(pid.value)
        system = c2.IsSystemSoundsSession() == 0
        name = "System sounds" if system else (file_description(path) or path.rsplit("\\", 1)[-1].removesuffix(".exe"))
        out.append({"pid": pid.value, "exe": path, "name": name, "identifier": _take_string(raw),
                    "state": STATES.get(state.value, state.value), "system": system,
                    "channels": cc.value, "volumes": vols, "vol": vol})
    return out


def set_volumes(dev, pid: int, volumes) -> list:
    """Set every channel volume of `pid`'s sessions; returns the sessions touched (read back)."""
    for s in sessions(dev):
        if s["pid"] == pid:
            for k, v in enumerate(volumes[: s["channels"]]):
                s["vol"].SetChannelVolume(k, float(v), None)
    return [s for s in sessions(dev) if s["pid"] == pid]


def show(rows) -> None:
    for s in rows:
        print(f"  pid {s['pid']:>6}  {s['state']:<8} ch={s['channels']} vol={s['volumes']}  {s['name']!r}"
              f"  exe={s['exe'] or '-'}\n      id={s['identifier']}")


# ---- commands -----------------------------------------------------------------------------------------------------


def cmd_list() -> None:
    dev, dev_id, name = default_output()
    rows = sessions(dev)
    print(f"default output: {name}  ({dev_id})\n{len(rows)} session(s):")
    show(rows)


def cmd_tone(seconds: float) -> None:
    """Child process: a quiet 440 Hz tone in every channel of the default output."""
    import numpy as np
    import pyaudiowpatch as pa

    p = pa.PyAudio()
    info = p.get_device_info_by_index(p.get_host_api_info_by_type(pa.paWASAPI)["defaultOutputDevice"])
    ch, sr = int(info["maxOutputChannels"]), int(info["defaultSampleRate"])
    s = p.open(format=pa.paFloat32, channels=ch, rate=sr, output=True, output_device_index=info["index"])
    print(os.getpid(), flush=True)  # the venv python.exe is a launcher: Popen.pid is not this process
    t0, n = time.time(), 0
    while time.time() - t0 < seconds:
        t = (np.arange(4800) + n) / sr
        n += 4800
        s.write(np.repeat((0.005 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)[:, None], ch, 1).tobytes())
    s.close()
    p.terminate()


def _tone(seconds: float) -> tuple[subprocess.Popen, int]:
    child = subprocess.Popen([sys.executable, __file__, "tone", str(seconds)], stdout=subprocess.PIPE, text=True)
    assert child.stdout is not None
    return child, int(child.stdout.readline())


def _wait_session(dev, pid: int, timeout: float = 3.0) -> list:
    end = time.time() + timeout
    while time.time() < end:
        rows = [s for s in sessions(dev) if s["pid"] == pid]
        if rows:
            return rows
        time.sleep(0.1)
    raise RuntimeError(f"no session for pid {pid}")


def cmd_check() -> None:
    import numpy as np
    import pyaudiowpatch as pa

    dev, _, name = default_output()
    print(f"default output: {name}")

    # 1. set + read back + loopback RMS per ear
    p = pa.PyAudio()
    lb = p.get_default_wasapi_loopback()
    ch, sr = int(lb["maxInputChannels"]), int(lb["defaultSampleRate"])
    blocks, stop = [], threading.Event()
    rec = p.open(format=pa.paFloat32, channels=ch, rate=sr, input=True, input_device_index=lb["index"],
                 frames_per_buffer=sr // 10)

    def record():
        while not stop.is_set():
            data = rec.read(sr // 10, exception_on_overflow=False)
            blocks.append((time.time(), np.frombuffer(data, np.float32).reshape(-1, ch)))

    threading.Thread(target=record, daemon=True).start()
    child, pid = _tone(11)
    try:
        print("\n1. tone child's session(s):")
        show(_wait_session(dev, pid))
        marks, set_ms = [], []
        for label, v in [("both (1, 1)", None), ("set (1, 0)", (1, 0)), ("set (0, 1)", (0, 1)),
                         ("set (0.5, 1)", (0.5, 1)), ("restore (1, 1)", (1, 1))]:
            if v is not None:
                rows = [s for s in sessions(dev) if s["pid"] == pid]
                t = time.perf_counter()
                for s in rows:
                    for k, x in enumerate(v[: s["channels"]]):
                        s["vol"].SetChannelVolume(k, float(x), None)
                set_ms.append((time.perf_counter() - t) * 1000)
                back = [s["volumes"] for s in sessions(dev) if s["pid"] == pid]
                print(f"   {label:<15} read back {back}")
            marks.append((label, time.time()))
            time.sleep(1.8)
        marks.append(("end", time.time()))
    finally:
        set_volumes(dev, pid, (1, 1))
        child.wait()
        stop.set()
        time.sleep(0.2)
        rec.close()
        p.terminate()
    print("\n   loopback RMS per ear (blocks 0.3 s after each change):")
    for (label, a), (_, b) in zip(marks, marks[1:], strict=False):
        seg = [x for t, x in blocks if a + 0.3 < t < b - 0.05]
        if seg:
            rms = np.sqrt((np.concatenate(seg)[:, :2] ** 2).mean(0))
            print(f"   {label:<15} L={rms[0]:.5f} R={rms[1]:.5f}")
    print(f"   SetChannelVolume for both channels: {', '.join(f'{x:.2f}' for x in set_ms)} ms")

    # 2. persistence across a restart of the same exe
    print("\n2. persistence (same exe, new process):")
    child, pid = _tone(3)
    try:
        _wait_session(dev, pid)
        print("   run 1 set (0.5, 1):", [s["volumes"] for s in set_volumes(dev, pid, (0.5, 1))])
    finally:
        child.wait()
    time.sleep(0.5)
    child, pid = _tone(3)
    try:
        print("   run 2 starts at   :", [s["volumes"] for s in _wait_session(dev, pid)])
        print("   run 2 restore     :", [s["volumes"] for s in set_volumes(dev, pid, (1, 1))])
    finally:
        child.wait()
    time.sleep(0.5)
    child, pid = _tone(3)
    try:
        print("   run 3 starts at   :", [s["volumes"] for s in _wait_session(dev, pid)])
    finally:
        set_volumes(dev, pid, (1, 1))
        child.wait()

    # 3. cost of one poll (default device + list sessions with exe, name, identifier, volumes)
    n = 50
    wall, cpu = time.perf_counter(), time.process_time()
    for _ in range(n):
        d, _, _ = default_output()
        sessions(d)
    wall, cpu = (time.perf_counter() - wall) / n * 1000, (time.process_time() - cpu) / n * 1000
    print(f"\n3. one poll: {wall:.2f} ms wall, {cpu:.2f} ms CPU  ->  {cpu / 10:.3f} % of a core at 1 poll/s")


def cmd_watch(seconds: float) -> None:
    """Print sessions that appear, change state or volumes, or go away (open Discord, Zoom, Chrome tabs...)."""
    end, seen = time.time() + seconds, {}
    dev_id = None
    while time.time() < end:
        dev, did, name = default_output()
        if did != dev_id:
            print(f"[{time.strftime('%H:%M:%S')}] default output: {name}")
            dev_id, seen = did, {}
        now = {}
        for s in sessions(dev):
            key = (s["pid"], s["identifier"])
            now[key] = (s["state"], s["volumes"])
            if seen.get(key) != now[key]:
                verb = "new" if key not in seen else "chg"
                print(f"[{time.strftime('%H:%M:%S')}] {verb} pid {s['pid']:>6} {s['state']:<8} vol={s['volumes']} "
                      f"{s['name']!r}  exe={s['exe'] or '-'}\n           id={s['identifier']}")
        for key in seen.keys() - now.keys():
            print(f"[{time.strftime('%H:%M:%S')}] gone pid {key[0]:>6}  id={key[1]}")
        seen = now
        time.sleep(1.0)


def main() -> None:
    args = sys.argv[1:] or ["list"]
    match args:
        case ["list"]:
            cmd_list()
        case ["check"]:
            cmd_check()
        case ["watch", *rest]:
            cmd_watch(float(rest[0]) if rest else 60)
        case ["tone", sec]:
            cmd_tone(float(sec))
        case ["set", pid, *vols]:
            show(set_volumes(default_output()[0], int(pid), [float(v) for v in vols]))
        case _:
            print(__doc__)


if __name__ == "__main__":
    main()
