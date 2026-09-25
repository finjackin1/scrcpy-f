"""
ATALHO DE UM APP NA AREA DE TRABALHO (r159, pedido dele, 25/set/2026 --
ideia I2 da v1.0).

O atalho tem o NOME e o ICONE do app e abre o scrcpy-f com "--app <pacote>":
  - scrcpy-f aberto: a instancia que esta rodando recebe o pedido (arquivo
    de chamado + o sinal que ja existia) e abre o app;
  - fechado: o scrcpy-f sobe so na bandeja (sem mostrar a janela) e abre o
    app;
  - sem celular: uma caixa "o celular nao esta conectado"; no OK ela fecha
    -- e, se o scrcpy-f subiu so por causa do atalho, ele fecha junto (sem
    ficar esperando conexao, pedido dele).

Como e um atalho comum do Windows (.lnk), ele e criado pelo proprio Windows
(WScript.Shell via PowerShell): nada de biblioteca a mais. Os textos vao
por variavel de ambiente, nunca montados dentro do comando -- nome de app
com aspas ou acento nao quebra nada.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from . import caminhos

log = logging.getLogger(__name__)

SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_POWERSHELL = (
    # (r174, pedido dele) Ja existe um atalho com esse nome? O novo ganha
    # " (1)", " (2)"... -- nunca escreve por cima de um que ja esta la.
    "$d=[Environment]::GetFolderPath('Desktop');$n=$env:SF_BASE;"
    "$p=Join-Path $d ($n+'.lnk');$i=1;"
    "while(Test-Path -LiteralPath $p){$p=Join-Path $d ($n+' ('+$i+').lnk');"
    "$i++};"
    "$l=(New-Object -ComObject WScript.Shell).CreateShortcut($p);"
    "$l.TargetPath=$env:SF_ALVO;$l.Arguments=$env:SF_ARGS;"
    "$l.WorkingDirectory=$env:SF_PASTA;$l.IconLocation=$env:SF_ICO+',0';"
    "$l.Description=$env:SF_DESC;$l.Save();Write-Output $p")


def alvo_do_programa() -> tuple[str, list]:
    """(executavel, argumentos antes do --app) de ESTE scrcpy-f."""
    if caminhos.empacotado():
        return sys.executable, []
    # Em codigo: o pythonw (sem console) rodando o app.py do projeto.
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    return str(pyw if pyw.exists() else py), [
        str(caminhos.pasta_do_programa() / "app.py")]


def _ico(png, destino: Path) -> Path:
    """O .ico do atalho, feito do icone do app (varios tamanhos)."""
    from PIL import Image
    destino.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(png) as img:
        img.convert("RGBA").resize((256, 256)).save(
            destino, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                            (64, 64), (128, 128), (256, 256)])
    return destino


def _aspas(texto: str) -> str:
    return '"%s"' % texto.replace('"', "")


def _area_de_trabalho() -> str:
    import ctypes
    buf = ctypes.create_unicode_buffer(260)
    # CSIDL_DESKTOPDIRECTORY = 0x10 (segue a pasta movida/OneDrive)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) != 0:
        raise OSError("sem a pasta da area de trabalho")
    return buf.value


def _nome_livre(pasta: str, base: str) -> str:
    """base.lnk, ou base (1).lnk, base (2).lnk... o primeiro que nao existe."""
    caminho = os.path.join(pasta, base + ".lnk")
    i = 1
    while os.path.exists(caminho):
        caminho = os.path.join(pasta, "%s (%d).lnk" % (base, i))
        i += 1
    return caminho


def _criar_direto(caminho, alvo, args, pasta, ico, desc) -> None:
    """
    (r176) O .lnk pelo PROPRIO Windows, sem abrir o PowerShell (que levava
    uns segundos so para subir -- queixa dele). IShellLinkW + IPersistFile
    chamados pela tabela de funcoes, so com ctypes. Qualquer falha levanta,
    e o `criar` cai no PowerShell como antes.
    """
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD),
                    ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

    def guid(texto):
        g = GUID()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(texto),
                                            ctypes.byref(g))
        return g

    def metodo(obj, indice, *tipos):
        vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(
            ctypes.c_void_p))).contents
        prot = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *tipos)
        return lambda *a: prot(vtbl[indice])(obj, *a)

    ole = ctypes.oledll.ole32
    iniciou = ctypes.windll.ole32.CoInitialize(None) in (0, 1)
    link = ctypes.c_void_p()
    arquivo = ctypes.c_void_p()
    try:
        ole.CoCreateInstance(
            ctypes.byref(guid("{00021401-0000-0000-C000-000000000046}")),
            None, 1,    # CLSCTX_INPROC_SERVER
            ctypes.byref(guid("{000214F9-0000-0000-C000-000000000046}")),
            ctypes.byref(link))
        texto = ctypes.c_wchar_p
        metodo(link, 20, texto)(alvo)                       # SetPath
        metodo(link, 11, texto)(args)                       # SetArguments
        metodo(link, 9, texto)(pasta)                       # SetWorkingDirectory
        metodo(link, 17, texto, ctypes.c_int)(ico, 0)       # SetIconLocation
        metodo(link, 7, texto)(desc)                        # SetDescription
        metodo(link, 0, ctypes.c_void_p, ctypes.c_void_p)(  # QueryInterface
            ctypes.byref(guid("{0000010B-0000-0000-C000-000000000046}")),
            ctypes.byref(arquivo))
        metodo(arquivo, 6, texto, wintypes.BOOL)(caminho, True)   # Save
    finally:
        for obj in (arquivo, link):
            if obj.value:
                try:
                    ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
                        ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(
                            ctypes.c_void_p))).contents[2])(obj)  # Release
                except Exception:
                    pass
        if iniciou:
            ctypes.windll.ole32.CoUninitialize()
    if not os.path.exists(caminho):
        raise OSError("o Windows nao gravou o atalho")


def criar(pacote: str, nome: str, png, icone_padrao) -> tuple[bool, str]:
    """
    Cria o atalho na area de trabalho (nome repetido ganha " (1)"). Devolve (ok, caminho ou
    motivo). `png` = icone do app; sem ele, `icone_padrao` (o do scrcpy-f).
    """
    try:
        pasta = caminhos.pasta_dados() / "janelas" / "icones" / \
            re.sub(r"[^A-Za-z0-9._-]", "_", pacote)
        origem = png if png and Path(png).exists() else icone_padrao
        if not origem or not Path(origem).exists():
            return False, "sem icone para o atalho"
        ico = _ico(origem, pasta / "atalho.ico")
        exe, antes = alvo_do_programa()
        nome_limpo = re.sub(r'[\\/:*?"<>|]', "", nome).strip() or pacote
        args = " ".join([_aspas(a) for a in antes] +
                        ["--app", pacote, "--nome", _aspas(nome_limpo)])
        desc = "%s no PC (scrcpy-f)" % nome_limpo
        # (r176) Direto pelo Windows, sem PowerShell; falhou -> PowerShell.
        try:
            caminho = _nome_livre(_area_de_trabalho(), nome_limpo)
            _criar_direto(caminho, exe, args,
                          str(caminhos.pasta_do_programa()), str(ico), desc)
            return True, caminho
        except Exception as erro:
            log.warning("atalho direto falhou (%s); indo pelo PowerShell",
                        erro)
        ambiente = dict(os.environ)
        ambiente.update({
            "SF_BASE": nome_limpo, "SF_ALVO": exe, "SF_ARGS": args,
            "SF_PASTA": str(caminhos.pasta_do_programa()),
            "SF_ICO": str(ico),
            "SF_DESC": "%s no PC (scrcpy-f)" % nome_limpo})
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             _POWERSHELL], capture_output=True, timeout=30, env=ambiente,
            creationflags=SEM_JANELA)
        saida = (r.stdout or b"").decode("utf-8", "replace").strip()
        erro = (r.stderr or b"").decode("utf-8", "replace").strip()
        if r.returncode != 0 or not saida.lower().endswith(".lnk"):
            return False, (erro or saida or "powershell %s" % r.returncode
                           )[:200]
        return True, saida.splitlines()[-1]
    except Exception as erro:
        log.exception("atalho de %s", pacote)
        return False, str(erro)[:200]


def ler_argumentos(argv) -> tuple[str, str]:
    """(pacote, nome) de "--app <pacote> [--nome <nome>]", ou ("", "")."""
    pacote = nome = ""
    for i, a in enumerate(argv):
        if a == "--app" and i + 1 < len(argv):
            pacote = argv[i + 1]
        elif a == "--nome" and i + 1 < len(argv):
            nome = argv[i + 1]
    # (r186) copia de app duplicado: "<pacote>@<usuario>".
    if not re.fullmatch(r"[A-Za-z0-9._]+(@\d+)?", pacote or ""):
        return "", ""
    return pacote, nome
