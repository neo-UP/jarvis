"""Cérebro local e gratuito: modelos do Ollama com function calling."""
from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Callable

from .brain import WEEKDAYS, BrainError, build_system_prompt
from .config import Config
from .tools import CREATE_NO_WINDOW, ToolBox, secret_names

log = logging.getLogger(__name__)

MAX_STEPS = 15
MAX_HISTORY = 40
OPTIONS = {"num_ctx": 8192, "temperature": 0.4}
KEEP_ALIVE = "30m"
VISION_PROMPT = (
    "Descreva em português, de forma objetiva, o que aparece nesta captura de tela: quais janelas e "
    "programas estão abertos, os textos importantes e os principais botões."
)


class OllamaBrain:
    def __init__(self, cfg: Config, toolbox: ToolBox):
        self.cfg = cfg
        self.toolbox = toolbox
        self.url = cfg.ollama_url.rstrip("/")
        self.model = cfg.ollama_model
        self._caps: dict[str, list[str]] = {}
        self.reset()

    def reset(self) -> None:
        hub = self.toolbox.hub
        prompt = build_system_prompt(
            self.cfg, local=True, integrations=hub.servers if hub else None, secrets=secret_names()
        )
        self.messages: list[dict] = [{"role": "system", "content": prompt}]

    # ── HTTP ──────────────────────────────────────────────────────────────
    def _request(self, path: str, payload: dict | None = None, timeout: float = 600):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.url + path, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET"
        )
        return urllib.request.urlopen(req, timeout=timeout)

    def _post(self, path: str, payload: dict, timeout: float = 600) -> dict:
        try:
            with self._request(path, payload, timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            log.error("Ollama %s: %s %s", path, e.code, detail)
            if e.code == 404:
                raise BrainError(f"O modelo {payload.get('model')} não está instalado no Ollama.")
            raise BrainError("O Ollama recusou o pedido. Os detalhes estão no log.")
        except (urllib.error.URLError, ConnectionError):
            raise BrainError("Não consegui falar com o Ollama. Verifique se ele está aberto.")
        except TimeoutError:
            raise BrainError("O modelo local demorou demais para responder.")

    def capabilities(self, model: str) -> list[str]:
        if model not in self._caps:
            try:
                self._caps[model] = self._post("/api/show", {"model": model}, 30).get("capabilities", [])
            except BrainError:
                self._caps[model] = []
        return self._caps[model]

    def _installed(self) -> list[str]:
        with self._request("/api/tags", timeout=5) as resp:
            return [m["name"] for m in json.loads(resp.read()).get("models", [])]

    # ── Preparação ────────────────────────────────────────────────────────
    def ensure_ready(self, report: Callable[[str], None]) -> None:
        """Garante que o Ollama está rodando, com o modelo baixado e carregado na memória."""
        try:
            installed = self._installed()
        except OSError:
            report("Iniciando o Ollama")
            subprocess.Popen(["ollama", "serve"], creationflags=CREATE_NO_WINDOW)
            for _ in range(30):
                time.sleep(0.5)
                try:
                    installed = self._installed()
                    break
                except OSError:
                    continue
            else:
                raise BrainError("Não consegui iniciar o Ollama.")

        names = set(installed) | {n.removesuffix(":latest") for n in installed}
        if self.model not in names:
            self._pull(report)
        if "tools" not in self.capabilities(self.model):
            report(f"{self.model} não suporta ferramentas")

        report(f"Carregando {self.model}")
        start = time.monotonic()
        # Uma resposta curta carrega o modelo e deixa o prompt de sistema e as ferramentas no cache.
        self._post(
            "/api/chat",
            self._payload(self.messages + [{"role": "user", "content": "Responda apenas: ok"}], num_predict=2),
        )
        report(f"Cérebro local pronto ({time.monotonic() - start:.0f}s)")

    def _pull(self, report: Callable[[str], None]) -> None:
        report(f"Baixando {self.model}")
        last = -10
        with self._request("/api/pull", {"model": self.model, "stream": True}, timeout=3600) as resp:
            for line in resp:
                event = json.loads(line)
                if event.get("error"):
                    raise BrainError(f"Falha ao baixar {self.model}: {event['error']}")
                total, done = event.get("total"), event.get("completed")
                if total and done:
                    pct = int(done * 100 / total)
                    if pct >= last + 10:
                        last = pct
                        report(f"Baixando {self.model}: {pct}%")

    # ── Conversa ──────────────────────────────────────────────────────────
    def _payload(self, messages: list[dict], **options) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": self.toolbox.ollama_tools(),
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "options": {**OPTIONS, **options},
        }
        if "thinking" in self.capabilities(self.model):
            payload["think"] = False
        return payload

    def _trim(self) -> None:
        if len(self.messages) <= MAX_HISTORY:
            return
        # Corta as conversas mais antigas, sempre começando num pedido do usuário.
        rest = self.messages[-MAX_HISTORY // 2 :]
        while rest and rest[0]["role"] != "user":
            rest.pop(0)
        self.messages = self.messages[:1] + rest

    def ask(self, text: str, cancel: threading.Event, on_tool: Callable[[], None]) -> str:
        self._trim()
        now = datetime.now()
        stamp = f"[{WEEKDAYS[now.weekday()]}, {now:%d/%m/%Y %H:%M}]"
        self.messages.append({"role": "user", "content": f"{stamp} {text}"})

        for _ in range(MAX_STEPS):
            msg = self._post("/api/chat", self._payload(self.messages))["message"]
            calls = msg.get("tool_calls") or []
            entry = {"role": "assistant", "content": msg.get("content", "")}
            if calls:
                entry["tool_calls"] = calls
            self.messages.append(entry)
            if cancel.is_set():
                return ""
            if not calls:
                return re.sub(r"(?s)<think>.*?</think>", "", msg.get("content", "")).strip()

            on_tool()
            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                log.info("Ferramenta %s %s", name, args)
                content, is_error = self.toolbox.run(name, args)
                self.messages.append(self._tool_message(name, content, is_error))
            if cancel.is_set():
                return ""

        return "Essa tarefa passou do número de passos que me permito. Parei por aqui."

    def _tool_message(self, name: str, content, is_error: bool) -> dict:
        if isinstance(content, str):
            return {"role": "tool", "tool_name": name, "content": ("Erro: " if is_error else "") + content}
        text = " ".join(b["text"] for b in content if b["type"] == "text")
        images = [b["source"]["data"] for b in content if b["type"] == "image"]
        if not images:
            return {"role": "tool", "tool_name": name, "content": text}
        if "vision" in self.capabilities(self.model):
            return {"role": "tool", "tool_name": name, "content": text, "images": images}
        return {"role": "tool", "tool_name": name, "content": f"{text}\n{self._describe(images[0])}"}

    def _describe(self, image_b64: str) -> str:
        """Modelo sem visão: pede ao modelo de visão local uma descrição em texto da imagem."""
        vision = self.cfg.ollama_vision_model
        if not vision or "vision" not in self.capabilities(vision):
            return "(O modelo atual não enxerga imagens e não há modelo de visão instalado.)"
        self.toolbox.log_activity("Analisando a tela (lento)")
        try:
            result = self._post(
                "/api/generate",
                {"model": vision, "prompt": VISION_PROMPT, "images": [image_b64], "stream": False, "keep_alive": 0},
                timeout=900,
            )
        except BrainError as e:
            return f"(Falha ao analisar a imagem: {e})"
        return "Descrição da tela: " + result.get("response", "").strip()
