"""Graphics-card engine: whisper.cpp's server with the Vulkan backend.

faster-whisper only reaches the GPU through CUDA (NVIDIA). whisper.cpp runs the
same Whisper models through Vulkan, so it uses any recent AMD, NVIDIA or Intel
card. CodeWhisper sets it up by itself the first time:

1. the runtime — whisper-server.exe, ggml (with ggml-vulkan.dll) and the MinGW
   DLLs they need — comes from the MSYS2 package repository (prebuilt, signed
   packages; nothing is compiled on your PC), unpacked into data/whispercpp/bin;
2. the model — ggml weights from Hugging Face, into data/whispercpp/models;
3. the server is started in the background on 127.0.0.1 and stopped with the
   app (a Windows job object kills it even if CodeWhisper crashes).

You can use your own build instead: point "stt.gpu_server" to whisper-server.exe.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import lzma
import os
import re
import shutil
import socket
import subprocess
import tarfile
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np
import requests

from .config import GGML_MODELS, VAD_MODEL_URL, WHISPERCPP_DIR

log = logging.getLogger(__name__)

BIN_DIR = WHISPERCPP_DIR / "bin"
MODELS_DIR = WHISPERCPP_DIR / "models"
SERVER_LOG = WHISPERCPP_DIR / "server.log"
RUNTIME_MARKER = BIN_DIR / "runtime.json"
SERVER_EXE = "whisper-server.exe"
MSYS2_HOME_EXE = Path(r"C:\msys64\ucrt64\bin") / SERVER_EXE   # a full MSYS2 install, if any

MSYS2_MIRRORS = [
    "https://mirror.msys2.org/mingw/ucrt64/",
    "https://repo.msys2.org/mingw/ucrt64/",
    "https://mirrors.dotsrc.org/msys2/mingw/ucrt64/",
]
PKG_PREFIX = "mingw-w64-ucrt-x86_64-"
ROOT_PACKAGE = PKG_PREFIX + "whisper.cpp"
# Dependencies whisper-server.exe never loads (scripts, other tools, optional
# ggml backends). Skipping them keeps the download around 40 Mo instead of 500.
SKIP_PACKAGES = {"python", "llama.cpp", "SDL2", "openblas", "opencl-icd", "curl", "openssl"}
# ggml backends whose DLL dependencies we skipped: remove them so ggml doesn't try.
DROP_FILES = {"ggml-blas.dll", "ggml-opencl.dll"}

CREATE_NO_WINDOW = 0x08000000
ProgressFn = Callable[[str, float | None], None]   # (what, fraction 0–1 or None)


class GpuEngineError(Exception):
    """Error with a message meant for the user."""


# ─── downloads ────────────────────────────────────────────────────────────────
def _download(url: str, dest: Path, progress: ProgressFn | None = None, what: str = "",
              sha256: str | None = None, timeout: int = 30) -> None:
    """Stream url → dest (via a .part file), reporting progress, checking sha256."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    with requests.get(url, stream=True, timeout=timeout, allow_redirects=True) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        last = 0.0
        with open(part, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                if not chunk:
                    continue
                fh.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                now = time.monotonic()
                if progress and total and now - last > 0.5:
                    last = now
                    progress(what, done / total)
    if sha256 and digest.hexdigest().lower() != sha256.lower():
        part.unlink(missing_ok=True)
        raise GpuEngineError(f"Fichier corrompu pendant le téléchargement ({dest.name}).")
    os.replace(part, dest)


def _zstandard():
    """The zstandard module, installed on the fly (with uv, like install.bat) if missing."""
    try:
        import zstandard
        return zstandard
    except ImportError:
        pass
    import sys
    home = Path.home()
    candidates = [shutil.which("uv"), home / ".local/bin/uv.exe",
                  Path(os.environ.get("LOCALAPPDATA", "")) / "uv/bin/uv.exe",
                  Path(os.environ.get("APPDATA", "")) / "uv/bin/uv.exe", home / ".cargo/bin/uv.exe"]
    uv = next((str(c) for c in candidates if c and Path(c).is_file()), None)
    python = Path(sys.executable)
    if python.name.lower() == "pythonw.exe":
        python = python.with_name("python.exe")
    if uv:
        log.info("Installing zstandard with %s", uv)
        subprocess.run([uv, "pip", "install", "zstandard>=0.22", "--python", str(python)],
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=300,
                       creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        import importlib
        importlib.invalidate_caches()
        import zstandard
        return zstandard
    except ImportError:
        raise GpuEngineError("Il manque le module zstandard : relance install.bat.") from None


def _decompress(data: bytes) -> bytes:
    """pacman databases and packages: zstd, gzip, xz or plain tar."""
    if data[:4] == b"\x28\xb5\x2f\xfd":
        zstandard = _zstandard()
        with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)) as r:
            return r.read()
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    if data[:6] == b"\xfd7zXZ\x00":
        return lzma.decompress(data)
    return data


# ─── MSYS2 package resolution ─────────────────────────────────────────────────
def _strip_version(dep: str) -> str:
    return re.split(r"[<>=]", dep, maxsplit=1)[0].strip()


def parse_pacman_db(raw: bytes) -> dict[str, dict]:
    """{package name: {"filename", "version", "sha256", "depends", "provides"}}"""
    packages = {}
    with tarfile.open(fileobj=io.BytesIO(_decompress(raw)), mode="r:") as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith("/desc"):
                continue
            fields: dict[str, list[str]] = {}
            key = None
            for line in tar.extractfile(member).read().decode("utf-8", "replace").splitlines():
                if line.startswith("%") and line.endswith("%"):
                    key = line.strip("%")
                    fields[key] = []
                elif line and key:
                    fields[key].append(line)
            name = (fields.get("NAME") or [""])[0]
            if not name:
                continue
            packages[name] = {
                "filename": (fields.get("FILENAME") or [""])[0],
                "version": (fields.get("VERSION") or [""])[0],
                "sha256": (fields.get("SHA256SUM") or [None])[0],
                "depends": [_strip_version(d) for d in fields.get("DEPENDS", [])],
                "provides": [_strip_version(p) for p in fields.get("PROVIDES", [])],
            }
    return packages


def resolve_packages(db: dict[str, dict], root: str = ROOT_PACKAGE,
                     skip: set[str] = SKIP_PACKAGES) -> list[str]:
    """Runtime closure of root, minus the skipped packages.

    A virtual dependency (e.g. "omp", "cc-libs") pulls in every package that
    provides it: they are small, and it avoids guessing which one ggml was
    linked against.
    """
    providers: dict[str, list[str]] = {}
    for name, pkg in db.items():
        for prov in pkg["provides"]:
            providers.setdefault(prov, []).append(name)

    def skipped(name: str) -> bool:
        return name.startswith(PKG_PREFIX) and name[len(PKG_PREFIX):] in skip

    wanted: list[str] = []
    todo = [root]
    while todo:
        name = todo.pop()
        if name in wanted or skipped(name):
            continue
        if name in db:
            candidates = [name]
        else:
            candidates = [p for p in providers.get(name, []) if not skipped(p)]
            if not candidates:
                if name == root:
                    raise GpuEngineError("whisper.cpp introuvable dans le dépôt MSYS2.")
                log.warning("MSYS2 dependency %s not found, skipped", name)
                continue
        for cand in candidates:
            if cand not in wanted:
                wanted.append(cand)
                todo.extend(db[cand]["depends"])
    return wanted


def _extract_bin(pkg_file: Path, dest: Path) -> int:
    """Copy the package's <prefix>/bin/*.dll and whisper-server.exe into dest."""
    n = 0
    with tarfile.open(fileobj=io.BytesIO(_decompress(pkg_file.read_bytes())), mode="r:") as tar:
        for member in tar:
            parts = member.name.split("/")
            if not member.isfile() or len(parts) != 3 or parts[1] != "bin":
                continue
            fname = parts[2]
            if not (fname.lower().endswith(".dll") or fname == SERVER_EXE) or fname in DROP_FILES:
                continue
            src = tar.extractfile(member)
            with open(dest / fname, "wb") as out:
                shutil.copyfileobj(src, out)
            if fname == SERVER_EXE and os.name != "nt":
                os.chmod(dest / fname, 0o755)
            n += 1
    return n


def install_runtime(progress: ProgressFn | None = None) -> Path:
    """Download whisper.cpp (Vulkan build) from MSYS2 into BIN_DIR."""
    WHISPERCPP_DIR.mkdir(parents=True, exist_ok=True)
    errors = []
    for mirror in MSYS2_MIRRORS:
        try:
            if progress:
                progress("moteur GPU", None)
            resp = requests.get(mirror + "ucrt64.db", timeout=30)
            resp.raise_for_status()
            db = parse_pacman_db(resp.content)
            names = resolve_packages(db)
            log.info("whisper.cpp runtime packages: %s", ", ".join(f"{n} {db[n]['version']}" for n in names))

            staging = WHISPERCPP_DIR / "bin.new"
            cache = WHISPERCPP_DIR / "packages"
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True)
            cache.mkdir(exist_ok=True)
            for i, name in enumerate(names):
                pkg = db[name]
                local = cache / pkg["filename"]
                if not local.exists():
                    _download(mirror + pkg["filename"], local, sha256=pkg["sha256"], timeout=60)
                if progress:
                    progress("moteur GPU", (i + 1) / len(names))
                _extract_bin(local, staging)
            if not (staging / SERVER_EXE).exists():
                raise GpuEngineError("Le paquet whisper.cpp ne contient pas whisper-server.exe.")
            if not (staging / "ggml-vulkan.dll").exists():
                raise GpuEngineError("Le paquet ggml ne contient pas le backend Vulkan.")
            (staging / RUNTIME_MARKER.name).write_text(json.dumps(
                {"source": mirror, "packages": {n: db[n]["version"] for n in names}}, indent=2))
            shutil.rmtree(BIN_DIR, ignore_errors=True)
            os.replace(staging, BIN_DIR)
            shutil.rmtree(cache, ignore_errors=True)
            return BIN_DIR / SERVER_EXE
        except GpuEngineError:
            raise
        except Exception as exc:  # network / mirror problem: try the next one
            log.warning("MSYS2 mirror %s failed: %s", mirror, exc)
            errors.append(f"{mirror}: {exc}")
    raise GpuEngineError("Téléchargement du moteur GPU impossible (dépôt MSYS2 injoignable : "
                         f"{errors[-1] if errors else '?'}).")


def find_server(custom_path: str = "") -> Path | None:
    """whisper-server.exe to use, without downloading anything."""
    if custom_path:
        p = Path(custom_path.strip('"'))
        if p.is_dir():
            p = p / SERVER_EXE
        if not p.is_file():
            raise GpuEngineError(f"whisper-server introuvable : {p}")
        return p
    if RUNTIME_MARKER.exists() and (BIN_DIR / SERVER_EXE).exists():
        return BIN_DIR / SERVER_EXE
    if MSYS2_HOME_EXE.exists():
        return MSYS2_HOME_EXE
    return None


# ─── models ───────────────────────────────────────────────────────────────────
def model_path(model_id: str) -> Path:
    """Where the ggml weights for model_id live (a custom .bin path is used as is)."""
    if model_id in GGML_MODELS:
        return MODELS_DIR / GGML_MODELS[model_id].rsplit("/", 1)[-1]
    if model_id.startswith(("http://", "https://")):
        return MODELS_DIR / model_id.split("?")[0].rsplit("/", 1)[-1]
    return Path(model_id.strip('"'))


def is_downloaded(model_id: str) -> bool:
    try:
        return model_path(model_id).is_file()
    except Exception:
        return False


def ensure_model(model_id: str, progress: ProgressFn | None = None, what: str = "") -> Path:
    path = model_path(model_id)
    if path.is_file():
        return path
    if model_id in GGML_MODELS:
        url = GGML_MODELS[model_id]
    elif model_id.startswith(("http://", "https://")):
        url = model_id
    else:
        raise GpuEngineError("Sur la carte graphique, « Autre modèle » doit être un fichier ggml (.bin) "
                             "ou son adresse https.")
    try:
        _download(url, path, progress, what or model_id)
    except requests.RequestException as exc:
        raise GpuEngineError(f"Téléchargement du modèle impossible ({exc}).") from exc
    return path


def ensure_vad() -> Path | None:
    path = MODELS_DIR / VAD_MODEL_URL.rsplit("/", 1)[-1]
    if not path.is_file():
        try:
            _download(VAD_MODEL_URL, path)
        except Exception as exc:
            log.warning("VAD model download failed, continuing without VAD: %s", exc)
            return None
    return path


# ─── server process ───────────────────────────────────────────────────────────
def parse_vulkan_devices(log_text: str) -> dict[int, tuple[str, bool]]:
    """{index: (name, is_integrated)} from ggml-vulkan's start-up lines."""
    cards = {}
    for m in re.finditer(r"ggml_vulkan: (\d+) = (.+?) \| uma: (\d)", log_text):
        name = re.sub(r"\s*\([^)]*\)\s*$", "", m.group(2)).strip()
        cards[int(m.group(1))] = (name, m.group(3) == "1")
    return cards


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _tail(path: Path, n: int = 12) -> str:
    try:
        return "\n".join(path.read_text("utf-8", "replace").splitlines()[-n:])
    except OSError:
        return ""


class WhisperCppEngine:
    """Same interface as LocalWhisper: load() then transcribe()."""

    requested = "gpu"

    def __init__(self, model_id: str, server_path: str = "", progress: ProgressFn | None = None):
        self.model_id = model_id
        self.server_path = server_path
        self.progress = progress
        self.device = "gpu"
        self.gpu_name = ""
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self._log_fh = None
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def load(self) -> None:
        exe = find_server(self.server_path)
        if exe is None:
            exe = install_runtime(self.progress)
        model = ensure_model(self.model_id, self.progress)
        vad = ensure_vad()
        self._start(exe, model, vad)
        better = self._detect_device()
        if better is not None:
            # whisper.cpp took the processor's integrated graphics: restart on the real card.
            log.info("Switching whisper.cpp to Vulkan device %d", better)
            self.close()
            self._start(exe, model, vad, gpu_index=better)
            self._detect_device(gpu_index=better)
        self._warm_up()

    def _start(self, exe: Path, model: Path, vad: Path | None, gpu_index: int = 0) -> None:
        self.port = _free_port()
        threads = max(4, min(8, (os.cpu_count() or 4) // 2))
        cmd = [str(exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(self.port),
               "-l", "auto", "-t", str(threads), "-nt"]
        if gpu_index:
            cmd += ["-dev", str(gpu_index)]
        if vad is not None:
            cmd += ["--vad", "-vm", str(vad)]
        WHISPERCPP_DIR.mkdir(parents=True, exist_ok=True)
        self._log_fh = open(SERVER_LOG, "w", encoding="utf-8", errors="replace")
        env = dict(os.environ)
        env["PATH"] = str(exe.parent) + os.pathsep + env.get("PATH", "")
        log.info("Starting %s", " ".join(cmd))
        self.proc = subprocess.Popen(
            cmd, cwd=str(exe.parent), env=env, stdin=subprocess.DEVNULL,
            stdout=self._log_fh, stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            from .winutil import kill_with_parent
            kill_with_parent(self.proc)
        except Exception as exc:
            log.debug("Job object unavailable: %s", exc)

        deadline = time.monotonic() + 240     # the first Vulkan start can be slow
        while time.monotonic() < deadline:
            rc = self.proc.poll()
            if rc is not None:
                self._log_fh.flush()
                tail = _tail(SERVER_LOG)
                log.error("whisper-server exited (%s):\n%s", rc, tail)
                self.close()
                if rc in (-1073741515, 3221225781):   # STATUS_DLL_NOT_FOUND
                    raise GpuEngineError("Une DLL manque au moteur GPU. Supprime data/whispercpp/bin et relance.")
                raise GpuEngineError("Le moteur GPU s'est arrêté au démarrage (voir data/whispercpp/server.log).")
            try:
                if requests.get(self.url + "/health", timeout=2).ok:
                    return
            except requests.RequestException:
                pass
            time.sleep(0.25)
        self.close()
        raise GpuEngineError("Le moteur GPU ne répond pas (voir data/whispercpp/server.log).")

    def _detect_device(self, gpu_index: int = 0) -> int | None:
        """Read the server log: which device is used. Returns a better Vulkan
        device index when an integrated GPU was picked over a dedicated card."""
        self._log_fh.flush()
        text = _tail(SERVER_LOG, 400)
        cards = parse_vulkan_devices(text)
        if gpu_index in cards:
            self.gpu_name = cards[gpu_index][0]
        if re.search(r"using (Vulkan|CUDA|ROCm|SYCL)\d* backend", text):
            self.device = "gpu"
            log.info("whisper.cpp on GPU: %s", self.gpu_name or "?")
            if gpu_index in cards and cards[gpu_index][1]:          # integrated graphics
                dedicated = [i for i, (_, uma) in sorted(cards.items()) if not uma]
                if dedicated:
                    return dedicated[0]
        elif "no GPU found" in text:
            self.device = "cpu"
            log.warning("whisper.cpp found no usable GPU, running on CPU")
        return None

    def _warm_up(self) -> None:
        """First inference builds the Vulkan pipelines: do it now, not on the first dictation."""
        try:
            silence = np.zeros(16000, dtype=np.float32)
            self._post(silence, None, "", 1, extra={"vad": "false"}, timeout=120)
        except Exception as exc:
            log.debug("Warm-up failed: %s", exc)

    def _post(self, audio: np.ndarray, language: str | None, prompt: str, beam_size: int,
              extra: dict | None = None, timeout: int = 120) -> str:
        from .engines import to_wav
        data = {"response_format": "json", "temperature": "0.0", "no_timestamps": "true",
                "language": language or "auto", "beam_size": str(max(1, int(beam_size or 1)))}
        if prompt:
            data["prompt"] = prompt
        if extra:
            data.update(extra)
        files = {"file": ("dictation.wav", to_wav(audio), "audio/wav")}
        resp = requests.post(self.url + "/inference", data=data, files=files, timeout=timeout)
        if not resp.ok:
            raise GpuEngineError(f"Moteur GPU : erreur {resp.status_code} ({resp.text[:160]})")
        try:
            return (resp.json().get("text") or "").strip()
        except ValueError:
            return resp.text.strip()

    def transcribe(self, audio: np.ndarray, language: str | None, prompt: str, beam_size: int) -> str:
        with self._lock:
            if self.proc is None or self.proc.poll() is not None:
                raise GpuEngineError("Le moteur GPU s'est arrêté. Rechoisis le modèle pour le relancer.")
            try:
                text = self._post(audio, language, prompt, beam_size)
            except requests.RequestException as exc:
                raise GpuEngineError(f"Moteur GPU injoignable ({exc}).") from exc
        # whisper.cpp keeps Whisper's segment spacing: normalise it.
        return re.sub(r"\s+", " ", text).strip()

    def close(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if self._log_fh is not None:
            try:
                self._log_fh.close()
            except OSError:
                pass
            self._log_fh = None
