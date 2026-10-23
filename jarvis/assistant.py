"""Orquestra o ciclo ouvir → transcrever → pensar → agir → falar."""
from __future__ import annotations

import logging
import queue
import threading

from PyQt6.QtCore import QObject, pyqtSignal

from .audio import Player, Recorder
from .brain import Brain, BrainError
from .brain_ollama import OllamaBrain
from .config import Config, save_api_key
from .integrations import McpHub
from .speech import Speaker, Transcriber, parse_yes_no, split_wake, wake_pattern
from .tools import ToolBox

log = logging.getLogger(__name__)


class Assistant(QObject):
    state_changed = pyqtSignal(str)
    level_changed = pyqtSignal(float)
    heard = pyqtSignal(str)
    replied = pyqtSignal(str)
    activity = pyqtSignal(str)
    confirm_requested = pyqtSignal(str)
    confirm_answered = pyqtSignal()
    key_missing = pyqtSignal()

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.jobs: queue.Queue = queue.Queue()
        self.recorder = Recorder(self.level_changed.emit, cfg.mic_threshold)
        self.player = Player(self.level_changed.emit)
        self.speaker = Speaker(cfg.voice, cfg.voice_rate, cfg.voice_pitch, self.player)
        self.stt = Transcriber(cfg.whisper_model, cfg.whisper_device, cfg.name)
        self.wake = wake_pattern(cfg.name)
        self.ack = "Sim?"
        self.hub = McpHub(self.activity.emit)
        self.toolbox = ToolBox(self._confirm, self.activity.emit, cfg.autonomy, self.hub)
        self.brain: Brain | OllamaBrain | None = None
        self.state = "inicializando"
        self._lock = threading.Lock()
        self._listening = False
        self._busy = False
        self._listen_stop = threading.Event()
        self._cancel = threading.Event()
        self._wake_stop = threading.Event()
        self._never = threading.Event()
        self._confirm_done = threading.Event()
        self._confirm_answer = False

    # ── API usada pela interface (qualquer thread) ────────────────────────
    def start(self) -> None:
        self.toolbox.preload()
        self.hub.start()
        threading.Thread(target=self._run, daemon=True, name="jarvis-worker").start()
        try:
            import keyboard

            keyboard.add_hotkey(self.cfg.hotkey, self.toggle_listen)
        except Exception:
            log.exception("Não consegui registrar o atalho global %s", self.cfg.hotkey)
            self.activity.emit(f"Atalho {self.cfg.hotkey} indisponível")

    def toggle_listen(self) -> None:
        with self._lock:
            if self._listening:
                self._listen_stop.set()
                return
            if self.state == "inicializando":
                return
            if self._busy or self.state == "falando":
                self.stop()
            self._enqueue("voz")

    def submit_text(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        with self._lock:
            if self._busy or self.state == "falando":
                self.stop()
            self._enqueue("texto", text)

    def stop(self) -> None:
        self._cancel.set()
        self._listen_stop.set()
        self.player.stop()

    def new_conversation(self) -> None:
        self.stop()
        self._enqueue("reset")

    def _enqueue(self, kind: str, payload: str | None = None) -> None:
        self.jobs.put((kind, payload))
        self._wake_stop.set()  # libera o microfone se ele estiver esperando o nome

    def set_api_key(self, key: str) -> None:
        save_api_key(key)
        self.cfg.api_key = key
        self.brain = None

    def answer_confirm(self, ok: bool) -> None:
        if self._confirm_done.is_set():  # já respondido por voz
            return
        self._confirm_answer = ok
        self._confirm_done.set()

    # ── Thread de trabalho ────────────────────────────────────────────────
    def _set_state(self, state: str) -> None:
        self.state = state
        self.state_changed.emit(state)

    def _confirm(self, question: str) -> bool:
        """Pede confirmação na tela e por voz; vale o que vier primeiro (sim/não falado ou clique)."""
        self._confirm_answer = False
        self._confirm_done.clear()
        previous = self.state
        self.confirm_requested.emit(question)
        self._say("Essa ação não tem volta. Posso executar? Diga sim ou não.")
        self._set_state("aguardando")
        for _ in range(3):
            if self._confirm_done.is_set() or self._cancel.is_set():
                break
            audio = self.recorder.record(self._confirm_done, self._cancel, silence_s=0.8, wait_s=10, background=True)
            answer = parse_yes_no(self.stt.transcribe(audio)) if audio is not None else None
            if answer is not None and not self._confirm_done.is_set():
                self._confirm_answer = answer
                self._confirm_done.set()
                self.confirm_answered.emit()
        self._confirm_done.wait(timeout=120)
        self.confirm_answered.emit()
        self._set_state(previous)
        self.activity.emit("Confirmado" if self._confirm_answer else "Cancelado")
        return self._confirm_answer

    def _run(self) -> None:
        self._set_state("inicializando")
        self.activity.emit("Carregando reconhecimento de voz")
        try:
            self.stt.load()
            self.activity.emit("Reconhecimento de voz pronto")
        except Exception as e:
            log.exception("Falha ao carregar o Whisper")
            self.activity.emit(f"Falha na voz: {e}")
        if self.cfg.brain == "ollama":
            try:
                self.brain = OllamaBrain(self.cfg, self.toolbox)
                self.brain.ensure_ready(self.activity.emit)
            except BrainError as e:
                self.activity.emit(str(e))
            except Exception as e:
                log.exception("Falha ao preparar o Ollama")
                self.activity.emit(f"Falha no Ollama: {e}")
        elif not self.cfg.api_key:
            self.key_missing.emit()
        name = self.cfg.name.title()
        try:
            self.speaker.prepare(self.ack)
        except Exception:
            log.exception("Falha ao preparar a resposta curta")
        self._set_state("pronto")
        if self.cfg.wake_word:
            self.activity.emit(f'Escutando o nome "{name}"')
            self._say(f"{name} online. É só me chamar pelo nome.")
        else:
            self._say(f"{name} online. Como posso ajudar?")

        while True:
            try:
                kind, payload = self.jobs.get(timeout=0.05 if self.cfg.wake_word else None)
            except queue.Empty:
                heard = self._listen_for_name()
                if heard is None:
                    continue
                kind, payload = "chamado", heard
            self._execute(kind, payload)

    def _execute(self, kind: str, payload: str | None) -> None:
        self._cancel.clear()
        self._busy = True
        try:
            if kind == "voz":
                self._handle_voice()
            elif kind == "texto":
                self.heard.emit(payload)
                self._think_and_reply(payload)
            elif kind == "chamado":
                self.heard.emit(payload)
                if split_wake(payload, self.wake):
                    self._think_and_reply(payload)
                else:
                    # Só chamou pelo nome: responde e escuta o pedido.
                    self._say(self.ack)
                    self._handle_voice()
            elif kind == "reset":
                if self.brain:
                    self.brain.reset()
                self.activity.emit("Nova conversa")
            self._set_state("pronto")
        except Exception as e:
            log.exception("Erro no ciclo do assistente")
            self.activity.emit(f"Erro: {e}")
            self._set_state("erro")
        finally:
            self._busy = False

    def _listen_for_name(self) -> str | None:
        """Escuta o ambiente até alguém falar; devolve a frase se ela começar com o nome."""
        self._wake_stop.clear()
        if not self.jobs.empty():
            return None
        try:
            audio = self.recorder.record(
                self._wake_stop, self._never, silence_s=0.8, wait_s=10, max_s=15, background=True
            )
        except Exception as e:
            log.exception("Microfone indisponível para a escuta do nome")
            self.activity.emit(f"Microfone indisponível: {e}")
            self._wake_stop.wait(10)
            return None
        if audio is None:
            return None
        text = self.stt.transcribe(audio)
        if not text or split_wake(text, self.wake) is None:
            if text:
                log.debug("Ignorado (sem o nome): %s", text)
            return None
        return text

    def _handle_voice(self) -> None:
        self._listen_stop.clear()
        self._listening = True
        self._set_state("ouvindo")
        try:
            audio = self.recorder.record(self._listen_stop, self._cancel, self.cfg.silence_seconds)
        finally:
            self._listening = False
            self.level_changed.emit(0.0)
        if audio is None or self._cancel.is_set():
            if not self._cancel.is_set():
                self.activity.emit("Não ouvi nada")
            return
        self._set_state("processando")
        text = self.stt.transcribe(audio)
        if not text:
            self.activity.emit("Não entendi o áudio")
            return
        self.heard.emit(text)
        self._think_and_reply(text)

    def _think_and_reply(self, text: str) -> None:
        if self.cfg.brain == "claude" and not self.cfg.api_key:
            self.key_missing.emit()
            self._say("Preciso da sua chave da API da Anthropic para pensar.")
            return
        if self.brain is None:
            if self.cfg.brain == "claude":
                self.brain = Brain(self.cfg, self.toolbox)
            else:
                self.brain = OllamaBrain(self.cfg, self.toolbox)
        self._set_state("processando")
        try:
            reply = self.brain.ask(text, self._cancel, lambda: self._set_state("executando"))
        except BrainError as e:
            self._set_state("erro")
            self.replied.emit(str(e))
            self._say(str(e))
            return
        if self._cancel.is_set() or not reply:
            return
        self.replied.emit(reply)
        self._say(reply)
        # Se terminou com uma pergunta, escuta a resposta sem precisar do nome.
        if not self._cancel.is_set() and "?" in reply[-150:]:
            answer = self._listen_follow_up()
            if answer:
                self._think_and_reply(answer)

    def _listen_follow_up(self) -> str | None:
        self._listen_stop.clear()
        self._listening = True
        self._set_state("ouvindo")
        try:
            audio = self.recorder.record(
                self._listen_stop, self._cancel, self.cfg.silence_seconds, wait_s=self.cfg.followup_seconds
            )
        finally:
            self._listening = False
            self.level_changed.emit(0.0)
        if audio is None or self._cancel.is_set():
            return None
        self._set_state("processando")
        text = self.stt.transcribe(audio)
        if text:
            self.heard.emit(text)
        return text or None

    def _say(self, text: str) -> None:
        previous = self.state
        self._set_state("falando")
        try:
            self.speaker.speak(text, self._cancel)
        except Exception as e:
            log.exception("Falha no TTS")
            self.activity.emit(f"Falha na fala: {e}")
        if previous == "erro":
            self._set_state("erro")
