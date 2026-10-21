"""Microphone capture with a live level meter, and short UI sounds."""

from __future__ import annotations

import logging
import threading

import numpy as np

from .config import SAMPLE_RATE

log = logging.getLogger(__name__)

try:
    import sounddevice as sd
except Exception as exc:  # PortAudio missing (only happens outside Windows)
    sd = None
    log.warning("sounddevice unavailable: %s", exc)


def list_microphones() -> list[str]:
    """Input device names for the default host API (avoids MME/WASAPI duplicates)."""
    if sd is None:
        return []
    try:
        default_api = sd.default.hostapi
        names = []
        for dev in sd.query_devices():
            if dev["max_input_channels"] > 0 and dev["hostapi"] == default_api:
                if dev["name"] not in names:
                    names.append(dev["name"])
        return names
    except Exception as exc:
        log.warning("Cannot list microphones: %s", exc)
        return []


def _find_device(name: str):
    if not name or sd is None:
        return None
    try:
        default_api = sd.default.hostapi
        for idx, dev in enumerate(sd.query_devices()):
            if dev["name"] == name and dev["max_input_channels"] > 0 and dev["hostapi"] == default_api:
                return idx
    except Exception:
        pass
    return None


class Recorder:
    def __init__(self):
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream = None
        self._rate = SAMPLE_RATE
        self.active = False
        self.level = 0.0          # smoothed 0..1, read by the overlay
        self.duration = 0.0       # seconds captured so far

    def start(self, device_name: str = "") -> None:
        if sd is None:
            raise RuntimeError("Aucun périphérique audio disponible.")
        self._chunks = []
        self.level = 0.0
        self.duration = 0.0
        self.active = True
        device = _find_device(device_name)
        try:
            self._open(device, SAMPLE_RATE)
        except Exception:
            # Some devices refuse 16 kHz: record at their native rate and resample later.
            info = sd.query_devices(device, "input")
            self._open(device, int(info["default_samplerate"]))

    def _open(self, device, rate: int) -> None:
        self._rate = rate
        self._stream = sd.InputStream(
            samplerate=rate, channels=1, dtype="float32",
            device=device, callback=self._cb, blocksize=int(rate * 0.03),
        )
        self._stream.start()

    def _cb(self, indata, frames, t, status):
        if not self.active:
            return
        mono = indata[:, 0].copy()
        with self._lock:
            self._chunks.append(mono)
            self.duration += frames / self._rate
        rms = float(np.sqrt(np.mean(mono ** 2)) + 1e-9)
        db = 20 * np.log10(rms)
        target = min(1.0, max(0.0, (db + 55) / 45))
        # fast attack, slower release — looks natural on the waveform
        k = 0.6 if target > self.level else 0.25
        self.level += (target - self.level) * k

    def stop(self) -> np.ndarray | None:
        self.active = False
        self.level = 0.0
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        with self._lock:
            if not self._chunks:
                return None
            audio = np.concatenate(self._chunks)
        if self._rate != SAMPLE_RATE:
            n = int(len(audio) * SAMPLE_RATE / self._rate)
            audio = np.interp(np.linspace(0, len(audio) - 1, n),
                              np.arange(len(audio)), audio).astype(np.float32)
        return audio


# ─── UI sounds ────────────────────────────────────────────────────────────────
def _tone(freqs, dur=0.07, rate=44100, volume=0.12) -> np.ndarray:
    parts = []
    for f in freqs:
        t = np.linspace(0, dur, int(rate * dur), endpoint=False)
        env = np.minimum(1, t / 0.008) * np.exp(-t * 28)
        parts.append(np.sin(2 * np.pi * f * t) * env * volume)
    return np.concatenate(parts).astype(np.float32)


_SOUNDS = {}


def play(name: str) -> None:
    if sd is None:
        return
    if not _SOUNDS:
        _SOUNDS.update({
            "start":  _tone([660, 990]),
            "stop":   _tone([880, 587]),
            "cancel": _tone([440, 330], volume=0.08),
            "error":  _tone([300, 300], volume=0.1),
        })
    try:
        sd.play(_SOUNDS[name], 44100)
    except Exception as exc:
        log.debug("sound failed: %s", exc)
