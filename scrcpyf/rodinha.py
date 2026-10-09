"""
RODINHA COMO ARRASTO nas janelas de app (08/out/2026, pedido dele).

No Instagram a rodinha do mouse rola os comentarios E o feed de baixo (o
scrcpy entrega a rolagem certinho ao que esta sob o ponteiro; e o app que
passa adiante -- testado por ele tambem com a extensao, mouse "fisico"). Com
o dedo isso nao acontece. Entao, nos apps com a correcao ligada, a rodinha
vira um ARRASTO curto no lugar do ponteiro:

- um gancho de mouse de baixo nivel ve a rodinha (WM_MOUSEWHEEL) da MAO
  (nao a injetada); se o ponteiro esta sobre a janela de um desses apps, ela
  e engolida (o scrcpy nao a ve) e vai para a fila;
- quem trabalha junta os giros de ~60 ms, converte o ponto da janela para a
  tela virtual do app (a imagem pode ter tarja dos lados) e manda
  `input -d <tela> swipe` pela conversa aberta com o celular.

So existe enquanto ha app com a correcao aberto (`atualizar`).
"""

from __future__ import annotations

import logging
import queue
import threading
import time

log = logging.getLogger(__name__)

WM_MOUSEWHEEL = 0x020A
INJETADO = 0x01                 # LLMHF_INJECTED
PASSO = 0.12                    # fracao da altura da tela por giro (120)
JUNTAR_S = 0.06


class Rodinha:
    def __init__(self, mandar) -> None:
        """`mandar(serial, comando)`: entrega o comando ao celular."""
        self._mandar = mandar
        self._alvos: dict = {}      # pid -> (serial, tela, larg, alt)
        self._fila: "queue.SimpleQueue" = queue.SimpleQueue()
        self._gancho: threading.Thread | None = None
        self._id_gancho = 0
        self._trabalho: threading.Thread | None = None
        self._trava = threading.Lock()

    # -- quem tem a correcao ------------------------------------------------

    def atualizar(self, alvos: dict) -> None:
        with self._trava:
            self._alvos = dict(alvos)
            if self._alvos and self._gancho is None:
                self._gancho = threading.Thread(target=self._rodar_gancho,
                                                daemon=True, name="rodinha")
                self._gancho.start()
                if self._trabalho is None:
                    self._trabalho = threading.Thread(
                        target=self._trabalhar, daemon=True,
                        name="rodinha-arrasto")
                    self._trabalho.start()
            elif not self._alvos and self._gancho is not None:
                self._tirar_gancho()

    def _tirar_gancho(self) -> None:
        t, self._gancho = self._gancho, None
        try:
            import ctypes
            ctypes.WinDLL("user32").PostThreadMessageW(self._id_gancho,
                                                       0x0012, 0, 0)  # WM_QUIT
        except Exception:
            pass
        if t is not None and t is not threading.current_thread():
            t.join(timeout=1.0)

    # -- o gancho -------------------------------------------------------------

    def _rodar_gancho(self) -> None:
        import ctypes
        from ctypes import wintypes
        try:
            u = ctypes.WinDLL("user32")
            k = ctypes.WinDLL("kernel32")
            LRESULT = ctypes.c_ssize_t

            class MSLLHOOKSTRUCT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long),
                            ("mouseData", wintypes.DWORD),
                            ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                            ("dwExtraInfo", ctypes.c_size_t)]

            PROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, ctypes.c_size_t,
                                      ctypes.c_ssize_t)
            u.SetWindowsHookExW.argtypes = [ctypes.c_int, PROC,
                                            ctypes.c_void_p, wintypes.DWORD]
            u.SetWindowsHookExW.restype = ctypes.c_void_p
            u.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                         ctypes.c_size_t, ctypes.c_ssize_t]
            u.CallNextHookEx.restype = LRESULT
            u.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
            u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG),
                                      ctypes.c_void_p, ctypes.c_uint,
                                      ctypes.c_uint]
            u.WindowFromPoint.argtypes = [wintypes.POINT]
            u.WindowFromPoint.restype = ctypes.c_void_p
            u.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            u.GetAncestor.restype = ctypes.c_void_p
            u.GetWindowThreadProcessId.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
            k.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
            k.GetModuleHandleW.restype = ctypes.c_void_p

            def gancho(codigo, wparam, lparam):
                try:
                    if codigo >= 0 and wparam == WM_MOUSEWHEEL:
                        d = MSLLHOOKSTRUCT.from_address(lparam)
                        if not d.flags & INJETADO:
                            hwnd = u.WindowFromPoint(wintypes.POINT(d.x, d.y))
                            raiz = u.GetAncestor(hwnd, 2) if hwnd else None
                            if raiz:
                                pid = wintypes.DWORD()
                                u.GetWindowThreadProcessId(raiz,
                                                           ctypes.byref(pid))
                                if pid.value in self._alvos:
                                    giro = ctypes.c_short(
                                        (d.mouseData >> 16) & 0xFFFF).value
                                    self._fila.put((pid.value, raiz, d.x, d.y,
                                                    giro, time.monotonic()))
                                    return 1      # engolida: o scrcpy nao ve
                except Exception:
                    pass
                return u.CallNextHookEx(None, codigo, wparam, lparam)

            proc = PROC(gancho)
            self._id_gancho = k.GetCurrentThreadId()
            h = u.SetWindowsHookExW(14, proc, k.GetModuleHandleW(None), 0)
            msg = wintypes.MSG()
            try:
                while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    pass
            finally:
                if h:
                    u.UnhookWindowsHookEx(h)
        except Exception:
            log.exception("rodinha: o gancho falhou")

    # -- o arrasto ------------------------------------------------------------

    def _trabalhar(self) -> None:
        while True:
            ev = self._fila.get()
            if ev is None:
                return
            pid, hwnd, x, y, giro, _t = ev
            fim = time.monotonic() + JUNTAR_S
            while time.monotonic() < fim:     # junta os giros seguidos
                try:
                    outro = self._fila.get(timeout=max(
                        0.0, fim - time.monotonic()))
                except queue.Empty:
                    break
                if outro is None:
                    return
                if outro[0] == pid:
                    giro += outro[4]
                    x, y = outro[2], outro[3]
                else:
                    self._fila.put(outro)
                    break
            try:
                self._arrastar(pid, hwnd, x, y, giro)
            except Exception:
                log.exception("rodinha: o arrasto falhou")

    @staticmethod
    def _cliente(hwnd):
        """(x0, y0, largura, altura) da area de dentro da janela, na tela."""
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        r = wintypes.RECT()
        u.GetClientRect(ctypes.c_void_p(hwnd), ctypes.byref(r))
        p = wintypes.POINT(0, 0)
        u.ClientToScreen(ctypes.c_void_p(hwnd), ctypes.byref(p))
        return p.x, p.y, r.right - r.left, r.bottom - r.top

    @staticmethod
    def ponto_na_tela(cliente, larg: int, alt: int, x: int, y: int):
        """O ponto da janela -> o da tela virtual (com a tarja descontada)."""
        cx, cy, cw, ch = cliente
        if cw <= 0 or ch <= 0 or larg <= 0 or alt <= 0:
            return None
        esc = min(cw / float(larg), ch / float(alt))
        ox, oy = (cw - larg * esc) / 2.0, (ch - alt * esc) / 2.0
        dx = (x - cx - ox) / esc
        dy = (y - cy - oy) / esc
        return (int(max(1, min(larg - 2, dx))),
                int(max(1, min(alt - 2, dy))))

    @staticmethod
    def arrasto(alt: int, py: int, giro: int):
        """(y de inicio, y de fim, ms): rodinha para cima = o dedo desce."""
        dist = int(alt * PASSO * giro / 120.0)
        dist = max(-int(alt * 0.8), min(int(alt * 0.8), dist))
        cima, baixo = int(alt * 0.05), int(alt * 0.95)
        y1 = max(cima, min(baixo, py))
        y2 = y1 + dist
        if y2 > baixo:
            y1, y2 = max(cima, baixo - dist), baixo
        elif y2 < cima:
            y1, y2 = min(baixo, cima - dist), cima
        ms = min(450, 220 + 40 * abs(giro) // 120)
        return y1, y2, ms

    def _arrastar(self, pid, hwnd, x, y, giro) -> None:
        alvo = self._alvos.get(pid)
        if not alvo or not giro:
            return
        serial, tela, larg, alt = alvo
        ponto = self.ponto_na_tela(self._cliente(hwnd), larg, alt, x, y)
        if ponto is None:
            return
        y1, y2, ms = self.arrasto(alt, ponto[1], giro)
        self._mandar(serial, "input -d %s swipe %d %d %d %d %d"
                     % (tela, ponto[0], y1, ponto[0], y2, ms))
