# CodeWhisper

Local speech-to-text for Windows. No API key, no cloud, no subscription — Whisper runs entirely on your machine.

Press **Ctrl+Space** to start recording. Press it again to stop. The transcription is pasted at your cursor and copied to your clipboard.

---

## Requirements

- Windows 10 or 11
- Internet access for first-time setup (downloads uv, Python, packages, and the Whisper model)

---

## Installation

1. Clone the project

2. Double-click `install.bat`

That's it. It will:
- Download `uv` (a fast Python package manager) if not already present
- Use `uv` to download Python 3.11 if not already present
- Create an isolated `.venv` virtual environment
- Install all Python packages
- Create a **CodeWhisper** shortcut on your Desktop

3. Launch via the Desktop shortcut or `run.bat`

> **First launch only:** The Whisper model downloads automatically and is cached permanently.
> `large-v3` = ~1.5 GB · `small.en` = ~500 MB · `base.en` = ~150 MB

---

## Usage

| Action | Result |
|--------|--------|
| Press `Ctrl+Space` | Starts recording — overlay appears bottom-right |
| Press `Ctrl+Space` again | Stops recording, transcribes, pastes at cursor |
| Right-click tray icon | Menu with Quit option |

The transcribed text is:
- **Pasted at your cursor** (works in any app — browser, Word, VS Code, etc.)
- **Copied to clipboard** so you can paste it again anywhere

---

## Configuration

Edit the top of `app.py` to change behaviour:

```python
HOTKEY      = "ctrl+space"   # global shortcut to start/stop recording
MODEL_SIZE  = "large-v3"     # Whisper model (see table below)
AUTO_PASTE  = True           # set to False to only copy, not paste
MAX_RECORD  = 120            # max recording length in seconds
```

### Model size guide

| Model | Size | Speed | Quality | Best for |
|-------|------|-------|---------|----------|
| `tiny.en` | ~75 MB | Very fast | Basic | Very slow CPUs |
| `base.en` | ~150 MB | Fast | Good | Intel N150, old laptops |
| `small.en` | ~500 MB | Moderate | Better | ThinkPad T14, mid-range |
| `distil-large-v3` | ~800 MB | Fast | Near-large | Best balance |
| `medium` | ~1.5 GB | Slow | Very good | Modern laptops |
| `large-v3` | ~3 GB | Slowest | Best | Fast CPUs (default) |

The `.en` suffix = English-only model, smaller and faster. Use it if you only dictate in English.

Change the model **before first launch** to avoid downloading the wrong one.

---

## Tech stack

| Component | Library / API | Role |
|-----------|--------------|------|
| Speech recognition | `faster-whisper` | Runs OpenAI Whisper locally, int8-quantized for CPU speed |
| Audio capture | `sounddevice` | Streams mic input via PortAudio callbacks into numpy chunks |
| Global hotkey | `keyboard` | Win32 low-level keyboard hook; `suppress=True` consumes Ctrl+Space system-wide |
| Clipboard | `pyperclip` | Writes transcription to the OS clipboard after every session |
| Paste simulation | `ctypes` + Win32 `SendInput` | Fires a hardware-level Ctrl+V — reliable in all apps including browsers and Office |
| Status overlay | `tkinter` | Borderless always-on-top window; background threads post to a `queue.SimpleQueue`, tkinter polls it every 50 ms via `.after()` |
| Pulsing dot | `tkinter .after()` | Toggles dot colour on a 450 ms timer while recording is active |
| System tray | `pystray` + `Pillow` | Green circle icon drawn with PIL; right-click menu with Quit |
| Python environment | `uv` | Creates isolated `.venv`, downloads Python if needed, installs packages |
| Desktop shortcut | `WScript.Shell` via PowerShell | `.lnk` file with `WindowStyle=7` so the terminal launches minimised |
