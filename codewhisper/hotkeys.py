"""Global hotkeys via the `keyboard` library (Win32 low-level hook)."""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

try:
    import keyboard
except Exception as exc:  # needs root on Linux; always fine on Windows
    keyboard = None
    log.warning("keyboard unavailable: %s", exc)

KEY_NAMES = {
    "ctrl": "Ctrl", "shift": "Maj", "alt": "Alt", "windows": "Win", "left windows": "Win",
    "space": "Espace", "escape": "Échap", "esc": "Échap", "enter": "Entrée",
    "right ctrl": "Ctrl droit", "right alt": "Alt Gr", "alt gr": "Alt Gr",
    "right shift": "Maj droite", "caps lock": "Verr. Maj", "tab": "Tab",
}


def pretty(hotkey: str) -> str:
    if not hotkey:
        return "—"
    parts = [p.strip() for p in hotkey.split("+")]
    return " + ".join(KEY_NAMES.get(p, p.upper() if len(p) == 1 else p.capitalize()) for p in parts)


def available() -> bool:
    return keyboard is not None


class HotkeyManager:
    def __init__(self):
        self._paused = False

    def register(self, shortcuts: list[dict], cancel_key: str, on_trigger, on_cancel) -> list[str]:
        """(Re)register every hotkey. Returns the list of hotkeys that failed."""
        if keyboard is None:
            return []
        failed = []
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        last = {"t": 0.0}

        def make_cb(sc):
            def cb():
                if self._paused:
                    return
                now = time.monotonic()
                if now - last["t"] < 0.35:   # ignore key auto-repeat
                    return
                last["t"] = now
                on_trigger(sc)
            return cb

        for sc in shortcuts:
            hk = sc.get("hotkey", "").strip()
            if not hk:
                continue
            try:
                keyboard.add_hotkey(hk, make_cb(sc), suppress=True)
            except Exception as exc:
                log.warning("Hotkey %s failed: %s", hk, exc)
                failed.append(hk)
        if cancel_key:
            try:
                keyboard.add_hotkey(cancel_key, lambda: (not self._paused) and on_cancel(), suppress=False)
            except Exception as exc:
                log.warning("Cancel hotkey %s failed: %s", cancel_key, exc)
                failed.append(cancel_key)
        return failed

    @staticmethod
    def is_held(hotkey: str) -> bool:
        if keyboard is None:
            return False
        try:
            return keyboard.is_pressed(hotkey)
        except Exception:
            return False

    def capture(self, callback) -> None:
        """Wait (in a thread) for the user to press a combination, then callback(str|None)."""
        if keyboard is None:
            callback(None)
            return
        self._paused = True

        def _go():
            try:
                combo = keyboard.read_hotkey(suppress=False)
            except Exception:
                combo = None
            finally:
                time.sleep(0.2)
                self._paused = False
            if combo in ("esc", "escape"):
                combo = None
            callback(combo)

        threading.Thread(target=_go, daemon=True, name="hotkey-capture").start()
