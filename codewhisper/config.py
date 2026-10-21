"""Settings, presets and paths.

Everything the user can change lives in data/settings.json (created on first
launch). Edit it through the settings window rather than by hand.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

APP_NAME = "CodeWhisper"
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "history.json"
LOG_FILE = DATA_DIR / "codewhisper.log"

SAMPLE_RATE = 16000

# ─── Local Whisper models (faster-whisper) ────────────────────────────────────
# speed / quality are 1–5, measured on a CPU with int8 quantisation.
LOCAL_MODELS = [
    {"id": "tiny",           "name": "Tiny",           "size": "75 Mo",  "speed": 5, "quality": 1,
     "note": "Instantané, mais fait beaucoup d'erreurs."},
    {"id": "base",           "name": "Base",           "size": "145 Mo", "speed": 4, "quality": 2,
     "note": "Rapide, correct pour des phrases simples."},
    {"id": "small",          "name": "Small",          "size": "480 Mo", "speed": 4, "quality": 3,
     "note": "Bon compromis sur une machine modeste."},
    {"id": "medium",         "name": "Medium",         "size": "1,5 Go", "speed": 2, "quality": 4,
     "note": "Très bon en français, un peu lent."},
    {"id": "large-v3-turbo", "name": "Large v3 Turbo", "size": "1,6 Go", "speed": 3, "quality": 5,
     "note": "Qualité proche de Large v3, bien plus rapide.", "recommended": True},
    {"id": "large-v3",       "name": "Large v3",       "size": "3 Go",   "speed": 1, "quality": 5,
     "note": "Le plus précis, le plus lent."},
    {"id": "distil-large-v3", "name": "Distil Large v3", "size": "1,5 Go", "speed": 4, "quality": 4,
     "note": "Rapide et précis, mais anglais uniquement.", "english_only": True},
]
LOCAL_MODEL_IDS = {m["id"] for m in LOCAL_MODELS}

# ─── Speech-to-text providers ─────────────────────────────────────────────────
STT_PROVIDERS = {
    "local": {
        "label": "Sur ce PC",
        "hint": "Whisper tourne en local. Gratuit, privé, fonctionne hors ligne.",
    },
    "groq": {
        "label": "Groq",
        "hint": "Whisper dans le cloud, quasi instantané. Offre gratuite généreuse.",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["whisper-large-v3-turbo", "whisper-large-v3"],
        "key_url": "https://console.groq.com/keys",
    },
    "openai": {
        "label": "OpenAI",
        "hint": "Modèles de transcription d'OpenAI. Payant à la minute.",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"],
        "key_url": "https://platform.openai.com/api-keys",
    },
    "custom": {
        "label": "Autre serveur",
        "hint": "N'importe quel serveur compatible OpenAI (/audio/transcriptions).",
        "base_url": "http://localhost:8000/v1",
        "models": [],
    },
}

# ─── Text clean-up (LLM) providers — all OpenAI-compatible ────────────────────
LLM_PROVIDERS = {
    "llamacpp": {
        "label": "llama.cpp (local)",
        "base_url": "http://localhost:8080/v1",
        "models": [],
        "needs_key": False,
    },
    "ollama": {
        "label": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "models": ["qwen3:8b", "llama3.2", "mistral"],
        "needs_key": False,
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        "needs_key": True,
        "key_url": "https://console.groq.com/keys",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4.1-mini", "gpt-4o-mini"],
        "needs_key": True,
        "key_url": "https://platform.openai.com/api-keys",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat"],
        "needs_key": True,
        "key_url": "https://platform.deepseek.com/api_keys",
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-haiku-5-5", "claude-sonnet-5-5"],
        "needs_key": True,
        "key_url": "https://console.anthropic.com/settings/keys",
    },
    "custom": {
        "label": "Autre serveur",
        "base_url": "http://localhost:1234/v1",
        "models": [],
        "needs_key": False,
    },
}

DEFAULT_CLEANUP_PROMPT = (
    "Tu reçois la transcription brute d'une dictée vocale. Réécris-la proprement :\n"
    "- corrige la ponctuation, les majuscules et les fautes évidentes de transcription ;\n"
    "- supprime les hésitations (euh, hum, du coup répétés…) et les faux départs ;\n"
    "- si la personne se corrige (« non, plutôt… »), garde seulement la version corrigée ;\n"
    "- garde la langue d'origine, le ton et le sens exact. Ne traduis pas, n'ajoute rien ;\n"
    "- conserve tels quels les termes techniques, noms de code, commandes et identifiants.\n"
    "Si le texte est une question ou une consigne, ne réponds pas : réécris-la seulement.\n"
    "Renvoie uniquement le texte final, sans guillemets ni commentaire."
)

LANGUAGES = [
    ("auto", "Détection auto"), ("fr", "Français"), ("en", "Anglais"),
    ("es", "Espagnol"), ("de", "Allemand"), ("it", "Italien"), ("pt", "Portugais"),
    ("nl", "Néerlandais"), ("el", "Grec"), ("he", "Hébreu"), ("la", "Latin"),
    ("ar", "Arabe"), ("zh", "Chinois"), ("ja", "Japonais"), ("ru", "Russe"),
]
LANG_LABELS = dict(LANGUAGES)

DEFAULTS = {
    "version": 2,
    "stt": {
        "provider": "local",
        "local_model": "medium",
        "custom_local_model": "",
        "device": "cpu",
        "beam_size": 5,
        "providers": {
            "groq":   {"key": "", "model": "whisper-large-v3-turbo"},
            "openai": {"key": "", "model": "gpt-4o-mini-transcribe"},
            "custom": {"key": "", "model": "", "base_url": "http://localhost:8000/v1"},
        },
    },
    "llm": {
        "enabled": False,
        "provider": "llamacpp",
        "prompt": DEFAULT_CLEANUP_PROMPT,
        "providers": {
            name: {"key": "", "model": (p["models"][0] if p["models"] else ""),
                   "base_url": p["base_url"]}
            for name, p in LLM_PROVIDERS.items()
        },
    },
    "vocabulary": "",
    "shortcuts": [
        {"hotkey": "ctrl+space", "language": "en"},
        {"hotkey": "ctrl+shift+space", "language": "fr"},
    ],
    "cancel_hotkey": "escape",
    "mode": "toggle",          # toggle | hold
    "microphone": "",          # device name, "" = Windows default
    "auto_paste": True,
    "restore_clipboard": False,
    "paste_delay": 0.05,
    "max_record": 120,
    "sounds": True,
    "idle_pill": True,
    "position": "bottom-center",   # bottom-center | bottom-right | top-center
    "theme": "system",             # system | light | dark
    "history_limit": 500,
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    """Dotted-path access to settings, persisted to JSON, with change listeners."""

    def __init__(self, path: Path = SETTINGS_FILE):
        self.path = path
        self._lock = threading.RLock()
        self._listeners = []
        self.first_run = not path.exists()
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        self.data = _deep_merge(DEFAULTS, data)
        if self.first_run:
            self.save()

    # ── access ────────────────────────────────────────────────────────────────
    def get(self, path: str, default=None):
        with self._lock:
            node = self.data
            for part in path.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return copy.deepcopy(node)

    def set(self, path: str, value) -> None:
        with self._lock:
            parts = path.split(".")
            node = self.data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            if node.get(parts[-1]) == value:
                return
            node[parts[-1]] = copy.deepcopy(value)
            self.save()
        for cb in list(self._listeners):
            cb(path)

    def on_change(self, callback) -> None:
        self._listeners.append(callback)

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)

    # ── helpers ───────────────────────────────────────────────────────────────
    def stt_model_label(self) -> str:
        provider = self.get("stt.provider")
        if provider == "local":
            model = self.local_model_id()
            for m in LOCAL_MODELS:
                if m["id"] == model:
                    return m["name"]
            return model
        model = self.get(f"stt.providers.{provider}.model") or "?"
        return f"{STT_PROVIDERS[provider]['label']} · {model}"

    def local_model_id(self) -> str:
        custom = (self.get("stt.custom_local_model") or "").strip()
        return custom or self.get("stt.local_model")

    def llm_settings(self) -> dict:
        name = self.get("llm.provider")
        conf = self.get(f"llm.providers.{name}") or {}
        preset = LLM_PROVIDERS.get(name, {})
        return {
            "name": name,
            "label": preset.get("label", name),
            "base_url": (conf.get("base_url") or preset.get("base_url", "")).rstrip("/"),
            "key": conf.get("key", ""),
            "model": conf.get("model", ""),
        }

    def stt_api_settings(self) -> dict:
        name = self.get("stt.provider")
        conf = self.get(f"stt.providers.{name}") or {}
        preset = STT_PROVIDERS.get(name, {})
        return {
            "name": name,
            "label": preset.get("label", name),
            "base_url": (conf.get("base_url") or preset.get("base_url", "")).rstrip("/"),
            "key": conf.get("key", ""),
            "model": conf.get("model", ""),
        }
