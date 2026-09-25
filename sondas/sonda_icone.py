"""
SONDA DO ICONE (25/set/2026, ideia I1 da v1.0)

Pedido dele: cada janela de app com o icone do app, o espelhar com o do
scrcpy-f, e cada janela no SEU botao da barra de tarefas (hoje o Windows
agrupa todas as do scrcpy num botao so -- ele considera erro).

Abre DUAS janelas do celular (espelho simples, sem som), UMA DEPOIS DA
OUTRA (as duas juntas travavam a 2a), e em cada passo TIRA UMA FOTO DA TELA
(relatorios\sonda_icone_passoN.png) -- eu olho as fotos; ele so espera:
  1  as duas nascem com SCRCPY_ICON_PATH = icone do scrcpy-f
     -> o icone da barra de titulo e o do scrcpy-f ou o robo verde?
  2  a janela B ganha um "nome proprio" no Windows (AppUserModelID)
     -> os dois botoes da barra separaram?
  3  a janela B recebe o icone do WhatsApp (WM_SETICON)
     -> o icone da janela B (titulo e botao da barra) mudou?

Grava relatorios\\sonda_icone.txt (substituido a cada sonda).
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)

from scrcpyf import caminhos, celular, icone, janela_scrcpy  # noqa: E402
from scrcpyf.config import Config  # noqa: E402

SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0
REL = os.path.join(AQUI, "relatorios")
SAIDA = os.path.join(REL, "sonda_icone.txt")
PAUSA = 10
linhas: list[str] = []
T0 = time.time()


def anotar(texto: str = "") -> None:
    linhas.append(texto)
    os.makedirs(REL, exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arq:
        arq.write("\n".join(linhas) + "\n")


def marca(texto: str) -> None:
    anotar("[%6.2f s] %s" % (time.time() - T0, texto))


# --------------------------------------------------------------- Windows
from ctypes import wintypes as w  # noqa: E402


class GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort),
                ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]


def guid(texto: str) -> GUID:
    g = GUID()
    ctypes.OleDLL("ole32").CLSIDFromString(ctypes.c_wchar_p(texto),
                                          ctypes.byref(g))
    return g


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("texto", ctypes.c_wchar_p), ("resto", ctypes.c_void_p)]


def dar_nome(hwnd, nome: str) -> str:
    """AppUserModelID proprio na janela (botao separado na barra)."""
    ctypes.OleDLL("ole32").CoInitialize(None)
    loja = ctypes.c_void_p()
    iid = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")   # IPropertyStore
    ctypes.OleDLL("shell32").SHGetPropertyStoreForWindow(
        w.HWND(hwnd), ctypes.byref(iid), ctypes.byref(loja))
    tabela = ctypes.cast(loja, ctypes.POINTER(ctypes.POINTER(
        ctypes.c_void_p)))[0]
    set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                   ctypes.POINTER(PROPERTYKEY),
                                   ctypes.POINTER(PROPVARIANT))(tabela[6])
    commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(tabela[7])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(tabela[2])
    chave = PROPERTYKEY(guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"), 5)
    valor = PROPVARIANT(31, 0, 0, 0, nome, None)             # VT_LPWSTR
    r1 = set_value(loja, ctypes.byref(chave), ctypes.byref(valor))
    r2 = commit(loja)
    release(loja)
    return "SetValue=%#x Commit=%#x" % (r1 & 0xFFFFFFFF, r2 & 0xFFFFFFFF)


def por_icone(hwnd, png: str) -> str:
    """WM_SETICON com um .ico feito do PNG (grande e pequeno)."""
    from PIL import Image
    ico = os.path.join(REL, "sonda_icone.ico")
    Image.open(png).convert("RGBA").save(
        ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (256, 256)])
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.LoadImageW.restype = w.HANDLE
    u.LoadImageW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int,
                             ctypes.c_int, w.UINT]
    u.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    res = []
    for tipo, lado in ((1, 32), (0, 16)):         # ICON_BIG, ICON_SMALL
        h = u.LoadImageW(None, ico, 1, lado, lado, 0x10)   # LR_LOADFROMFILE
        u.SendMessageW(hwnd, 0x80, tipo, h or 0)             # WM_SETICON
        res.append("%s=%s" % ("grande" if tipo else "pequeno", bool(h)))
    return " ".join(res)


def foto(n: int) -> None:
    """A tela inteira, para eu olhar (barra de tarefas e titulos)."""
    time.sleep(2.5)
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=True)
        img.save(os.path.join(REL, "sonda_icone_passo%d.png" % n))
        marca("foto do passo %d: %sx%s" % (n, img.width, img.height))
    except Exception as erro:
        marca("foto do passo %d FALHOU: %r" % (n, erro))


def main() -> int:
    config = Config.carregar()
    adb, scr = str(config.adb_exe), str(config.scrcpy_exe)
    serial = celular.achar(adb, config.ip_reserva)
    if not serial:
        marca("celular NAO encontrado")
        print("\n   Nao achei o celular.")
        return 1
    desenho = icone.gravar_para_janela(caminhos.pasta_dados())
    marca("icone do scrcpy-f: %s (existe=%s)" % (
        desenho, bool(desenho) and os.path.exists(str(desenho))))
    ambiente = dict(os.environ)
    if desenho:
        ambiente["SCRCPY_ICON_PATH"] = str(desenho)
    procs = {}
    janelas = {}
    for nome, x in (("A", 100), ("B", 800)):
        log = open(os.path.join(REL, "sonda_icone_%s.txt" % nome), "w",
                   encoding="utf-8", errors="replace")
        procs[nome] = subprocess.Popen(
            [scr, "-s", serial, "--no-audio", "--max-size=600",
             "--video-bit-rate=2M", "--no-power-on", "--window-x=%d" % x,
             "--window-y=100", "--window-title=teste do icone %s" % nome],
            stdout=log, stderr=subprocess.STDOUT, env=ambiente,
            cwd=os.path.dirname(scr), creationflags=SEM_JANELA)
        fim = time.time() + 20
        while nome not in janelas and time.time() < fim:
            h = janela_scrcpy.achar(procs[nome].pid)
            if h:
                janelas[nome] = h
            time.sleep(0.2)
    time.sleep(1.5)
    marca("janelas: %s" % janelas)
    if len(janelas) < 2:
        print("\n   As janelas nao abriram. Veja o celular e tente de novo.")
        for p in procs.values():
            p.terminate()
        return 1
    print("\n   Pode so esperar: eu tiro fotos da tela e olho depois.")
    marca("passo 1: as duas com SCRCPY_ICON_PATH")
    foto(1)
    try:
        marca("passo 2: nome proprio na B -> %s"
              % dar_nome(janelas["B"], "scrcpyf.teste.B"))
    except Exception as erro:
        marca("passo 2 FALHOU: %r" % erro)
    foto(2)
    whats = os.path.join(caminhos.pasta_dados(), "celulares")
    png = None
    for raiz, _d, arqs in os.walk(whats):
        if "com.whatsapp.png" in arqs:
            png = os.path.join(raiz, "com.whatsapp.png")
            break
    try:
        marca("passo 3: icone do WhatsApp na B (%s) -> %s"
              % (png, por_icone(janelas["B"], png) if png else "sem png"))
    except Exception as erro:
        marca("passo 3 FALHOU: %r" % erro)
    foto(3)
    for p in procs.values():
        p.terminate()
    marca("fim")
    print("\n   Pronto. Pode avisar no chat que terminou.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        marca("ERRO: %r" % erro)
        raise
