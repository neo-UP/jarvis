from jarvis.config import WORKSPACE
from jarvis.speech import clean_for_speech, split_sentences
from jarvis.tools import TOOLS, best_match, is_risky, resolve_path


def test_comandos_de_risco_pedem_confirmacao():
    assert is_risky("Remove-Item C:\\temp -Recurse")
    assert is_risky("Stop-Computer")
    assert is_risky("taskkill /im chrome.exe")
    assert is_risky("format d: /q")
    assert is_risky("'oi' | Set-Content a.txt")


def test_comandos_de_leitura_rodam_direto():
    assert not is_risky("Get-Process | Sort-Object CPU -Descending | Select-Object -First 5")
    assert not is_risky("Get-ChildItem C:\\ | Format-Table Name")
    assert not is_risky("Get-NetAdapter")
    assert not is_risky("(Get-CimInstance Win32_Battery).EstimatedChargeRemaining")


def test_caminho_relativo_vai_para_workspace():
    assert resolve_path("sites/loja/index.html") == WORKSPACE / "sites" / "loja" / "index.html"
    assert resolve_path("C:\\x.txt").is_absolute()


def test_busca_de_programa_aproximada():
    apps = ["Spotify", "Bloco de Notas", "Google Chrome", "Calculadora", "Microsoft Edge"]
    assert best_match("spotify", apps) == "Spotify"
    assert best_match("chrome", apps) == "Google Chrome"
    assert best_match("bloco de notas", apps) == "Bloco de Notas"
    assert best_match("calculadorra", apps) == "Calculadora"
    assert best_match("photoshop", apps) is None


def test_texto_falado_sem_markdown():
    text = "**Pronto!** Veja [o site](https://x.com):\n- item um\n- item dois"
    assert clean_for_speech(text) == "Pronto! Veja o site: item um item dois"


def test_primeiro_trecho_sai_sozinho():
    chunks = split_sentences("Olá. Tudo certo por aqui. Os sistemas estão normais. Algo mais?")
    assert chunks[0] == "Olá."
    assert len(chunks) == 2


def test_ferramentas_tem_nomes_unicos():
    names = [t["name"] for t in TOOLS]
    assert len(names) == len(set(names))


def test_ferramentas_locais_no_formato_do_ollama():
    from jarvis.tools import ollama_tools

    tools = ollama_tools()
    names = [t["function"]["name"] for t in tools]
    assert "pesquisar_web" in names and "web_search" not in names
    assert all(t["type"] == "function" and "parameters" in t["function"] for t in tools)


def test_html_vira_texto():
    from jarvis.tools import html_to_text

    html = "<html><head><style>x{}</style></head><body><h1>Dólar</h1><script>a()</script><p>R$ 5,42 &amp; alta</p></body></html>"
    assert html_to_text(html) == "Dólar\n R$ 5,42 & alta"


def test_chamado_pelo_nome():
    from jarvis.speech import split_wake, wake_pattern

    wake = wake_pattern("VEKTOR")
    assert split_wake("Vektor, abra o Spotify.", wake) == "abra o Spotify"
    assert split_wake("Vector, que horas são?", wake) == "que horas são"
    assert split_wake("Ei, Vetor! Aumenta o volume", wake) == "Aumenta o volume"
    assert split_wake("Véktor.", wake) == ""
    assert split_wake("o vetor da matriz é ortogonal", wake) is None
    assert split_wake("vou ligar pro Victor amanhã", wake) is None
    assert split_wake("Abra o Spotify", wake) is None


def test_autonomia_total_so_trava_o_catastrofico():
    from jarvis.tools import is_catastrophic

    assert is_catastrophic(r"Remove-Item C:\ -Recurse -Force")
    assert is_catastrophic("Remove-Item $env:USERPROFILE -Recurse")
    assert is_catastrophic(r'Remove-Item "C:\Program Files" -Recurse')
    assert is_catastrophic("Format-Volume -DriveLetter D")
    assert not is_catastrophic(r"Remove-Item C:\Users\Vekto\Desktop\teste.txt")
    assert not is_catastrophic("Stop-Process -Name chrome")
    assert not is_catastrophic("winget install Spotify.Spotify")


def test_confirmacao_falada():
    from jarvis.speech import parse_yes_no

    assert parse_yes_no("Sim, pode.") is True
    assert parse_yes_no("Pode mandar") is True
    assert parse_yes_no("Não, cancela!") is False
    assert parse_yes_no("não pode") is False
    assert parse_yes_no("hmm, deixa eu ver") is None


def test_segredos_do_env(monkeypatch):
    from jarvis.tools import expand_secrets

    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    assert expand_secrets("https://api.telegram.org/bot${TELEGRAM_TOKEN}/send") == "https://api.telegram.org/bot123:abc/send"
    assert expand_secrets("${NAO_EXISTE}") == "${NAO_EXISTE}"


def test_emojis_nao_vao_para_a_voz():
    assert clean_for_speech("Claro! 😊 Pode deixar 👍🏽") == "Claro! Pode deixar"
