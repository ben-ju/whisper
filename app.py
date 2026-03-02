#!/usr/bin/env python3
"""
CodeWhisper — Local speech-to-text (Whisper, no API key)
Press Ctrl+Space to start recording, press again to stop and paste.
"""

import time
import threading
import queue
import ctypes
import ctypes.wintypes
import numpy as np
import sounddevice as sd
import keyboard
import pyperclip
import tkinter as tk
from PIL import Image, ImageDraw
import pystray
from faster_whisper import WhisperModel


def _send_paste():
    """Simulate Ctrl+V via Win32 SendInput — reliable across all Windows apps."""
    VK_CONTROL      = 0x11
    VK_V            = 0x56
    KEYEVENTF_KEYUP = 0x0002
    INPUT_KEYBOARD  = 1

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         ctypes.c_ushort),
            ("wScan",       ctypes.c_ushort),
            ("dwFlags",     ctypes.c_ulong),
            ("time",        ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type",    ctypes.c_ulong),
            ("ki",      KEYBDINPUT),
            ("padding", ctypes.c_ubyte * 8),
        ]

    def _key(vk, flags=0):
        return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, dwFlags=flags))

    seq = (INPUT * 4)(
        _key(VK_CONTROL),
        _key(VK_V),
        _key(VK_V,       KEYEVENTF_KEYUP),
        _key(VK_CONTROL, KEYEVENTF_KEYUP),
    )
    ctypes.windll.user32.SendInput(4, ctypes.byref(seq), ctypes.sizeof(INPUT))

# ─── Config (edit these to customise) ────────────────────────────────────────
HOTKEY      = "ctrl+space"        # English transcription
HOTKEY_FR   = "ctrl+shift+space"  # French transcription
HOTKEY_ESC  = "escape"            # cancel recording / transcription
MODEL_SIZE  = "medium"     # tiny · base · small · medium · large-v3
#                        tiny=fastest/least accurate, large-v3=slowest/best
SAMPLE_RATE = 16000
AUTO_PASTE  = True     # paste transcription automatically with Ctrl+V
PASTE_DELAY = 0.05     # seconds to wait before sending Ctrl+V
MAX_RECORD  = 120      # safety cap: auto-stop after this many seconds


# ─── Overlay window ───────────────────────────────────────────────────────────
class Overlay:
    """
    Small always-on-top status window in the bottom-right corner.
    Thread-safe: call signal_*() from any thread.
    The tkinter loop runs in its own daemon thread.
    """

    _BG   = "#16213E"
    _TEXT = "#FFFFFF"
    _HINT = "#8892B0"
    _COLORS = {"idle": "#4CAF50", "recording": "#F44336", "processing": "#FF9800"}

    def __init__(self):
        self._q      = queue.SimpleQueue()
        self._pulse  = False
        self._root   = None

        t = threading.Thread(target=self._loop, daemon=True, name="overlay")
        t.start()

        # wait for the tkinter root to exist before returning
        while self._root is None:
            time.sleep(0.02)

    # ── internal (runs on overlay thread) ─────────────────────────────────────

    def _loop(self):
        r = tk.Tk()
        self._root = r

        r.title("CodeWhisper")
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.attributes("-alpha", 0.93)
        r.configure(bg=self._BG)
        r.withdraw()

        W, H = 248, 72
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        r.geometry(f"{W}x{H}+{sw - W - 20}+{sh - H - 60}")

        outer = tk.Frame(r, bg=self._BG, padx=14, pady=12)
        outer.pack(fill="both", expand=True)

        self._dot = tk.Label(outer, text="●", bg=self._BG,
                             fg=self._COLORS["idle"], font=("Segoe UI", 18))
        self._dot.pack(side="left", padx=(0, 10))

        col = tk.Frame(outer, bg=self._BG)
        col.pack(side="left", fill="both", expand=True)

        tk.Label(col, text="CodeWhisper", bg=self._BG, fg=self._HINT,
                 font=("Segoe UI", 7)).pack(anchor="w")

        self._status = tk.StringVar(value="")
        tk.Label(col, textvariable=self._status, bg=self._BG, fg=self._TEXT,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")

        r.after(50, self._poll)
        r.mainloop()

    def _poll(self):
        try:
            while True:
                self._handle(self._q.get_nowait())
        except queue.Empty:
            pass
        if self._root:
            self._root.after(50, self._poll)

    def _handle(self, msg):
        cmd = msg[0]
        r   = self._root

        if cmd == "loading":
            r.deiconify()
            self._status.set("Loading model…")
            self._dot.configure(fg=self._COLORS["processing"])

        elif cmd == "recording":
            lang_label = msg[1] if len(msg) > 1 else "EN"
            r.deiconify()
            self._status.set(f"Recording… [{lang_label}]")
            self._dot.configure(fg=self._COLORS["recording"])
            self._pulse = True
            self._do_pulse()

        elif cmd == "processing":
            self._pulse = False
            self._status.set("Transcribing…")
            self._dot.configure(fg=self._COLORS["processing"])

        elif cmd == "done":
            self._pulse = False
            text    = msg[1]
            preview = (text[:38] + "…") if len(text) > 38 else text
            self._status.set(preview or "(nothing heard)")
            self._dot.configure(fg=self._COLORS["idle"])
            r.after(2500, r.withdraw)

        elif cmd == "cancelled":
            self._pulse = False
            self._status.set("Annulé")
            self._dot.configure(fg=self._COLORS["idle"])
            r.after(1200, r.withdraw)

        elif cmd == "hide":
            self._pulse = False
            r.withdraw()

    def _do_pulse(self):
        if not self._pulse:
            self._dot.configure(fg=self._COLORS["recording"])
            return
        # toggle between recording-red and background to create blink effect
        current = self._dot.cget("fg")
        next_c  = self._BG if current == self._COLORS["recording"] else self._COLORS["recording"]
        self._dot.configure(fg=next_c)
        self._root.after(450, self._do_pulse)

    # ── public thread-safe signals ─────────────────────────────────────────────

    def signal_loading(self):                        self._q.put(("loading",))
    def signal_recording(self, lang: str = "EN"):   self._q.put(("recording", lang))
    def signal_processing(self):                    self._q.put(("processing",))
    def signal_done(self, text: str):               self._q.put(("done", text))
    def signal_cancelled(self):                     self._q.put(("cancelled",))
    def signal_hide(self):                          self._q.put(("hide",))


# ─── Audio recorder ───────────────────────────────────────────────────────────
class Recorder:
    def __init__(self):
        self._chunks = []
        self._lock   = threading.Lock()
        self._stream = None
        self.active  = False

    def start(self):
        self._chunks = []
        self.active  = True
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            callback=self._cb,
        )
        self._stream.start()

    def _cb(self, indata, frames, t, status):
        if self.active:
            with self._lock:
                self._chunks.append(indata.copy())

    def stop(self) -> "np.ndarray | None":
        self.active = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            return np.concatenate(self._chunks).flatten() if self._chunks else None


# ─── Whisper transcriber ──────────────────────────────────────────────────────
class Transcriber:
    def __init__(self):
        self.model  = None
        self._ready = threading.Event()

    def load_async(self, on_ready=None):
        def _go():
            print(f"[CodeWhisper] Loading Whisper '{MODEL_SIZE}' model…")
            print("  (First run: downloads ~150 MB — subsequent starts are instant)")
            self.model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
            self._ready.set()
            print(f"[CodeWhisper] Ready — press {HOTKEY} to dictate.")
            if on_ready:
                on_ready()
        threading.Thread(target=_go, daemon=True, name="model-loader").start()

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    def transcribe(self, audio: np.ndarray, language: str = "en") -> str:
        self._ready.wait()
        segs, _ = self.model.transcribe(audio, beam_size=5, language=language)
        return " ".join(s.text for s in segs).strip()


# ─── Main application ─────────────────────────────────────────────────────────
class App:
    def __init__(self):
        self.overlay     = Overlay()
        self.recorder    = Recorder()
        self.transcriber = Transcriber()
        self._recording  = False
        self._cancelled  = False
        self._lock       = threading.Lock()

    # called from keyboard hook thread
    def _on_escape(self):
        with self._lock:
            if not self._recording:
                return  # nothing active — let Escape pass through normally
            self._cancelled = True
            self.recorder.active = False   # stop audio capture immediately

    def _on_hotkey(self, language: str = "en"):
        with self._lock:
            if not self.transcriber.ready:
                return  # model still loading — ignore
            if self._recording:
                self.recorder.active = False   # signal the session thread to stop
                return
            self._recording  = True
            self._cancelled  = False

        threading.Thread(target=self._session, args=(language,),
                         daemon=True, name="session").start()

    def _session(self, language: str = "en"):
        lang_label = "FR" if language == "fr" else "EN"
        try:
            self.recorder.start()
            self.overlay.signal_recording(lang_label)

            deadline = time.time() + MAX_RECORD
            while self.recorder.active and time.time() < deadline:
                time.sleep(0.05)

            audio = self.recorder.stop()

            # Escape was pressed — discard everything
            if self._cancelled:
                self.overlay.signal_cancelled()
                return

            if audio is None or len(audio) < SAMPLE_RATE * 0.2:   # < 0.2 s
                self.overlay.signal_done("")
                return

            self.overlay.signal_processing()
            text = self.transcriber.transcribe(audio, language=language)

            # Escape pressed while transcribing — discard result silently
            if self._cancelled:
                self.overlay.signal_cancelled()
                return

            print(f"[CodeWhisper/{lang_label}] {text!r}")

            if text:
                pyperclip.copy(text)
                if AUTO_PASTE:
                    time.sleep(PASTE_DELAY)   # let hotkey release + focus settle
                    _send_paste()

            self.overlay.signal_done(text)

        finally:
            with self._lock:
                self._recording = False

    def _make_tray_icon(self):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse([6, 6, 58, 58], fill="#4CAF50")
        return img

    def run(self):
        # Start model loading immediately; hide overlay once it's ready
        self.overlay.signal_loading()
        self.transcriber.load_async(on_ready=self.overlay.signal_hide)

        # Global hotkeys (suppress=True so they don't reach the active app)
        keyboard.add_hotkey(HOTKEY,    self._on_hotkey,                        suppress=True)
        keyboard.add_hotkey(HOTKEY_FR, lambda: self._on_hotkey(language="fr"), suppress=True)
        # Escape: suppress=False so it still works normally in other apps
        keyboard.add_hotkey(HOTKEY_ESC, self._on_escape, suppress=False)

        # System tray — run() blocks the main thread until "Quit" is clicked
        def _quit(icon, _):
            icon.stop()

        menu = pystray.Menu(
            pystray.MenuItem("CodeWhisper", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"English: {HOTKEY}",    None, enabled=False),
            pystray.MenuItem(f"French:  {HOTKEY_FR}", None, enabled=False),
            pystray.MenuItem(f"Cancel:  {HOTKEY_ESC}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", _quit),
        )
        tray = pystray.Icon("CodeWhisper", self._make_tray_icon(),
                            "CodeWhisper", menu)
        tray.run()


if __name__ == "__main__":
    App().run()
