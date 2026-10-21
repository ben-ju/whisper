"""Speech-to-text engines (local faster-whisper or OpenAI-compatible API)
and the optional LLM clean-up pass."""

from __future__ import annotations

import io
import logging
import re
import threading
import wave

import numpy as np
import requests

from .config import SAMPLE_RATE

log = logging.getLogger(__name__)

HTTP_TIMEOUT = 60


class EngineError(Exception):
    """Error with a message meant for the user."""


def _api_error(resp: requests.Response) -> EngineError:
    try:
        detail = resp.json()
        detail = detail.get("error", detail)
        if isinstance(detail, dict):
            detail = detail.get("message", str(detail))
    except ValueError:
        detail = resp.text[:200]
    if resp.status_code in (401, 403):
        return EngineError("Clé API refusée. Vérifie-la dans Modèles IA.")
    if resp.status_code == 404:
        return EngineError(f"Modèle ou adresse introuvable ({detail})")
    if resp.status_code == 429:
        return EngineError("Limite de requêtes atteinte chez le fournisseur.")
    return EngineError(f"Erreur {resp.status_code} : {detail}")


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"} if key else {}


def to_wav(audio: np.ndarray) -> bytes:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def list_remote_models(base_url: str, key: str) -> list[str]:
    """GET {base_url}/models — works with OpenAI, Groq, Ollama, llama.cpp, DeepSeek…"""
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/models", headers=_headers(key), timeout=8)
    except requests.RequestException as exc:
        raise EngineError(f"Serveur injoignable : {base_url}") from exc
    if not resp.ok:
        raise _api_error(resp)
    data = resp.json()
    items = data.get("data", data.get("models", []))
    ids = []
    for it in items:
        mid = it.get("id") or it.get("name") or it.get("model") if isinstance(it, dict) else it
        if mid:
            ids.append(str(mid))
    return sorted(set(ids))


# ─── Local Whisper ────────────────────────────────────────────────────────────
class LocalWhisper:
    def __init__(self, model_id: str, device: str = "cpu"):
        self.model_id = model_id
        self.device = device
        self.model = None

    @staticmethod
    def is_downloaded(model_id: str) -> bool:
        try:
            from faster_whisper.utils import download_model
            download_model(model_id, local_files_only=True)
            return True
        except Exception:
            return False

    def load(self) -> None:
        from faster_whisper import WhisperModel
        if self.device in ("cuda", "auto"):
            try:
                self.model = WhisperModel(self.model_id, device="cuda", compute_type="float16")
                self.device = "cuda"
                return
            except Exception as exc:
                if self.device == "cuda":
                    log.warning("CUDA unavailable (%s), falling back to CPU", exc)
        self.model = WhisperModel(self.model_id, device="cpu", compute_type="int8")
        self.device = "cpu"

    def transcribe(self, audio: np.ndarray, language: str | None, prompt: str, beam_size: int) -> str:
        segs, _ = self.model.transcribe(
            audio, beam_size=beam_size, language=language,
            initial_prompt=prompt or None, vad_filter=True,
        )
        return " ".join(s.text.strip() for s in segs).strip()


# ─── API Whisper ──────────────────────────────────────────────────────────────
class ApiWhisper:
    def __init__(self, base_url: str, key: str, model: str, label: str):
        self.base_url = base_url.rstrip("/")
        self.key = key
        self.model = model
        self.label = label

    def transcribe(self, audio: np.ndarray, language: str | None, prompt: str, beam_size: int = 5) -> str:
        if not self.model:
            raise EngineError(f"Choisis un modèle pour {self.label} dans Modèles IA.")
        data = {"model": self.model, "response_format": "json", "temperature": "0"}
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt
        files = {"file": ("dictation.wav", to_wav(audio), "audio/wav")}
        try:
            resp = requests.post(f"{self.base_url}/audio/transcriptions", headers=_headers(self.key),
                                 data=data, files=files, timeout=HTTP_TIMEOUT)
        except requests.RequestException as exc:
            raise EngineError(f"{self.label} injoignable. Vérifie ta connexion.") from exc
        if not resp.ok:
            raise _api_error(resp)
        try:
            return resp.json().get("text", "").strip()
        except ValueError:
            return resp.text.strip()


# ─── LLM clean-up ─────────────────────────────────────────────────────────────
_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def cleanup_text(text: str, settings: dict, prompt: str, vocabulary: str = "") -> str:
    system = prompt
    if vocabulary.strip():
        system += "\n\nOrthographe à respecter pour ces termes : " + vocabulary.strip()
    body = {
        "model": settings["model"] or "default",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        "temperature": 0.2,
        "stream": False,
    }
    try:
        resp = requests.post(f"{settings['base_url']}/chat/completions",
                             headers=_headers(settings["key"]), json=body, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise EngineError(f"{settings['label']} injoignable ({settings['base_url']}).") from exc
    if not resp.ok:
        raise _api_error(resp)
    out = resp.json()["choices"][0]["message"]["content"] or ""
    out = _THINK_RE.sub("", out).strip()
    pairs = {'"': '"', "«": "»", "“": "”", "'": "'"}
    if len(out) >= 2 and pairs.get(out[0]) == out[-1] and out.count(out[0]) == 1 + (out[0] == out[-1]):
        out = out[1:-1].strip()
    return out or text


# ─── Engine manager ───────────────────────────────────────────────────────────
class EngineManager:
    """Keeps the current STT engine, reloading the local model only when needed."""

    def __init__(self, config):
        self.config = config
        self._local: LocalWhisper | None = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self.loading_model: str | None = None
        self.error: str | None = None

    @property
    def ready(self) -> bool:
        if self.config.get("stt.provider") != "local":
            return True
        return self._ready.is_set()

    def ensure_loaded(self, on_status) -> None:
        """Load the local model in the background if the config needs one.

        on_status(kind, text) is called with ("loading"|"downloading", label),
        ("ready", label) or ("error", message).
        """
        if self.config.get("stt.provider") != "local":
            self._ready.set()
            on_status("ready", self.config.stt_model_label())
            return
        model_id = self.config.local_model_id()
        device = self.config.get("stt.device")
        with self._lock:
            if self._local and self._local.model_id == model_id and self._ready.is_set() \
                    and (device == self._local.device or device == "auto"):
                on_status("ready", self.config.stt_model_label())
                return
            self._ready.clear()
            self.loading_model = model_id

        def _go():
            label = self.config.stt_model_label()
            downloaded = LocalWhisper.is_downloaded(model_id)
            on_status("loading" if downloaded else "downloading", label)
            engine = LocalWhisper(model_id, device)
            try:
                engine.load()
            except Exception as exc:
                log.exception("Model load failed")
                with self._lock:
                    if self.loading_model == model_id:
                        self.loading_model = None
                        self.error = str(exc)
                on_status("error", f"Impossible de charger {label}")
                return
            with self._lock:
                if self.loading_model != model_id:
                    return  # user switched model while we were loading
                self._local = engine
                self.loading_model = None
                self.error = None
                self._ready.set()
            log.info("Model %s ready on %s", model_id, engine.device)
            on_status("ready", label)

        threading.Thread(target=_go, daemon=True, name="model-loader").start()

    def transcribe(self, audio: np.ndarray, language: str | None) -> str:
        vocab = self.config.get("vocabulary") or ""
        prompt = ", ".join(w.strip() for w in re.split(r"[,\n]", vocab) if w.strip())
        provider = self.config.get("stt.provider")
        if provider == "local":
            self._ready.wait()
            return self._local.transcribe(audio, language, prompt, self.config.get("stt.beam_size"))
        s = self.config.stt_api_settings()
        return ApiWhisper(s["base_url"], s["key"], s["model"], s["label"]).transcribe(audio, language, prompt)

    def cleanup(self, text: str) -> str:
        return cleanup_text(text, self.config.llm_settings(), self.config.get("llm.prompt"),
                            self.config.get("vocabulary") or "")
