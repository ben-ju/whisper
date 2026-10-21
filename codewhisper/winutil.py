"""Windows-specific helpers: paste simulation, launch at login, dark title bar."""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from pathlib import Path

from .config import ROOT_DIR, APP_NAME

log = logging.getLogger(__name__)
IS_WIN = sys.platform == "win32"


def send_paste() -> None:
    """Simulate Ctrl+V via Win32 SendInput — reliable across all Windows apps."""
    if not IS_WIN:
        return
    VK_CONTROL, VK_SHIFT, VK_V = 0x11, 0x10, 0x56
    KEYEVENTF_KEYUP = 0x0002
    INPUT_KEYBOARD = 1

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("ki", KEYBDINPUT), ("padding", ctypes.c_ubyte * 8)]

    def _key(vk, flags=0):
        return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, dwFlags=flags))

    # Release Shift first in case it's still held from Ctrl+Shift+Space,
    # otherwise some apps receive Ctrl+Shift+V.
    seq = (INPUT * 5)(
        _key(VK_SHIFT, KEYEVENTF_KEYUP),
        _key(VK_CONTROL),
        _key(VK_V),
        _key(VK_V, KEYEVENTF_KEYUP),
        _key(VK_CONTROL, KEYEVENTF_KEYUP),
    )
    ctypes.windll.user32.SendInput(5, ctypes.byref(seq), ctypes.sizeof(INPUT))


def _startup_shortcut() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup" / f"{APP_NAME}.lnk"


def launch_at_login_enabled() -> bool:
    return IS_WIN and _startup_shortcut().exists()


def set_launch_at_login(enabled: bool) -> bool:
    if not IS_WIN:
        return False
    lnk = _startup_shortcut()
    if not enabled:
        try:
            lnk.unlink(missing_ok=True)
            return True
        except OSError:
            return False
    pyw = ROOT_DIR / ".venv" / "Scripts" / "pythonw.exe"
    script = (
        "$ws = New-Object -ComObject WScript.Shell;"
        f"$sc = $ws.CreateShortcut('{lnk}');"
        f"$sc.TargetPath = '{pyw}';"
        "$sc.Arguments = 'app.py';"
        f"$sc.IconLocation = '{ROOT_DIR / 'codewhisper' / 'assets' / 'codewhisper.ico'},0';"
        f"$sc.WorkingDirectory = '{ROOT_DIR}';"
        f"$sc.Description = '{APP_NAME}';"
        "$sc.Save()"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True,
                       creationflags=0x08000000, timeout=15)  # CREATE_NO_WINDOW
        return True
    except Exception as exc:
        log.warning("Startup shortcut failed: %s", exc)
        return False


def set_dark_title_bar(widget, dark: bool) -> None:
    if not IS_WIN:
        return
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), 4) == 0:
                break
    except Exception:
        pass


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if IS_WIN:
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", str(path)])
