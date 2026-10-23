"""Microfone (gravação com detecção de fim de fala) e alto-falante."""
from __future__ import annotations

import io
import queue
import threading
from typing import Callable

import numpy as np
import sounddevice as sd

MIC_RATE = 16000
MIC_BLOCK = 480  # 30 ms


class Recorder:
    def __init__(self, on_level: Callable[[float], None], threshold: float = 0.0):
        self.on_level = on_level
        self.threshold = threshold

    def record(
        self,
        stop: threading.Event,
        cancel: threading.Event,
        silence_s: float = 1.0,
        wait_s: float = 7.0,
        max_s: float = 30.0,
        background: bool = False,
    ) -> np.ndarray | None:
        """Grava até a pessoa parar de falar. Devolve áudio float32 16 kHz, ou None.

        Em segundo plano (escuta do nome), não mexe no medidor do HUD e descarta o áudio
        quando `stop` interrompe a escuta.
        """
        blocks: queue.Queue[np.ndarray] = queue.Queue()

        def callback(indata, frames, time_info, status):
            blocks.put(indata[:, 0].copy())

        chunks: list[np.ndarray] = []
        noise: list[float] = []
        speech = False
        voiced_run = 0
        silent = 0.0
        elapsed = 0.0
        block_s = MIC_BLOCK / MIC_RATE

        with sd.InputStream(samplerate=MIC_RATE, channels=1, dtype="float32", blocksize=MIC_BLOCK, callback=callback):
            while True:
                if cancel.is_set() or (background and stop.is_set()):
                    return None
                if stop.is_set():
                    break
                try:
                    block = blocks.get(timeout=0.3)
                except queue.Empty:
                    continue
                chunks.append(block)
                elapsed += block_s
                rms = float(np.sqrt(np.mean(block**2)))
                if not background:
                    self.on_level(min(1.0, rms * 14))

                if len(noise) < 10:
                    noise.append(rms)
                    continue
                threshold = self.threshold or min(0.03, max(0.008, float(np.median(noise)) * 3))
                if rms > threshold:
                    voiced_run += 1
                    silent = 0.0
                    if voiced_run >= 3:
                        speech = True
                else:
                    voiced_run = 0
                    if speech:
                        silent += block_s
                    else:
                        noise.append(rms)

                if speech and silent >= silence_s:
                    break
                if not speech and elapsed >= wait_s:
                    return None
                if elapsed >= max_s:
                    break

        if not chunks or elapsed < 0.4:
            return None
        # Parada manual sem fala detectada ainda vai para a transcrição: o limiar pode ter errado.
        return np.concatenate(chunks)


class Player:
    def __init__(self, on_level: Callable[[float], None]):
        self.on_level = on_level
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def reset(self) -> None:
        self._stop.clear()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def play(self, pcm: np.ndarray, rate: int) -> None:
        step = rate // 25
        with sd.OutputStream(samplerate=rate, channels=1, dtype="int16") as out:
            for i in range(0, len(pcm), step):
                if self._stop.is_set():
                    break
                chunk = pcm[i : i + step]
                out.write(chunk.reshape(-1, 1))
                rms = float(np.sqrt(np.mean((chunk.astype(np.float32) / 32768) ** 2)))
                self.on_level(min(1.0, rms * 6))
        self.on_level(0.0)


def decode_mp3(data: bytes, rate: int = 24000) -> np.ndarray:
    import av

    parts: list[np.ndarray] = []
    with av.open(io.BytesIO(data)) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                parts.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            parts.append(out.to_ndarray().reshape(-1))
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)
