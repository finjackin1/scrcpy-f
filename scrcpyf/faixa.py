"""
A faixa: um risquinho discreto na borda da tela mostrando onde o celular esta.

Pedido dele (18/set/2026): no lugar do quadradinho que aparecia na borda, so
uma "bordinha" marcando o trecho que leva o mouse para o celular -- visivel
com a extensao ligada e enquanto ele escolhe o lugar na janela, e "bem
discreta, que nao incomode em nada".

O QUE ELA E
------------
Uma janela do proprio Windows (nao do Tk), sem moldura, de 2 px de espessura
ao longo do trecho, na cor de acento com pouca opacidade. Ela:

- deixa o mouse ATRAVESSAR (WS_EX_TRANSPARENT): nunca rouba um clique;
- nunca recebe foco nem aparece na barra de tarefas ou no Alt+Tab;
- fica por cima das outras janelas, senao sumiria atras de qualquer uma.

POR QUE WIN32 E NAO TK: a posicao vem em pixels reais (ver `monitores.py`), e
o Tk deste programa enxerga pixels "de mentira" quando o Windows esta com
escala. Esta janela vive numa thread propria, ciente de escala, e fala a
mesma medida do vigia.

ANIMACAO (pedido dele, 18/set/2026: "a transicao entre as telas tem que ser
mais suave, se possivel com uma animacao")
-----------------------------------------------------------------------------
A faixa nao some nem aparece de estalo: a opacidade vai ate o alvo numa
curva suave (comeca devagar, acelera, freia), com DURACAO FIXA medida no
relogio -- nao por quadro, senao um quadro atrasado mudaria a velocidade no
meio (queixa dele: "rapida e lenta em momentos diferentes"). `brilhar()` acende a faixa no maximo na hora -- o vigia usa
na troca: ao entrar ela brilha e se apaga (o mouse "atravessou"), ao voltar
ela brilha e assenta no discreto de sempre.

DOIS PEDIDOS, UMA FAIXA
------------------------
Quem pede e o vigia (extensao ligada) e a janela (previa, enquanto a aba
Extensao esta na tela). O pedido do vigia ganha; sem ele, vale a previa; sem
nenhum, a faixa some. Os dois so deixam o pedido e a thread da faixa aplica.
"""

from __future__ import annotations

import logging
import math
import sys
import threading
import time

from . import monitores as mon, tema

log = logging.getLogger(__name__)

NO_WINDOWS = sys.platform == "win32"

ESPESSURA = 2            # px reais
OPACIDADE = 130          # de 255: discreta, mas visivel num fundo escuro
PARADA_S = 1.0               # so para reconferir de vez em quando
INTERVALO_S = 0.03
QUADRO_S = 0.008         # enquanto anima
BRILHO = 255
DURACAO_S = 0.22         # acender/apagar
DURACAO_BRILHO_S = 0.34  # do brilho de volta ao alvo


# ESTILO AJUSTAVEL (visual novo, 21/set/2026, aba "personalizar"): cor,
# transparencia, espessura e o brilho ao trocar de tela. Os valores acima sao
# o ponto de partida; `Faixa.definir_estilo` muda estes globais, que o vigia
# e a previa leem na hora de pedir (por isso ninguem guarda copia deles).
COR = "#FF5A1F"
BRILHAR = True


def _canais(cor: str) -> tuple[int, int, int]:
    cor = (cor or "#FF5A1F").lstrip("#")
    try:
        return int(cor[0:2], 16), int(cor[2:4], 16), int(cor[4:6], 16)
    except (ValueError, IndexError):
        return 255, 90, 31


def retangulo(alvo) -> tuple[int, int, int, int] | None:
    """(x, y, largura, altura) da faixa para um trecho de `monitores.trecho`."""
    if alvo is None:
        return None
    m, lado, inicio, fim = alvo
    if lado == "direita":
        return (m["x"] + m["l"] - ESPESSURA, inicio, ESPESSURA, fim - inicio)
    if lado == "esquerda":
        return (m["x"], inicio, ESPESSURA, fim - inicio)
    if lado == "baixo":
        return (inicio, m["y"] + m["a"] - ESPESSURA, fim - inicio, ESPESSURA)
    return (inicio, m["y"], fim - inicio, ESPESSURA)


class Faixa:
    def __init__(self) -> None:
        self._trava = threading.Lock()
        self._pedidos = {"vigia": None, "previa": None}
        self._brilhar = threading.Event()
        # Acorda a thread quando chega pedido novo (ver `_acordar`).
        self._novidade = threading.Event()
        self._thread: threading.Thread | None = None
        self._sair = threading.Event()

    # -- quem pede ------------------------------------------------------------

    def _acordar(self) -> None:
        """Tira a thread do sono (ver o fim de `_rodar`)."""
        self._novidade.set()

    def definir_estilo(self, cor: str, transparencia: float, espessura: int,
                       brilhar: bool) -> None:
        """
        A aparencia da marca. `transparencia` de 0 (opaca) a 0,9; espessura
        em pixels reais (2 a 8). Vale na hora -- a thread repinta sozinha.
        """
        global COR, OPACIDADE, ESPESSURA, BRILHAR
        COR = cor if isinstance(cor, str) and cor.startswith("#") else "#FF5A1F"
        transparencia = min(0.9, max(0.0, float(transparencia)))
        OPACIDADE = max(20, int(round(255 * (1.0 - transparencia))))
        ESPESSURA = min(8, max(2, int(espessura)))
        BRILHAR = bool(brilhar)
        with self._trava:
            # Pedidos ja feitos passam a usar a opacidade nova (quem pediu
            # "apagada", alfa 0, continua apagada).
            for quem, pedido in list(self._pedidos.items()):
                if pedido and pedido[1] > 0:
                    self._pedidos[quem] = (pedido[0], OPACIDADE)
        self._acordar()

    def pedir(self, quem: str, ret, alfa: int | None = None) -> None:
        """
        `ret` = (x, y, l, a) em pixels reais, ou None para retirar. `alfa` e
        a opacidade de destino: 0 apaga a faixa suavemente sem soltar o
        lugar (o vigia usa com o mouse no celular).
        """
        if alfa is None:
            alfa = OPACIDADE
        with self._trava:
            self._pedidos[quem] = (tuple(ret), int(alfa)) if ret else None
        self._garantir_thread()
        self._acordar()

    def brilhar(self) -> None:
        """Acende no maximo agora; a animacao leva de volta ao alvo."""
        if not BRILHAR:
            return
        self._brilhar.set()
        self._garantir_thread()
        self._acordar()

    def encerrar(self) -> None:
        self._sair.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _desejado(self):
        with self._trava:
            return self._pedidos["vigia"] or self._pedidos["previa"]

    # -- a thread --------------------------------------------------------------

    def _garantir_thread(self) -> None:
        if not NO_WINDOWS or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._rodar, daemon=True,
                                        name="faixa")
        self._thread.start()

    def _rodar(self) -> None:
        try:
            with mon.pixels_reais():
                self._laco()
        except Exception:
            # Sem faixa a extensao funciona igual; so perde o risquinho.
            log.exception("a faixa parou")

    def _laco(self) -> None:
        import ctypes
        from ctypes import wintypes

        u = ctypes.WinDLL("user32")
        g = ctypes.WinDLL("gdi32")
        k = ctypes.WinDLL("kernel32")
        w = ctypes.WinDLL("winmm")
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_uint,
                                     ctypes.c_size_t, ctypes.c_ssize_t)

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("style", ctypes.c_uint),
                        ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int),
                        ("hInstance", ctypes.c_void_p),
                        ("hIcon", ctypes.c_void_p),
                        ("hCursor", ctypes.c_void_p),
                        ("hbrBackground", ctypes.c_void_p),
                        ("lpszMenuName", ctypes.c_wchar_p),
                        ("lpszClassName", ctypes.c_wchar_p),
                        ("hIconSm", ctypes.c_void_p)]

        u.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                     ctypes.c_size_t, ctypes.c_ssize_t]
        u.DefWindowProcW.restype = LRESULT
        u.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
        u.RegisterClassExW.restype = ctypes.c_ushort
        u.CreateWindowExW.argtypes = [
            wintypes.DWORD, ctypes.c_wchar_p, ctypes.c_wchar_p, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        u.CreateWindowExW.restype = ctypes.c_void_p
        u.SetLayeredWindowAttributes.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                                 ctypes.c_ubyte, wintypes.DWORD]
        u.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_uint]
        u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u.DestroyWindow.argtypes = [ctypes.c_void_p]
        u.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), ctypes.c_void_p,
                                   ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        g.CreateSolidBrush.argtypes = [wintypes.DWORD]
        g.CreateSolidBrush.restype = ctypes.c_void_p
        g.DeleteObject.argtypes = [ctypes.c_void_p]
        k.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        k.GetModuleHandleW.restype = ctypes.c_void_p

        def proc(hwnd, msg, wparam, lparam):
            return u.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc = WNDPROC(proc)          # vivo enquanto a thread vive
        r, gr, b = _canais(COR)
        pincel = g.CreateSolidBrush(r | (gr << 8) | (b << 16))   # 0x00BBGGRR
        cor_aplicada = COR
        # Trocar a cor com a janela ja criada: novo pincel de fundo da classe
        # e um pedido de repintura.
        try:
            troca_pincel = u.SetClassLongPtrW
        except AttributeError:
            troca_pincel = u.SetClassLongW
        troca_pincel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        troca_pincel.restype = ctypes.c_void_p
        u.InvalidateRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                     wintypes.BOOL]
        instancia = k.GetModuleHandleW(None)
        classe = WNDCLASSEXW()
        classe.cbSize = ctypes.sizeof(WNDCLASSEXW)
        classe.lpfnWndProc = wndproc
        classe.hInstance = instancia
        classe.hbrBackground = pincel
        classe.lpszClassName = "scrcpy-f-faixa"
        u.RegisterClassExW(ctypes.byref(classe))

        # LAYERED | TRANSPARENT | TOPMOST | TOOLWINDOW | NOACTIVATE
        estilo_ex = 0x00080000 | 0x00000020 | 0x00000008 | 0x00000080 | 0x08000000
        hwnd = u.CreateWindowExW(estilo_ex, "scrcpy-f-faixa", "", 0x80000000,
                                 0, 0, 1, 1, None, None, instancia, None)
        if not hwnd:
            log.warning("nao consegui criar a faixa")
            return
        u.SetLayeredWindowAttributes(hwnd, 0, OPACIDADE, 0x2)   # LWA_ALPHA

        lugar = None             # retangulo aplicado
        mostrando = False
        atual = 0.0              # opacidade na tela agora
        gravada = -1             # ultima opacidade mandada ao Windows
        curva = None             # (de, para, inicio, duracao)
        alvo_da_curva = None
        msg = wintypes.MSG()
        fino = False
        try:
            while not self._sair.is_set():
                while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    u.TranslateMessage(ctypes.byref(msg))
                    u.DispatchMessageW(ctypes.byref(msg))
                desejado = self._desejado()
                ret, alvo = desejado if desejado else (None, 0)
                agora = time.perf_counter()

                if COR != cor_aplicada:
                    # A pessoa escolheu outra cor na aba personalizar.
                    r, gr, b = _canais(COR)
                    novo = g.CreateSolidBrush(r | (gr << 8) | (b << 16))
                    if novo:
                        troca_pincel(hwnd, -10, novo)       # GCLP_HBRBACKGROUND
                        g.DeleteObject(pincel)
                        pincel = novo
                        u.InvalidateRect(hwnd, None, True)
                    cor_aplicada = COR

                if ret is None:
                    # Sem pedido nenhum (extensao desligada, aba fechada):
                    # sai de cena na hora, sem animacao.
                    self._brilhar.clear()
                    if mostrando:
                        u.ShowWindow(hwnd, 0)
                        mostrando = False
                    lugar, atual, curva, alvo_da_curva = None, 0.0, None, None
                else:
                    if self._brilhar.is_set():
                        self._brilhar.clear()
                        atual = float(BRILHO)
                        curva = (atual, float(alvo), agora, DURACAO_BRILHO_S)
                        alvo_da_curva = alvo
                    elif alvo != alvo_da_curva:
                        curva = (atual, float(alvo), agora, DURACAO_S)
                        alvo_da_curva = alvo
                    if curva is not None:
                        de, para, inicio, duracao = curva
                        t = min(1.0, (agora - inicio) / duracao)
                        # Seno: sai devagar, acelera, chega devagar.
                        f = (1 - math.cos(math.pi * t)) / 2
                        atual = de + (para - de) * f
                        if t >= 1.0:
                            curva = None

                    valor = int(round(atual))
                    if valor != gravada:
                        u.SetLayeredWindowAttributes(hwnd, 0, max(1, valor),
                                                     0x2)
                        gravada = valor
                    if valor <= 0:
                        if mostrando:
                            u.ShowWindow(hwnd, 0)
                            mostrando = False
                    elif ret != lugar or not mostrando:
                        x, y, l, a = ret
                        # HWND_TOPMOST, SHOWWINDOW | NOACTIVATE
                        u.SetWindowPos(hwnd, ctypes.c_void_p(-1), int(x),
                                       int(y), max(1, int(l)), max(1, int(a)),
                                       0x0040 | 0x0010)
                        lugar, mostrando = ret, True

                # Relogio fino so enquanto anima (ver `borda.relogio_fino`).
                animando = curva is not None
                if animando != fino:
                    try:
                        (w.timeBeginPeriod if animando else w.timeEndPeriod)(1)
                        fino = animando
                    except Exception:
                        pass
                # DORMIR DE VERDADE QUANDO NAO HA NADA (21/set/2026): sem
                # faixa na tela e sem animacao, a thread esperava acordada
                # ~33 vezes por segundo para sempre. Agora ela fica parada
                # ate alguem pedir alguma coisa (`_acordar`).
                if animando:
                    time.sleep(QUADRO_S)
                elif ret is None:
                    self._novidade.wait(PARADA_S)
                    self._novidade.clear()
                else:
                    time.sleep(INTERVALO_S)
        finally:
            if fino:
                try:
                    w.timeEndPeriod(1)
                except Exception:
                    pass
            u.DestroyWindow(hwnd)
            g.DeleteObject(pincel)
            del wndproc
