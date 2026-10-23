"""Cérebro do Jarvis: conversa com o Claude e executa as ferramentas pedidas."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Callable

import anthropic

from .config import DESKTOP, DOCUMENTS, DOWNLOADS, WORKSPACE, Config
from .tools import ToolBox, load_memory, secret_names

log = logging.getLogger(__name__)

MAX_STEPS = 25
MAX_HISTORY = 80  # mensagens; acima disso a conversa recomeça do zero

WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


class BrainError(Exception):
    """Erro com uma mensagem pronta para ser falada ao usuário."""


def build_system_prompt(
    cfg: Config, local: bool = False, integrations: list[str] | None = None, secrets: list[str] | None = None
) -> str:
    if local:
        search = "pesquisar_web (tipo noticias para notícias; ler_pagina se os trechos não bastarem)"
        extra = (
            "\n- Para agir, CHAME a ferramenta de verdade; nunca escreva a chamada no texto nem finja que agiu."
            "\n- Responda só com a fala final, sem explicar seu raciocínio."
        )
    else:
        search, extra = "web_search", ""
    who = cfg.user_name or "seu usuário"
    if cfg.form_of_address:
        address = f"Trate o usuário por '{cfg.form_of_address}'."
    else:
        address = "Trate o usuário de forma neutra, sem pressupor gênero."
    memory = "\n".join(f"- {m}" for m in load_memory()) or "(vazia)"
    if cfg.autonomy == "total":
        autonomy = (
            "Você tem autonomia total neste computador: execute qualquer ação pedida sem pedir permissão,\n"
            "inclusive tarefas de vários passos (instalar programas, organizar arquivos, configurar o sistema).\n"
            "Só ações que destroem discos, o sistema ou pastas inteiras pedem confirmação, automaticamente."
        )
    else:
        autonomy = (
            "Não peça permissão para ações simples e reversíveis. Comandos de risco pedem confirmação\n"
            "automaticamente; nunca faça nada irreversível que não tenha sido pedido claramente."
        )
    links = ", ".join(integrations or []) or "nenhuma configurada"
    keys = ", ".join(f"${{{k}}}" for k in secrets or []) or "nenhum"
    name = cfg.name.title()
    return f"""Você é {name}, o assistente pessoal por voz de {who}, rodando num PC com Windows.
Personalidade: educado, espirituoso, confiante e direto, no estilo do JARVIS dos filmes do Homem de Ferro,
mas seu nome é {name}. {address}
O usuário chama você dizendo "{name}" no começo do pedido; a transcrição pode trazer seu nome escrito
errado (Vector, Vetor): ignore isso e atenda ao pedido.

Suas respostas são faladas em voz alta por um sintetizador:
- Responda sempre em português do Brasil, em frases curtas e naturais, normalmente de uma a três frases.
- Nada de markdown, listas, tabelas, emojis ou blocos de código na resposta. Não leia URLs em voz alta.
- Se o assunto pedir mais detalhe, resuma o essencial e ofereça aprofundar.

{autonomy}

Você age no computador com as ferramentas:
- Quando o pedido for uma ação, execute direto e confirme em poucas palavras ("Pronto, abri o Spotify.").
- Se faltar uma informação essencial, faça UMA pergunta curta terminando com "?". O usuário responde
  em seguida sem precisar dizer seu nome.
- Nunca responda fatos atuais de memória. Para clima use clima; para moedas e cripto use cotacao;
  para notícias, placares, preços e qualquer outro fato recente use {search}. Diga a fonte em poucas palavras.
- Para saber o que está na tela, use ver_tela. Para clicar, use as coordenadas da última captura.
- Para digitar num app, coloque-o em foco antes com focar_janela ou abrir_programa.
- Para criar um site, escreva arquivos completos, modernos e responsivos em sites/<nome-do-projeto>/
  e abra o index.html (escrever_arquivo com abrir=true). Depois diga em uma frase o que criou.
- Caminhos relativos são salvos em {WORKSPACE}. Pastas do usuário: Área de Trabalho {DESKTOP},
  Documentos {DOCUMENTS}, Downloads {DOWNLOADS}.
- Use lembrar quando o usuário pedir para guardar algo ou disser uma preferência duradoura.
- Para integrar com outras plataformas use as ferramentas das integrações (nomes no formato
  servidor__ferramenta) ou requisicao_http. Integrações ativas: {links}. Segredos disponíveis para
  requisicao_http: {keys}.{extra}

Cada mensagem do usuário começa com a data e a hora atuais entre colchetes. O texto vem de
reconhecimento de voz e pode ter erros de transcrição: interprete com bom senso.

Memória de longo prazo:
{memory}"""


class Brain:
    def __init__(self, cfg: Config, toolbox: ToolBox):
        self.cfg = cfg
        self.toolbox = toolbox
        self.client = anthropic.Anthropic(api_key=cfg.api_key, base_url="https://api.anthropic.com")
        self.reset()

    def reset(self) -> None:
        self.messages: list[dict] = []
        # O prompt de sistema fica fixo durante a conversa (cache e histórico só crescem no fim).
        hub = self.toolbox.hub
        self.system = build_system_prompt(
            self.cfg, integrations=hub.servers if hub else None, secrets=secret_names()
        )

    def _append_user(self, blocks: list[dict]) -> None:
        if self.messages and self.messages[-1]["role"] == "user":
            self.messages[-1]["content"].extend(blocks)
        else:
            self.messages.append({"role": "user", "content": blocks})

    def _create(self):
        kwargs = {}
        if not self.cfg.model.startswith("claude-haiku"):
            kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        return self.client.beta.messages.create(
            model=self.cfg.model,
            max_tokens=16000,
            system=self.system,
            messages=self.messages,
            tools=self.toolbox.claude_tools(),
            output_config={"effort": self.cfg.effort},
            cache_control={"type": "ephemeral"},
            **kwargs,
        )

    def ask(self, text: str, cancel: threading.Event, on_tool: Callable[[], None]) -> str:
        if len(self.messages) > MAX_HISTORY:
            log.info("Histórico longo; recomeçando a conversa")
            self.reset()
        now = datetime.now()
        stamp = f"[{WEEKDAYS[now.weekday()]}, {now:%d/%m/%Y %H:%M}]"
        self._append_user([{"type": "text", "text": f"{stamp} {text}"}])

        for _ in range(MAX_STEPS):
            try:
                response = self._create()
            except anthropic.AuthenticationError:
                raise BrainError("A chave da API da Anthropic foi recusada. Confira o arquivo ponto env.")
            except anthropic.PermissionDeniedError:
                raise BrainError("A chave da API não tem permissão para usar este modelo.")
            except anthropic.NotFoundError:
                raise BrainError(f"O modelo {self.cfg.model} não foi encontrado.")
            except anthropic.RateLimitError:
                raise BrainError("Atingi o limite de uso da API. Tente de novo em instantes.")
            except anthropic.APIStatusError as e:
                log.error("Erro da API: %s", e)
                if "credit balance" in str(e):
                    raise BrainError("Sua conta da Anthropic está sem créditos. Adicione créditos em Plans and Billing.")
                if e.status_code >= 500:
                    raise BrainError("Os servidores da Anthropic estão instáveis agora.")
                raise BrainError("A API recusou o pedido. Os detalhes estão no log.")
            except anthropic.APIConnectionError:
                raise BrainError("Estou sem conexão com a internet.")

            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason == "refusal":
                return "Desculpe, não posso ajudar com isso."
            if response.stop_reason != "tool_use":
                return "".join(b.text for b in response.content if b.type == "text").strip()

            on_tool()
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if cancel.is_set():
                    content, is_error = "Cancelado pelo usuário.", True
                else:
                    log.info("Ferramenta %s %s", block.name, block.input)
                    content, is_error = self.toolbox.run(block.name, dict(block.input))
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error}
                )
            self._append_user(results)
            if cancel.is_set():
                return ""

        return "Essa tarefa passou do número de passos que me permito. Parei por aqui."
