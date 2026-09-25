"""
O DISFARCE DA TROCA DE JANELA (r136, pedido dele, 24/set/2026).

Ao mudar um ajuste de um app aberto, a janela do scrcpy e trocada por outra
(`Programa._trocar_sem_reiniciar`). Para a troca nao aparecer: uma FOTO do
pedaco da tela onde esta a janela velha fica parada por cima, num quadro
sem borda, enquanto a troca acontece por baixo; quando a janela nova ja
mostra o app, o quadro some esmaecendo (~150 ms).

REGRAS DELE
-----------
- O mais suave e rapido possivel: a foto e tirada da TELA (o que ja esta
  aparecendo, ~poucos ms), o quadro nasce sem animacao do Windows e some por
  esmaecimento suave.
- A foto NUNCA vai para arquivo: vive so na memoria de desenho do Windows
  (um bitmap GDI) e, ao terminar, e apagada (pintada de preto) e destruida.
  Nada disto grava em disco.

O quadro fica POR CIMA DE TUDO (senao a janela nova, que nasce na frente,
apareceria por cima dele), deixa o clique passar e nunca pega o foco. Se
algo travar, some sozinho em ESPERA_MAX_S. Qualquer falha = sem disfarce,
e a troca segue normal. Fora do Windows nao faz nada.

Tudo roda numa thread propria, com contexto de DPI PER_MONITOR_AWARE_V2:
a foto, a medida da janela e o quadro falam em pixels reais.
"""

from __future__ import annotations

import ctypes
import logging
import math
import sys
import threading
import time

log = logging.getLogger(__name__)

NO_WINDOWS = sys.platform == "win32"

ESPERA_MAX_S = 3.0      # teto: o quadro nunca fica mais que isto
SUMIR_S = 0.10          # esmaecimento no fim (r137: era 0,15)
ASSENTAR_S = 0.05       # depois que a nova aparece (r137: era 0,12)
PASSO_S = 0.012         # passo do esmaecimento

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020     # o clique passa atraves
WS_EX_TOOLWINDOW = 0x00000080      # sem botao na barra de tarefas
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000      # nunca pega o foco
SW_SHOWNOACTIVATE = 4
SRCCOPY = 0x00CC0020
BLACKNESS = 0x00000042
ULW_ALPHA = 0x00000002
PM_REMOVE = 0x0001
DWMWA_TRANSITIONS_FORCEDISABLED = 3
DWMWA_EXTENDED_FRAME_BOUNDS = 9
PER_MONITOR_AWARE_V2 = -4

_API = None


def _api():
    """user32/gdi32/kernel32/dwmapi com copia PROPRIA (tipos declarados no
    user32 compartilhado brigariam -- ver monitores.py)."""
    global _API
    if _API is not None:
        return _API
    from ctypes import wintypes as w

    class BLEND(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte),
                    ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte),
                    ("AlphaFormat", ctypes.c_ubyte)]

    u = ctypes.WinDLL("user32", use_last_error=True)
    g = ctypes.WinDLL("gdi32", use_last_error=True)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        d = ctypes.WinDLL("dwmapi")
        d.DwmGetWindowAttribute.argtypes = [w.HWND, w.DWORD, ctypes.c_void_p,
                                            w.DWORD]
        d.DwmSetWindowAttribute.argtypes = [w.HWND, w.DWORD, ctypes.c_void_p,
                                            w.DWORD]
    except (OSError, AttributeError):
        d = None

    u.IsWindow.argtypes = [w.HWND]
    u.IsIconic.argtypes = [w.HWND]
    u.IsWindowVisible.argtypes = [w.HWND]
    u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    u.GetDC.argtypes = [w.HWND]
    u.GetDC.restype = w.HDC
    u.ReleaseDC.argtypes = [w.HWND, w.HDC]
    u.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE,
                                  w.LPVOID]
    u.CreateWindowExW.restype = w.HWND
    u.DestroyWindow.argtypes = [w.HWND]
    u.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
    u.UpdateLayeredWindow.argtypes = [
        w.HWND, w.HDC, ctypes.POINTER(w.POINT), ctypes.POINTER(w.SIZE),
        w.HDC, ctypes.POINTER(w.POINT), w.COLORREF, ctypes.POINTER(BLEND),
        w.DWORD]
    u.PeekMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT,
                               w.UINT, w.UINT]
    u.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
    u.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
    try:
        u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    except AttributeError:                      # Windows antigo
        pass
    g.CreateCompatibleDC.argtypes = [w.HDC]
    g.CreateCompatibleDC.restype = w.HDC
    g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]
    g.CreateCompatibleBitmap.restype = w.HBITMAP
    g.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
    g.SelectObject.restype = w.HGDIOBJ
    g.BitBlt.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, w.HDC, ctypes.c_int, ctypes.c_int,
                         w.DWORD]
    g.PatBlt.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, w.DWORD]
    g.DeleteObject.argtypes = [w.HGDIOBJ]
    g.DeleteDC.argtypes = [w.HDC]
    k.GetModuleHandleW.argtypes = [w.LPCWSTR]
    k.GetModuleHandleW.restype = w.HMODULE
    _API = (u, g, k, d, w, BLEND)
    return _API


class Disfarce:
    """Um quadro com a foto da janela. `soltar()` pode ser chamado quantas
    vezes quiser, de qualquer thread; sem Windows ou sem janela, nao faz
    nada."""

    def __init__(self, hwnd) -> None:
        self._alvo = hwnd
        self._soltar = threading.Event()
        self._pronto = threading.Event()
        self.ativo = False
        self.motivo = ""                # por que nao cobriu (vai pro log)

    def soltar(self) -> None:
        self._soltar.set()

    def _comecar(self, espera: float) -> None:
        if not NO_WINDOWS or not self._alvo:
            self.motivo = "sem janela"
            return
        threading.Thread(target=self._rodar, daemon=True,
                         name="disfarce").start()
        self._pronto.wait(espera)

    def _rodar(self) -> None:
        tela = memdc = foto = antigo = quadro = None
        lw = la = 0
        try:
            u, g, k, d, w, BLEND = _api()
            try:
                u.SetThreadDpiAwarenessContext(
                    ctypes.c_void_p(PER_MONITOR_AWARE_V2))
            except Exception:
                pass
            alvo = w.HWND(self._alvo)
            if (not u.IsWindow(alvo) or u.IsIconic(alvo)
                    or not u.IsWindowVisible(alvo)):
                self.motivo = "janela escondida"
                return
            # A moldura VISIVEL (sem a borda invisivel de redimensionar).
            r = w.RECT()
            if d is None or d.DwmGetWindowAttribute(
                    alvo, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r),
                    ctypes.sizeof(r)) != 0:
                if not u.GetWindowRect(alvo, ctypes.byref(r)):
                    self.motivo = "sem medida"
                    return
            x, y = r.left, r.top
            lw, la = r.right - r.left, r.bottom - r.top
            if lw <= 0 or la <= 0:
                self.motivo = "medida vazia"
                return
            # A foto: o que a tela mostra ali agora. So na memoria.
            tela = u.GetDC(None)
            memdc = g.CreateCompatibleDC(tela)
            foto = g.CreateCompatibleBitmap(tela, lw, la)
            if not (tela and memdc and foto):
                self.motivo = "sem memoria de desenho"
                return
            antigo = g.SelectObject(memdc, foto)
            if not g.BitBlt(memdc, 0, 0, lw, la, tela, x, y, SRCCOPY):
                self.motivo = "foto falhou"
                return
            quadro = u.CreateWindowExW(
                WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
                | WS_EX_NOACTIVATE | WS_EX_TOPMOST,
                "STATIC", None, WS_POPUP, x, y, lw, la, None, None,
                k.GetModuleHandleW(None), None)
            if not quadro:
                self.motivo = "quadro nao abriu"
                return
            if d is not None:                   # nasce sem animacao
                sim = ctypes.c_int(1)
                d.DwmSetWindowAttribute(quadro,
                                        DWMWA_TRANSITIONS_FORCEDISABLED,
                                        ctypes.byref(sim), ctypes.sizeof(sim))
            pos, tam, zero = w.POINT(x, y), w.SIZE(lw, la), w.POINT(0, 0)

            def pintar(alfa: int) -> bool:
                mistura = BLEND(0, 0, max(0, min(255, alfa)), 0)
                return bool(u.UpdateLayeredWindow(
                    quadro, tela, ctypes.byref(pos), ctypes.byref(tam),
                    memdc, ctypes.byref(zero), 0, ctypes.byref(mistura),
                    ULW_ALPHA))

            if not pintar(255):
                self.motivo = "pintura falhou"
                return
            u.ShowWindow(quadro, SW_SHOWNOACTIVATE)
            self.ativo = True
            self._pronto.set()
            msg = w.MSG()

            def bombear() -> None:
                while u.PeekMessageW(ctypes.byref(msg), None, 0, 0,
                                     PM_REMOVE):
                    u.TranslateMessage(ctypes.byref(msg))
                    u.DispatchMessageW(ctypes.byref(msg))

            fim = time.monotonic() + ESPERA_MAX_S
            while not self._soltar.is_set() and time.monotonic() < fim:
                bombear()
                self._soltar.wait(0.01)
            # Esmaecimento suave (curva cosseno: comeca e termina devagar).
            t0 = time.monotonic()
            while True:
                f = (time.monotonic() - t0) / SUMIR_S
                if f >= 1:
                    break
                pintar(int(255 * (0.5 + 0.5 * math.cos(math.pi * f))))
                bombear()
                time.sleep(PASSO_S)
        except Exception as erro:
            self.motivo = "erro: %s" % erro
            log.warning("disfarce da troca falhou: %s", erro)
        finally:
            self._pronto.set()
            self._destruir(tela, memdc, foto, antigo, quadro, lw, la)

    @staticmethod
    def _destruir(tela, memdc, foto, antigo, quadro, lw, la) -> None:
        """A foto deixa de existir: pintada de preto e destruida."""
        if _API is None:
            return
        u, g = _API[0], _API[1]
        for passo in (
                lambda: quadro and u.DestroyWindow(quadro),
                lambda: memdc and foto and g.PatBlt(memdc, 0, 0, lw, la,
                                                    BLACKNESS),
                lambda: memdc and antigo and g.SelectObject(memdc, antigo),
                lambda: foto and g.DeleteObject(foto),
                lambda: memdc and g.DeleteDC(memdc),
                lambda: tela and u.ReleaseDC(None, tela)):
            try:
                passo()
            except Exception:
                pass


def cobrir(hwnd, espera: float = 0.2) -> Disfarce:
    """Poe o quadro com a foto por cima da janela `hwnd` e so volta quando
    ele ja esta na tela (ou em `espera` s). Sempre devolve um Disfarce --
    se nao deu pra cobrir, `soltar()` simplesmente nao faz nada."""
    capa = Disfarce(hwnd)
    try:
        capa._comecar(espera)
    except Exception as erro:
        capa.motivo = "erro: %s" % erro
    return capa
