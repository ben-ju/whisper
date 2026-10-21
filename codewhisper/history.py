"""Transcription history, stored in data/history.json."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .config import HISTORY_FILE


class History:
    def __init__(self, path: Path = HISTORY_FILE, limit: int = 500):
        self.path = path
        self.limit = limit
        self._lock = threading.Lock()
        try:
            self.items: list[dict] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.items = []

    def add(self, text: str, raw: str, language: str, engine: str, duration: float) -> dict:
        item = {
            "id": f"{time.time():.3f}",
            "ts": time.time(),
            "text": text,
            "raw": raw if raw != text else "",
            "language": language,
            "engine": engine,
            "duration": round(duration, 1),
            "words": len(text.split()),
        }
        with self._lock:
            self.items.insert(0, item)
            del self.items[self.limit:]
            self._save()
        return item

    def delete(self, item_id: str) -> None:
        with self._lock:
            self.items = [i for i in self.items if i["id"] != item_id]
            self._save()

    def clear(self) -> None:
        with self._lock:
            self.items = []
            self._save()

    def stats(self) -> dict:
        now = time.time()
        week = [i for i in self.items if now - i["ts"] < 7 * 86400]
        words = sum(i["words"] for i in self.items)
        secs = sum(i["duration"] for i in self.items if i["duration"] > 0)
        timed_words = sum(i["words"] for i in self.items if i["duration"] > 0)
        return {
            "total_words": words,
            "week_words": sum(i["words"] for i in week),
            "sessions": len(self.items),
            "wpm": round(timed_words / (secs / 60)) if secs > 5 else 0,
            # typing at ~40 wpm vs speaking: minutes saved
            "saved_min": max(0, round(timed_words / 40 - secs / 60)),
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
