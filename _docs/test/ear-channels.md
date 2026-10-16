# Test plan: Ear channels (hear each app in the left ear, the right ear or both)

Spec: [`_docs/specs/2026-10-15-ear-channels.md`](../specs/2026-10-15-ear-channels.md).
Baseline on `feature/ear-channels` after C5: **433 fast + 3 slow pytest pass** (`current-state.md`). Every change must
keep them passing **by name**, plus its own new tests.

Fast check after every step: `node tools/verify.mjs`. Single file:
`app\.venv\Scripts\python.exe -m pytest app/tests/test_channels.py -v`. The slow COM test (real speakers):
`node tools/verify.mjs --full`.

## 1. Automated tests (pytest, `app/tests/`)

Only one test touches real audio (the slow C2 test); the rest use `FakeAudio` (`test_channels.py`) or a fake router
(`test_ears_ui.py`). Window tests use the real Tk window, kept invisible.

| File | Step | Needs | Cases |
|---|---|---|---|
| `test_channels.py` (pure core) | C1 | no | §3.2 rules (see §1.1); volumes clamped to 0..1; `Selection` immutable; menu rows: All apps, separator, apps by name, checked ones marked; **journal**: empty without a file, write and read back, keeps the volumes from before the first change, forget (file removed when empty), a crash in the middle of a write leaves the old file, a damaged file is moved to `.bad` before writing, an unreadable one raises and is left alone, a failed remove of the last entry keeps it, bad entries dropped and clamped, path in `%LOCALAPPDATA%\Wisper\` |
| `test_channels.py` (COM layer) | C2 | no / **real speakers** (slow) | `FakeAudio` has the real `WasapiAudio` methods; apps named and grouped by exe (§4.4: FileDescription, exe name, System sounds, Wisper (narration)); `set` refuses a session that isn't stereo; **slow**: `test_wasapi_sets_reads_and_restores_a_childs_channel_volumes` (a child playing silence set to (1, 0), read back, restored, its next run starts at (1, 1); skipped without an audio output) |
| `test_channels.py` (router) | C3 | no (`FakeAudio`, fake clock) | start-up changes nothing; each session journaled before it changes; back to All apps restores and empties the journal; a command re-applies only what changed; drifted volumes (an app, the Volume Mixer) re-applied; app volume (D9); app gone and back (rules 3.2.6, 3.2.7); device change restores the old device first; a leftover journal restores each session when it appears, and keeps the original while changing; Reset restores everything; a device that isn't stereo changes nothing; an error is reported once, restores what it can, Reset retries; every process of one app restored; a mono stream doesn't switch the strip off; a bad command is reported, not fatal; the "plays in neither ear" message; the real thread applies commands and `close()` restores |
| `test_ears_ui.py` | C4, C5 | Tk window, fake router | start-up state (All apps, 100 %, router started; D2); an update fills the menus and the device label; choosing follows rule 3.2.5; an update keeps the choice and shows a closed app as "(not running)"; an error shows in the status line, no dialog; Reset puts the strip back and tells the router; ear volume sent throttled (~20/s); app volume (D9); a router that can't start leaves the strip off; not stereo disables menus and scales (Reset stays); `on_close` puts the apps back before `pa.terminate()`; a leftover journal is put back at start-up (real `Router`) |
| `test_window_layout.py` | C4 | Tk window | `test_ear_strip_below_both_panes_and_fully_visible` at the default and the minimum size |
| `test_architecture.py` | C1 | no | `channels` is a leaf; `app` may import it |

### 1.1 Rules (spec §3.2) → tests

| Rule | Test |
|---|---|
| 3.2.1 both All apps at 100 % changes nothing | `test_start_up_state_changes_nothing`, `test_router_start_up_changes_nothing` |
| 3.2.2 Discord left, Zoom right; an app in neither is silent | `test_users_example_discord_left_zoom_right`, `test_neither_message` |
| 3.2.3 one app left, All apps right | `test_one_app_left_all_apps_right` |
| 3.2.4 same app in both ears | `test_same_app_in_both_ears_at_each_ears_volume` |
| 3.2.5 All apps ⇄ apps in a menu | `test_checking_an_app_unchecks_all_apps`, `test_checking_all_apps_unchecks_the_apps`, `test_unchecking_the_last_app_checks_all_apps_again`, `test_choosing_apps_follows_rule_3_2_5` |
| 3.2.6 a new app is listed unchecked and gets its gains at once | `test_new_app_is_listed_unchecked_and_starts_silent`, `test_router_app_gone_and_back` |
| 3.2.7 a checked app that closed stays "(not running)" | `test_checked_app_that_closed_stays_as_not_running`, `test_unchecked_app_that_closed_is_removed` |
| 3.2.8 Wisper (narration) follows the rules | `test_wisper_follows_the_same_rules` |
| 3.2.9 errors in the status line, no dialog | `test_router_error_reported_once_restores_and_reset_retries`, `test_error_shows_in_the_status_line_without_a_dialog` |
| D5 several apps per ear | `test_several_apps_per_ear` |
| D9 app volume × ear volume | `test_app_volume_multiplies_the_ear_volume`, `test_router_app_volume`, `test_app_volume` |

## 2. Performance checks (recorded in the spec §4.1 and `performance.md`)

| Check | Target | Result |
|---|---|---|
| `SetChannelVolume`, 2 channels | — | 0.3 ms (C0) |
| One session listing on the real device | — | 4.3 ms (C2) |
| Router poll CPU at 1 s | < 0.5 % of a core | 0.03–0.08 % (C3) |
| Change → heard | within one 100 ms loopback block | VERIFIED by loopback RMS (C0) |

## 3. Manual checks (Tkinter UI: the user runs these)

Run the app with `cd app` + `.venv\Scripts\python.exe app.py`. Use the **wired earphones as the Windows default
output**. Apps: Discord, Zoom (or Meet in Chrome), YouTube in Chrome, and a second browser (Edge or Brave) for
T-EAR-5. Two tabs of the **same** browser can't be split (spec §2, non-goal).

To see what Wisper changed outside the app: Windows Settings → System → Sound → Volume mixer (each app's slider), or
`app\.venv\Scripts\python.exe tools\ear_spike.py list` (each session's L/R).

| ID | Steps | Expected |
|---|---|---|
| T-EAR-1 | Start Wisper, play YouTube | Both ear menus show "All apps (default)", volumes 100 %; YouTube sounds as before, both ears; the Earphones label names the default output |
| T-EAR-2 | Open Discord (voice channel or the mic test sound) while Wisper runs | "Discord" appears in both menus within ~2 s without touching anything; nothing chosen changes |
| T-EAR-3 | Left ear = Discord, Right ear = Google Chrome (Meet or YouTube) | Discord only in the left earbud, Chrome only in the right, both at once, no delay or crackle (A1, A6) |
| T-EAR-4 | While T-EAR-3 plays, Left volume to 30 % | Discord gets quieter, Chrome doesn't change |
| T-EAR-10 | While T-EAR-3 plays, App = Discord, its volume to 30 % | Discord gets quieter in the left ear; Chrome doesn't change; the Volume Mixer's Discord slider doesn't move (D9) |
| T-EAR-5 | Right ear = Zoom Meetings + Edge (two checks); leave Chrome unchecked | Both in the right ear; the status line says "Google Chrome plays in neither ear." and Chrome is silent (D4) |
| T-EAR-6 | Close Discord, open it again and join a call | In between the Left menu shows "Discord (not running)" (checked); when it plays again it's left-only again, also after joining the call |
| T-EAR-7 | Reset; then choose Left = Discord again and close Wisper with ✕ | After Reset both menus are All apps at 100 % and every app is in both ears; after closing too: the Volume Mixer / `ear_spike.py list` shows every app back at L = R = 1 |
| T-EAR-8 | Left = Discord, kill Wisper in Task Manager; Discord is still left-only; start Wisper | Discord returns to both ears once Wisper runs and Discord plays (A5). (Passed with YouTube in C5, user 2026-10-16; check Discord here) |
| T-EAR-9 | Live captions on; an app in neither ear speaks, then one in an ear | The first isn't captioned (spec §3.3, documented); the second is |
| T-EAR-11 | While Discord is left-only, switch the Windows default output to another device (or unplug if the earphones are their own endpoint), then back | The Earphones label follows the default; the old device's apps are put back (both ears) when it stops being the default; on the earphones again the choice applies again |
| T-EAR-12 | Speak a text in the TTS pane while Left = Discord, Right = Google Chrome | "Wisper (narration)" is in the menus and, unchecked, plays in neither ear (status line names it); checked in an ear, it plays there. The call (Others / VB-Cable) still hears it: the strip only touches the default output (§3.3) |

Record each result here (passed / failed + what was heard, with the date) and in `current-state.md`.

### 3.1 Results

| Date | Rows | Result |
|---|---|---|
| 2026-10-16 (user, C4/C5) | strip layout; moving apps between the left and right ear (without Discord); T-EAR-8 with YouTube instead of Discord | passed |
| 2026-10-16 | T-EAR-1…12 with Discord + Zoom/Meet/YouTube | **not run yet** (the user hasn't tested with Discord; the PR was opened without it) |
