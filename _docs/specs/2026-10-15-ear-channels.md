# Spec: Ear channels (hear each app in the left ear, the right ear or both)

| Field | Value |
|---|---|
| Status | Draft (2026-10-15): spec and steps written, C0's main question answered (§4.1); decisions D1–D8 proposed, waiting for the user's yes |
| Date | 2026-10-15 |
| Owner | shoonya0 |
| Priority | **Highest** (user, 2026-10-15): goes before narration latency |
| Test plan | `_docs/test/ear-channels.md` (written in C6) |

Claims are marked **VERIFIED** (run or read in code) or **ASSUMED**.

## 1. Problem

The user wears wired earphones and wants to hear **two apps at once without them
talking over each other**: for example Discord in the left ear and Zoom / Google Meet /
YouTube in the right ear. Windows plays every app in both ears and has no per-app
left/right control.

This is only about **what the user hears**. Nothing is sent anywhere: the people in the
Discord call or the meeting hear the user's mic exactly as before (user, 2026-10-15).

## 2. Goals and non-goals

**Goals**

1. A new strip at the **bottom of the window**, across both panes, with two channels:
   **Left ear** and **Right ear**.
2. Each channel has a dropdown of the apps that play sound on the earphones. At start-up
   both show **All apps (default)**, so every app plays in both ears as it does today.
3. When an app starts playing sound (or stops existing), **both dropdowns update** on
   their own, keeping what is chosen.
4. Choosing apps in a channel makes exactly those apps heard in that ear; each ear has its own
   volume. This is "full control" of the two channels (rules §3.2).
5. Nothing Wisper changes outlives it: closing Wisper, Reset, or the next start after a
   crash puts every app back the way it was (§4.2 explains why this matters).

**Non-goals (first version)**

- Bluetooth or USB headsets as a goal: they work if Windows gives them a stereo output
  (same API), but only wired earphones on the default output are checked.
- More than 2 channels (5.1/7.1 speakers): the strip says the device isn't stereo and
  stays disabled.
- Separating two tabs of the **same** browser (Meet and YouTube both in Chrome): Windows
  sees one app (§4.4). Workaround: use a second browser (Edge) for one of them.
- Remembering the choice between runs (no settings file yet; every start is All apps).
- Effects (EQ, mono mixdown, spatial audio).

## 3. User experience

### 3.1 The strip

Packed at the bottom of the root window **before** the panes (the same reason as
`_build_status`: a widget packed after a `fill="both", expand=True` one gets pushed off).

```text
┌ Speech to text ─────────────────────────┬ Text to speech ─────────────────────────┐
│ …                                       │ …                                       │
├─────────────────────────────────────────┴─────────────────────────────────────────┤
│ Ear channels   Earphones: Speakers (High Definition Audio Device)        [Reset]  │
│ Left ear:  [Discord               ▾]  Volume [━━━━━━━━━━━━○──]  85 %             │
│ Right ear: [Zoom Meetings, Edge   ▾]  Volume [━━━━━━━━━━━━━━○] 100 %             │
│ YouTube (Chrome) plays in neither ear.                                             │
└────────────────────────────────────────────────────────────────────────────────────┘
```

| Control | Behavior |
|---|---|
| Earphones | Name of the **Windows default output** (where the wired earphones play). It follows the default: plug in, switch device in Windows → the strip moves to the new device (§5.3) |
| Left ear / Right ear | A dropdown (`ttk.Menubutton` + a menu of check items, so one ear can take several apps): **All apps (default)**, a separator, then each app that has sound on the earphones, sorted by name. The button shows the chosen names, or "All apps (default)" |
| Volume | 0–100 % per ear (`ttk.Scale`), default 100 %. Applies at once while dragging (throttled to ~20 changes/s) |
| Reset | Both ears back to All apps at 100 %; every app back to what it had before Wisper (§5.4) |
| Status line | Says what isn't obvious: "X plays in neither ear.", "Earphones aren't stereo: ear channels are off.", "Ear channels stopped: <error>". Empty otherwise |

### 3.2 Rules

For each app **A** playing on the earphones, Wisper sets A's left and right volume:

```text
left(A)  = left_volume   if Left ear  is "All apps" or A is checked in Left ear  else 0
right(A) = right_volume  if Right ear is "All apps" or A is checked in Right ear else 0
```

1. **Both All apps at 100 %** (the start-up state): Wisper changes nothing; every app has
   the volumes it had before Wisper.
2. **The user's example**: Left = Discord, Right = Zoom Meetings → Discord only in the
   left ear, Zoom only in the right. An app checked in neither (YouTube in Chrome) plays in
   **neither** ear, and the status line says so (the user can check it into a channel).
3. Left = Discord, Right = All apps → Discord in both ears, every other app only in the
   right ear.
4. The same app in both channels plays in both ears, each at that ear's volume.
5. In a channel's menu, checking an app unchecks All apps; checking All apps unchecks
   the apps; unchecking the last app checks All apps again.
6. **New app**: it is added to both menus within ~1 s (unchecked) and gets the volumes the
   rule gives it right away (so with Discord / Zoom chosen, a new app starts silent and the
   status line names it). The selection doesn't change.
7. **App closes**: a checked app stays in the menu as "Discord (not running)" so the
   choice still holds when it comes back (Discord restarts its audio when a call
   starts); an unchecked one is removed from the menus.
8. **Wisper itself** (the narration) is listed as "Wisper (narration)" and follows the
   same rules.
9. Errors (COM failure, device gone) never show a dialog: the strip shows "Ear channels
   stopped: …", restores what it can, and Reset tries again.

### 3.3 Interaction with the rest of Wisper

- **Live captions** record the speakers' loopback, which is mixed **after** these
  volumes (VERIFIED §4.1: the loopback showed the tone in one ear only). Captions mix
  down to mono, so panning doesn't matter, but **an app in neither ear isn't captioned**.
  The status line's "plays in neither ear" covers it; documented in the test plan.
- The narration's Me / Others devices don't change. Others (VB-Cable) is a different
  device; the strip only touches the default output.

## 4. Why this design

### 4.1 Windows already has per-app left/right volumes (VERIFIED, 2026-10-15)

Each app's audio on a device is an **audio session**. Its `IAudioSessionControl` also
implements **`IChannelAudioVolume`** (one volume per channel), and another process can
change it. Spike (C# through PowerShell, files in the session scratchpad, re-done in Python in C0):

| Step | Result |
|---|---|
| Enumerate sessions on the default output (`IMMDeviceEnumerator` → `IAudioSessionManager2` → `IAudioSessionEnumerator`) | the system-sounds session and a separate `python` process playing silence: both QI to `IChannelAudioVolume`, 2 channels, L = R = 1.0 |
| Child process plays a 440 Hz tone at 0.005 in both channels; another process sets its session's channel volumes; a third records the speakers' loopback (RMS per channel) | both: L 0.00354 / R 0.00354 · set (1, 0): L 0.00354 / **R 0.00000** · set (0, 1): **L 0.00000** / R 0.00354 · set (0.5, 1): **L 0.00177** / R 0.00354 |

So **no audio passes through Wisper**: no capture, no mixing, no virtual cable, no
added delay, and it works the same for any app. The change takes effect within one
100 ms loopback block.

### 4.2 Windows remembers the volumes (VERIFIED, 2026-10-15)

Set `python.exe`'s session to (0.5, 1), let the process end, start a new one: it starts
at **(0.5, 1)**. Windows keeps per-app volumes across restarts (ASSUMED: and across
reboots, like the per-app volume in the Volume Mixer). Setting (1, 1) and restarting
gave (1, 1) again (the spike left `python.exe` as it was).

Consequence: if Wisper crashes or is killed (Task Manager, the Job Object, power loss)
while Discord is left-only, **Discord stays left-only** outside Wisper. Hence D6: a
restore journal on disk, written before each change and replayed at the next start.

### 4.3 Rejected

| Option | Why not |
|---|---|
| Capture each app (process loopback, Windows 10 2004+) and mix L/R in Wisper | The app still plays normally, so it has to be muted or routed elsewhere first; adds delay, CPU, glitches and a mixer thread. §4.1 does the same with no audio path |
| One virtual cable per app (per-app output device) and a Wisper mixer | Needs several VB-Cables (the user has one), the undocumented `IAudioPolicyConfig` API, and the same mixer |
| `pycaw` | Built on comtypes, but adds `psutil` and has more than we need; 5 small interfaces are defined in our module (D3) |

### 4.4 What an "app" is

Sessions are grouped by **process image path** (`QueryFullProcessImageNameW`): all of
Chrome's sessions (ASSUMED: Chrome plays every tab from one audio process, so Meet and
YouTube in Chrome are one session; C0 checks it) are one app. The name shown is the
exe's version-info `FileDescription` ("Discord", "Zoom Meetings", "Google Chrome",
"Microsoft Edge"), else the exe name without `.exe`; the session with
`IsSystemSoundsSession` is "System sounds"; Wisper's own process is "Wisper (narration)".

## 5. Design

### 5.1 `app/channels.py` (new leaf)

Imports only the stdlib, `ctypes` and `comtypes` (D3). Two layers, so most of it is
testable without audio:

| Name | Responsibility |
|---|---|
| `ALL` | The "All apps" choice |
| `gains(app, left, right, left_vol, right_vol)` | Pure: the §3.2 rule → `(l, r)` |
| `Selection` | Pure: one channel's choice (`ALL` or a set of app keys) and rule 3.2.5 (`toggle(key)`, `choose_all()`) |
| `menu_items(apps, selection)` | Pure: the rows of one menu (rule 3.2.7: "(not running)" for a checked app that is gone) |
| `Journal(path)` | Pure file logic: `{session_identifier: [l, r]}` of the volumes **before** Wisper's first change; `remember()`, `forget()`, `entries()`; atomic write (temp file + `os.replace`) |
| `Session` | Data: `key` (exe path, lower case), `name`, `pid`, `identifier` (`GetSessionIdentifier`: stable per app and device), `channels`, `state` |
| `WasapiAudio` | The **only COM code**: `default_output()` → `(device_id, name)`; `sessions(device_id)` → `[Session]` (expired ones skipped); `get(session)` / `set(session, l, r)` channel volumes. comtypes interface definitions for `IMMDeviceEnumerator`, `IMMDevice`, `IAudioSessionManager2`, `IAudioSessionEnumerator`, `IAudioSessionControl2`, `IChannelAudioVolume` (GUIDs and method order as in the §4.1 spike) |
| `Router(audio, journal, on_update, on_error, poll_s=1.0)` | The `ear-channels` thread (§5.2). `start()`, `choose(side, selection)`, `volume(side, v)`, `reset()`, `close()` are called from the UI thread and only put commands on its queue |

### 5.2 Threads

- **Only the `ear-channels` thread touches COM audio objects** (`CoInitializeEx`
  multi-threaded at its start, `CoUninitialize` at its end). COM objects are bound to
  the thread that made them; the same rule as the Whisper model (CLAUDE.md).
- Loop: every `poll_s` (1 s) or when a command arrives:
  1. read the default output; if it changed, restore the old device's sessions (§5.4)
     and start over on the new one;
  2. list sessions; for each one Wisper hasn't seen, **first** journal its current
     volumes, then apply `gains`; for every known session whose gains changed (a
     command), apply them;
  3. if the app list or device changed, call `on_update(device_name, apps, warnings)`.
- Polling instead of `RegisterSessionNotification`: no COM callback object to implement
  and keep alive, and a 1 s delay is fine for "a new app shows up". C3 measures the
  poll's CPU cost (target < 0.5 % of one core).
- `on_update` / `on_error` only put `("ear_update", …)` / `("ear_error", msg)` on a new
  `ear_results` queue; `App._poll` (already every 100 ms) drains it and rebuilds the two
  menus. No Tk call on the router thread.

### 5.3 Device

The strip works on the **Windows default output** (`eRender`, `eMultimedia`), checked on
every poll. Plugging in wired earphones on most PCs keeps the same endpoint (jack
detection); on PCs where "Headphones" is a separate endpoint and becomes the default,
the strip moves to it. A device with ≠ 2 channels → strip disabled with the status line
message, nothing changed.

### 5.4 Restoring

| When | What |
|---|---|
| Rule 3.2.1 holds again (both All apps, 100 %) | Each touched session gets its journaled volumes back; the journal is emptied |
| Reset | The same, and the UI goes back to the start-up state |
| `App.on_close` | `router.close()`: restore, empty the journal, end the thread (joined, 2 s cap), before `pa.terminate()` |
| Wisper starts and the journal isn't empty (crash, kill) | The router restores each listed session **when it next appears** on any poll (the app may not be running yet), then forgets it. The journal file stays until it is empty |
| Default device changes | The old device's sessions are restored first |

Journal path: `%LOCALAPPDATA%\Wisper\ear-channels-restore.json` (outside the repo,
survives a crash; ASSUMED the folder can be created there, C1 tests with a temp path).

### 5.5 `app/app.py`

- `_build_ears(root)`, called **before** `_build_panes` and packed `side="bottom"`:
  the strip of §3.1. The window gets ~100 px taller (`geometry` 1440×780, `minsize`
  height 520; C4 checks it on the user's screen).
- Builds `channels.Router(channels.WasapiAudio(), channels.Journal(path), …)` and starts
  it; `on_close` closes it.
- Menu check items call `router.choose`, the scales call `router.volume`, Reset calls
  `router.reset`.
- `_poll` drains `ear_results`: rebuilds both menus from `menu_items`, updates the
  device label and the status line.

Imports: `app` → `channels`; `channels` is a leaf. `test_architecture.py` and
`architecture-overview.md` get the new module.

## 6. Decisions (proposed; the user confirms)

| # | Decision | Why |
|---|---|---|
| D1 | Per-app session channel volumes (`IChannelAudioVolume`), no audio through Wisper | §4.1: VERIFIED to work, zero delay |
| D2 | "All apps (default)" at start: Wisper changes nothing until the user chooses | The user's "at starting it will be set to default"; safe |
| D3 | New dependency **comtypes** (runtime, `app/requirements.txt`, `comtypes>=1.4.17,<1.5`). Exists and is maintained: 1.4.17 released 2026-09-21, Python ≥ 3.9, pure Python. Not `pycaw` (§4.3) | Calling COM vtables with raw ctypes is possible but error-prone; comtypes is the standard Python COM layer |
| D4 | An app checked in neither ear is **silent** (rule 3.2.2), named in the status line | "Full control": each ear plays exactly what is chosen. Alternative: unchosen apps stay in both ears (then Left = Discord would still have YouTube in the left ear) |
| D5 | One menu with check items per ear (several apps per ear) | The user's example puts "zoom/meet/youtube" in one ear |
| D6 | Restore journal in `%LOCALAPPDATA%\Wisper\` | §4.2: Windows remembers the volumes |
| D7 | Follow the Windows default output; no device picker | The earphones are the default output; a picker can come later |
| D8 | Poll every 1 s, no COM notifications | §5.2 |

## 7. Steps

Each step is one branch (`feature/ear-channels-cN`) or one commit on `feature/ear-channels`,
with `node tools/verify.mjs` green and the user's yes before the next.

| Step | What | Done when |
|---|---|---|
| **C0** Spike in Python | `tools/ear_spike.py`: the §4.1 checks with comtypes from the venv (list sessions with exe, name, identifier, channels, L/R; set and read back on a child process playing a quiet tone; loopback RMS per ear; restore). Also: open Discord, Zoom and Meet + YouTube in Chrome and record what sessions each makes (one or several? Chrome tabs one session? does the app reset its volumes when it reopens its stream, e.g. Discord joining a call?) | Table of results in this spec (§4.1, §4.4) and `performance.md` (time to set, poll cost); D1–D8 confirmed or changed by the user |
| **C1** Pure core | `channels.py`: `ALL`, `gains`, `Selection`, `menu_items`, `Journal` (temp-path tests: write, crash in the middle leaves the old file, read back). `comtypes` added to `requirements.txt` | `app/tests/test_channels.py` covers every rule of §3.2 and the journal; architecture test knows `channels` |
| **C2** COM layer | `WasapiAudio` (default output, sessions, get/set) | A `slow` test (`--full`) plays silence from a child process, sets (1, 0) on its session, reads (1, 0), restores (1, 1), and checks the child's next run starts at (1, 1); fast tests use a fake |
| **C3** Router thread | `Router` with a fake `audio` and a fake clock: new session → journal then gains; command → re-apply; app gone / back (rule 3.2.7); device change → restore old; `close()` restores and empties the journal; start with a leftover journal restores when the session appears; errors → `on_error` once, nothing escapes the thread | `test_channels.py` (router part); poll CPU measured with the real `WasapiAudio` (< 0.5 % of a core) |
| **C4** The strip | `_build_ears` at the bottom, menus, scales, Reset, status line, `ear_results` in `_poll`; window size | `test_ears_ui.py` with a fake router (invisible Tk window, like the other UI tests): start-up state, menus rebuilt on update with the selection kept, rule 3.2.5 in the menu, status messages; `test_window_layout.py`: the strip is visible at `minsize` and the panes keep their controls |
| **C5** Lifetime | `on_close` order (router before `pa.terminate()`), the start-up replay of a leftover journal, the device-not-stereo state | tests with fakes; manual: kill Wisper from Task Manager with Discord left-only, start it again → Discord is back in both ears once it plays |
| **C6** Test plan + docs | `_docs/test/ear-channels.md` (§8), `architecture-overview.md` (module, thread, flow), `current-state.md`, `_docs/README.md` | The user runs §8 with Discord + Zoom/Meet/YouTube on the wired earphones; results recorded |
| C7 (optional, later) | A small level meter next to each app in the menus (`IAudioMeterInformation`), so it's clear which app is which | the user asks for it after C6 |

## 8. Manual checks (the test plan in C6 starts from these)

| ID | Steps | Pass when |
|---|---|---|
| T-EAR-1 | Start Wisper, play YouTube | both dropdowns show "All apps (default)"; YouTube sounds as before, both ears |
| T-EAR-2 | Open Discord (voice channel or the mic test sound) while Wisper runs | "Discord" appears in both menus within ~2 s without touching anything |
| T-EAR-3 | Left = Discord, Right = Chrome (Meet or YouTube) | Discord only in the left earbud, Chrome only in the right, both at once, no delay or crackle |
| T-EAR-4 | Left volume to 30 % while T-EAR-3 plays | Discord gets quieter, Chrome doesn't change |
| T-EAR-5 | Right = Zoom Meetings + Edge (two checks) | both in the right ear; the status line names any app now in neither ear |
| T-EAR-6 | Close Discord, open it again | the menu shows "Discord (not running)" in between; when it plays again it's left-only again |
| T-EAR-7 | Reset, then close Wisper | after Reset all apps are in both ears; after closing too (check in Windows' Volume Mixer that nothing stays changed) |
| T-EAR-8 | Left = Discord, kill Wisper in Task Manager, open Discord: it's still left-only; start Wisper | Discord returns to both ears once Wisper is running |
| T-EAR-9 | Live captions on, an app in neither ear speaks | not captioned, as documented (§3.3); an app in either ear is captioned |

## 9. Acceptance criteria

| # | Criterion | How checked |
|---|---|---|
| A1 | Discord in the left ear and Zoom/Meet/YouTube in the right, at the same time, on the wired earphones | manual T-EAR-3 |
| A2 | At start nothing changes and both channels show All apps (default) | `test_ears_ui.py` + T-EAR-1 |
| A3 | A new app appears in both dropdowns by itself, the selection stays | `test_channels.py` (router) + `test_ears_ui.py` + T-EAR-2 |
| A4 | Every rule of §3.2 gives the right (l, r) | `test_channels.py` |
| A5 | Closing, Reset and a restart after a crash leave no app changed | `test_channels.py` (journal, router) + T-EAR-7, T-EAR-8 |
| A6 | No audio goes through Wisper; no extra delay | design (§4.1) + T-EAR-3 |
| A7 | `node tools/verify.mjs` passes at every step; `--full` passes after C2 | verify output |

## 10. Open questions for the user

1. **D4**: an app in neither ear is silent (proposed), or it keeps playing in both ears?
2. **D5**: several apps per ear (proposed), or exactly one app per dropdown?
3. Is a per-ear **volume** what "full control" means, or is more wanted (balance per app,
   mute per app, swap L/R button)?
