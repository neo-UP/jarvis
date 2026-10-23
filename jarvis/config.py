"""Configuração do Jarvis, lida do arquivo .env na raiz do projeto."""
from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv, set_key

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
WORKSPACE = ROOT / "workspace"
DATA_DIR = ROOT / "dados"
LOG_DIR = ROOT / "logs"

for _d in (WORKSPACE, DATA_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Config:
    name: str
    wake_word: bool
    autonomy: str
    followup_seconds: float
    brain: str
    ollama_url: str
    ollama_model: str
    ollama_vision_model: str
    api_key: str
    model: str
    effort: str
    hotkey: str
    voice: str
    voice_rate: str
    voice_pitch: str
    whisper_model: str
    whisper_device: str
    user_name: str
    form_of_address: str
    silence_seconds: float
    mic_threshold: float


def load_config() -> Config:
    load_dotenv(ENV_PATH, override=True)
    return Config(
        name=_get("JARVIS_NOME_ASSISTENTE", "VEKTOR").upper(),
        wake_word=_get("JARVIS_ESCUTA_CONTINUA", "1") not in ("0", "nao", "não", "false"),
        autonomy=_get("JARVIS_AUTONOMIA", "total").lower(),
        followup_seconds=float(_get("JARVIS_ESPERA_RESPOSTA_SEGUNDOS", "8")),
        brain=_get("JARVIS_CEREBRO", "ollama").lower(),
        ollama_url=_get("JARVIS_OLLAMA_URL", "http://localhost:11434"),
        ollama_model=_get("JARVIS_OLLAMA_MODELO", "qwen3:8b"),
        ollama_vision_model=_get("JARVIS_OLLAMA_VISAO", "llama3.2-vision"),
        api_key=_get("ANTHROPIC_API_KEY"),
        model=_get("JARVIS_MODELO", "claude-opus-5-5"),
        effort=_get("JARVIS_ESFORCO", "low"),
        hotkey=_get("JARVIS_ATALHO", "ctrl+alt+j"),
        voice=_get("JARVIS_VOZ", "pt-BR-AntonioNeural"),
        voice_rate=_get("JARVIS_VOZ_VELOCIDADE", "+8%"),
        voice_pitch=_get("JARVIS_VOZ_TOM", "-4Hz"),
        whisper_model=_get("JARVIS_WHISPER_MODELO", "small"),
        whisper_device=_get("JARVIS_WHISPER_DISPOSITIVO", "cpu"),
        user_name=_get("JARVIS_NOME_USUARIO"),
        form_of_address=_get("JARVIS_TRATAMENTO"),
        silence_seconds=float(_get("JARVIS_SILENCIO_SEGUNDOS", "1.0")),
        mic_threshold=float(_get("JARVIS_LIMIAR_MICROFONE", "0")),
    )


def save_api_key(key: str) -> None:
    if not ENV_PATH.exists():
        ENV_PATH.write_text("", encoding="utf-8")
    set_key(str(ENV_PATH), "ANTHROPIC_API_KEY", key)
    os.environ["ANTHROPIC_API_KEY"] = key


def _known_folder(csidl: int, fallback: Path) -> Path:
    buf = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0:
        return Path(buf.value)
    return fallback


HOME = Path.home()
DESKTOP = _known_folder(0x10, HOME / "Desktop")
DOCUMENTS = _known_folder(0x05, HOME / "Documents")
DOWNLOADS = HOME / "Downloads"
