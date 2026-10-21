"""Application controller: hotkeys → recording → transcription → paste."""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
import threading
import time

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import audio, winutil
from .config import (APP_NAME, DATA_DIR, LANG_LABELS, LOCAL_MODELS, LOG_FILE, SAMPLE_RATE,
                     STT_PROVIDERS, Config)
from .engines import EngineError, EngineManager
from .history import History
from .hotkeys import HotkeyManager, pretty
from .overlay import AMBER, RED, Pill

log = logging.getLogger("codewhisper")

# Whisper sometimes "hears" these in silence (it learned them from subtitles).
HALLUCINATIONS = {
    "sous-titres réalisés para la communauté d'amara.org",
    "sous-titres réalisés par la communauté d'amara.org",
    "sous-titrage st' 501", "sous-titrage société radio-canada",
    "merci d'avoir regardé cette vidéo", "merci d'avoir regardé",
    "thank you for watching", "thanks for watching", "you", "…",
}

RELOAD_KEYS = {"stt.provider", "stt.local_model", "stt.custom_local_model", "stt.device", "stt.gpu_server"}


def _norm(text: str) -> str:
    return re.sub(r"[\s!.…]+$", "", text.strip().lower())


HALLUCINATIONS = {_norm(h) for h in HALLUCINATIONS}


ICON_COLORS = {
    "idle": ("#7A6BFF", "#3E2CC2"),
    "recording": ("#FF6B6F", "#C9303B"),
    "processing": ("#F7C25A", "#C7801A"),
    "polishing": ("#A89BFF", "#5546D6"),
}


def make_pixmap(state: str = "idle", size: int = 64) -> QPixmap:
    """The app icon (rounded square + waveform), tinted by state."""
    top, bottom = ICON_COLORS.get(state, ICON_COLORS["idle"])
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0, QColor(top))
    grad.setColorAt(1, QColor(bottom))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    m = size * 0.04
    p.drawRoundedRect(QRectF(m, m, size - 2 * m, size - 2 * m), size * 0.24, size * 0.24)
    p.setBrush(QColor("#FFFFFF"))
    small = size <= 24
    heights = (0.40, 0.72, 0.44) if small else (0.30, 0.56, 0.80, 0.50, 0.34)
    bw = size * (0.14 if small else 0.085)
    gap = size * (0.22 if small else 0.145)
    x0 = size / 2 - gap * (len(heights) - 1) / 2
    for i, h in enumerate(heights):
        hh = size * h * 0.78
        p.drawRoundedRect(QRectF(x0 + i * gap - bw / 2, size / 2 - hh / 2, bw, hh), bw / 2, bw / 2)
    p.end()
    return pm


def make_icon(state: str = "idle") -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128):
        icon.addPixmap(make_pixmap(state, size))
    return icon


class App(QObject):
    status_changed = Signal(str, str)
    history_changed = Signal()
    _pill = Signal(str, str, str, str, int)      # state, text, badge, accent, timeout
    _trigger = Signal(object)
    _engine_status = Signal(str, str)

    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.config = Config()
        self.history = History(limit=self.config.get("history_limit"))
        self.engine = EngineManager(self.config)
        self.recorder = audio.Recorder()
        self.hotkeys = HotkeyManager()
        self.status = ("loading", self.config.stt_model_label())

        self._active = False
        self._cancelled = False
        self._lock = threading.Lock()

        self.pill = Pill(level_source=lambda: self.recorder.level)
        self.pill.idle_visible = self.config.get("idle_pill")
        self.pill.position = self.config.get("position")
        self.pill.cancel_clicked.connect(self._on_cancel)
        self.pill.stop_clicked.connect(self._stop)
        self.pill.start_clicked.connect(self._start_default)
        self.pill.settings_clicked.connect(lambda: self.show_window())

        self._pill.connect(self._apply_pill)
        self._trigger.connect(self._on_trigger)
        self._engine_status.connect(self._on_engine_status)

        self._reload_timer = QTimer(self, singleShot=True, interval=350)
        self._reload_timer.timeout.connect(self._reload_engine)
        self.config.on_change(self._on_config)

        self.window = None
        self.quitting = False
        self._build_tray()

    # ── startup ───────────────────────────────────────────────────────────────
    def start(self):
        self._register_hotkeys()
        self._show("idle")
        self.engine.ensure_loaded(self._engine_status.emit)
        if self.config.first_run:
            QTimer.singleShot(400, self.show_window)

    def show_window(self, page: str | None = None):
        if self.window is None:
            from .settings import SettingsWindow
            self.window = SettingsWindow(self)
            self.window.setWindowIcon(make_icon())
        self.window.present(page)

    def quit(self):
        self.quitting = True
        self.recorder.active = False
        self.engine.shutdown()      # stops whisper-server and frees the VRAM
        self.tray.hide()
        self.pill.hide()
        if self.window is not None:
            self.window.hide()
        self.qapp.exit(0)

    # ── config reactions ─────────────────────────────────────────────────────
    def _on_config(self, path: str):
        if path in RELOAD_KEYS:
            self._reload_timer.start()
        elif path in ("shortcuts", "cancel_hotkey"):
            self._register_hotkeys()
        elif path == "idle_pill":
            self.pill.set_idle_visible(self.config.get("idle_pill"))
        elif path == "position":
            self.pill.set_position(self.config.get("position"))
        if path.startswith(("stt.", "llm.")):
            self._update_tray_tooltip()

    def _reload_engine(self):
        self.engine.ensure_loaded(self._engine_status.emit)

    def _register_hotkeys(self):
        shortcuts = self.config.get("shortcuts")
        failed = self.hotkeys.register(shortcuts, self.config.get("cancel_hotkey"),
                                       lambda sc: self._trigger.emit(sc), self._on_cancel)
        first = next((s["hotkey"] for s in shortcuts if s.get("hotkey")), "")
        self.pill.hint = pretty(first) if first else "le raccourci"
        if failed:
            self._show("message", f"Raccourci invalide : {', '.join(failed)}", accent=RED, timeout=4000)

    def _on_engine_status(self, kind: str, text: str):
        self.status = (kind, text)
        self.status_changed.emit(kind, text)
        self._update_tray_tooltip()
        if self._active:
            return
        if kind == "loading":
            self._show("loading", f"Chargement de {text}…")
        elif kind == "downloading":
            size = next((m["size"] for m in LOCAL_MODELS if text in (m["name"], f"{m['name']} · GPU")), "")
            self._show("loading", f"Téléchargement de {text}" + (f" ({size})…" if size else "…"))
        elif kind == "ready":
            if self.pill.state == "loading":
                self._show("done", f"{text} est prêt", timeout=1600)
        elif kind == "error":
            self._show("message", text, accent=RED, timeout=5000)

    # ── pill (thread-safe) ───────────────────────────────────────────────────
    def _show(self, state, text="", badge="", accent=None, timeout=0):
        c = accent.name() if accent is not None else ""
        self._pill.emit(state, text, badge, c, timeout)

    def _apply_pill(self, state, text, badge, accent, timeout):
        self.pill.set_state(state, text, badge, QColor(accent) if accent else None, timeout)
        self.tray.setIcon(self._icons.get(state, self._icons["idle"]))

    # ── dictation flow ───────────────────────────────────────────────────────
    def _start_default(self):
        shortcuts = self.config.get("shortcuts")
        if shortcuts:
            self._on_trigger(shortcuts[0], from_click=True)

    def _stop(self):
        self.recorder.active = False

    def _on_cancel(self):
        with self._lock:
            if not self._active:
                return
            self._cancelled = True
        self.recorder.active = False

    def _on_trigger(self, sc: dict, from_click: bool = False):
        with self._lock:
            if self._active:
                if self.config.get("mode") == "toggle" or from_click:
                    self.recorder.active = False
                return
            if not self.engine.ready:
                self._show("message", "Le modèle se charge encore, patiente un instant…", accent=AMBER, timeout=2000)
                return
            provider = self.config.get("stt.provider")
            if provider in ("groq", "openai") and not self.config.get(f"stt.providers.{provider}.key"):
                self._show("message", f"Ajoute ta clé {STT_PROVIDERS[provider]['label']} dans Modèles IA",
                           accent=RED, timeout=3500)
                QTimer.singleShot(0, lambda: self.show_window("models"))
                return
            self._active = True
            self._cancelled = False
        hold = self.config.get("mode") == "hold" and not from_click
        threading.Thread(target=self._session, args=(sc, hold), daemon=True, name="session").start()

    def _session(self, sc: dict, hold: bool):
        lang = sc.get("language") or "auto"
        badge = "AUTO" if lang == "auto" else lang.upper()
        sounds = self.config.get("sounds")
        try:
            if sounds:
                audio.play("start")
                time.sleep(0.12)   # don't record our own beep
            try:
                self.recorder.start(self.config.get("microphone"))
            except Exception as exc:
                log.exception("Microphone error")
                self._show("message", f"Micro indisponible : {exc}", accent=RED, timeout=4000)
                return
            self._show("recording", badge=badge)

            started = time.monotonic()
            deadline = started + self.config.get("max_record")
            while self.recorder.active and time.monotonic() < deadline:
                if hold and time.monotonic() - started > 0.25 and not self.hotkeys.is_held(sc["hotkey"]):
                    break
                time.sleep(0.03)
            duration = self.recorder.duration
            pcm = self.recorder.stop()

            if self._cancelled:
                if sounds:
                    audio.play("cancel")
                self._show("message", "Annulé", accent=QColor("#8A8F99"), timeout=1100)
                return
            if pcm is None or len(pcm) < SAMPLE_RATE * 0.3:
                self._show("idle")
                return
            if sounds:
                audio.play("stop")
            self._show("processing")

            try:
                text = self.engine.transcribe(pcm, None if lang == "auto" else lang)
            except EngineError as exc:
                self._fail(str(exc))
                return
            except Exception as exc:
                log.exception("Transcription failed")
                self._fail(f"Échec de la transcription : {exc}")
                return
            if _norm(text) in HALLUCINATIONS:
                text = ""
            if self._cancelled:
                self._show("message", "Annulé", accent=QColor("#8A8F99"), timeout=1100)
                return
            if not text:
                self._show("message", "Rien entendu", accent=QColor("#8A8F99"), timeout=1400)
                return

            raw = text
            warning = ""
            if self.config.get("llm.enabled"):
                llm = self.config.llm_settings()
                self._show("polishing", f"Mise en forme avec {llm['label']}…")
                try:
                    text = self.engine.cleanup(text)
                except Exception as exc:
                    log.warning("Clean-up failed: %s", exc)
                    warning = f"Mise en forme impossible ({exc}). Texte brut collé."
                if self._cancelled:
                    self._show("message", "Annulé", accent=QColor("#8A8F99"), timeout=1100)
                    return

            log.info("[%s] %r", badge, text)
            self._deliver(text)
            self.history.add(text, raw, lang, self.config.stt_model_label(), duration)
            self.history_changed.emit()
            if warning:
                self._show("message", warning, accent=AMBER, timeout=4500)
            else:
                self._show("done", text, timeout=2400)
        finally:
            with self._lock:
                self._active = False

    def _fail(self, message: str):
        if self.config.get("sounds"):
            audio.play("error")
        self._show("message", message, accent=RED, timeout=5000)

    def _deliver(self, text: str):
        import pyperclip
        previous = None
        if self.config.get("restore_clipboard"):
            try:
                previous = pyperclip.paste()
            except Exception:
                previous = None
        pyperclip.copy(text)
        if self.config.get("auto_paste"):
            time.sleep(self.config.get("paste_delay"))
            winutil.send_paste()
            if previous is not None:
                time.sleep(0.4)
                pyperclip.copy(previous)

    # ── tray ──────────────────────────────────────────────────────────────────
    def _build_tray(self):
        self._icons = {state: make_icon(state) for state in ICON_COLORS}
        self.tray = QSystemTrayIcon(self._icons["idle"], self)
        self.menu = QMenu()
        self.menu.aboutToShow.connect(self._fill_menu)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(
            lambda reason: self.show_window() if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self._fill_menu()
        self._update_tray_tooltip()
        self.tray.show()

    def _update_tray_tooltip(self):
        tip = f"{APP_NAME} : {self.config.stt_model_label()}"
        if self.config.get("llm.enabled"):
            tip += f"\nMise en forme : {self.config.llm_settings()['label']}"
        self.tray.setToolTip(tip)

    def _fill_menu(self):
        m = self.menu
        m.clear()
        m.addAction("Ouvrir CodeWhisper", self.show_window)
        m.addSeparator()

        stt = m.addMenu("Transcription")
        group = QActionGroup(stt)
        provider = self.config.get("stt.provider")
        current_local = self.config.local_model_id()
        for model in LOCAL_MODELS:
            a = QAction(f"{model['name']}  ({model['size']})", stt, checkable=True)
            a.setChecked(provider == "local" and current_local == model["id"])
            a.triggered.connect(lambda _=False, mid=model["id"]: self._pick_local(mid))
            group.addAction(a)
            stt.addAction(a)
        stt.addSeparator()
        gpu = QAction("Calculer sur la carte graphique", stt, checkable=True)
        gpu.setChecked(self.config.get("stt.device") == "gpu")
        gpu.triggered.connect(lambda on: self.config.set("stt.device", "gpu" if on else "cpu"))
        stt.addAction(gpu)
        stt.addSeparator()
        for name in ("groq", "openai", "custom"):
            conf = self.config.get(f"stt.providers.{name}")
            usable = bool(conf.get("key")) or name == "custom"
            a = QAction(f"{STT_PROVIDERS[name]['label']} : {conf.get('model') or '?'}", stt, checkable=True)
            a.setChecked(provider == name)
            a.setEnabled(usable)
            a.triggered.connect(lambda _=False, n=name: self.config.set("stt.provider", n))
            group.addAction(a)
            stt.addAction(a)
        stt.addSeparator()
        stt.addAction("Configurer…", lambda: self.show_window("models"))

        polish = QAction(f"Mise en forme IA ({self.config.llm_settings()['label']})", m, checkable=True)
        polish.setChecked(self.config.get("llm.enabled"))
        polish.triggered.connect(lambda on: self.config.set("llm.enabled", on))
        m.addAction(polish)

        m.addSeparator()
        for sc in self.config.get("shortcuts"):
            a = m.addAction(f"{LANG_LABELS.get(sc['language'], sc['language'])} : {pretty(sc['hotkey'])}")
            a.setEnabled(False)
        m.addAction("Historique", lambda: self.show_window("history"))
        m.addSeparator()
        m.addAction("Quitter", self.quit)

    def _pick_local(self, mid: str):
        self.config.set("stt.custom_local_model", "")
        self.config.set("stt.local_model", mid)
        self.config.set("stt.provider", "local")


# ─── entry point ──────────────────────────────────────────────────────────────
def _setup_logging():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Under pythonw.exe there is no console: libraries that write progress bars
    # (model downloads) would crash on a None stream.
    if sys.stdout is None or sys.stderr is None:
        sink = open(LOG_FILE.with_suffix(".out.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or sink
        sys.stderr = sys.stderr or sink
    handlers = [logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2,
                                                     encoding="utf-8")]
    if sys.stdout and getattr(sys.stdout, "isatty", lambda: False)():
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def main():
    _setup_logging()
    if winutil.IS_WIN:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CodeWhisper.App")
        except Exception:
            pass

    qapp = QApplication(sys.argv)
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setWindowIcon(make_icon())

    # Single instance: a second launch just opens the window of the first one.
    sock = QLocalSocket()
    sock.connectToServer("CodeWhisper-instance")
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        return 0

    app = App(qapp)
    QLocalServer.removeServer("CodeWhisper-instance")
    server = QLocalServer()
    server.listen("CodeWhisper-instance")
    server.newConnection.connect(lambda: (server.nextPendingConnection(), app.show_window()))
    app.start()
    log.info("CodeWhisper started")
    return qapp.exec()
