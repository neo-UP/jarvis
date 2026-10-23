# Integrações do Vektor

O Vektor se conecta a outras plataformas de dois jeitos.

## 1. Servidores MCP (recomendado)

MCP (Model Context Protocol) é o padrão aberto que Claude, ChatGPT e outros assistentes usam para falar com
apps. Existem servidores prontos para Gmail, Google Agenda, Google Drive, Notion, GitHub, Slack, Spotify,
bancos de dados e muito mais, e plataformas como Zapier e Composio expõem milhares de apps por um único
servidor MCP remoto.

Os servidores ficam em `dados/mcp.json` (criado na primeira vez que o Vektor abre), no mesmo formato do
Claude Desktop:

```json
{
  "mcpServers": {
    "hora": {
      "command": "python",
      "args": ["-m", "mcp_server_time", "--local-timezone=America/Sao_Paulo"]
    },
    "um_servidor_npm": {
      "command": "npx",
      "args": ["-y", "nome-do-pacote-mcp"],
      "env": {"API_KEY": "${MINHA_CHAVE}"}
    },
    "um_servidor_remoto": {
      "url": "https://endereco-do-servidor/mcp",
      "headers": {"Authorization": "Bearer ${TOKEN_DO_SERVIDOR}"}
    }
  }
}
```

- `"disabled": true` desliga um servidor sem apagar a configuração.
- `${NOME}` puxa o valor do `.env`, então chaves e tokens não ficam no `mcp.json`.
- Feche e abra o Vektor depois de editar. O painel ATIVIDADE mostra as integrações conectadas, e
  problemas ficam em `logs/mcp.log`.
- Servidores via `npx` precisam do Node.js (já instalado nesta máquina).

Depois é só pedir: *"Vektor, quais são meus compromissos de amanhã?"*, *"crie uma página no Notion com…"*.

## 2. Requisições HTTP e webhooks

Para qualquer API ou automação, o Vektor tem a ferramenta `requisicao_http`. Guarde os segredos no `.env`:

```
TELEGRAM_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=987654
N8N_WEBHOOK=https://seu-n8n/webhook/abc
```

E peça em linguagem natural:

- *"Vektor, me manda no Telegram a cotação do dólar."* Ele chama
  `https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage` com o `${TELEGRAM_CHAT_ID}`.
- *"Vektor, dispara o meu fluxo do n8n com o resumo das notícias."* Ele faz um POST em `${N8N_WEBHOOK}`.

O modelo só vê os nomes dos segredos, nunca os valores.

## Dica

Com o cérebro local (Ollama), muitas integrações deixam o modelo mais lento e mais confuso: ligue só as que
você usa. Com o Claude (`JARVIS_CEREBRO=claude`) o uso de integrações é bem mais preciso.
