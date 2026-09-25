# -*- mode: python ; coding: utf-8 -*-
"""
Receita do executavel. Usada pelo `publicar.bat` (nao rodar a mao).

MODO PASTA, NAO ARQUIVO UNICO
------------------------------
Sai um `scrcpy-f.exe` com as DLLs ao lado, nao um .exe gigante sozinho. O
arquivo unico descompacta tudo num temporario A CADA ABERTURA -- segundos de
espera toda vez, num programa que pode abrir junto com o Windows. Mesma
escolha do LightWireless.

O QUE COSTUMA QUEBRAR AO CONGELAR (os dois sao silenciosos)
------------------------------------------------------------
1. `ImageTk`, da Pillow, e achado por um modulo que ninguem importa pelo
   nome (`PIL._tkinter_finder`). Sem ele a janela abre SEM os desenhos (o
   mapa dos monitores, os icones da barra).
2. `pystray` escolhe o backend em tempo de execucao; sem `pystray._win32`
   o programa abre sem bandeja.

Conferir os dois no primeiro teste do executavel: a janela tem os desenhos?
o icone aparece ao lado do relogio?
"""

NOME = "scrcpy-f"

# A receita mora em publicacao\; tudo e achado a partir da RAIZ do projeto.
import os as _os
RAIZ = _os.path.abspath(_os.path.join(SPECPATH, ".."))

# FICHA DO .EXE (botao direito > Propriedades > Detalhes). Executavel sem
# nome, versao nem autor e um dos sinais que o antivirus pesa contra; a
# versao e lida do codigo, como no publicar.bat.
import re as _re
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
    VarFileInfo, VarStruct)

with open(_os.path.join(RAIZ, "scrcpyf", "__init__.py"), encoding="utf-8") as _arq:
    VERSAO = _re.search(r'VERSAO\s*=\s*"([^"]+)"', _arq.read()).group(1)
_numeros = tuple((int(n) for n in VERSAO.split(".")[:3])) + (0,)
_numeros = (_numeros + (0, 0, 0, 0))[:4]


def _ficha(nome_exe, descricao):
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=_numeros, prodvers=_numeros,
                          mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1,
                          subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("041604B0", [
                StringStruct("CompanyName", "finjackin"),
                StringStruct("FileDescription", descricao),
                StringStruct("FileVersion", VERSAO),
                StringStruct("InternalName", nome_exe),
                StringStruct("LegalCopyright", "GPLv3"),
                StringStruct("OriginalFilename", nome_exe + ".exe"),
                StringStruct("ProductName", "scrcpy-f"),
                StringStruct("ProductVersion", VERSAO),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
        ])

ocultos = [
    "PIL._tkinter_finder",   # ImageTk -- os desenhos da janela
    "pystray._win32",        # backend da bandeja no Windows
]

# O que NAO entra: so esta instalado na maquina de quem publica por ser
# dependencia de outra coisa, e cada um pesa dezenas de MB. `tkinter` NAO
# pode entrar aqui: e a janela inteira.
fora = [
    "matplotlib", "scipy", "pandas", "numpy", "IPython", "jupyter",
    "notebook", "pytest", "setuptools", "pip", "wheel",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
    "PIL.ImageQt",
    # (r169) "ssl" SAIU daqui: os atualizadores baixam do GitHub por https
    # e, sem ele, o .exe dava "unknown url type: https". Custo: ~7,5 MB.
]

# Pedacos binarios da Pillow que o programa nunca usa: ele so desenha
# (Image, ImageDraw, ImageTk) e salva PNG/ICO. Fora: AVIF (~8 MB sozinho),
# WebP, fontes, perfis de cor e as operacoes matematicas/morfologicas. Os
# modulos Python que os usariam ja sao escritos para seguir sem eles.
PIL_SEM_USO = ("_avif", "_webp", "_imagingft", "_imagingcms",
               "_imagingmath", "_imagingmorph")

a = Analysis(
    [_os.path.join(RAIZ, "app.py")],
    pathex=[RAIZ],
    binaries=[],
    # O programinha que roda no celular e devolve os icones dos apps (ver
    # android\LEIA-ME.txt). Vai para _internal\android.
    # (r154) E o que religa o painel da tela (scrcpyf-tela.jar).
    datas=[(_os.path.join(RAIZ, "android", "scrcpyf-icones.jar"), "android"),
           (_os.path.join(RAIZ, "android", "scrcpyf-tela.jar"), "android")],
    hiddenimports=ocultos,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=fora,
    noarchive=False,
    optimize=0,
)

def _sem_o_que_nao_usa(binarios):
    return [b for b in binarios
            if not any(("PIL" in b[0]) and (nome + ".") in b[0]
                       for nome in PIL_SEM_USO)]


a.binaries = _sem_o_que_nao_usa(a.binaries)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NOME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # Sem UPX: antivirus desconfia de executavel comprimido, e um programa que
    # instala gancho de teclado (a extensao) ja e candidato a falso positivo.
    upx=False,
    # SEM CONSOLE: programa de bandeja; uma janela preta presa a ele seria
    # justamente o que o `scrcpy-f.bat` evita na versao em codigo.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_os.path.join(SPECPATH, "scrcpy-f.ico"),
    version=_ficha(NOME, "scrcpy-f - celular Android junto do PC"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=NOME,
)
