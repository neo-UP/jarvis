"""Ferramentas que o Jarvis usa para agir no PC."""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import difflib
import io
import json
import logging
import os
import re
import subprocess
import threading
import unicodedata
import webbrowser
from pathlib import Path
from typing import Callable

from .config import DATA_DIR, WORKSPACE

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000
MEMORY_FILE = DATA_DIR / "memoria.json"

TOOLS: list[dict] = [
    {
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": 5,
        "user_location": {"type": "approximate", "country": "BR", "timezone": "America/Sao_Paulo"},
    },
    {
        "name": "abrir_programa",
        "description": "Abre um programa ou app instalado no Windows pelo nome (ex.: 'Spotify', "
        "'Bloco de Notas', 'Calculadora', 'Google Chrome', 'Steam', 'WhatsApp'). Procura no Menu "
        "Iniciar, inclusive apps da Microsoft Store.",
        "input_schema": {
            "type": "object",
            "properties": {"nome": {"type": "string", "description": "Nome do programa."}},
            "required": ["nome"],
        },
    },
    {
        "name": "abrir_url",
        "description": "Abre um site, uma pesquisa ou um arquivo local no navegador padrão.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL completa ou caminho de arquivo."}},
            "required": ["url"],
        },
    },
    {
        "name": "executar_powershell",
        "description": "Executa um comando do PowerShell no PC e devolve a saída. Use para consultar "
        "informações do sistema, gerenciar arquivos, ajustar configurações e automações. Comandos "
        "que apagam, movem, sobrescrevem, encerram processos ou desligam o PC pedem confirmação ao "
        "usuário automaticamente. Tempo limite: 60 segundos.",
        "input_schema": {
            "type": "object",
            "properties": {"comando": {"type": "string"}},
            "required": ["comando"],
        },
    },
    {
        "name": "escrever_arquivo",
        "description": "Cria ou sobrescreve um arquivo de texto (HTML, CSS, JS, código, notas). "
        "Caminhos relativos ficam na pasta workspace do assistente. Cria as pastas que faltarem.",
        "input_schema": {
            "type": "object",
            "properties": {
                "caminho": {"type": "string"},
                "conteudo": {"type": "string"},
                "abrir": {"type": "boolean", "description": "Abrir o arquivo depois de salvar."},
            },
            "required": ["caminho", "conteudo"],
        },
    },
    {
        "name": "ler_arquivo",
        "description": "Lê um arquivo de texto do PC.",
        "input_schema": {
            "type": "object",
            "properties": {"caminho": {"type": "string"}},
            "required": ["caminho"],
        },
    },
    {
        "name": "listar_pasta",
        "description": "Lista arquivos e subpastas de uma pasta.",
        "input_schema": {
            "type": "object",
            "properties": {"caminho": {"type": "string"}},
            "required": ["caminho"],
        },
    },
    {
        "name": "ver_tela",
        "description": "Tira uma captura da tela principal e devolve a imagem. Use para responder "
        "sobre o que está na tela ou antes de clicar em algo.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "clicar",
        "description": "Clica num ponto da tela. As coordenadas são em pixels da ÚLTIMA imagem "
        "devolvida por ver_tela.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "botao": {"type": "string", "enum": ["esquerdo", "direito"]},
                "duplo": {"type": "boolean"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "teclado",
        "description": "Digita um texto ou pressiona um atalho na janela em foco. Exemplos de "
        "atalho: 'ctrl+s', 'alt+tab', 'enter', 'win+d'. Foque o app certo antes de digitar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "acao": {"type": "string", "enum": ["digitar", "atalho"]},
                "texto": {"type": "string"},
            },
            "required": ["acao", "texto"],
        },
    },
    {
        "name": "focar_janela",
        "description": "Traz para a frente a janela aberta cujo título contém o texto informado.",
        "input_schema": {
            "type": "object",
            "properties": {"titulo": {"type": "string"}},
            "required": ["titulo"],
        },
    },
    {
        "name": "controle_midia",
        "description": "Controla a mídia e o volume do Windows.",
        "input_schema": {
            "type": "object",
            "properties": {
                "acao": {
                    "type": "string",
                    "enum": ["tocar_pausar", "proxima", "anterior", "volume_mais", "volume_menos", "mudo"],
                },
                "vezes": {"type": "integer", "description": "Repetições (para volume). Padrão 1."},
            },
            "required": ["acao"],
        },
    },
    {
        "name": "status_sistema",
        "description": "Mostra o estado do PC: uso de CPU, memória, discos, bateria, tempo ligado e os "
        "processos que mais consomem memória.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "clima",
        "description": "Previsão do tempo atual e dos próximos dias para uma cidade (fonte: wttr.in).",
        "input_schema": {
            "type": "object",
            "properties": {"cidade": {"type": "string", "description": "Ex.: 'São Paulo', 'Mauá'."}},
            "required": ["cidade"],
        },
    },
    {
        "name": "cotacao",
        "description": "Cotação atual de moedas e criptomoedas em reais (fonte: AwesomeAPI). "
        "Ex.: 'USD-BRL', 'EUR-BRL', 'BTC-BRL'; várias separadas por vírgula.",
        "input_schema": {
            "type": "object",
            "properties": {"pares": {"type": "string"}},
            "required": ["pares"],
        },
    },
    {
        "name": "requisicao_http",
        "description": "Faz uma requisição HTTP para integrar com outras plataformas: APIs, webhooks do "
        "n8n/Zapier/Make, bot do Telegram, Discord etc. Use ${NOME} para inserir segredos guardados no "
        ".env (por exemplo ${TELEGRAM_TOKEN}); nunca peça nem fale o valor de um segredo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metodo": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
                "url": {"type": "string"},
                "cabecalhos": {"type": "object", "description": "Cabeçalhos HTTP."},
                "corpo": {"type": "string", "description": "Corpo da requisição (JSON como texto)."},
            },
            "required": ["metodo", "url"],
        },
    },
    {
        "name": "lembrar",
        "description": "Guarda na memória de longo prazo um fato ou preferência do usuário.",
        "input_schema": {
            "type": "object",
            "properties": {"fato": {"type": "string"}},
            "required": ["fato"],
        },
    },
    {
        "name": "esquecer",
        "description": "Remove da memória de longo prazo os itens que contêm o trecho informado.",
        "input_schema": {
            "type": "object",
            "properties": {"trecho": {"type": "string"}},
            "required": ["trecho"],
        },
    },
]

# Pesquisa na web para cérebros sem busca embutida (o Claude usa o web_search do servidor).
LOCAL_SEARCH_TOOLS: list[dict] = [
    {
        "name": "pesquisar_web",
        "description": "Pesquisa na internet (DuckDuckGo) e devolve títulos, links, datas e trechos. "
        "Use para notícias, placares, preços, lançamentos e qualquer fato recente.",
        "input_schema": {
            "type": "object",
            "properties": {
                "consulta": {"type": "string"},
                "tipo": {"type": "string", "enum": ["web", "noticias"], "description": "Padrão: web."},
                "periodo": {
                    "type": "string",
                    "enum": ["dia", "semana", "mes", "qualquer"],
                    "description": "Limita a resultados recentes. Padrão: qualquer.",
                },
            },
            "required": ["consulta"],
        },
    },
    {
        "name": "ler_pagina",
        "description": "Baixa uma página da web e devolve o texto dela. Use depois de pesquisar_web "
        "quando os trechos não trouxerem a resposta.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
]


def ollama_tools(extra: list[dict] | None = None) -> list[dict]:
    """Ferramentas no formato de function calling do Ollama."""
    client_tools = [t for t in TOOLS if "input_schema" in t] + LOCAL_SEARCH_TOOLS + (extra or [])
    return [
        {
            "type": "function",
            "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]},
        }
        for t in client_tools
    ]


# Comandos de PowerShell que exigem confirmação do usuário antes de rodar.
RISKY_COMMAND = re.compile(
    r"\b(remove-item|rm|rmdir|rd|del|erase|move-item|mv|rename-item|ren|clear-content|"
    r"set-content|out-file|copy-item|format-volume|format\s+[a-z](?=:)|clear-disk|initialize-disk|"
    r"stop-computer|restart-computer|shutdown|logoff|stop-process|taskkill|kill|stop-service|"
    r"remove-itemproperty|set-itemproperty|reg|diskpart|bcdedit|cipher|takeown|icacls|"
    r"set-executionpolicy|uninstall-package|winget|choco|invoke-expression|iex|net)\b",
    re.IGNORECASE,
)

# Mesmo com autonomia total, estes pedem confirmação: apagam discos, o sistema ou pastas inteiras.
CATASTROPHIC_COMMAND = re.compile(
    r"\b(format-volume|clear-disk|initialize-disk|remove-partition|diskpart|bcdedit|vssadmin\s+delete|"
    r"cipher\s+/w|format\s+[a-z](?=:))\b"
    r"|\b(remove-item|rm|rmdir|rd|del|erase)\b[^;|\n]*?\s['\"]?"
    r"([a-z]:\\?\*?|[a-z]:\\(windows|users|program files[^'\"]*|programdata)\\?|~|\$env:(userprofile|systemroot|windir))"
    r"['\"]?(\s|$)",
    re.IGNORECASE,
)

NEWS_WORDS = ("noticia", "ultimas", "hoje", "agora", "recente", "aconteceu", "lancamento", "placar", "resultado")
NEWS_FILLER = r"\b(quais|qual|as|os|[uú]ltimas?|not[ií]cias?|mais recentes|recentes?|hoje|agora|sobre)\b"

MEDIA_KEYS = {
    "tocar_pausar": "play/pause media",
    "proxima": "next track",
    "anterior": "previous track",
    "volume_mais": "volume up",
    "volume_menos": "volume down",
    "mudo": "volume mute",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def is_risky(command: str) -> bool:
    return bool(RISKY_COMMAND.search(command))


def is_catastrophic(command: str) -> bool:
    return bool(CATASTROPHIC_COMMAND.search(command))


def expand_secrets(text: str) -> str:
    """Troca ${NOME} pelo valor guardado no .env (o modelo nunca vê o valor)."""
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: os.environ.get(m.group(1), m.group(0)), text)


def secret_names() -> list[str]:
    """Nomes (não valores) dos segredos do .env que servem para integrações."""
    from .config import ENV_PATH

    try:
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    names = [ln.split("=", 1)[0].strip() for ln in lines if "=" in ln and not ln.lstrip().startswith("#")]
    return [n for n in names if n and not n.startswith(("JARVIS_", "ANTHROPIC_")) and os.environ.get(n)]


def resolve_path(raw: str) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(raw.strip().strip('"'))))
    return path if path.is_absolute() else WORKSPACE / path


def best_match(query: str, names: list[str]) -> str | None:
    q = normalize(query)
    normalized = {normalize(n): n for n in names}
    if q in normalized:
        return normalized[q]
    starts = [n for k, n in normalized.items() if k.startswith(q)]
    if starts:
        return min(starts, key=len)
    contains = [n for k, n in normalized.items() if q in k]
    if contains:
        return min(contains, key=len)
    close = difflib.get_close_matches(q, list(normalized), n=1, cutoff=0.6)
    return normalized[close[0]] if close else None


def load_memory() -> list[str]:
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_memory(items: list[str]) -> None:
    MEMORY_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


class ToolBox:
    """Executa as ferramentas pedidas pelo Claude."""

    def __init__(
        self,
        confirm: Callable[[str], bool],
        log_activity: Callable[[str], None],
        autonomy: str = "total",
        hub=None,
    ):
        self.confirm = confirm
        self.log_activity = log_activity
        self.autonomy = autonomy
        self.hub = hub  # integrações MCP (opcional)
        self._apps: dict[str, str] = {}
        self._apps_ready = threading.Event()
        self._shot: tuple[int, int, float] | None = None  # (left, top, scale) da última captura

    # ── Apps do Menu Iniciar ──────────────────────────────────────────────
    def preload(self) -> None:
        threading.Thread(target=self._load_apps, daemon=True).start()

    def _load_apps(self) -> None:
        try:
            out = _powershell("Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress", 30)
            data = json.loads(out or "[]")
            if isinstance(data, dict):
                data = [data]
            self._apps = {item["Name"]: item["AppID"] for item in data if item.get("Name")}
            log.info("%d apps do Menu Iniciar carregados", len(self._apps))
        except Exception:
            log.exception("Falha ao listar apps do Menu Iniciar")
        finally:
            self._apps_ready.set()

    # ── Despacho ──────────────────────────────────────────────────────────
    def claude_tools(self) -> list[dict]:
        return TOOLS + (self.hub.schemas if self.hub else [])

    def ollama_tools(self) -> list[dict]:
        return ollama_tools(self.hub.schemas if self.hub else None)

    def _needs_confirmation(self, command: str) -> bool:
        if self.autonomy == "total":
            return is_catastrophic(command)
        return is_risky(command)

    def run(self, name: str, args: dict) -> tuple[str | list, bool]:
        if self.hub and name in self.hub.tools:
            try:
                self.log_activity(f"Integração: {name.replace('__', ' › ')}")
                return self.hub.call(name, args), False
            except Exception as e:
                log.exception("Erro na integração %s", name)
                return f"Erro: {e}", True
        handler = getattr(self, f"_t_{name}", None)
        if handler is None:
            return f"Ferramenta desconhecida: {name}", True
        try:
            return handler(**args), False
        except Exception as e:
            log.exception("Erro na ferramenta %s", name)
            return f"Erro: {e}", True

    def _t_abrir_programa(self, nome: str) -> str:
        self._apps_ready.wait(timeout=30)
        match = best_match(nome, list(self._apps))
        if match:
            self.log_activity(f"Abrindo {match}")
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{self._apps[match]}"])
            return f"Abri '{match}'."
        try:
            os.startfile(nome)
            self.log_activity(f"Abrindo {nome}")
            return f"Abri '{nome}'."
        except OSError:
            suggestions = difflib.get_close_matches(nome, list(self._apps), n=5, cutoff=0.3)
            raise RuntimeError(f"Não encontrei '{nome}'. Parecidos: {', '.join(suggestions) or 'nenhum'}")

    def _t_abrir_url(self, url: str) -> str:
        target = url.strip()
        if not re.match(r"^[a-z][a-z0-9+.-]*://", target, re.I) and not Path(target).exists():
            target = "https://" + target
        self.log_activity(f"Abrindo {url}")
        webbrowser.open(target)
        return f"Abri {target}."

    def _t_executar_powershell(self, comando: str) -> str:
        if self._needs_confirmation(comando) and not self.confirm(f"Executar este comando?\n\n{comando}"):
            return "O usuário NÃO autorizou o comando. Nada foi executado."
        self.log_activity(f"PowerShell: {comando[:70]}")
        out = _powershell(comando, 60)
        return out[:6000] or "(comando executado, sem saída)"

    def _t_escrever_arquivo(self, caminho: str, conteudo: str, abrir: bool = False) -> str:
        path = resolve_path(caminho)
        outside = WORKSPACE not in path.parents
        ask = self.autonomy != "total" and path.exists() and outside
        if ask and not self.confirm(f"Sobrescrever o arquivo?\n\n{path}"):
            return "O usuário NÃO autorizou sobrescrever o arquivo."
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(conteudo, encoding="utf-8")
        self.log_activity(f"Salvo {path.name}")
        if abrir:
            os.startfile(str(path))
        return f"Arquivo salvo em {path} ({len(conteudo)} caracteres)."

    def _t_ler_arquivo(self, caminho: str) -> str:
        path = resolve_path(caminho)
        data = path.read_bytes()[:200_000]
        if b"\0" in data[:4000]:
            return f"{path} parece ser um arquivo binário ({path.stat().st_size} bytes)."
        text = data.decode("utf-8", errors="replace")
        return text[:30_000] + ("\n[... truncado]" if len(text) > 30_000 else "")

    def _t_listar_pasta(self, caminho: str) -> str:
        path = resolve_path(caminho)
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        lines = [f"{'[pasta] ' if p.is_dir() else ''}{p.name}" for p in entries[:300]]
        more = f"\n... e mais {len(entries) - 300}" if len(entries) > 300 else ""
        return f"{path}:\n" + "\n".join(lines) + more

    def _t_ver_tela(self) -> list:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            mon = sct.monitors[1]
            raw = sct.grab(mon)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        scale = min(1.0, 1366 / img.width)
        if scale < 1.0:
            img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
        self._shot = (mon["left"], mon["top"], scale)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75)
        self.log_activity("Captura de tela")
        return [
            {"type": "text", "text": f"Captura da tela principal, {img.width}x{img.height} pixels."},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(buf.getvalue()).decode(),
                },
            },
        ]

    def _t_clicar(self, x: int, y: int, botao: str = "esquerdo", duplo: bool = False) -> str:
        if self._shot is None:
            raise RuntimeError("Chame ver_tela antes de clicar.")
        left, top, scale = self._shot
        rx, ry = left + round(x / scale), top + round(y / scale)
        user32 = ctypes.windll.user32
        user32.SetCursorPos(rx, ry)
        down, up = (0x0002, 0x0004) if botao != "direito" else (0x0008, 0x0010)
        for _ in range(2 if duplo else 1):
            user32.mouse_event(down, 0, 0, 0, 0)
            user32.mouse_event(up, 0, 0, 0, 0)
        self.log_activity(f"Clique em {rx},{ry}")
        return f"Cliquei em ({x}, {y}) da captura."

    def _t_teclado(self, acao: str, texto: str) -> str:
        import keyboard

        if acao == "atalho":
            keyboard.send(texto)
            self.log_activity(f"Atalho {texto}")
            return f"Pressionei {texto}."
        keyboard.write(texto, delay=0.005)
        self.log_activity(f"Digitando {len(texto)} caracteres")
        return "Texto digitado."

    def _t_focar_janela(self, titulo: str) -> str:
        hwnd, title = _find_window(titulo)
        if not hwnd:
            raise RuntimeError(f"Nenhuma janela aberta com '{titulo}' no título.")
        user32 = ctypes.windll.user32
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        # Apertar Alt libera a trava de foco do Windows para SetForegroundWindow.
        user32.keybd_event(0x12, 0, 0, 0)
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(0x12, 0, 2, 0)
        self.log_activity(f"Foco em {title[:40]}")
        return f"Janela em foco: {title}"

    def _t_controle_midia(self, acao: str, vezes: int = 1) -> str:
        import keyboard

        for _ in range(max(1, min(vezes, 50))):
            keyboard.send(MEDIA_KEYS[acao])
        self.log_activity(f"Mídia: {acao}")
        return "Feito."

    def _t_pesquisar_web(self, consulta: str, tipo: str = "web", periodo: str = "qualquer") -> str:
        from ddgs import DDGS

        self.log_activity(f"Pesquisando: {consulta[:50]}")
        limit = {"dia": "d", "semana": "w", "mes": "m"}.get(periodo)
        lines: list[str] = []
        # Perguntas sobre algo recente também buscam notícias, mesmo sem o modelo pedir.
        if tipo == "noticias" or any(w in normalize(consulta) for w in NEWS_WORDS):
            topic = re.sub(NEWS_FILLER, " ", consulta, flags=re.IGNORECASE)
            topic = re.sub(r"^\W*(de|da|do|das|dos|sobre)\b|\s+", " ", topic).strip() or consulta
            news = _safe_search(DDGS().news, topic, limit, 8)
            news = sorted(news, key=lambda r: r.get("date", ""), reverse=True)[:6]
            lines += [
                f"{r.get('date', '')[:10]} · {r.get('source', '')}: {r['title']}\n{r['url']}\n{r['body']}"
                for r in news
            ]
        results = _safe_search(DDGS().text, consulta, limit, 3 if lines else 6)
        lines += [f"{r['title']}\n{r['href']}\n{r['body']}" for r in results]
        return "\n\n".join(lines) or "Nenhum resultado. Tente outras palavras."

    def _t_status_sistema(self) -> str:
        import time

        import psutil

        self.log_activity("Status do sistema")
        mem = psutil.virtual_memory()
        lines = [
            f"CPU: {psutil.cpu_percent(interval=0.5):.0f}% de uso, {psutil.cpu_count()} núcleos.",
            f"Memória: {mem.percent:.0f}% em uso ({mem.used / 2**30:.1f} de {mem.total / 2**30:.1f} GB).",
        ]
        for part in psutil.disk_partitions():
            try:
                du = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            lines.append(f"Disco {part.mountpoint}: {du.percent:.0f}% usado, {du.free / 2**30:.0f} GB livres.")
        battery = psutil.sensors_battery()
        if battery:
            lines.append(f"Bateria: {battery.percent:.0f}%{' (carregando)' if battery.power_plugged else ''}.")
        hours = (time.time() - psutil.boot_time()) / 3600
        lines.append(f"Ligado há {hours:.1f} horas.")
        procs = sorted(
            psutil.process_iter(["name", "memory_info"]),
            key=lambda pr: pr.info["memory_info"].rss if pr.info["memory_info"] else 0,
            reverse=True,
        )[:5]
        top = ", ".join(f"{pr.info['name']} ({pr.info['memory_info'].rss / 2**20:.0f} MB)" for pr in procs)
        lines.append(f"Processos que mais usam memória: {top}.")
        return "\n".join(lines)

    def _t_clima(self, cidade: str) -> str:
        import urllib.parse

        self.log_activity(f"Clima: {cidade}")
        data = json.loads(_http_get(f"https://wttr.in/{urllib.parse.quote(cidade)}?format=j1&lang=pt"))
        now = data["current_condition"][0]
        desc = (now.get("lang_pt") or now["weatherDesc"])[0]["value"]
        lines = [
            f"Agora em {cidade}: {now['temp_C']}°C (sensação {now['FeelsLikeC']}°C), {desc}, "
            f"umidade {now['humidity']}%, vento {now['windspeedKmph']} km/h."
        ]
        for day in data.get("weather", [])[:3]:
            rain = max(int(h.get("chanceofrain", 0)) for h in day["hourly"])
            lines.append(
                f"{day['date']}: mínima {day['mintempC']}°C, máxima {day['maxtempC']}°C, chance de chuva até {rain}%."
            )
        return "\n".join(lines)

    def _t_cotacao(self, pares: str) -> str:
        codes = ",".join(p.strip().upper() for p in pares.split(",") if p.strip())
        self.log_activity(f"Cotação: {codes}")
        data = json.loads(_http_get(f"https://economia.awesomeapi.com.br/json/last/{codes}"))
        return "\n".join(
            f"{v['name']}: compra {v['bid']}, venda {v['ask']}, variação {v['pctChange']}%, atualizado {v['create_date']}"
            for v in data.values()
        )

    def _t_requisicao_http(
        self, metodo: str, url: str, cabecalhos: dict | None = None, corpo: str | None = None
    ) -> str:
        import urllib.error
        import urllib.request

        self.log_activity(f"HTTP {metodo} {url[:50]}")
        headers = {"User-Agent": "Vektor/1.0", **{k: expand_secrets(str(v)) for k, v in (cabecalhos or {}).items()}}
        data = expand_secrets(corpo).encode() if corpo else None
        if data and not any(k.lower() == "content-type" for k in headers):
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(expand_secrets(url), data=data, headers=headers, method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status, body = resp.status, resp.read(500_000)
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read(100_000)
        return f"HTTP {status}\n{body.decode('utf-8', errors='replace')[:8000]}"

    def _t_ler_pagina(self, url: str) -> str:
        import urllib.request

        self.log_activity(f"Lendo {url[:50]}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            html = resp.read(2_000_000).decode(charset, errors="replace")
        return html_to_text(html)[:8000]

    def _t_lembrar(self, fato: str) -> str:
        items = load_memory()
        items.append(fato.strip())
        _save_memory(items)
        self.log_activity("Memória atualizada")
        return "Guardado na memória."

    def _t_esquecer(self, trecho: str) -> str:
        items = load_memory()
        keep = [i for i in items if normalize(trecho) not in normalize(i)]
        _save_memory(keep)
        return f"Removi {len(items) - len(keep)} item(ns) da memória."


def _safe_search(search: Callable, query: str, timelimit: str | None, max_results: int) -> list[dict]:
    """Uma busca do DuckDuckGo que falha (sem resultados, limite de acessos) não derruba a outra."""
    try:
        return search(query, region="br-pt", timelimit=timelimit, max_results=max_results) or []
    except Exception as e:
        log.warning("Busca falhou (%s): %s", query, e)
        return []


def _http_get(url: str, timeout: int = 20) -> str:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def html_to_text(html: str) -> str:
    import html as html_lib

    html = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", html)
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _powershell(command: str, timeout: int) -> str:
    prefix = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ProgressPreference = 'SilentlyContinue'; "
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", prefix + command],
        capture_output=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    err = proc.stderr.decode("utf-8", errors="replace").strip()
    if err:
        out = f"{out}\n[erro]\n{err}".strip()
    return out


def _find_window(part: str) -> tuple[int, str]:
    user32 = ctypes.windll.user32
    wanted = normalize(part)
    found: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            if buf.value and wanted in normalize(buf.value):
                found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else (0, "")
