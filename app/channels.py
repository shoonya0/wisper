"""Ear channels (spec _docs/specs/2026-10-15-ear-channels.md): hear each app in the left ear, the right
ear or both, through Windows' per-app channel volumes. No audio passes through Wisper.

C1: the pure core, no COM. `gains` is the §3.2 rule, `Selection` one ear's choice (rule 3.2.5),
`menu_items` the rows of one ear's menu (rule 3.2.7), `Journal` the restore file of §5.4: the
volumes each session had **before** Wisper's first change, so a crash can't leave them changed
(Windows remembers them, §4.2). Volumes are floats 0..1.

C2: `WasapiAudio`, the only COM code (§5.1): the default output, its sessions as `Session`s, and
their channel volumes (`IChannelAudioVolume`, VERIFIED in the C0 spike, tools/ear_spike.py).
"""

import ctypes
import json
import os
from ctypes import POINTER, Structure, byref, c_float, c_uint, c_ushort, c_void_p, wstring_at
from ctypes.wintypes import BOOL, DWORD, HANDLE, LPCWSTR, LPVOID, UINT
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

import comtypes
from comtypes import CLSCTX_ALL, GUID, HRESULT, STDMETHOD, IUnknown

ALL = "*all*"  # the "All apps (default)" choice; never a real app key (keys are exe paths)
ALL_LABEL = "All apps (default)"
NOT_RUNNING = " (not running)"
JOURNAL_NAME = "ear-channels-restore.json"


def _clamp(v):
    return min(1.0, max(0.0, float(v)))


@dataclass(frozen=True)
class Selection:
    """One ear's choice: All apps (no keys) or a set of app keys. Immutable, so it can be put on the
    router's queue as is; `toggle` and `choose_all` return a new one."""

    keys: frozenset[str] = frozenset()

    @property
    def is_all(self):
        return not self.keys

    def includes(self, key):
        return self.is_all or key in self.keys

    def toggle(self, key):
        """Rule 3.2.5: checking an app unchecks All apps, checking All apps unchecks the apps,
        unchecking the last app checks All apps again."""
        if key == ALL:
            return self.choose_all()
        return Selection(self.keys ^ {key})

    def choose_all(self):
        return Selection()


class App(NamedTuple):
    key: str      # exe path, lower case (§4.4)
    name: str     # what the menus show
    running: bool  # False: gone, but kept because an ear has it checked (rule 3.2.7)


class MenuItem(NamedTuple):
    key: str      # an App key, or ALL
    label: str
    checked: bool


def gains(app, left, right, left_vol, right_vol, app_vol=1.0):
    """§3.2: `app`'s (left, right) channel volumes. An ear plays the app at the ear's volume times the
    app's volume if it is All apps or has the app checked, else not at all (D4)."""
    a = _clamp(app_vol)
    return (_clamp(left_vol) * a if left.includes(app) else 0.0,
            _clamp(right_vol) * a if right.includes(app) else 0.0)


def untouched(left, right, left_vol, right_vol, app_vols):
    """Rule 3.2.1: both ears All apps and every volume 100 %. Then Wisper changes nothing and puts back
    what it changed (§5.4). `app_vols` is {key: volume} of the apps the user set."""
    return (left.is_all and right.is_all and _clamp(left_vol) == 1.0 and _clamp(right_vol) == 1.0
            and all(_clamp(v) == 1.0 for v in app_vols.values()))


def menu_items(apps, selection):
    """The rows of one ear's menu: All apps, a separator (None), then the apps sorted by name. A gone
    app stays while this ear has it checked, as "Name (not running)"; an unchecked gone one is left out."""
    rows: list[MenuItem | None] = [MenuItem(ALL, ALL_LABEL, selection.is_all), None]
    for app in sorted(apps, key=lambda a: (a.name.casefold(), a.key)):
        checked = app.key in selection.keys
        if app.running:
            rows.append(MenuItem(app.key, app.name, checked))
        elif checked:
            rows.append(MenuItem(app.key, app.name + NOT_RUNNING, True))
    return rows


def silent(apps, left, right):
    """Rule 3.2.2: names of the running apps that play in neither ear (the status line names them)."""
    return [a.name for a in sorted(apps, key=lambda a: a.name.casefold())
            if a.running and not left.includes(a.key) and not right.includes(a.key)]


def journal_path():
    """%LOCALAPPDATA%\\Wisper\\ear-channels-restore.json (D6): outside the repo, survives a crash."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Wisper" / JOURNAL_NAME


class Journal:
    """{session identifier: [left, right]} of the volumes a session had before Wisper's first change.
    Written before each change (`remember`), so a crash between the write and the change only restores
    what was already there. Every write is atomic (temp file + os.replace): a crash in the middle leaves
    the old file. The file is removed once empty. Not thread safe: the ear-channels thread only."""

    def __init__(self, path):
        self.path = Path(path)
        self._entries = self._load()

    def _load(self):
        """A missing file is an empty journal. A file that can't be read (locked, no access) raises, so it is
        never overwritten. A damaged one is moved aside to `<name>.bad` first, for the same reason."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            os.replace(self.path, self.path.with_name(self.path.name + ".bad"))
            return {}
        entries = {}
        for ident, vols in data.items():
            if (isinstance(vols, list) and len(vols) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vols)):
                entries[ident] = (_clamp(vols[0]), _clamp(vols[1]))
        return entries

    def entries(self):
        return dict(self._entries)

    def __contains__(self, ident):
        return ident in self._entries

    def remember(self, ident, left, right):
        """Keep the first volumes seen for `ident`; later calls don't overwrite them."""
        if ident in self._entries:
            return
        self._entries[ident] = (_clamp(left), _clamp(right))
        try:
            self._write()
        except OSError:
            del self._entries[ident]
            raise

    def forget(self, ident):
        if ident not in self._entries:
            return
        old = self._entries.pop(ident)
        try:
            self._write()
        except OSError:
            self._entries[ident] = old
            raise

    def _write(self):
        if not self._entries:
            self.path.unlink(missing_ok=True)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({k: list(v) for k, v in self._entries.items()}, f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)


# ---- C2: the COM layer (mmdeviceapi.h, audiopolicy.h; GUIDs and method order as in the C0 spike) -------------------

SYSTEM_KEY = "*system sounds*"  # the system-sounds session has no process (pid 0)
SYSTEM_NAME = "System sounds"
OWN_NAME = "Wisper (narration)"
STATE_INACTIVE, STATE_ACTIVE, STATE_EXPIRED = 0, 1, 2


@dataclass
class Session:
    """One audio session on the default output. `handle` is the COM object `WasapiAudio` reads and sets
    through; only the thread that listed the session may use it (§5.2). Fakes leave it None."""

    key: str                  # app key: exe path in lower case, SYSTEM_KEY, or "pid:N" if the path can't be read
    name: str
    pid: int
    identifier: str           # GetSessionIdentifier: stable per app and device (§4.1); the journal's key
    channels: int
    state: int                # STATE_INACTIVE or STATE_ACTIVE (expired sessions aren't listed)
    volumes: tuple[float, ...]  # as read when the session was listed
    handle: Any = field(default=None, compare=False, repr=False)


def describe(pid, path, system, own_pid, description=""):
    """(key, name) of a session's app (§4.4): grouped by exe path; named by the exe's FileDescription, else
    the exe name without .exe. The system-sounds session and Wisper's own process have fixed names."""
    if system:
        return SYSTEM_KEY, SYSTEM_NAME
    key = path.lower() if path else f"pid:{pid}"
    if pid == own_pid:
        return key, OWN_NAME
    if description:
        return key, description
    exe = path.rsplit("\\", 1)[-1] if path else f"Process {pid}"
    return key, exe[:-4] if exe.lower().endswith(".exe") else exe


class _PROPERTYKEY(Structure):
    _fields_ = [("fmtid", GUID), ("pid", DWORD)]


class _PROPVARIANT(Structure):  # only the VT_LPWSTR case is read
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                ("data", c_void_p), ("pad", c_void_p)]


class IPropertyStore(IUnknown):
    _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    _methods_ = [
        STDMETHOD(HRESULT, "GetCount", [POINTER(DWORD)]),
        STDMETHOD(HRESULT, "GetAt", [DWORD, POINTER(_PROPERTYKEY)]),
        STDMETHOD(HRESULT, "GetValue", [POINTER(_PROPERTYKEY), POINTER(_PROPVARIANT)]),
        STDMETHOD(HRESULT, "SetValue", [POINTER(_PROPERTYKEY), POINTER(_PROPVARIANT)]),
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
        STDMETHOD(HRESULT, "GetDevice", [LPCWSTR, POINTER(POINTER(IMMDevice))]),
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


_CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
_PKEY_Device_FriendlyName = _PROPERTYKEY(GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14)
_E_RENDER, _E_MULTIMEDIA, _VT_LPWSTR, _STGM_READ = 0, 1, 31, 0
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Own DLL objects, so the argtypes set here don't leak into other modules' ctypes.windll.
_ole32, _kernel32, _version = ctypes.WinDLL("ole32"), ctypes.WinDLL("kernel32"), ctypes.WinDLL("version")
_kernel32.OpenProcess.restype = HANDLE
_kernel32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
_kernel32.QueryFullProcessImageNameW.argtypes = [HANDLE, DWORD, ctypes.c_wchar_p, POINTER(DWORD)]
_kernel32.CloseHandle.argtypes = [HANDLE]
_version.GetFileVersionInfoSizeW.argtypes = [LPCWSTR, POINTER(DWORD)]
_version.GetFileVersionInfoW.argtypes = [LPCWSTR, DWORD, DWORD, LPVOID]
_version.VerQueryValueW.argtypes = [LPVOID, LPCWSTR, POINTER(LPVOID), POINTER(UINT)]
_ole32.CoTaskMemFree.argtypes = [c_void_p]
_ole32.PropVariantClear.argtypes = [c_void_p]


def _take_string(p):
    """A CoTaskMem string from an out parameter, freed."""
    s = wstring_at(p.value) if p.value else ""
    _ole32.CoTaskMemFree(p)
    return s


def exe_path(pid):
    """Full Win32 path of a process's exe, or "" (process gone, or no access)."""
    h = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf, n = ctypes.create_unicode_buffer(1024), DWORD(1024)
        return buf.value if _kernel32.QueryFullProcessImageNameW(h, 0, buf, byref(n)) else ""
    finally:
        _kernel32.CloseHandle(h)


def file_description(path):
    """The exe's version-info FileDescription ("Discord", "Zoom Meetings"), or ""."""
    size = _version.GetFileVersionInfoSizeW(path, None)
    if not size:
        return ""
    data = ctypes.create_string_buffer(size)
    if not _version.GetFileVersionInfoW(path, 0, size, data):
        return ""
    p, n = LPVOID(), UINT()
    if not _version.VerQueryValueW(data, "\\VarFileInfo\\Translation", byref(p), byref(n)) or n.value < 4:
        return ""
    words = ctypes.cast(p, POINTER(c_ushort))
    lang, cp = words[0], words[1]
    if not _version.VerQueryValueW(data, f"\\StringFileInfo\\{lang:04x}{cp:04x}\\FileDescription", byref(p), byref(n)):
        return ""
    return wstring_at(p.value or 0, max(n.value - 1, 0)).strip() if n.value else ""


def _read_volumes(vol):
    n = c_uint()
    vol.GetChannelCount(byref(n))
    out = []
    for k in range(n.value):
        v = c_float()
        vol.GetChannelVolume(k, byref(v))
        out.append(v.value)
    return tuple(out)


class WasapiAudio:
    """The default output's audio sessions and their channel volumes. Not thread safe: COM objects belong to
    the thread that made them, so one thread (the router's, §5.2) makes every call, after initialising COM on
    it. COM failures raise `comtypes.COMError` (or OSError); a session that ends while it is read is skipped."""

    def __init__(self):
        self._enum: Any = None
        self._device: Any = None
        self._device_id = ""
        self._names: dict[str, str] = {}  # exe path -> FileDescription, read once per exe
        self._own_pid = os.getpid()

    def _enumerator(self):
        if self._enum is None:
            self._enum = comtypes.CoCreateInstance(_CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL)
        return self._enum

    def default_output(self):
        """(device id, friendly name) of the Windows default output (eRender, eMultimedia; §5.3)."""
        dev: Any = POINTER(IMMDevice)()
        self._enumerator().GetDefaultAudioEndpoint(_E_RENDER, _E_MULTIMEDIA, byref(dev))
        raw = c_void_p()
        dev.GetId(byref(raw))
        device_id = _take_string(raw)
        store: Any = POINTER(IPropertyStore)()
        dev.OpenPropertyStore(_STGM_READ, byref(store))
        pv = _PROPVARIANT()
        store.GetValue(byref(_PKEY_Device_FriendlyName), byref(pv))
        name = wstring_at(pv.data) if pv.vt == _VT_LPWSTR and pv.data else device_id
        _ole32.PropVariantClear(byref(pv))
        self._device, self._device_id = dev, device_id
        return device_id, name

    def _device_for(self, device_id):
        if device_id != self._device_id or self._device is None:
            dev: Any = POINTER(IMMDevice)()
            self._enumerator().GetDevice(device_id, byref(dev))
            self._device, self._device_id = dev, device_id
        return self._device

    def sessions(self, device_id):
        """Every live session on the device (expired ones skipped), with their volumes read."""
        unk: Any = POINTER(IUnknown)()
        self._device_for(device_id).Activate(byref(IAudioSessionManager2._iid_), CLSCTX_ALL, None, byref(unk))
        mgr: Any = unk.QueryInterface(IAudioSessionManager2)
        en: Any = POINTER(IAudioSessionEnumerator)()
        mgr.GetSessionEnumerator(byref(en))
        n = ctypes.c_int()
        en.GetCount(byref(n))
        out = []
        for i in range(n.value):
            try:
                session = self._session(en, i)
            except (comtypes.COMError, OSError):
                continue  # the session ended while we read it
            if session is not None:
                out.append(session)
        return out

    def _session(self, en, i):
        s: Any = POINTER(IUnknown)()
        en.GetSession(i, byref(s))
        c2: Any = s.QueryInterface(IAudioSessionControl2)
        state = c_uint()
        c2.GetState(byref(state))
        if state.value == STATE_EXPIRED:
            return None
        vol: Any = s.QueryInterface(IChannelAudioVolume)
        pid, raw = DWORD(), c_void_p()
        c2.GetProcessId(byref(pid))
        c2.GetSessionIdentifier(byref(raw))
        identifier = _take_string(raw)
        system = c2.IsSystemSoundsSession() == 0  # S_OK: yes, S_FALSE: no
        path = "" if system else exe_path(pid.value)
        if path and path not in self._names:
            self._names[path] = file_description(path)
        key, name = describe(pid.value, path, system, self._own_pid, self._names.get(path, ""))
        volumes = _read_volumes(vol)
        return Session(key, name, pid.value, identifier, len(volumes), state.value, volumes, handle=vol)

    def get(self, session):
        """The session's channel volumes, read now."""
        return _read_volumes(session.handle)

    def set(self, session, left, right):
        """Set a stereo session's left and right volumes (0..1). ValueError for a session that isn't stereo."""
        if session.channels != 2:
            raise ValueError(f"{session.name}: {session.channels} channels, not stereo")
        session.handle.SetChannelVolume(0, _clamp(left), None)
        session.handle.SetChannelVolume(1, _clamp(right), None)

    def close(self):
        """Drop the cached COM objects, so they are released on this thread before it calls CoUninitialize. The
        caller drops its `Session`s too (their handles are COM objects)."""
        self._enum = self._device = None
        self._device_id = ""
