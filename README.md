# Wisper: local speech-to-text for the AMD RX 580

Fast, fully offline speech-to-text on an **AMD Radeon RX 580**, running
**whisper.cpp with the Vulkan backend** on Windows. There are three modes:

- **Dictation**: transcribes your microphone as you speak.
- **Live captions**: transcribes desktop or meeting audio (WASAPI loopback).
- **File**: transcribes an audio file, and the text appears as it goes.

It also speaks: the right-hand pane reads typed or pasted text aloud with **Kokoro-82M**
(offline, on the CPU), to yourself, into a call (Meet, Zoom, Discord) through a virtual
cable, or both. With "Send my mic to the call", the call hears your voice and the
narration together. Speak, Pause and Resume share one button (Ctrl+Enter), and Stop ends the narration.

**DeepSeek terminal**: the left pane runs
the `deepseek` command line (Claude Code talking to DeepSeek's API). What you say is typed into
its prompt (never sent: you press Enter), and each answer it finishes is read aloud.

## Why we made it

- **Talk to the AI instead of typing.** Explaining a feature out loud, in your own words, is
  faster and closer to what you mean than writing a careful prompt. Wisper turns speech into
  the prompt and reads the answer back, so a conversation with the AI feels like talking to a
  teammate.
- **The whole team can take part.** In a call, everyone's voice can reach the AI and everyone
  hears its answers. People who don't use the AI tools themselves can still explain an idea,
  suggest a change, or hear where the work stands.
- **Local and private.** Speech to text (whisper.cpp) and the voice (Kokoro) run on your own
  PC with no cloud service. Only the text you choose to send goes to the AI.
- **Fast on ordinary hardware.** It's tuned for an older AMD card (RX 580) through Vulkan, so
  you don't need a recent NVIDIA GPU to get real-time transcription.

## System requirements

| What | Needed | Notes |
|---|---|---|
| OS | **Windows 10 or 11, 64-bit** | Windows only (WASAPI, ConPTY, Job Objects) |
| GPU | A **Vulkan** GPU with a current driver | Built and measured on an AMD RX 580 8 GB; turbo runs ~4.6× real time there |
| CPU / RAM | 4+ cores, 8 GB RAM | Narration (Kokoro) runs on the CPU |
| Disk | ~2.5 GB | whisper.cpp clone + build + Whisper models ~1.3 GB, Kokoro ~0.35 GB, Python venv ~0.4 GB |
| Python | **3.12** (64-bit) | The venv is built with `py -3.12` |
| Git | Git for Windows | Includes Git Bash, which Claude Code needs for its hooks |
| Build tools | **Visual Studio 2022+ Build Tools** ("Desktop development with C++"), **CMake** 3.21+, **Vulkan SDK** | Only to build whisper.cpp |
| Node.js | 18+ | Only for the dev checks (`tools/verify.mjs`) |
| Optional | [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) | To send the narration into a call |
| Optional | Claude Code + a DeepSeek API key | For the DeepSeek terminal |

Install the tools with winget (then open a **new** terminal so `PATH` updates):

```bat
winget install Git.Git Python.Python.3.12 Kitware.CMake KhronosGroup.VulkanSDK OpenJS.NodeJS.LTS
winget install Microsoft.VisualStudio.2022.BuildTools --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

## Setup from scratch

All commands run from a normal Command Prompt (`cmd`) unless marked PowerShell.

### 1. Clone

```bat
git clone https://github.com/shoonya0/wisper.git
cd wisper
```

### 2. Python environment

```bat
py -3.12 -m venv app\.venv
app\.venv\Scripts\python.exe -m pip install -r app\requirements-dev.txt
```

`requirements.txt` holds what the app needs; `requirements-dev.txt` adds ruff, pytest and pyright.

### 3. Build whisper.cpp with Vulkan

whisper.cpp isn't in this repo (it's gitignored). Clone it **into the repo root** and build the
pinned commit. `app/whisper_native.py` mirrors its C structs at `6e4ab85`, so don't build
another commit without diffing `whisper.cpp/include/whisper.h` first.

```bat
git clone https://github.com/ggml-org/whisper.cpp
cd whisper.cpp
git checkout 6e4ab85
cmake -B build -DGGML_VULKAN=1
cmake --build build --config Release -j
cd ..
```

Check: `whisper.cpp\build\bin\Release\` contains `whisper.dll` and `ggml-vulkan.dll`.
If CMake can't find Vulkan, check that `VULKAN_SDK` is set (open a new terminal after
installing the SDK).

### 4. Whisper models

```bat
whisper.cpp\models\download-ggml-model.cmd base.en-q5_1
whisper.cpp\models\download-ggml-model.cmd small.en-q5_1
whisper.cpp\models\download-ggml-model.cmd large-v3-turbo-q5_0
```

They land in `whisper.cpp\models\` as `ggml-base.en-q5_1.bin` (fastest, 57 MB),
`ggml-small.en-q5_1.bin` (balanced, 181 MB) and `ggml-large-v3-turbo-q5_0.bin` (most
accurate, 547 MB).

### 5. Kokoro narration model

From Git Bash, in the repo root:

```bash
mkdir -p models/kokoro && cd models/kokoro
B=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1
curl -LO $B/kokoro-v1.0.onnx && curl -LO $B/voices-v1.0.bin
sha256sum kokoro-v1.0.onnx voices-v1.0.bin
# kokoro-v1.0.onnx  beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a
# voices-v1.0.bin   bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d
cd ../..
```

Use the fp32 `kokoro-v1.0.onnx`, not the int8 one (~10× slower on the CPU). Without these
files, speech to text still works and the narration pane says the model is missing.

### 6. (Optional) Narration into calls

Install [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) and restart. Wisper finds
`CABLE Input` by itself; in Meet/Zoom/Discord pick **CABLE Output** as the microphone. Use
headphones, or your mic picks up the narration and the call hears it twice.

### 7. (Optional) DeepSeek terminal

Wisper starts `deepseek` from **Windows PowerShell 5.1** (`powershell.exe`, not `pwsh`), so
`deepseek` must be a function in that profile.

1. **Install Claude Code** (PowerShell):
   ```powershell
   irm https://claude.ai/install.ps1 | iex
   ```
   Check with `claude --version` in a new terminal.
2. **Get a DeepSeek API key** at <https://platform.deepseek.com/api_keys> and store it for your
   user (then open a new terminal):
   ```powershell
   setx DEEPSEEK_API_KEY "sk-..."
   ```
3. **Allow your profile to run** (once):
   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```
4. **Add the `deepseek` function** to your profile. Open it with `notepad $PROFILE` (create the
   file if asked; it's `Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1`) and paste:
   ```powershell
   # DeepSeek-backed Claude Code. Usage: deepseek [any claude CLI args]
   function deepseek {
       $deepseekKey = $env:DEEPSEEK_API_KEY
       if (-not $deepseekKey) { $deepseekKey = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User') }
       if (-not $deepseekKey) {
           Write-Error 'DEEPSEEK_API_KEY is not set. Run: setx DEEPSEEK_API_KEY "sk-..." and open a new terminal.'
           return
       }
       $prevConfigDir = $env:CLAUDE_CONFIG_DIR
       $prevBaseUrl   = $env:ANTHROPIC_BASE_URL
       $prevAuthToken = $env:ANTHROPIC_AUTH_TOKEN
       $prevApiKey    = $env:ANTHROPIC_API_KEY
       try {
           $env:CLAUDE_CONFIG_DIR    = "$env:USERPROFILE\.claude-deepseek"   # kept apart from your normal Claude Code
           $env:ANTHROPIC_BASE_URL   = "https://api.deepseek.com/anthropic"
           $env:ANTHROPIC_AUTH_TOKEN = $deepseekKey
           Remove-Item Env:\ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
           claude @args
       }
       finally {
           if ($null -eq $prevConfigDir) { Remove-Item Env:\CLAUDE_CONFIG_DIR -ErrorAction SilentlyContinue }
           else { $env:CLAUDE_CONFIG_DIR = $prevConfigDir }
           $env:ANTHROPIC_BASE_URL   = $prevBaseUrl
           $env:ANTHROPIC_AUTH_TOKEN = $prevAuthToken
           $env:ANTHROPIC_API_KEY    = $prevApiKey
       }
   }
   ```
5. **Pick the model** (optional): create `%USERPROFILE%\.claude-deepseek\settings.json` with
   ```json
   { "model": "deepseek-flash" }
   ```
   or `deepseek-v4-pro` for stronger reasoning. Switch later with `/model` inside `deepseek`.
6. **Run it once by hand** in a new PowerShell window: `deepseek`. Finish the first-run
   questions (theme etc.), check that a question gets an answer, then `/exit`.

### Where DeepSeek works: `AI_workspace\`

Wisper always starts `deepseek` in **`AI_workspace\`** at the repo root. That folder is its
project: its file tools, its git and its instructions all start there.

```
wisper\
├── app\, _docs\, whisper.cpp\ …   Wisper itself: deepseek doesn't load these
└── AI_workspace\                   deepseek's project (created on first start)
    ├── .git\                       its own git repo, made by Wisper
    ├── CLAUDE.md                   your instructions for deepseek (optional)
    ├── .claude\settings.json       its permissions, e.g. deny Write/Edit (optional)
    ├── .claude\skills\             its skills (optional)
    └── <your project>\             code you want it to work on (optional)
```

- **Walled off from Wisper.** `AI_workspace` is its own git repo, and Wisper tells `deepseek`
  to skip the `CLAUDE.md` files above it. So Wisper's instructions, skills, agents, docs and git
  status never reach `deepseek`, and its answers aren't steered by them. It can still open a
  Wisper file if you ask it to by path: this is a separate project, not a sandbox.
- **Starts empty.** The folder is gitignored by Wisper, so a fresh clone has no `CLAUDE.md`,
  settings or skills there. Everything in it is yours: add what you want `deepseek` to follow.
- **To work on code**, put the project inside it, for example
  `git clone <your-repo> AI_workspace\myproject`, and ask `deepseek` to work in `myproject\`.
  Keep it a git repo of its own: Wisper ignores everything under `AI_workspace`, so nothing
  there is saved in Wisper's history. If `AI_workspace\.claude\settings.json` or `CLAUDE.md`
  forbids file reads or edits, `deepseek` will refuse to change code until you allow it.
- **First start:** `deepseek` asks whether to trust the folder. Answer in the Wisper terminal
  with the keyboard; it's asked only once.

## Run

```bat
cd app
.venv\Scripts\pythonw.exe app.py
```

To see error messages (tracebacks), run `.venv\Scripts\python.exe app.py` instead.

Pick a **Mode** and a **Model** (fastest ↔ most accurate), select a device or file, and
press **Start**. On first start the model loads onto the GPU (a few seconds).

## Working on a feature with the AI

Setup: steps 1–7, with the project you're working on cloned into `AI_workspace\` (see
[Where DeepSeek works](#where-deepseek-works-ai_workspace)).

### On your own

1. Start Wisper, choose **Dictation (microphone)**, and press **▶ Start**.
2. Explain the feature in your own words: what it should do, why, what to keep in mind.
   The text appears in the `deepseek` prompt as you speak. Nothing is sent yet.
3. Read the prompt and fix any misheard words with the keyboard (click to move the cursor,
   select and type over, Ctrl+A selects the whole prompt). Then press **Enter**.
4. The answer appears in the terminal and is read aloud. While it's speaking, Wisper stops
   listening, so it doesn't type the answer back in. Press **▶ Start** to talk again, which also
   pauses the narration.
5. Go round: ask for a plan, react to it out loud ("no, keep the old file format"), let it
   make the change, ask it to explain what it did.

Useful things to say: "Before writing code, tell me your plan in a few sentences.", "Explain
what you changed and how to test it.", "What's left to do on this feature?"

### As a team, in a call

Teammates explain the feature and make suggestions in their own words, the AI hears them, and
everyone hears its answers. One person (the host) runs Wisper and shares the call.

1. **Host setup:** install VB-Cable (step 6), use headphones, and in the call app set the
   microphone to **CABLE Output**. In Wisper set **Output** to **Both** (you and the call hear
   the answers), check that **Others** is `CABLE Input` (picked by itself; **How to set up…**
   explains the cable), and tick **Send my mic to the call** so the call still hears you.
2. **Hear teammates:** choose **Live captions (desktop audio)** with your speakers or
   headphones as the source, and press **▶ Start**. What teammates say in the call is typed
   into the prompt. To speak yourself, switch to **Dictation (microphone)**: one mode at a
   time.
3. **Review, then send.** Wisper never presses Enter. The host reads the prompt out or shares
   the screen, the team agrees it says what they mean, fixes it if needed, and the host presses
   **Enter**.
4. **Everyone hears the answer.** It's read aloud into the call. Teammates react, add
   suggestions, or ask "what does it look like now?", and the host presses **▶ Start** to
   capture the next round.
5. **Status check-ins:** ask "Summarise where this feature stands and what's next." The team
   hears the current state of the work without anyone opening the code.

Tips: one speaker at a time keeps the transcript clean. Short turns work better than long
monologues. Because the prompt is editable before it's sent, nobody needs to phrase things
perfectly.

## Check the setup

```bat
node tools/verify.mjs          & rem ruff + pyright + pytest, about a minute
node tools/verify.mjs --full   & rem adds the slow tests (real Kokoro model), what CI runs
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Status says "Could not load model: …" | `whisper.dll` missing: step 3 (the build must be in `whisper.cpp\build\bin\Release\`); or the model file is missing: step 4 (file names must match exactly) |
| "Kokoro model not found" in the narration pane | Step 5 |
| Terminal says "`deepseek` wasn't found" | Step 7.4: the function must be in the **Windows PowerShell** profile, and the execution policy must allow it (7.3) |
| `deepseek` starts but answers fail | `DEEPSEEK_API_KEY` not set in a new terminal, or no credit on the DeepSeek account |
| Slow transcription | Check the GPU driver supports Vulkan (`vulkaninfo --summary` from the Vulkan SDK) |

## Docs

Everything else is in **[`_docs/`](./_docs/README.md)**: architecture, current state and
known issues, and benchmarks with the reasons for this stack.
