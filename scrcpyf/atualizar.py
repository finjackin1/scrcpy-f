"""
Baixar e instalar o scrcpy (r166, bloco 1 da v1 -- pedido dele, 25/set/2026:
"clicar em um botao e o programa baixar e colocar na pasta correta").

COMO
----
1. Pergunta ao GitHub qual e a versao mais nova (api de releases) e pega o
   zip do Windows certo (64 ou 32 bits).
2. Baixa SEM pedir nada, para `pasta_dados()\\atualizacao`, e confere o
   tamanho e o SHA-256 que o proprio GitHub publica. Nao bateu = apaga.
3. TROCAR ARQUIVO PEDE ADMINISTRADOR (regra dele: tudo que o antivirus possa
   implicar fica atras da permissao, como o agendador). Um .bat em
   `ferramentas\\` extrai com o `tar` do Windows, guarda a pasta velha, poe a
   nova no lugar e so entao apaga a velha. Qualquer falha devolve a velha.
   O .bat so usa caminhos RELATIVOS a ele (ASCII): pasta com acento no nome
   quebraria o cmd, que le o arquivo noutra codificacao.
4. O resultado volta num arquivo (`resultado.txt`): "ok" ou "erro <motivo>".

O scrcpy instalado fica em `scrcpy\\` AO LADO do programa -- o lugar que o
config ja aceitava como reserva (`Config.PASTA_SCRCPY_JUNTO`), portable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import time
import urllib.request
from pathlib import Path

from . import caminhos

log = logging.getLogger(__name__)

REPO_SCRCPY = "Genymobile/scrcpy"
API = "https://api.github.com/repos/%s/releases/latest"
AGENTE = "scrcpy-f"
ESPERA_S = 20                       # cada pergunta/pedaco de download
BAT = "instalar-scrcpy.bat"


def _bits() -> str:
    """win64 ou win32, pelo Windows (nao pelo Python)."""
    maquina = (os.environ.get("PROCESSOR_ARCHITEW6432")
               or os.environ.get("PROCESSOR_ARCHITECTURE")
               or platform.machine() or "").upper()
    return "win64" if "64" in maquina else "win32"


def pasta_de_trabalho() -> Path:
    p = caminhos.pasta_dados() / "atualizacao"
    p.mkdir(parents=True, exist_ok=True)
    return p


def pasta_do_scrcpy() -> Path:
    """Onde o scrcpy baixado mora: `scrcpy\\` ao lado do programa."""
    return caminhos.arquivo("scrcpy")


def ultima_do_scrcpy() -> tuple[dict | None, str]:
    """(info, erro). info = versao, nome, url, tamanho, sha256 (ou "")."""
    return _ultima(API % REPO_SCRCPY,
                   re.compile(r"scrcpy-%s-v[\w.]+\.zip$" % _bits()))


# (r168) O PROPRIO scrcpy-f: o zip do publicar.bat publicado como release
# no GitHub dele. SCRCPYF_TESTE_API troca o endereco por um arquivo local
# (file:///...) -- so para a bancada de teste, sem publicar nada.
REPO_APP = "finjackin1/scrcpy-f"
BAT_APP = "atualizar-scrcpy-f.bat"


def ultima_do_app() -> tuple[dict | None, str]:
    url = os.environ.get("SCRCPYF_TESTE_API") or API % REPO_APP
    return _ultima(url, re.compile(r"scrcpy-f-[\w.]+\.zip$"))


def _ultima(url: str, padrao) -> tuple[dict | None, str]:
    try:
        pedido = urllib.request.Request(
            url, headers={"User-Agent": AGENTE,
                          "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(pedido, timeout=ESPERA_S) as r:
            dados = json.loads(r.read().decode("utf-8"))
    except Exception as erro:
        return None, "sem resposta do GitHub (%s)" % erro
    tag = str(dados.get("tag_name") or "")
    for a in dados.get("assets") or []:
        nome = str(a.get("name") or "")
        if padrao.match(nome):
            digest = str(a.get("digest") or "")
            return {"versao": tag.lstrip("v"), "nome": nome,
                    "url": a.get("browser_download_url"),
                    "tamanho": int(a.get("size") or 0),
                    "sha256": digest[7:] if digest.startswith("sha256:")
                    else ""}, ""
    return None, "a versão %s não tem o zip do Windows" % (tag or "?")


def baixar(info: dict, progresso=None) -> tuple[Path | None, str]:
    """Baixa e confere. (arquivo, erro). `progresso(baixado, total)`."""
    destino = pasta_de_trabalho() / info["nome"]
    parcial = destino.with_name(destino.name + ".parcial")
    soma = hashlib.sha256()
    baixado = 0
    total = info.get("tamanho") or 0
    try:
        pedido = urllib.request.Request(info["url"],
                                        headers={"User-Agent": AGENTE})
        with urllib.request.urlopen(pedido, timeout=ESPERA_S) as r, \
                open(parcial, "wb") as saida:
            ultimo = 0.0
            while True:
                pedaco = r.read(256 * 1024)
                if not pedaco:
                    break
                saida.write(pedaco)
                soma.update(pedaco)
                baixado += len(pedaco)
                agora = time.monotonic()
                if progresso and agora - ultimo > 0.2:
                    ultimo = agora
                    progresso(baixado, total)
    except Exception as erro:
        _apagar(parcial)
        return None, "o download falhou (%s)" % erro
    if total and baixado != total:
        _apagar(parcial)
        return None, "o arquivo chegou incompleto (%d de %d)" % (baixado,
                                                                 total)
    if info.get("sha256") and soma.hexdigest() != info["sha256"].lower():
        _apagar(parcial)
        return None, "o arquivo chegou diferente do publicado (conferência)"
    try:
        _apagar(destino)
        parcial.replace(destino)
    except Exception as erro:
        return None, "não consegui guardar o arquivo (%s)" % erro
    return destino, ""


def _apagar(p: Path) -> None:
    try:
        p.unlink()
    except Exception:
        pass


def _rel(de: Path, alvo: Path) -> str:
    return os.path.relpath(str(alvo), str(de))


def escrever_bat(zip_: Path) -> tuple[Path | None, Path]:
    """O .bat que troca a pasta. Devolve (bat, arquivo de resultado)."""
    ferr = caminhos.pasta_ferramentas()
    trabalho = pasta_de_trabalho()
    resultado = trabalho / "resultado.txt"
    r = lambda p: "%~dp0" + _rel(ferr, p)            # noqa: E731
    linhas = [
        "@echo off",
        "REM Gerado pelo scrcpy-f: instala o scrcpy baixado. Pode apagar.",
        "setlocal",
        'set "LOG=%s"' % r(caminhos.pasta_relatorios() / "atualizar.txt"),
        'set "ZIP=%s"' % r(zip_),
        'set "DEST=%s"' % r(pasta_do_scrcpy()),
        'set "TMPX=%s"' % r(trabalho / "extraido"),
        'set "RES=%s"' % r(resultado),
        '>>"%LOG%" echo === ABERTURA %date% %time% -- instalar scrcpy ===',
        'del "%RES%" 2>nul',
        'if exist "%DEST%\\adb.exe" "%DEST%\\adb.exe" kill-server >>"%LOG%" 2>&1',
        'if exist "%TMPX%" rmdir /s /q "%TMPX%"',
        'mkdir "%TMPX%"',
        'tar -xf "%ZIP%" -C "%TMPX%" 2>>"%LOG%"',
        'if errorlevel 1 (>"%RES%" echo erro extrair& goto fim)',
        'set "NOVA="',
        'for /d %%D in ("%TMPX%\\*") do if exist "%%D\\scrcpy.exe" set "NOVA=%%D"',
        'if exist "%TMPX%\\scrcpy.exe" set "NOVA=%TMPX%"',
        'if not defined NOVA (>"%RES%" echo erro sem-scrcpy& goto fim)',
        'if exist "%DEST%.velha" rmdir /s /q "%DEST%.velha"',
        'if not exist "%DEST%" goto por',
        'move "%DEST%" "%DEST%.velha" >>"%LOG%" 2>&1',
        'if errorlevel 1 (>"%RES%" echo erro em-uso& goto fim)',
        ':por',
        'move "%NOVA%" "%DEST%" >>"%LOG%" 2>&1',
        'if errorlevel 1 (',
        '    if exist "%DEST%.velha" move "%DEST%.velha" "%DEST%" >>"%LOG%" 2>&1',
        '    >"%RES%" echo erro mover',
        '    goto fim',
        ')',
        'if exist "%DEST%.velha" rmdir /s /q "%DEST%.velha"',
        'if exist "%TMPX%" rmdir /s /q "%TMPX%"',
        'del "%ZIP%" 2>nul',
        '>"%RES%" echo ok',
        ':fim',
        '>>"%LOG%" type "%RES%" 2>nul',
        '>>"%LOG%" echo === FECHAMENTO %date% %time% ===',
        "endlocal",
        "",
    ]
    try:
        bat = ferr / BAT
        bat.write_text("\r\n".join(linhas), encoding="ascii",
                       errors="replace")
        _apagar(resultado)
        return bat, resultado
    except Exception as erro:
        log.warning("nao escrevi o %s: %s", BAT, erro)
        return None, resultado


MOTIVOS = {
    "extrair": "não consegui abrir o zip baixado",
    "sem-scrcpy": "o zip não tinha o scrcpy dentro",
    "em-uso": "a pasta do scrcpy está em uso -- feche o que usa o scrcpy "
              "e tente de novo",
    "mover": "não consegui pôr a pasta nova no lugar (a antiga foi mantida)",
}


def instalar(zip_: Path) -> tuple[bool, str]:
    """Pede o administrador e roda o .bat. (ok, texto para a tela)."""
    from . import inicio_windows
    bat, resultado = escrever_bat(zip_)
    if bat is None:
        return False, "não consegui preparar a instalação"
    if not inicio_windows._executar_elevado(str(bat)):
        return False, "a permissão de administrador foi negada"
    try:
        texto = resultado.read_text(encoding="ascii",
                                    errors="replace").strip()
    except Exception:
        texto = ""
    if texto == "ok":
        return True, ""
    if texto.startswith("erro"):
        motivo = texto[4:].strip()
        return False, MOTIVOS.get(motivo, "a instalação falhou (%s)" % motivo)
    return False, "a instalação não terminou a tempo"


def escrever_bat_app(zip_: Path, pid: int, exe: Path) -> tuple[Path | None,
                                                                Path]:
    """
    (r168) O .bat que troca o PROPRIO programa. Roda como administrador,
    ESPERA este processo fechar, extrai, guarda uma copia do config.json e
    copia os arquivos novos POR CIMA (robocopy sem apagar nada): o que e da
    pessoa -- config.json, celulares\\, janelas\\, relatorios\\, o scrcpy
    baixado -- nao vem no zip e fica como esta. Quem REABRE o programa e o
    `reabrir-scrcpy-f.bat`, sem administrador (`esperar_e_reabrir`): o
    explorer.exe chamado daqui, elevado, nao abria nada (teste dele).
    """
    ferr = caminhos.pasta_ferramentas()
    trabalho = pasta_de_trabalho()
    resultado = trabalho / "resultado-app.txt"
    prog = caminhos.pasta_do_programa()
    r = lambda p: "%~dp0" + _rel(ferr, p)            # noqa: E731
    linhas = [
        "@echo off",
        "REM Gerado pelo scrcpy-f: atualiza o proprio programa. Pode apagar.",
        "setlocal",
        'set "LOG=%s"' % r(caminhos.pasta_relatorios() / "atualizar.txt"),
        'set "ZIP=%s"' % r(zip_),
        # caminho limpo (sem ".."): o robocopy prefere assim
        'for %%%%P in ("%s") do set "PROG=%%%%~fP"' % r(prog),
        'for %%%%P in ("%s") do set "EXE=%%%%~fP"' % r(exe),
        'set "TMPX=%s"' % r(trabalho / "extraido-app"),
        'set "RES=%s"' % r(resultado),
        '>>"%LOG%" echo === ABERTURA %date% %time% -- atualizar scrcpy-f ===',
        'del "%RES%" 2>nul',
        # espera o programa sair (ate ~30 s)
        "set /a N=0",
        ":espera",
        'tasklist /FI "PID eq %d" 2>nul | find "%d" >nul' % (pid, pid),
        "if errorlevel 1 goto saiu",
        "set /a N+=1",
        "if %N% GEQ 30 (>\"%RES%\" echo erro nao-fechou& goto abrir)",
        "timeout /t 1 /nobreak >nul",
        "goto espera",
        ":saiu",
        'if exist "%TMPX%" rmdir /s /q "%TMPX%"',
        'mkdir "%TMPX%"',
        'tar -xf "%ZIP%" -C "%TMPX%" 2>>"%LOG%"',
        'if errorlevel 1 (>"%RES%" echo erro extrair& goto abrir)',
        'set "NOVA="',
        'for /d %%D in ("%TMPX%\\*") do if exist "%%D\\scrcpy-f.exe" set "NOVA=%%D"',
        'if exist "%TMPX%\\scrcpy-f.exe" set "NOVA=%TMPX%"',
        'if not defined NOVA (>"%RES%" echo erro sem-programa& goto abrir)',
        # (r172) a copia fica escondida, na pasta de trabalho
        'if exist "%%PROG%%\\config.json" copy /y "%%PROG%%\\config.json" '
        '"%s" >nul' % r(trabalho / "config.json.antes-da-atualizacao"),
        'robocopy "%NOVA%" "%PROG%" /E /R:3 /W:1 /XF config.json /NP /NFL '
        '/NDL >>"%LOG%" 2>&1',
        'if errorlevel 8 (>"%RES%" echo erro copiar& goto abrir)',
        'rmdir /s /q "%TMPX%" 2>nul',
        'del "%ZIP%" 2>nul',
        '>"%RES%" echo ok',
        ":abrir",
        'if not exist "%RES%" >"%RES%" echo erro desconhecido',
        '>>"%LOG%" type "%RES%" 2>nul',
        '>>"%LOG%" echo === FECHAMENTO %date% %time% ===',
        "endlocal",
        "",
    ]
    try:
        bat = ferr / BAT_APP
        bat.write_text("\r\n".join(linhas), encoding="ascii",
                       errors="replace")
        _apagar(resultado)
        return bat, resultado
    except Exception as erro:
        log.warning("nao escrevi o %s: %s", BAT_APP, erro)
        return None, resultado


MOTIVOS_APP = {
    "nao-fechou": "o programa demorou a fechar",
    "extrair": "não consegui abrir o zip baixado",
    "sem-programa": "o zip não tinha o scrcpy-f dentro",
    "copiar": "não consegui copiar todos os arquivos novos",
}


def resultado_da_ultima_do_app() -> str | None:
    """
    Lido ao abrir: None = nao houve atualizacao; "" = deu certo; texto =
    o motivo da falha. Apaga o arquivo (o aviso e dado uma vez so).
    """
    arq = caminhos.pasta_dados() / "atualizacao" / "resultado-app.txt"
    try:
        texto = arq.read_text(encoding="ascii", errors="replace").strip()
    except Exception:
        return None
    _apagar(arq)
    if texto == "ok":
        return ""
    motivo = texto[4:].strip() if texto.startswith("erro") else texto
    return MOTIVOS_APP.get(motivo, motivo or "motivo desconhecido")


BAT_REABRIR = "reabrir-scrcpy-f.bat"


def esperar_e_reabrir(exe: Path) -> bool:
    """
    (r169) Sobe, SEM administrador e escondido, um .bat que espera o
    resultado da troca (ate ~3 min) e abre o programa de novo. Fica de pe
    depois que este processo fecha. True se subiu.
    """
    import subprocess
    ferr = caminhos.pasta_ferramentas()
    resultado = pasta_de_trabalho() / "resultado-app.txt"
    r = lambda p: "%~dp0" + _rel(ferr, p)            # noqa: E731
    linhas = [
        "@echo off",
        "REM Gerado pelo scrcpy-f: reabre o programa depois da atualizacao.",
        "setlocal",
        'set "RES=%s"' % r(resultado),
        'for %%%%P in ("%s") do set "EXE=%%%%~fP"' % r(exe),
        "set /a N=0",
        ":espera",
        'if exist "%RES%" goto abrir',
        "set /a N+=1",
        "if %N% GEQ 180 goto abrir",
        "timeout /t 1 /nobreak >nul",
        "goto espera",
        ":abrir",
        "timeout /t 1 /nobreak >nul",
        'start "" "%EXE%"',
        "endlocal",
        "",
    ]
    try:
        bat = ferr / BAT_REABRIR
        bat.write_text("\r\n".join(linhas), encoding="ascii",
                       errors="replace")
        subprocess.Popen(
            ["cmd.exe", "/c", str(bat)], cwd=str(ferr),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True)
        return True
    except Exception as erro:
        log.warning("nao subi o %s: %s", BAT_REABRIR, erro)
        return False
