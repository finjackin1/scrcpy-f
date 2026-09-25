"""
A janela de um scrcpy rodando, vista de fora: achar, medir, por no lugar e
apertar o atalho de apagar a tela do celular.

Existe para a TROCA SEM DESLIGAR (`Programa.trocar`, 19/set/2026): mudar a
qualidade com o espelhamento no ar sobe um scrcpy novo por cima do velho, e o
novo tem que nascer exatamente onde o velho estava.

COORDENADAS NA LINGUA DA JANELA
--------------------------------
Com escala do Windows acima de 100% cada programa pode enxergar a tela num
tamanho diferente (o mesmo problema do `monitores.py`). Medir o scrcpy no
"idioma" deste programa e passar para o outro daria a janela deslocada. Por
isso toda medida aqui e feita com a thread falando a mesma lingua da janela
medida (`SetThreadDpiAwarenessContext` com o contexto DELA): o numero que sai
e o que o proprio scrcpy entende no `--window-x`.

Fora do Windows tudo devolve None/False sem quebrar.
"""

from __future__ import annotations

import ctypes
import logging
import sys

log = logging.getLogger(__name__)

NO_WINDOWS = sys.platform == "win32"

if NO_WINDOWS:
    from ctypes import wintypes

    _u = ctypes.WinDLL("user32", use_last_error=True)
    _PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _u.EnumWindows.argtypes = [_PROC, wintypes.LPARAM]
    _u.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
    _u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR,
                                  ctypes.c_int]
    _u.IsWindowVisible.argtypes = [wintypes.HWND]
    _u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _u.ClientToScreen.argtypes = [wintypes.HWND,
                                  ctypes.POINTER(wintypes.POINT)]
    _u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT]
    _u.GetForegroundWindow.restype = wintypes.HWND
    _u.SetForegroundWindow.argtypes = [wintypes.HWND]
    _u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _u.GetWindowLongW.restype = ctypes.c_long
    _u.IsIconic.argtypes = [wintypes.HWND]
    _u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _u.BringWindowToTop.argtypes = [wintypes.HWND]
    _u.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    _u.MapVirtualKeyW.restype = wintypes.UINT
    _u.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD,
                               ctypes.c_void_p]
    try:
        _u.GetWindowDpiAwarenessContext.argtypes = [wintypes.HWND]
        _u.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
        _u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        _u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        _TEM_DPI = True
    except AttributeError:                      # Windows antigo
        _TEM_DPI = False

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x0008
KEYEVENTF_KEYUP = 0x0002
VK_LMENU = 0xA4          # Alt da esquerda: o modificador padrao do scrcpy
VK_O = 0x4F              # Alt+O = "apagar a tela do celular" no scrcpy


class _MesmaLingua:
    """Enquanto dura, a thread mede a tela como a janela `hwnd` mede."""

    def __init__(self, hwnd) -> None:
        self.hwnd = hwnd
        self.anterior = None

    def __enter__(self):
        if NO_WINDOWS and _TEM_DPI:
            try:
                ctx = _u.GetWindowDpiAwarenessContext(self.hwnd)
                if ctx:
                    self.anterior = _u.SetThreadDpiAwarenessContext(ctx)
            except Exception:
                self.anterior = None
        return self

    def __exit__(self, *_):
        if self.anterior:
            try:
                _u.SetThreadDpiAwarenessContext(self.anterior)
            except Exception:
                pass


def _titulo(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _u.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def achar(pid: int, titulo: str | None = None, visivel: bool = True):
    """
    A janela de topo do processo `pid` (com esse titulo, se dado). O SDL cria
    janelas auxiliares escondidas no mesmo processo; o titulo separa a do
    espelhamento. `visivel=True` so conta a que ja apareceu -- o scrcpy so
    mostra a janela quando o primeiro quadro chega, entao "visivel" quer
    dizer "ja tem imagem".
    """
    if not NO_WINDOWS or not pid:
        return None
    achadas = []

    def olhar(hwnd, _param):
        dono = wintypes.DWORD()
        _u.GetWindowThreadProcessId(hwnd, ctypes.byref(dono))
        if dono.value != pid:
            return True
        if visivel and not _u.IsWindowVisible(hwnd):
            return True
        if titulo and _titulo(hwnd) != titulo:
            return True
        achadas.append(hwnd)
        return False                            # achou: para de procurar

    try:
        _u.EnumWindows(_PROC(olhar), 0)
    except Exception as erro:
        log.warning("nao consegui procurar a janela do scrcpy: %s", erro)
    return achadas[0] if achadas else None


def area(hwnd):
    """(x, y, largura, altura) da area de imagem, na lingua da janela."""
    if not NO_WINDOWS or not hwnd:
        return None
    with _MesmaLingua(hwnd):
        r = wintypes.RECT()
        p = wintypes.POINT(0, 0)
        if not _u.GetClientRect(hwnd, ctypes.byref(r)):
            return None
        if not _u.ClientToScreen(hwnd, ctypes.byref(p)):
            return None
        return (p.x, p.y, r.right - r.left, r.bottom - r.top)


def por_no_lugar(hwnd, alvo) -> bool:
    """
    Acerta a area de imagem de `hwnd` para `alvo` (x, y, largura, altura),
    se ela nasceu fora. So mexe se a diferenca passar de 2 pixels: na maioria
    das vezes o `--window-x/y/width/height` ja acertou e nada se move.
    """
    if not NO_WINDOWS or not hwnd or not alvo:
        return False
    with _MesmaLingua(hwnd):
        agora = area(hwnd)
        if agora is None:
            return False
        dx, dy = alvo[0] - agora[0], alvo[1] - agora[1]
        dl, da = alvo[2] - agora[2], alvo[3] - agora[3]
        if max(abs(dx), abs(dy), abs(dl), abs(da)) <= 2:
            return False
        fora = wintypes.RECT()
        if not _u.GetWindowRect(hwnd, ctypes.byref(fora)):
            return False
        return bool(_u.SetWindowPos(
            hwnd, None, fora.left + dx, fora.top + dy,
            (fora.right - fora.left) + dl, (fora.bottom - fora.top) + da,
            SWP_NOZORDER | SWP_NOACTIVATE))


def frente():
    """A janela que esta na frente agora (de qualquer programa)."""
    if not NO_WINDOWS:
        return None
    try:
        return _u.GetForegroundWindow()
    except Exception:
        return None


def trazer(hwnd) -> bool:
    """
    Poe a janela na frente e com o foco (desminimiza se preciso). O Windows
    so deixa roubar a frente em certas condicoes; com a tecla Alt "apertada"
    durante o pedido ele libera (o mesmo truque do `moldura`), e a Alt e
    solta na hora, sem abrir menu nenhum.
    """
    if not NO_WINDOWS or not hwnd:
        return False
    try:
        if _u.IsIconic(hwnd):
            _u.ShowWindow(hwnd, 9)                      # SW_RESTORE
        _u.BringWindowToTop(hwnd)
        _u.SetForegroundWindow(hwnd)
        if _u.GetForegroundWindow() != hwnd:
            alt = _u.MapVirtualKeyW(VK_LMENU, 0) & 0xFF
            _u.keybd_event(VK_LMENU, alt, 0, None)
            try:
                _u.SetForegroundWindow(hwnd)
            finally:
                _u.keybd_event(VK_LMENU, alt, KEYEVENTF_KEYUP, None)
        return _u.GetForegroundWindow() == hwnd
    except Exception as erro:
        log.warning("nao consegui trazer a janela: %s", erro)
        return False


def por_cima(hwnd) -> bool:
    """A janela esta presa por cima de todas as outras?"""
    if not NO_WINDOWS or not hwnd:
        return False
    try:
        return bool(_u.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)
    except Exception:
        return False


def fixar_por_cima(hwnd, fixar: bool) -> bool:
    """
    Prende (ou solta) a janela por cima de todas as outras, sem mexer no
    lugar, no tamanho nem no foco. Atalho pedido por ele (21/set/2026); o
    `--always-on-top` do scrcpy so vale ao subir, isto vale com ele no ar.
    """
    if not NO_WINDOWS or not hwnd:
        return False
    try:
        return bool(_u.SetWindowPos(
            hwnd, wintypes.HWND(HWND_TOPMOST if fixar else HWND_NOTOPMOST),
            0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))
    except Exception as erro:
        log.warning("nao consegui fixar a janela por cima: %s", erro)
        return False


def apagar_tela_do_celular(hwnd) -> bool:
    """
    Aperta Alt+O na janela do scrcpy: o atalho dele que apaga a tela do
    celular sem parar o espelhamento.

    Por que isto existe: quando o scrcpy VELHO sai, a limpeza dele devolve
    a tela do celular ao normal -- e o NOVO, que ja tinha apagado a tela ao
    subir, nao fica sabendo. Nao ha outro jeito de pedir ao scrcpy que apague
    de novo com ele no ar.

    Tecla de verdade (com codigo de varredura), e so com a janela dele em
    primeiro plano: o SDL confere o estado real do Alt, e mandar tecla para
    uma janela que nao e a da frente poderia cair em outro programa.
    """
    if not NO_WINDOWS or not hwnd:
        return False
    try:
        if _u.GetForegroundWindow() != hwnd:
            _u.SetForegroundWindow(hwnd)
        if _u.GetForegroundWindow() != hwnd:
            return False
        alt = _u.MapVirtualKeyW(VK_LMENU, 0) & 0xFF
        letra = _u.MapVirtualKeyW(VK_O, 0) & 0xFF
        _u.keybd_event(VK_LMENU, alt, 0, None)
        _u.keybd_event(VK_O, letra, 0, None)
        _u.keybd_event(VK_O, letra, KEYEVENTF_KEYUP, None)
        _u.keybd_event(VK_LMENU, alt, KEYEVENTF_KEYUP, None)
        return True
    except Exception as erro:
        log.warning("nao consegui apagar a tela do celular: %s", erro)
        return False


def pid_sob_o_mouse() -> int:
    """
    O processo dono da janela de topo que esta embaixo do ponteiro (0 se
    nenhuma). Usado pelo vigia do foco (r113): mouse parado sobre a janela
    de um app = o app ganha a atencao do Android.
    """
    if not NO_WINDOWS:
        return 0
    try:
        u = _u_foco()
        ponto = wintypes.POINT()
        if not u.GetCursorPos(ctypes.byref(ponto)):
            return 0
        hwnd = u.WindowFromPoint(ponto)
        if not hwnd:
            return 0
        raiz = u.GetAncestor(hwnd, 2) or hwnd          # GA_ROOT
        pid = wintypes.DWORD(0)
        _u.GetWindowThreadProcessId(raiz, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


_U_FOCO = None


def _u_foco():
    """Copia propria do user32 para as tres funcoes do vigia do foco (tipos
    declarados no user32 compartilhado brigariam -- ver monitores.py)."""
    global _U_FOCO
    if _U_FOCO is None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        u.GetCursorPos.restype = wintypes.BOOL
        u.WindowFromPoint.argtypes = [wintypes.POINT]
        u.WindowFromPoint.restype = wintypes.HWND
        u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetAncestor.restype = wintypes.HWND
        _U_FOCO = u
    return _U_FOCO
