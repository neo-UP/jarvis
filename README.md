# V.E.K.T.O.R

Assistente de voz em português para Windows. O cérebro é um modelo local e gratuito no Ollama
(ou o Claude, da Anthropic, se preferir). A interface tem estilo TRON: um rosto 3D feito de bits que
fala, pisca e muda de cor conforme o que está fazendo (`JARVIS_TEMA=reator` volta ao anel antigo). Ele age no seu PC: abre programas, pesquisa na web, vê a tela, clica, digita,
roda PowerShell, cria arquivos e sites.

## Instalação

Requer Python 3.13 (`py install 3.13`).

1. Dê dois cliques em `instalar.bat`.
2. Abra com `iniciar.bat`.
3. Tenha o Ollama instalado (https://ollama.com). Na primeira vez o modelo `qwen3:8b` (5 GB) é baixado sozinho.

A primeira abertura também baixa o modelo de reconhecimento de voz (cerca de 500 MB). Para usar o Claude
no lugar do Ollama, coloque `JARVIS_CEREBRO=claude` e sua `ANTHROPIC_API_KEY` no `.env`.

## Como usar

- **Chamar pelo nome:** diga *"Vektor, abre o Spotify"* (tudo de uma vez) ou só *"Vektor"*, espere o "Sim?" e faça o pedido.
- **Responder perguntas dele:** quando ele termina com uma pergunta, o reator fica verde e você responde direto, sem dizer o nome.
- **Atalho:** aperte `Ctrl+Alt+J` (de qualquer lugar) ou clique no reator, fale, e ele para sozinho quando você fica em silêncio.
- **Digitar:** escreva na caixa de baixo e aperte Enter.
- `Esc` interrompe · `F11` tela cheia · `Ctrl+N` nova conversa.

Exemplos: *"abra o Spotify"*, *"qual a cotação do dólar?"*, *"o que tem na minha tela?"*,
*"crie um site para a minha padaria em Mauá"*, *"aumenta o volume"*, *"lembre que eu prefiro respostas curtas"*.

## Autonomia e segurança

Por padrão (`JARVIS_AUTONOMIA=total`) ele faz qualquer coisa no PC sem pedir permissão: instala programas,
mexe em arquivos, encerra processos, desliga. Só o que destrói discos, o Windows ou pastas inteiras
(formatar, apagar `C:\`, `C:\Windows`, `C:\Users`, `Program Files`) pede confirmação, por voz ("sim"/"não")
ou na tela. Com `JARVIS_AUTONOMIA=confirmar`, ele pede confirmação para qualquer ação de risco.

Ele roda com as permissões do seu usuário (não como administrador). Lembre que o reconhecimento de voz pode
errar e um modelo local pequeno também: acompanhe o que ele faz.

## Internet e dados atualizados

- **Notícias e pesquisa:** DuckDuckGo, com busca de notícias automática quando a pergunta é sobre algo recente.
- **Clima:** wttr.in. **Cotações de moedas e cripto:** AwesomeAPI. **Páginas:** ele lê o texto de qualquer site.
- **Estado do PC:** CPU, memória, discos, bateria e processos.

## Integrações

Veja [INTEGRACOES.md](INTEGRACOES.md): servidores MCP (Gmail, Agenda, Notion, GitHub, Slack, Zapier…),
requisições HTTP e webhooks (n8n, Make, Telegram, Discord).

## Configuração

Copie `.env.example` para `.env` para trocar o nome, o cérebro, a voz, o atalho e o tratamento. Arquivos criados
pelo assistente ficam em `workspace/`, a memória em `dados/memoria.json` e os logs em `logs/`.

## Estrutura

```
jarvis/
  hud.py        janela, painéis e legendas
  tron.py       tema TRON: rosto de bits, piso em grade e motos de luz
  assistant.py  ciclo ouvir → transcrever → pensar → agir → falar
  brain.py      cérebro Claude e prompt de sistema
  brain_ollama.py  cérebro local (Ollama)
  tools.py      ações no PC, pesquisa e requisições HTTP
  integrations.py  integrações MCP
  speech.py     transcrição (faster-whisper) e fala (Edge TTS)
  audio.py      microfone e alto-falante
```
