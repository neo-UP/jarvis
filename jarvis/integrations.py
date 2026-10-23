"""Integrações com outras plataformas pelo MCP (Model Context Protocol).

Os servidores ficam em dados/mcp.json, no mesmo formato do Claude Desktop:

    {"mcpServers": {
        "nome": {"command": "npx", "args": ["-y", "pacote"], "env": {"CHAVE": "${SEGREDO_DO_ENV}"}},
        "remoto": {"url": "https://servidor/mcp", "headers": {"Authorization": "Bearer ${TOKEN}"}}
    }}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import threading
from contextlib import AsyncExitStack
from typing import Callable

from .config import DATA_DIR, LOG_DIR
from .tools import expand_secrets

log = logging.getLogger(__name__)

CONFIG_PATH = DATA_DIR / "mcp.json"
EXAMPLE = {
    "mcpServers": {
        "hora": {
            "command": "python",
            "args": ["-m", "mcp_server_time", "--local-timezone=America/Sao_Paulo"],
            "disabled": True,
        },
        "exemplo_remoto": {
            "url": "https://seu-servidor.exemplo/mcp",
            "headers": {"Authorization": "Bearer ${TOKEN_DO_SERVIDOR}"},
            "disabled": True,
        },
    }
}


def exposed_name(server: str, tool: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", f"{server}__{tool}")[:64]


class McpHub:
    def __init__(self, report: Callable[[str], None]):
        self.report = report
        self.tools: dict[str, tuple[str, str]] = {}  # nome exposto → (servidor, ferramenta)
        self.schemas: list[dict] = []
        self.servers: list[str] = []
        self.ready = threading.Event()
        self._sessions: dict = {}
        self._stack: AsyncExitStack | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        if not CONFIG_PATH.exists():
            CONFIG_PATH.write_text(json.dumps(EXAMPLE, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            servers = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("mcpServers", {})
        except ValueError as e:
            self.report(f"mcp.json inválido: {e}")
            servers = {}
        active = {k: v for k, v in servers.items() if not v.get("disabled")}
        if not active:
            self.ready.set()
            return
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True, name="mcp").start()
        asyncio.run_coroutine_threadsafe(self._connect_all(active), self._loop)

    async def _connect_all(self, servers: dict) -> None:
        self._stack = AsyncExitStack()
        for name, spec in servers.items():
            try:
                await asyncio.wait_for(self._connect(name, spec), timeout=90)
                self.servers.append(name)
            except Exception as e:
                log.exception("Falha ao conectar a integração %s", name)
                self.report(f"Integração {name} falhou: {e}")
        if self.servers:
            self.report(f"Integrações: {', '.join(self.servers)} ({len(self.tools)} ferramentas)")
        self.ready.set()

    async def _connect(self, name: str, spec: dict) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        if "url" in spec:
            import httpx2
            from mcp.client.streamable_http import streamable_http_client

            headers = {k: expand_secrets(str(v)) for k, v in spec.get("headers", {}).items()}
            client = httpx2.AsyncClient(headers=headers, timeout=httpx2.Timeout(60, read=300))
            streams = await self._stack.enter_async_context(
                streamable_http_client(expand_secrets(spec["url"]), http_client=client)
            )
        else:
            command = spec["command"]
            if command in ("python", "python3"):
                command = sys.executable  # o Python do assistente, com os pacotes dele
            command = shutil.which(command) or command  # npx → npx.cmd no Windows
            env = {**os.environ, **{k: expand_secrets(str(v)) for k, v in spec.get("env", {}).items()}}
            params = StdioServerParameters(command=command, args=[expand_secrets(a) for a in spec.get("args", [])], env=env)
            errlog = open(LOG_DIR / "mcp.log", "a", encoding="utf-8")
            streams = await self._stack.enter_async_context(stdio_client(params, errlog=errlog))

        session = await self._stack.enter_async_context(ClientSession(streams[0], streams[1]))
        await session.initialize()
        listed = await session.list_tools()
        for tool in listed.tools:
            exposed = exposed_name(name, tool.name)
            self.tools[exposed] = (name, tool.name)
            schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
            self.schemas.append(
                {
                    "name": exposed,
                    "description": f"[{name}] {(tool.description or tool.name)[:900]}",
                    "input_schema": schema or {"type": "object", "properties": {}},
                }
            )
        self._sessions[name] = session

    def call(self, exposed: str, args: dict, timeout: float = 300) -> str:
        server, tool = self.tools[exposed]
        future = asyncio.run_coroutine_threadsafe(self._sessions[server].call_tool(tool, args), self._loop)
        result = future.result(timeout)
        parts = []
        for item in result.content:
            if getattr(item, "type", "") == "text":
                parts.append(item.text)
            else:
                parts.append(f"[{getattr(item, 'type', 'conteúdo')}]")
        text = "\n".join(parts)[:15000] or "(sem conteúdo)"
        is_error = getattr(result, "isError", None) or getattr(result, "is_error", False)
        if is_error:
            raise RuntimeError(text)
        return text
