"""Voz do assistente: transcrição (faster-whisper), palavra de ativação e fala (Edge TTS) em pt-BR."""
from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
import unicodedata

import numpy as np

from .audio import Player, decode_mp3

log = logging.getLogger(__name__)

# Frases que o Whisper costuma "alucinar" em áudio sem fala.
HALLUCINATIONS = ("amara.org", "legendas pela comunidade", "obrigado por assistir", "inscreva-se", "legendado por")


class Transcriber:
    def __init__(self, model_size: str, device: str, name: str):
        self.model_size = model_size
        self.device = device
        # O nome no prompt inicial ensina o Whisper a escrevê-lo do jeito certo.
        self.initial_prompt = f"{name.title()}, abra o navegador e pesquise a previsão do tempo."
        self.model = None

    def load(self) -> None:
        from faster_whisper import WhisperModel

        compute = "int8" if self.device == "cpu" else "float16"
        self.model = WhisperModel(self.model_size, device=self.device, compute_type=compute)

    def transcribe(self, audio: np.ndarray) -> str:
        if self.model is None:
            self.load()
        segments, _ = self.model.transcribe(
            audio,
            language="pt",
            beam_size=1,
            vad_filter=True,
            initial_prompt=self.initial_prompt,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        if any(h in text.lower() for h in HALLUCINATIONS):
            return ""
        # Em áudio só com ruído o Whisper às vezes repete o prompt inicial.
        if len(text) > 12 and _fold(text).strip(" .") in _fold(self.initial_prompt):
            return ""
        return text


GREETINGS = {"ei", "ey", "hey", "oi", "ola", "ok", "okay", "e ai", "fala", "alo", "bom dia", "boa tarde", "boa noite"}


def _fold(text: str) -> str:
    """Minúsculas sem acento, mantendo o tamanho do texto (posições continuam valendo no original)."""
    return "".join(unicodedata.normalize("NFKD", c)[0] for c in text.lower())


def wake_pattern(name: str) -> re.Pattern:
    """Aceita as grafias que o Whisper costuma usar para o nome (Vektor → Vector, Vetor)."""
    n = _fold(name)
    variants = {n, n.replace("k", "c"), n.replace("k", ""), n.replace("k", "qu")}
    alternatives = "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
    return re.compile(rf"\b({alternatives})\b")


def split_wake(text: str, pattern: re.Pattern) -> str | None:
    """Se a fala chama o assistente pelo nome, devolve o pedido que vem depois ('' se só chamou)."""
    folded = _fold(text)
    match = pattern.search(folded)
    if not match:
        return None
    # O nome precisa abrir a frase ("o vetor da matriz" não é um chamado).
    before = folded[: match.start()].strip(" ,.!?-")
    if before and before not in GREETINGS:
        return None
    return text[match.end() :].strip(" ,.!?:;-–")


YES = {"sim", "pode", "confirmo", "confirma", "claro", "ok", "okay", "manda", "vai", "autorizo",
       "positivo", "isso", "faz", "faca", "executa", "execute", "beleza", "certo", "bora"}
NO = {"nao", "cancela", "cancelar", "cancele", "negativo", "para", "pare", "espera", "nunca", "jamais"}


def parse_yes_no(text: str) -> bool | None:
    """Interpreta uma resposta falada de confirmação. None se não der para saber."""
    words = re.findall(r"[a-z]+", _fold(text))
    if any(w in NO for w in words):
        return False
    if any(w in YES for w in words):
        return True
    return None


def clean_for_speech(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "o link", text)
    text = re.sub(r"^\s*(?:[-•*]|\d+\.)\s+", "", text, flags=re.M)
    text = re.sub(r"[*_#`>|~]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str, limit: int = 220) -> list[str]:
    """Quebra o texto em trechos curtos; o primeiro sai rápido para a fala começar logo."""
    sentences = [s for s in re.split(r"(?<=[.!?…;:])\s+", text) if s.strip()]
    chunks: list[str] = []
    for s in sentences:
        if len(chunks) > 1 and len(chunks[-1]) + len(s) < limit:
            chunks[-1] += " " + s
        else:
            chunks.append(s)
    return chunks


class Speaker:
    def __init__(self, voice: str, rate: str, pitch: str, player: Player):
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.player = player
        self._cache: dict[str, np.ndarray] = {}

    def prepare(self, text: str) -> None:
        """Sintetiza uma frase curta com antecedência, para tocar sem atraso."""
        self._cache[text] = decode_mp3(self._synthesize(text))

    def _synthesize(self, text: str) -> bytes:
        import edge_tts

        async def run() -> bytes:
            comm = edge_tts.Communicate(text, self.voice, rate=self.rate, pitch=self.pitch)
            audio = bytearray()
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    audio.extend(chunk["data"])
            return bytes(audio)

        return asyncio.run(run())

    def speak(self, text: str, cancel: threading.Event) -> None:
        if text in self._cache:
            self.player.reset()
            self.player.play(self._cache[text], 24000)
            return
        chunks = split_sentences(clean_for_speech(text))
        if not chunks:
            return
        ready: queue.Queue = queue.Queue()

        def produce() -> None:
            for chunk in chunks:
                if cancel.is_set() or self.player.stopped:
                    break
                try:
                    ready.put(decode_mp3(self._synthesize(chunk)))
                except Exception as e:
                    ready.put(e)
                    return
            ready.put(None)

        self.player.reset()
        threading.Thread(target=produce, daemon=True).start()
        while True:
            item = ready.get()
            if item is None or cancel.is_set() or self.player.stopped:
                break
            if isinstance(item, Exception):
                raise item
            self.player.play(item, 24000)
