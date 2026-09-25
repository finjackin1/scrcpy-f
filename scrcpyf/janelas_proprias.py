"""
CADA APP NA SUA JANELA DA BARRA DE TAREFAS, COM O ICONE DELE (r158, pedido
dele, 25/set/2026: "cada um tiver icone eles vao precisar estar separados e
nao agrupados").

POR QUE UM .EXE POR APP
-----------------------
O Windows junta na barra de tarefas as janelas que saem do MESMO .exe, e nao
deixa um programa separar as janelas de outro (a sonda_icone provou: o
"nome proprio" posto de fora foi recusado). Entao cada app roda de um
"<pacote>.exe" so dele, dentro de uma pasta nossa (dados\\janelas): o Windows
ve programas diferentes e da um botao para cada um.

SEM OCUPAR ESPACO
-----------------
A pasta tem LINKS FISICOS dos arquivos do scrcpy (o mesmo arquivo com dois
nomes: zero espaco a mais). So da no mesmo disco; noutro, copia UMA vez
(~31 MB, decisao dele: "copie"). O adb e o scrcpy-server NAO vao para la: o
scrcpy acha os de verdade pelas variaveis ADB e SCRCPY_SERVER_PATH.

O ICONE
-------
O scrcpy 4.0 le o icone de SCRCPY_ICON_DIR (uma PASTA com "scrcpy.png"; a
variavel antiga SCRCPY_ICON_PATH ele ignora -- achado nas strings do exe).
Cada app ganha dados\\janelas\\icones\\<pacote>\\scrcpy.png com o icone dele.

Trocou a pasta do scrcpy (ou atualizou)? A pasta e refeita. Qualquer falha
aqui devolve o scrcpy de sempre: a janela abre, so fica agrupada.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
from pathlib import Path

from . import caminhos

log = logging.getLogger(__name__)

_TRAVA = threading.Lock()
MARCA = "origem.txt"
# O que vai para a pasta: o exe e as bibliotecas que ele carrega ao lado.
EXTENSOES = (".dll",)


def _pasta() -> Path:
    return caminhos.pasta_dados() / "janelas"


def _assinatura(scrcpy_exe: Path) -> str:
    st = scrcpy_exe.stat()
    return "%s|%d|%d" % (scrcpy_exe, st.st_size, int(st.st_mtime))


def _ligar(origem: Path, destino: Path) -> str:
    """Link fisico; noutro disco (ou sem suporte), copia."""
    try:
        os.link(origem, destino)
        return "link"
    except OSError:
        shutil.copy2(origem, destino)
        return "copia"


def _preparar(scrcpy_exe: Path) -> tuple[Path, str]:
    """A pasta com o scrcpy.exe e as DLLs, conferida contra a origem."""
    pasta = _pasta()
    pasta.mkdir(parents=True, exist_ok=True)
    marca = pasta / MARCA
    assinatura = _assinatura(scrcpy_exe)
    try:
        atual = marca.read_text(encoding="utf-8").strip()
    except OSError:
        atual = ""
    base = pasta / "scrcpy.exe"
    if atual == assinatura and base.exists():
        return pasta, "pronta"
    # Origem nova: some com o que era da velha (exe de app aberto fica --
    # o Windows nao deixa apagar exe rodando; e refeito na proxima).
    presos = 0
    for item in pasta.iterdir():
        if item.is_file() and item.suffix.lower() in (".exe", ".dll"):
            try:
                item.unlink()
            except OSError:
                presos += 1
    como = set()
    for item in scrcpy_exe.parent.iterdir():
        if item.is_file() and (item.suffix.lower() in EXTENSOES
                               or item.name.lower() == "scrcpy.exe"):
            destino = pasta / item.name
            if not destino.exists():
                como.add(_ligar(item, destino))
    # (r165) Sobrou arquivo velho preso (janela de app aberta na hora da
    # atualizacao do scrcpy): NAO marca como pronta -- senao a DLL velha
    # ficava para sempre ao lado do exe novo. Na proxima abertura refaz.
    if not presos:
        marca.write_text(assinatura, encoding="utf-8")
    else:
        log.warning("janelas: %d arquivo(s) velho(s) em uso; refaco depois",
                    presos)
    return pasta, "+".join(sorted(como)) or "pronta"


def pasta_de_icone(nome: str, png, scrcpy_exe=None):
    """dados\\janelas\\icones\\<nome>\\scrcpy.png a partir de `png` (ou None
    se nao der). Leva junto o disconnected.png do scrcpy, se houver."""
    try:
        pasta = _pasta() / "icones" / nome
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / "scrcpy.png"
        origem = Path(png)
        if not destino.exists() or \
                destino.stat().st_mtime < origem.stat().st_mtime:
            from PIL import Image
            with Image.open(origem) as img:
                img.convert("RGBA").resize((256, 256)).save(destino)
        if scrcpy_exe is not None:
            desligado = Path(scrcpy_exe).parent / "disconnected.png"
            alvo = pasta / "disconnected.png"
            if desligado.exists() and not alvo.exists():
                shutil.copy2(desligado, alvo)
        return pasta
    except Exception as erro:
        log.debug("icone de %s: %s", nome, erro)
        return None


def para_o_app(scrcpy_exe, adb_exe, pacote: str, png_do_app, icone_padrao):
    """
    (exe, pasta do icone, variaveis a mais, como) para abrir `pacote` na
    janela dele. Falhou qualquer coisa: o scrcpy de sempre, com o icone
    padrao, e `como` diz o motivo (vai para o registro).
    """
    scrcpy_exe = Path(scrcpy_exe)
    icone = None
    if png_do_app and Path(png_do_app).exists():
        icone = pasta_de_icone(pacote, png_do_app, scrcpy_exe)
    icone = icone or icone_padrao
    try:
        with _TRAVA:
            pasta, como = _preparar(scrcpy_exe)
            nome = "scrcpy-f_%s.exe" % re.sub(r"[^A-Za-z0-9._-]", "_",
                                              pacote)
            exe = pasta / nome
            if not exe.exists():
                como = "%s/%s" % (como, _ligar(pasta / "scrcpy.exe", exe))
        extra = {
            "ADB": str(adb_exe),
            "SCRCPY_SERVER_PATH": str(scrcpy_exe.parent / "scrcpy-server"),
        }
        return exe, icone, extra, como
    except Exception as erro:
        return scrcpy_exe, icone, {}, "agrupada (%s)" % erro
