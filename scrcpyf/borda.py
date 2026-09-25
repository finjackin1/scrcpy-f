"""
O vigia da borda: quando o mouse do PC encosta no lado onde o celular fica,
mouse e teclado passam a mandar no celular; Alt (ou desligar) devolve.

COMO FUNCIONA (caminho A, testado por ele em 18/set/2026)
----------------------------------------------------------
O modo "extensao" sobe um scrcpy SEM IMAGEM, com teclado, mouse e controle
simulados como aparelhos fisicos no celular (UHID -- o Android enxerga como
se estivessem ligados por Bluetooth, com cursor proprio). Esse scrcpy tem uma
janelinha, e e ela quem recebe o mouse e o teclado: quando a janela "pega" o
mouse, o cursor some do PC e aparece no celular. Tab duas vezes devolve.

Este modulo faz a costura:

1. acha a janelinha do scrcpy e a deixa fora da barra de tarefas e
   escondida. Quando aparece, a janela tem o tamanho de sempre (64 px), mas
   RECORTADA num pontinho de 4 px no meio -- o resto nao e desenhado (ver
   `LADO_DA_JANELINHA`);
2. olha onde esta o mouse ~60 vezes por segundo (so uma pergunta ao Windows:
   custo desprezivel, e so enquanto a extensao esta ligada);
3. mouse encostou no trecho da borda: poe a janelinha debaixo do ponteiro e
   CLICA nela. O clique traz a janela para a frente e o scrcpy pega o mouse.
   O primeiro clique as vezes so ativa a janela (o SDL, que desenha a janela
   do scrcpy, ignora o clique que ativa); por isso confere e clica de novo,
   SO se ainda nao pegou -- senao o segundo clique iria parar no celular;
4. enquanto o mouse esta la, TODO o teclado vai para o celular, inclusive o
   que o Windows pegaria (ver `GanchoDeTeclas`);
5. a volta: 2x Tab (pelo gancho) ou qualquer perda de foco da janelinha.
   Esconde a janelinha -- o foco volta para a janela que estava antes -- e
   poe o ponteiro de novo junto da borda, um pouco para dentro, na altura em
   que ele saiu.

A VOLTA PELA BORDA NAO EXISTE NESTE CAMINHO: o scrcpy nao diz onde o cursor
esta dentro do celular, entao nao ha como saber que ele "saiu pelo outro
lado". Volta e por tecla. Registrado no CONTEXTO.

PIXELS REAIS: a thread inteira roda "ciente de escala por monitor" (ver
`monitores.py`), para mouse, monitores e janela falarem a mesma medida.

SEGURANCAS
----------
- Nao entra com botao do mouse apertado (arrastando janela, selecionando).
- Nao entra se algum programa esta prendendo o mouse numa area menor que o
  monitor (jogo em tela cheia): o mouse preso num jogo que encosta na borda
  nao pode escapar para o celular.
- Depois de voltar, um intervalo curto antes de poder entrar de novo.
- Ao desligar no meio, devolve o mouse (solta a trava, esconde a janela).
"""

from __future__ import annotations

from collections import deque
import logging
import sys
import threading
import time
from contextlib import contextmanager

from . import monitores as mon, sistema

log = logging.getLogger(__name__)

NO_WINDOWS = sys.platform == "win32"

INTERVALO_S = 0.016          # ~60 olhadas por segundo, longe da borda
# PERTO DA BORDA E DENTRO DO CELULAR, O DOBRO (21/set/2026, "delay acima de
# estabilidade"): e nesses dois momentos que o atraso aparece -- a hora de
# detectar que o ponteiro encostou, e a hora de notar que ele voltou. Longe
# da borda nao ha nada para ver, e olhar menos poupa a maquina para o jogo.
INTERVALO_PERTO_S = 0.008    # ~120 olhadas por segundo
PERTO_DA_BORDA_PX = 400
RELER_MONITORES_S = 2.0      # monitor ligado/desligado no meio do uso
PROCURAR_JANELA_S = 0.25
# A janelinha tem 64 px, INTEIRA dentro da tela, encostada na borda -- o
# tamanho e o lugar da primeira versao, a que funcionou. O que mudou e o
# RECORTE: so um pontinho de PONTO_VISIVEL px no meio dela e desenhado, e e
# justamente ali que o SDL prende o ponteiro quando pega o mouse.
#
# Historico (18/set/2026), para nao repetir:
# - 64 px sem recorte: funcionava, mas aparecia um quadradinho na borda;
# - quase toda fora da tela: o meio ficava fora, o mouse nao era preso e
#   andava no celular E no PC ao mesmo tempo;
# - 4 px: o ponteiro escapava do quadrado entre achar a borda e clicar, e o
#   clique caia em outra janela -- "nao pegou" ou volta na hora.
LADO_DA_JANELINHA = 64
PONTO_VISIVEL = 4
# A tela do celular e acesa quando o mouse vem rapido e ja esta a menos
# disto da borda (e de novo ao entrar): quando ele chega, ela ja esta acesa.
ACORDAR_A_PX = 300
RECUO_NA_VOLTA = 40          # px para dentro, ao desistir de uma entrada
# A VOLTA (pedido dele, 18/set/2026: "bem perto pra nao perceber que e so uma
# animacao", "natural do comeco ao fim"): o ponteiro reaparece colado na
# borda e freia como um movimento de verdade -- sai com a velocidade com que
# ele tinha chegado na borda e para por desaceleracao constante. Distancia e
# duracao saem dessa velocidade, dentro destes limites:
VOLTA_MIN_PX, VOLTA_MAX_PX = 4, 14
VOLTA_MIN_S, VOLTA_MAX_S = 0.06, 0.14
VELOCIDADE_PADRAO = 600.0    # px/s, se nao deu para medir a chegada
# Depois de voltar, um instante antes de poder entrar de novo (senao o mouse,
# parado colado na borda, iria e voltaria sem parar). Curto: quem volta e
# logo quer ir de novo nao pode sentir a borda "grudar".
# CALIBRAR SO COM A MAO PARADA (pedido dele, 21/set/2026). A calibracao
# empurra o cursor do celular ate o canto para saber onde ele esta; se a mao
# estiver andando nessa hora, o movimento dela entra na conta e a calibracao
# nasce torta. Entao o vigia espera o ponteiro ficar parado -- normalmente
# menos de meio segundo -- e so ai calibra, avisando na janela enquanto isso.
PARADO_S = 0.22              # ponteiro sem se mexer por este tempo
ENTRE_CALIBRACOES_S = 1.5    # respiro entre uma tentativa e a proxima
TENTATIVAS_DE_CALIBRAR = 3   # depois disso, espera a primeira passagem
ESPERA_ENTRE_ENTRADAS = 0.12
ESPERA_DEPOIS_DE_FALHAR = 1.5


def disponivel() -> bool:
    return NO_WINDOWS


class _Win:
    """As chamadas ao Windows, com os tipos declarados uma vez so."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ct = ctypes
        self.wt = wintypes
        # Copia PROPRIA do user32: os tipos declarados aqui nao podem brigar
        # com os que outros modulos declaram no `windll.user32` compartilhado.
        u = ctypes.WinDLL("user32")
        self.u = u

        LONG_PTR = ctypes.c_ssize_t
        HWND = ctypes.c_void_p

        u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        u.GetClipCursor.argtypes = [ctypes.POINTER(wintypes.RECT)]
        u.ClipCursor.argtypes = [ctypes.c_void_p]   # RECT* ou None
        u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        u.GetAsyncKeyState.restype = ctypes.c_short
        u.GetForegroundWindow.restype = HWND
        u.IsWindow.argtypes = [HWND]
        u.IsWindowVisible.argtypes = [HWND]
        u.GetForegroundWindow.argtypes = []
        u.ShowWindow.argtypes = [HWND, ctypes.c_int]
        u.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        u.GetWindowThreadProcessId.argtypes = [HWND,
                                               ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowTextW.argtypes = [HWND, ctypes.c_wchar_p, ctypes.c_int]
        # No Python de 32 bits as versoes "Ptr" nao existem no user32.
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self._ler_estilo = u.GetWindowLongPtrW
            self._gravar_estilo = u.SetWindowLongPtrW
        else:
            self._ler_estilo = u.GetWindowLongW
            self._gravar_estilo = u.SetWindowLongW
        self._ler_estilo.argtypes = [HWND, ctypes.c_int]
        self._ler_estilo.restype = LONG_PTR
        self._gravar_estilo.argtypes = [HWND, ctypes.c_int, LONG_PTR]
        self._gravar_estilo.restype = LONG_PTR
        u.GetWindowRect.argtypes = [HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetClassNameW.argtypes = [HWND, ctypes.c_wchar_p, ctypes.c_int]
        u.SetLayeredWindowAttributes.argtypes = [HWND, wintypes.DWORD,
                                                 ctypes.c_ubyte, wintypes.DWORD]

        class CURSORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("hCursor", ctypes.c_void_p),
                        ("ptScreenPos", wintypes.POINT)]
        self.CURSORINFO = CURSORINFO
        u.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                        ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                        ("wParamH", wintypes.WORD)]

        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT),
                        ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

        self.INPUT = INPUT
        u.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT),
                                ctypes.c_int]

        u.PostMessageW.argtypes = [HWND, ctypes.c_uint, ctypes.c_size_t,
                                   ctypes.c_ssize_t]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD,
                                        wintypes.BOOL]
        u.BringWindowToTop.argtypes = [HWND]
        u.SetForegroundWindow.argtypes = [HWND]
        k = ctypes.WinDLL("kernel32")
        k.GetCurrentThreadId.restype = wintypes.DWORD
        self.k = k

        g = ctypes.WinDLL("gdi32")
        g.CreateRectRgn.argtypes = [ctypes.c_int] * 4
        g.CreateRectRgn.restype = ctypes.c_void_p
        u.SetWindowRgn.argtypes = [HWND, ctypes.c_void_p, wintypes.BOOL]
        self.g = g

        self.ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, ctypes.c_void_p)
        u.EnumWindows.argtypes = [self.ENUM, ctypes.c_void_p]


    # -- mouse ---------------------------------------------------------------

    def ponteiro(self) -> tuple[int, int]:
        p = self.wt.POINT()
        self.u.GetCursorPos(self.ct.byref(p))
        return (p.x, p.y)

    def mover(self, x: int, y: int) -> None:
        self.u.SetCursorPos(int(x), int(y))

    def botao_apertado(self) -> bool:
        # VK_LBUTTON, VK_RBUTTON, VK_MBUTTON
        return any(self.u.GetAsyncKeyState(vk) & 0x8000 for vk in (1, 2, 4))

    def trava(self) -> tuple[int, int, int, int] | None:
        """A area onde o ponteiro esta preso agora (sem trava = a tela toda)."""
        r = self.wt.RECT()
        if not self.u.GetClipCursor(self.ct.byref(r)):
            return None
        return (r.left, r.top, r.right, r.bottom)

    def capturado(self, nossa=None) -> bool:
        """
        O scrcpy esta com o mouse? Quando pega, o SDL esconde o ponteiro e o
        prende num quadradinho dentro da janelinha (que tem 64 px). Qualquer
        um dos dois sinais basta -- versoes diferentes do SDL fazem um ou os
        dois. Comparar com um quadrado pequeno, e nao com "a tela toda",
        dispensa saber o tamanho da tela na mesma escala.

        `nossa` e a trava que o proprio vigia pos antes de clicar: ela nao
        conta como sinal (senao "pegou" seria sempre verdade).
        """
        if self.escondido():
            return True
        t = self.trava()
        return (bool(t) and t != tuple(nossa or ())
                and (t[2] - t[0]) <= 200 and (t[3] - t[1]) <= 200)

    def livre(self, tela: tuple[int, int, int, int]) -> bool:
        """
        O ponteiro anda solto pela TELA INTEIRA (todos os monitores)? Um jogo
        em tela cheia prende o ponteiro no proprio monitor -- que e do tamanho
        do monitor, e nao menor -- entao "solto" tem que ser comparado com a
        tela toda: qualquer trava, de qualquer tamanho, bloqueia a borda.
        """
        t = self.trava()
        if not t:
            return True
        return (t[0] <= tela[0] + 2 and t[1] <= tela[1] + 2
                and t[2] >= tela[2] - 2 and t[3] >= tela[3] - 2)

    def tela_cheia_em(self, m: dict) -> bool:
        """
        A janela da frente cobre o monitor inteiro (jogo ou video em tela
        cheia sem prender o mouse)? A area de trabalho tambem "cobre", mas
        nao conta.
        """
        frente = self.u.GetForegroundWindow()
        if not frente:
            return False
        classe = self.ct.create_unicode_buffer(64)
        self.u.GetClassNameW(frente, classe, 64)
        if classe.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False
        r = self.wt.RECT()
        if not self.u.GetWindowRect(frente, self.ct.byref(r)):
            return False
        return (r.left <= m["x"] and r.top <= m["y"]
                and r.right >= m["x"] + m["l"] and r.bottom >= m["y"] + m["a"])

    def visivel(self, hwnd) -> bool:
        return bool(self.u.IsWindowVisible(hwnd))

    def escondido(self) -> bool:
        ci = self.CURSORINFO()
        ci.cbSize = self.ct.sizeof(self.CURSORINFO)
        if not self.u.GetCursorInfo(self.ct.byref(ci)):
            return False
        return not (ci.flags & 1) or not ci.hCursor

    def soltar_trava(self) -> None:
        self.u.ClipCursor(None)

    def prender_em(self, ret: tuple[int, int, int, int]) -> None:
        """Prende o ponteiro (escondido) dentro de (esq, topo, dir, baixo)."""
        r = self.wt.RECT(*ret)
        self.u.ClipCursor(self.ct.byref(r))

    def clicar(self) -> None:
        dados = (self.INPUT * 2)()
        for i, bandeira in enumerate((0x0002, 0x0004)):   # LEFTDOWN, LEFTUP
            dados[i].type = 0                              # INPUT_MOUSE
            dados[i].u.mi.dwFlags = bandeira
        self.u.SendInput(2, dados, self.ct.sizeof(self.INPUT))

    # -- janela --------------------------------------------------------------

    def achar(self, pid: int, titulo: str):
        """A janela visivel do processo `pid` com o titulo dado, ou None."""
        achada = []

        def cada(hwnd, _dado):
            dono = self.wt.DWORD()
            self.u.GetWindowThreadProcessId(hwnd, self.ct.byref(dono))
            if dono.value == pid:
                texto = self.ct.create_unicode_buffer(256)
                self.u.GetWindowTextW(hwnd, texto, 256)
                if titulo in texto.value:
                    achada.append(hwnd)
                    return False
            return True

        self.u.EnumWindows(self.ENUM(cada), None)
        return achada[0] if achada else None

    def existe(self, hwnd) -> bool:
        return bool(hwnd) and bool(self.u.IsWindow(hwnd))

    def preparar(self, hwnd) -> None:
        """Quase invisivel, fora da barra de tarefas, e escondida."""
        GWL_EXSTYLE = -20
        estilo = self._ler_estilo(hwnd, GWL_EXSTYLE)
        estilo |= 0x00080000 | 0x00000080          # LAYERED | TOOLWINDOW
        estilo &= ~0x00040000                       # sem APPWINDOW
        self.u.ShowWindow(hwnd, 0)                  # SW_HIDE (reler o estilo)
        self._gravar_estilo(hwnd, GWL_EXSTYLE, estilo)
        self.u.SetLayeredWindowAttributes(hwnd, 0, 1, 0x2)   # LWA_ALPHA
        # Sem a animacao de abrir do Windows (aquele "surgir" das janelas):
        # ela desenha a janela INTEIRA por um instante, por cima do recorte.
        try:
            valor = self.ct.c_int(1)
            self.ct.WinDLL("dwmapi").DwmSetWindowAttribute(
                self.ct.c_void_p(hwnd), 3,          # DWMWA_TRANSITIONS_FORCEDISABLED
                self.ct.byref(valor), self.ct.sizeof(valor))
        except Exception:
            pass

    def aquecer(self, hwnd) -> None:
        """
        Mostra a janelinha uma vez FORA de todas as telas e esconde de novo.

        Por que (teste dele, 19/set/2026: "mancha na borda" so na PRIMEIRA
        passagem depois de ligar a extensao): a primeira vez que a janela
        aparece, o Windows e o scrcpy fazem a preparacao de desenho dela --
        e isso aparecia na borda por um instante. Feito aqui, longe de
        qualquer tela, ninguem ve; as passagens de verdade ja pegam a janela
        pronta.
        """
        t, p = LADO_DA_JANELINHA, PONTO_VISIVEL
        a = (t - p) // 2
        self.u.SetWindowRgn(hwnd, self.g.CreateRectRgn(a, a, a + p, a + p),
                            False)
        self.u.SetWindowPos(hwnd, self.ct.c_void_p(-1), -32000, -32000, t, t,
                            0x0040 | 0x0010)        # SHOWWINDOW | NOACTIVATE
        time.sleep(0.2)
        self.u.ShowWindow(hwnd, 0)

    def por_debaixo(self, hwnd, x: int, y: int) -> None:
        """
        Mostra a janelinha em (x, y), por cima de tudo, sem ativar, recortada
        no pontinho do meio. O recorte e aplicado ANTES de mostrar, para o
        quadrado inteiro nao piscar na tela.
        """
        t, p = LADO_DA_JANELINHA, PONTO_VISIVEL
        a = (t - p) // 2
        # O Windows passa a ser dono da regiao: nao apagar.
        self.u.SetWindowRgn(hwnd, self.g.CreateRectRgn(a, a, a + p, a + p),
                            False)
        self.u.SetWindowPos(hwnd, self.ct.c_void_p(-1), int(x), int(y), t, t,
                            0x0040 | 0x0010)        # SHOWWINDOW | NOACTIVATE

    def rajada(self, dx: int, dy: int, vezes: int) -> None:
        """`vezes` movimentos injetados numa chamada so: chegam de uma vez."""
        self.movimentos([(dx, dy)] * vezes)

    def movimentos(self, lista) -> None:
        """Movimentos injetados (dx, dy), todos numa chamada so."""
        if not lista:
            return
        dados = (self.INPUT * len(lista))()
        for d, (dx, dy) in zip(dados, lista):
            d.type = 0
            d.u.mi.dx, d.u.mi.dy = int(dx), int(dy)
            d.u.mi.dwFlags = 0x0001                    # MOUSEEVENTF_MOVE
        self.u.SendInput(len(lista), dados, self.ct.sizeof(self.INPUT))

    def tem_o_teclado(self, hwnd) -> bool:
        """
        A janelinha ja recebeu o foco do teclado DENTRO do scrcpy? Trazer para
        a frente e pedido a outro programa: ele processa quando puder. So
        depois disso a tecla de captura e ouvida.
        """
        ct, wt = self.ct, self.wt

        class GUITHREADINFO(ct.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD),
                        ("hwndActive", ct.c_void_p), ("hwndFocus", ct.c_void_p),
                        ("hwndCapture", ct.c_void_p),
                        ("hwndMenuOwner", ct.c_void_p),
                        ("hwndMoveSize", ct.c_void_p),
                        ("hwndCaret", ct.c_void_p), ("rcCaret", wt.RECT)]

        info = GUITHREADINFO()
        info.cbSize = ct.sizeof(GUITHREADINFO)
        dono = self.u.GetWindowThreadProcessId(hwnd, None)
        if not dono or not self.u.GetGUIThreadInfo(dono, ct.byref(info)):
            return False
        return (info.hwndFocus or 0) == (hwnd or 0)

    def passou_por_cima(self, hwnd) -> None:
        """
        Avisa a janelinha que o mouse passou sobre o meio dela, sem mexer no
        ponteiro de verdade (ver o uso em `Borda._entrar`).
        """
        meio = LADO_DA_JANELINHA // 2
        self.u.PostMessageW(hwnd, 0x0200, 0, (meio << 16) | meio)  # MOUSEMOVE

    def soltar_scrcpy(self, hwnd) -> None:
        """
        Pede ao PROPRIO scrcpy que solte o mouse: a tecla de atalho dele
        (Windows da direita, `--shortcut-mod=rsuper`) apertada e solta
        sozinha liga/desliga a captura. Vai direto para a janela dele, entao
        o Windows nao ve a tecla (o menu Iniciar nao abre).

        Por que (teste dele, 18/set/2026): so esconder a janela deixava o
        scrcpy achando que ainda estava com o mouse -- ele seguia recebendo o
        movimento e os cliques e prendendo o ponteiro, e o mouse "continuava
        no celular" depois do 2x Tab.
        """
        VK_RWIN, SCAN = 0x5C, 0x5C
        base = 1 | (SCAN << 16) | (1 << 24)             # repeticao 1, estendida
        self.u.PostMessageW(hwnd, 0x0100, VK_RWIN, base)                 # DOWN
        self.u.PostMessageW(hwnd, 0x0101, VK_RWIN,
                            base | (1 << 30) | (1 << 31))                # UP

    def ativar(self, hwnd) -> None:
        """
        Devolve a frente da tela a `hwnd` (a janela que estava ativa antes de
        entrar). Junta-se por um instante a fila de entrada da janela da
        frente: sem isso o Windows recusa o pedido vindo de outro programa.
        """
        frente = self.u.GetForegroundWindow()
        minha = self.k.GetCurrentThreadId()
        dela = self.u.GetWindowThreadProcessId(frente, None) if frente else 0
        juntou = bool(dela and dela != minha
                      and self.u.AttachThreadInput(minha, dela, True))
        try:
            self.u.BringWindowToTop(hwnd)
            self.u.SetForegroundWindow(hwnd)
        finally:
            if juntou:
                self.u.AttachThreadInput(minha, dela, False)

    def esconder(self, hwnd) -> None:
        self.u.ShowWindow(hwnd, 0)

    def na_frente(self):
        return self.u.GetForegroundWindow()


class GanchoDeTeclas:
    """
    TODO o teclado vai para o celular enquanto o mouse esta la -- inclusive o
    que o Windows pegaria para si -- e 2x Tab devolve tudo ao PC.

    POR QUE (pedidos dele, 18/set/2026): com o mouse no celular, a tecla
    Windows abria o Iniciar do PC; depois ele pediu que TODOS os atalhos do
    Windows ficassem bloqueados, e que a volta fosse com Tab duas vezes. O
    Windows trata a tecla Windows, Alt+Tab, Ctrl+Esc, Alt+F4 e companhia no
    proprio sistema, ANTES de a janela com foco ver qualquer coisa.

    COMO: um gancho de teclado de baixo nivel ENGOLE toda tecla de verdade
    (assim o sistema nao sabe dela e nenhum atalho do Windows dispara) e a
    entrega direto na janelinha do scrcpy, como se tivesse sido apertada ali.
    O scrcpy repassa ao celular como teclado fisico. O primeiro Tab vai para o
    celular normalmente; se outro Tab vier em ate `JANELA_2X_TAB_S`, ele e
    engolido e vira o pedido de volta.

    O QUE NAO DA: Ctrl+Alt+Del e Win+L sao do Windows e ninguem intercepta --
    e ainda bem: sao a saida de emergencia se algo travar.

    O CUSTO: gancho de teclado e o mecanismo que o `motor_atalhos.py` evita de
    proposito (antivirus desconfia, toda tecla passa por ele). Aqui e aceito
    porque so existe enquanto o mouse esta no celular -- que e justamente
    quando toda tecla TEM que ir para outro lugar.
    """

    TAB = 0x09
    JANELA_2X_TAB_S = 0.35
    # VOLUME DO CELULAR (pergunta dele, 19/set/2026, teclado 60%): as teclas
    # de volume do teclado, se houver (camada Fn), e Ctrl+Alt+= / Ctrl+Alt+-
    # (e Ctrl+Alt+0 para mudo) -- teclas que todo teclado 60% tem sem Fn. Com
    # AltGr (Alt da direita) tambem vale: o Windows manda AltGr como Ctrl+Alt.
    VOLUME_DIRETO = {0xAF: "subir", 0xAE: "descer", 0xAD: "mudo"}
    VOLUME_COM_CTRL_ALT = {0xBB: "subir", 0xBD: "descer", 0x30: "mudo"}
    CTRL = {0x11, 0xA2, 0xA3}
    SHIFT = {0x10, 0xA0, 0xA1}
    ALT = {0x12, 0xA4, 0xA5}
    INJETADA = 0x10          # LLKHF_INJECTED
    ESTENDIDA = 0x01         # LLKHF_EXTENDED

    def __init__(self, hwnd, ao_pedir_volta, ao_volume=None) -> None:
        self.hwnd = hwnd
        self._ao_pedir_volta = ao_pedir_volta
        self._ao_volume = ao_volume
        self._thread: threading.Thread | None = None
        self._id_thread = 0
        self._pronto = threading.Event()

    def ligar(self) -> None:
        if self._thread is not None:
            return
        self._pronto.clear()
        self._thread = threading.Thread(target=self._rodar, daemon=True,
                                        name="gancho-teclas")
        self._thread.start()
        self._pronto.wait(1.0)

    def desligar(self) -> None:
        if self._thread is None:
            return
        try:
            import ctypes
            ctypes.WinDLL("user32").PostThreadMessageW(self._id_thread,
                                                       0x0012, 0, 0)  # WM_QUIT
        except Exception:
            pass
        self._thread.join(timeout=1.0)
        self._thread = None

    def _rodar(self) -> None:
        try:
            self._instalar_e_ouvir()
        except Exception:
            # Sem gancho a extensao continua funcionando -- os atalhos do
            # Windows voltam a agir no PC e a volta fica so pela perda de foco.
            log.exception("o gancho de teclas falhou")
        finally:
            self._pronto.set()

    def _instalar_e_ouvir(self) -> None:
        import ctypes
        from ctypes import wintypes

        u = ctypes.WinDLL("user32")
        k = ctypes.WinDLL("kernel32")
        LRESULT = ctypes.c_ssize_t

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        PROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, ctypes.c_size_t,
                                  ctypes.c_ssize_t)
        u.SetWindowsHookExW.argtypes = [ctypes.c_int, PROC, ctypes.c_void_p,
                                        wintypes.DWORD]
        u.SetWindowsHookExW.restype = ctypes.c_void_p
        u.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                     ctypes.c_size_t, ctypes.c_ssize_t]
        u.CallNextHookEx.restype = LRESULT
        u.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        u.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                   ctypes.c_size_t, ctypes.c_ssize_t]
        u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), ctypes.c_void_p,
                                  ctypes.c_uint, ctypes.c_uint]
        k.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        k.GetModuleHandleW.restype = ctypes.c_void_p

        hwnd = self.hwnd
        estado = {"ultimo_tab": 0.0, "tab_segurado": False,
                  "engolir_tab_ate_subir": False, "apertadas": set(),
                  "engolidas": {}}

        def volume(vk: int, subiu: bool):
            """True = a tecla e de volume e ja foi tratada (engolir)."""
            engolidas = estado["engolidas"]
            if vk in engolidas:
                if subiu:
                    del engolidas[vk]
                    return True
                acao = engolidas[vk]          # segurando: repete o volume
            else:
                if subiu or self._ao_volume is None:
                    return False
                acao = self.VOLUME_DIRETO.get(vk)
                if acao is None:
                    ap = estado["apertadas"]
                    if ap & self.CTRL and ap & self.ALT:
                        acao = self.VOLUME_COM_CTRL_ALT.get(vk)
                if acao is None:
                    return False
                engolidas[vk] = acao
            try:
                self._ao_volume(acao)
            except Exception:
                pass
            return True

        def entregar(tecla, subiu: bool) -> None:
            # A mensagem que a janela receberia se a tecla tivesse chegado
            # nela: repeticao 1, codigo da tecla, bit de estendida, e os bits
            # de "estava apertada" e "soltou" quando e soltura.
            info = 1 | (tecla.scanCode & 0xFF) << 16
            if tecla.flags & self.ESTENDIDA:
                info |= 1 << 24
            if subiu:
                info |= (1 << 30) | (1 << 31)
            u.PostMessageW(hwnd, 0x0101 if subiu else 0x0100,
                           tecla.vkCode, info)

        def gancho(n, wparam, lparam):
            try:
                if n == 0:
                    tecla = ctypes.cast(lparam,
                                        ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    if not tecla.flags & self.INJETADA:
                        subiu = wparam in (0x0101, 0x0105)   # KEYUP, SYSKEYUP
                        # O gancho engole as teclas, entao o Windows nao
                        # sabe o que esta apertado: a conta e nossa.
                        if subiu:
                            estado["apertadas"].discard(tecla.vkCode)
                        else:
                            estado["apertadas"].add(tecla.vkCode)
                        if volume(tecla.vkCode, subiu):
                            return 1
                        if tecla.vkCode in self.SHIFT:
                            # SHIFT PASSA DIRETO (teste dele, 19/set/2026: o
                            # "?" saia "/"). O SDL, que o scrcpy usa, confere
                            # a cada volta se o Windows ainda ve o Shift
                            # apertado e, se nao ve, o solta -- e engolido, o
                            # Windows nunca o via. Solto para o sistema, ele
                            # chega na janelinha (que e a da frente) do jeito
                            # normal. Sozinho, Shift nao dispara atalho nenhum
                            # do Windows: Ctrl, Alt e a tecla Windows, que
                            # formariam os atalhos com ele, continuam presos.
                            return u.CallNextHookEx(None, n, wparam, lparam)
                        if tecla.vkCode == self.TAB:
                            if subiu:
                                estado["tab_segurado"] = False
                                if estado["engolir_tab_ate_subir"]:
                                    estado["engolir_tab_ate_subir"] = False
                                    return 1
                            elif not estado["tab_segurado"]:
                                # Tab novo (nao a repeticao de tecla segurada).
                                estado["tab_segurado"] = True
                                agora = time.monotonic()
                                if agora - estado["ultimo_tab"] <= self.JANELA_2X_TAB_S:
                                    estado["ultimo_tab"] = 0.0
                                    estado["engolir_tab_ate_subir"] = True
                                    self._ao_pedir_volta()
                                    return 1
                                estado["ultimo_tab"] = agora
                            elif estado["engolir_tab_ate_subir"]:
                                return 1
                        entregar(tecla, subiu)
                        return 1                              # engole
            except Exception:
                pass
            return u.CallNextHookEx(None, n, wparam, lparam)

        proc = PROC(gancho)          # segurado vivo ate o fim da thread
        self._id_thread = k.GetCurrentThreadId()
        manivela = u.SetWindowsHookExW(13, proc, k.GetModuleHandleW(None), 0)
        self._pronto.set()
        if not manivela:
            log.warning("nao consegui instalar o gancho de teclas")
            return
        try:
            msg = wintypes.MSG()
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                pass
        finally:
            u.UnhookWindowsHookEx(manivela)
            del proc


# ---------------------------------------------------------------------------
# Volta pela borda do celular (pedido dele, 18/set/2026: "da pra voltar o
# mouse sem o tab?" -> escolheu "empurrar na borda")
# ---------------------------------------------------------------------------
#
# O Android NAO diz onde o cursor esta (sonda de 18/set/2026). Entao o vigia
# CALCULA: ouve o movimento cru do mouse do PC (o mesmo que o scrcpy repassa
# ao celular) e aplica a mesma curva de aceleracao que o Android aplica -- a
# curva vem do proprio celular (`dumpsys input`, aparelho "scrcpy"). Na
# entrada o cursor e empurrado ate a borda do lado do PC (posicao conhecida:
# zero); dali em diante o vigia soma.
#
# A volta: o cursor calculado CHEGOU na borda do lado do PC e a mao continua
# indo -- troca na hora, como entre dois monitores (pedido dele, 19/set/2026:
# "tem que trocar a tela assim que chegar no limite de uma e nao ficar
# empurrando"). Antes era preciso empurrar 200 px alem da borda, com a conta
# atrasada de proposito (movimento para o PC valendo 85%) para nunca voltar
# cedo -- e esse empurrao era o que deixava a troca "bugada". Agora a conta
# vale 1:1 e basta passar da borda. O risco aceito: a conta e uma estimativa
# (o Android nao diz onde o cursor esta), entao as vezes pode voltar um pouco
# antes ou um pouco depois do cursor encostar de verdade.

# Quanto o cursor precisa passar da borda para a troca acontecer. Agora que a
# conta bate com o cursor de verdade (CPI certo, 21/set/2026), volta a ser
# "encostou, trocou" -- so que com um fio de folga em vez de 1 px, para um
# tremido da mao na borda nao jogar ninguem para o PC.
EMPURRAO_PX = 6
EMPURRAO_CONTAGENS = 1
# A MAO NAO PARA NA ENTRADA (teste dele, 18/set/2026: rapido, o cursor do
# celular "aparece colado na borda e nao vai o equivalente ao movimento"): o
# movimento feito entre encostar na borda e o celular estar pronto e gravado
# e REPETIDO no celular logo depois, com o mesmo ritmo -- ate este tanto:
REPETIR_ATE_S = 0.25
# Tempo em que o ajuste da entrada (levar o cursor do celular ao ponto
# equivalente) e espalhado: curto para nao se notar, longo o bastante para o
# celular nao acelerar no maximo.
AJUSTE_S = 0.18
# O ajuste da entrada e uma conta em cima de outra conta: quanto MAIOR o
# pedaco a percorrer, mais ele erra, e o cursor nasce fora do lugar (relato
# dele, 21/set/2026: "essa deteccao buga as vezes"). Entao:
# - salto grande AO LONGO da borda: nada de conta -- empurra ate o canto,
#   que e posicao certa, e volta o que falta (o caminho forte de sempre);
# - salto pequeno: ajuste suave, com o tempo esticado conforme o tamanho,
#   para o Android nao entrar no ganho maximo no meio do caminho.
SALTO_GRANDE = 0.35          # fracao do lado do celular
AJUSTE_MAX_S = 0.30
VELOCIDADE_DO_AJUSTE = 4000.0    # px do celular por segundo
FATOR_NA_DIRECAO_DO_PC = 1.0
EMPURRAO_SOLTO_S = 0.35      # parou de empurrar por mais que isso: zera
# SO VALE EMPURRAO QUE VAI PARA O PC (teste dele, 20/set/2026: "com o
# celular em retrato o mouse nao vai ate o final da tela, ele volta pro pc").
# Com o empurrao de 1 pixel, descer o cursor rente a borda do lado do PC --
# o caminho natural ate a barra de baixo, e bem mais longo em retrato -- com
# um desvio minimo da mao para o lado do PC ja contava como "voltar". Agora
# o movimento recente tem que apontar MAIS para o PC do que ao longo da
# borda (angulo de ate 45 graus). Empurrar de proposito continua imediato.
RAZAO_DO_EMPURRAO = 1.0
# QUANTO EMPURRAR PARA VOLTAR, conforme a CONFIANCA da conta (teste dele,
# 20/set/2026, celular em cima: "as vezes no meio da tela vai pro pc").
# A conta e uma estimativa: o erro dela cresce com o tanto que o cursor
# andou desde a ultima vez em que a posicao era certa (a entrada poe o
# cursor colado na borda do PC -- ali a conta vale; encostar na borda oposta
# tambem vale). Entao o empurrao pedido para voltar cresce junto: logo
# depois de entrar basta encostar; depois de atravessar a tela inteira pede
# um empurraozinho -- ainda curto, mas o bastante para a conta atrasada nao
# jogar a pessoa para o PC no meio da tela.
# A margem larga (30%, teto 300 px) era o remendo de enquanto a conta errava
# o cursor. Com o CPI certo ela voltou a ser fina (pedido dele, 21/set/2026:
# "o momento de voltar e quando chegar no limite da tela, ao encostar"):
# poucos pixels de folga, que crescem devagar com o caminho andado.
ERRO_POR_PX = 0.05           # 5% do caminho andado
EMPURRAO_MAX_PX = 60.0
# QUANTAS CONTAGENS DO MOUSE O ANDROID CONTA POR MILIMETRO.
# A curva de aceleracao do celular e escrita em mm/s, e o mouse do scrcpy nao
# declara resolucao nenhuma (no `dumpsys input`: "resolution=0.000") -- entao
# o Android usa o valor que ele supoe. A sonda do celular dele (20/set/2026)
# mostrou esse valor: "Mouse CPI (real): [1000.000000]" -- 1000 contagens por
# polegada, e nao as 800 que estavam aqui. Com 800, a conta achava que a mao
# ia MAIS RAPIDO do que ia, pegava um ganho maior na curva e andava mais que
# o cursor de verdade -- e por isso "voltava pro PC na metade da tela".
CPI_PADRAO = 1000.0
CONTAGENS_POR_MM = CPI_PADRAO / 25.4
JANELA_DA_VELOCIDADE_S = 0.08
# A curva do celular dele (Android 16, sensibilidade padrao), para quando nao
# der para perguntar: {velocidade maxima mm/s, ganho base, reciproco}.
CURVA_PADRAO = [(32.002, 2.0416, 0.0), (52.83, 3.0656, -32.80256),
                (119.124, 4.6592, -116.95168), (float("inf"), 9.6256, -708.83584)]
TELA_PADRAO = (1080, 2340)


def ler_celular(texto: str) -> dict:
    """
    Do `dumpsys input` do celular: a curva de aceleracao do mouse do scrcpy
    e o tamanho da tela como esta agora (girada ou nao). Campo que nao achar
    fica de fora.
    """
    import re
    info: dict = {}
    m = re.search(r"logicalFrame=\[(-?\d+), (-?\d+), (-?\d+), (-?\d+)\]",
                  texto)
    if m:
        l, t, r, b = (int(v) for v in m.groups())
        if r > l and b > t:
            info["tela"] = (r - l, b - t)
    # O bloco do MOUSE do scrcpy (ele cria dois aparelhos: teclado e mouse).
    # A curva tem que sair DESTE bloco: pega-la do texto inteiro pegaria a de
    # outro aparelho do celular (o touchpad, por exemplo), com outros numeros.
    alvo = texto
    for pedaco in re.findall(r"Device \d+: scrcpy\b(.*?)(?=\n  Device \d+:|\Z)",
                             texto, re.S):
        if "Cursor Input Mapper" in pedaco:
            alvo = pedaco
            break

    # Contagens por milimetro que o Android supoe deste mouse (ver
    # CONTAGENS_POR_MM). Vem em polegadas.
    cpi = re.search(r"Mouse CPI[^\[]*\[([0-9.]+)\]", texto)
    if cpi:
        try:
            valor = float(cpi.group(1))
            if valor > 0:
                info["contagens_por_mm"] = valor / 25.4
        except ValueError:
            pass
    c = re.search(r"Acceleration Curve[^\n]*\n((?:\s*\{[^}]*\}\n?)+)", alvo)
    if c:
        curva = []
        for linha in re.findall(r"\{([^}]*)\}", c.group(1)):
            partes = [p.strip() for p in linha.split(",")]
            try:
                curva.append((float(partes[0]), float(partes[1]),
                              float(partes[2])))
            except (ValueError, IndexError):
                curva = []
                break
        if curva:
            info["curva"] = curva
    return info


def ganho(curva, contagens_por_s: float, contagens_por_mm: float = None) -> float:
    """Pixels do celular por contagem do mouse, na velocidade dada."""
    mm_s = contagens_por_s / (contagens_por_mm or CONTAGENS_POR_MM)
    if mm_s <= 0:
        return curva[0][1]
    for limite, base, reciproco in curva:
        if mm_s <= limite:
            return max(0.1, base + reciproco / mm_s)
    return curva[-1][1]


class Estimativa:
    """
    Onde o cursor esta no celular, so no eixo que importa: a distancia (em
    pixels do celular) ate a borda do lado do PC. Pura conta, sem Windows --
    da para testar fora dele.
    """

    def __init__(self, lado: str, largura_util: int, curva,
                 comprimento: int = 1,
                 contagens_por_mm: float = CONTAGENS_POR_MM) -> None:
        # Movimento do mouse que AFASTA do PC, por lado onde o celular esta.
        self._eixo = {"direita": (1, 0), "esquerda": (-1, 0),
                      "baixo": (0, 1), "cima": (0, -1)}[lado]
        # E o eixo AO LONGO da borda (de cima para baixo nos lados, da
        # esquerda para a direita em cima/embaixo): da onde o mouse sai no
        # PC -- saiu pelo alto do celular, aparece no alto do trecho.
        self._longo = (0, 1) if lado in ("direita", "esquerda") else (1, 0)
        self.comprimento = max(1, int(comprimento))
        self.ao_longo = 0.0
        self.limite = max(1, int(largura_util))
        self.curva = curva
        self.contagens_por_mm = contagens_por_mm or CONTAGENS_POR_MM
        self.distancia = 0.0
        self.empurrao = 0.0
        self.empurrao_contagens = 0.0
        # Quanto o cursor andou (em px do celular, no eixo que importa) desde
        # a ultima posicao CERTA. Quanto maior, menos a conta vale.
        self.percorrido = 0.0
        self.velocidade = 0.0
        self.ultimo_ganho = curva[0][1]
        self.disparou = False
        self._ultimo_empurrao = 0.0
        # A janela dos ultimos movimentos, para a velocidade. Fila com soma
        # guardada: antes cada movimento somava a janela inteira de novo, e
        # um mouse de jogo manda centenas por segundo (21/set/2026).
        self._recentes: deque = deque()
        self._soma_x = 0
        self._soma_y = 0

    def mover(self, dx: int, dy: int, agora: float,
              empurra: bool = True) -> bool:
        """
        Soma um movimento cru. True = empurrou a borda o bastante: voltar.
        `empurra=False`: movimento do proprio vigia (o ajuste da entrada) --
        conta na posicao, mas nunca vale como empurrao de volta.
        """
        # O scrcpy manda ao celular no maximo 127 por movimento (e corta o
        # resto): a conta corta igual, senao "andaria" mais que o cursor.
        dx = max(-127, min(127, dx))
        dy = max(-127, min(127, dy))
        recentes = self._recentes
        recentes.append((agora, dx, dy))
        self._soma_x += dx
        self._soma_y += dy
        limite_t = agora - JANELA_DA_VELOCIDADE_S
        while recentes and recentes[0][0] < limite_t:
            _t, vx, vy = recentes.popleft()
            self._soma_x -= vx
            self._soma_y -= vy
        sx, sy = self._soma_x, self._soma_y
        vel = (sx * sx + sy * sy) ** 0.5 / JANELA_DA_VELOCIDADE_S
        self.velocidade = vel
        g = ganho(self.curva, vel, self.contagens_por_mm)
        self.ultimo_ganho = g

        self.ao_longo = min(float(self.comprimento), max(
            0.0, self.ao_longo + (dx * self._longo[0] + dy * self._longo[1]) * g))
        contagens = dx * self._eixo[0] + dy * self._eixo[1]
        afasta = contagens * g
        if afasta < 0:
            afasta *= FATOR_NA_DIRECAO_DO_PC
        antes = self.distancia
        depois = antes + afasta
        self.percorrido += abs(afasta)
        # POSICAO CERTA DE NOVO: empurrando na borda oposta a do PC, o cursor
        # esta encostado nela de verdade, por mais que a conta tenha errado
        # o caminho -- a tela do celular acaba ali.
        if afasta > 0 and antes >= self.limite:
            self.distancia = float(self.limite)
            self.percorrido = 0.0
        if not empurra:
            self.distancia = min(float(self.limite), max(0.0, depois))
            return False
        if afasta < 0:
            if agora - self._ultimo_empurrao > EMPURRAO_SOLTO_S:
                self.empurrao = 0.0
                self.empurrao_contagens = 0.0
            self._ultimo_empurrao = agora
            rumo_pc = -(sx * self._eixo[0] + sy * self._eixo[1])
            de_lado = abs(sx * self._longo[0] + sy * self._longo[1])
            if depois < 0 and rumo_pc >= de_lado * RAZAO_DO_EMPURRAO:
                passou = min(-depois, -afasta)  # o que passou da borda
                self.empurrao += passou
                self.empurrao_contagens += -contagens * passou / -afasta
        elif afasta > 0:
            self.empurrao = 0.0
            self.empurrao_contagens = 0.0
        self.distancia = min(float(self.limite), max(0.0, depois))
        if (self.empurrao >= self.empurrao_pedido
                and self.empurrao_contagens >= EMPURRAO_CONTAGENS):
            self.percorrido = 0.0        # colado na borda do PC: certo
            return True
        return False

    @property
    def empurrao_pedido(self) -> float:
        """Quanto empurrar na borda para voltar, dada a confianca de agora."""
        return min(EMPURRAO_MAX_PX,
                   max(float(EMPURRAO_PX), self.percorrido * ERRO_POR_PX))

    @property
    def fracao(self) -> float:
        """Onde o cursor esta ao longo da borda: 0 = inicio, 1 = fim."""
        return self.ao_longo / self.comprimento

    def semear(self, dx: int, dy: int, vezes: int, agora: float) -> None:
        """
        O empurrao da entrada (injetado) entra so na VELOCIDADE, nao na
        posicao: o Android tambem viu esse movimento rapido e, por uns
        instantes, acelera o que vier depois. Sem isto a conta ficaria atras
        do cursor logo na entrada.
        """
        dx = max(-127, min(127, dx))
        dy = max(-127, min(127, dy))
        for _ in range(vezes):
            self._recentes.append((agora, dx, dy))
            self._soma_x += dx
            self._soma_y += dy

    def na_borda(self) -> None:
        self.distancia = 0.0
        self.empurrao = 0.0
        self.empurrao_contagens = 0.0
        self._recentes.clear()
        self._soma_x = self._soma_y = 0


class LeitorDoMouse:
    """
    Ouve o movimento CRU do mouse (Raw Input, mesmo com outra janela na
    frente) e entrega (dx, dy, instante) a `ao_mover`. So os mouses de
    verdade: o movimento que o proprio vigia injeta (o empurrao da entrada)
    vem sem aparelho e e ignorado.
    """

    def __init__(self, ao_mover) -> None:
        self._ao_mover = ao_mover
        self._thread: threading.Thread | None = None
        self._id_thread = 0
        self._pronto = threading.Event()

    def ligar(self) -> None:
        if self._thread is not None:
            return
        self._pronto.clear()
        self._thread = threading.Thread(target=self._rodar, daemon=True,
                                        name="leitor-mouse")
        self._thread.start()
        self._pronto.wait(1.0)

    def desligar(self) -> None:
        if self._thread is None:
            return
        try:
            import ctypes
            ctypes.WinDLL("user32").PostThreadMessageW(self._id_thread,
                                                       0x0012, 0, 0)  # WM_QUIT
        except Exception:
            pass
        self._thread.join(timeout=1.0)
        self._thread = None

    def _rodar(self) -> None:
        try:
            self._ouvir()
        except Exception:
            # Sem leitor, so a volta pela borda deixa de existir; 2x Tab segue.
            log.exception("o leitor do mouse falhou")
        finally:
            self._pronto.set()

    def _ouvir(self) -> None:
        import ctypes
        from ctypes import wintypes

        u = ctypes.WinDLL("user32")
        k = ctypes.WinDLL("kernel32")
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

        class RAWINPUTDEVICE(ctypes.Structure):
            _fields_ = [("usUsagePage", ctypes.c_ushort),
                        ("usUsage", ctypes.c_ushort),
                        ("dwFlags", wintypes.DWORD),
                        ("hwndTarget", ctypes.c_void_p)]

        class RAWINPUTHEADER(ctypes.Structure):
            _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                        ("hDevice", ctypes.c_void_p),
                        ("wParam", ctypes.c_size_t)]

        class _Botoes(ctypes.Structure):
            _fields_ = [("usButtonFlags", ctypes.c_ushort),
                        ("usButtonData", ctypes.c_ushort)]

        class _UniaoBotoes(ctypes.Union):
            _fields_ = [("ulButtons", ctypes.c_ulong), ("b", _Botoes)]

        class RAWMOUSE(ctypes.Structure):
            _fields_ = [("usFlags", ctypes.c_ushort), ("u", _UniaoBotoes),
                        ("ulRawButtons", ctypes.c_ulong),
                        ("lLastX", ctypes.c_long), ("lLastY", ctypes.c_long),
                        ("ulExtraInformation", ctypes.c_ulong)]

        class RAWINPUT(ctypes.Structure):
            _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]

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
        u.DestroyWindow.argtypes = [ctypes.c_void_p]
        u.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE),
                                              ctypes.c_uint, ctypes.c_uint]
        u.GetRawInputData.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                      ctypes.c_void_p,
                                      ctypes.POINTER(ctypes.c_uint),
                                      ctypes.c_uint]
        u.GetRawInputData.restype = ctypes.c_uint
        u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), ctypes.c_void_p,
                                  ctypes.c_uint, ctypes.c_uint]
        u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        k.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        k.GetModuleHandleW.restype = ctypes.c_void_p

        dado = RAWINPUT()
        tamanho_cab = ctypes.sizeof(RAWINPUTHEADER)
        # Um mouse de jogo manda centenas de pacotes por segundo: nada aqui
        # dentro pode criar objeto novo a cada pacote (21/set/2026).
        def proc(hwnd, msg, wparam, lparam):
            if msg == 0x00FF:                                  # WM_INPUT
                try:
                    tam = ctypes.c_uint(ctypes.sizeof(dado))
                    lido = u.GetRawInputData(ctypes.c_void_p(lparam), 0x10000003,
                                             ctypes.byref(dado), ctypes.byref(tam),
                                             tamanho_cab)
                    if (lido != 0xFFFFFFFF and dado.header.dwType == 0
                            and dado.header.hDevice
                            and not dado.mouse.usFlags & 0x01):   # so relativo
                        dx, dy = dado.mouse.lLastX, dado.mouse.lLastY
                        if dx or dy:
                            self._ao_mover(dx, dy, time.perf_counter())
                except Exception:
                    log.exception("leitura do mouse")
            return u.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc = WNDPROC(proc)
        instancia = k.GetModuleHandleW(None)
        classe = WNDCLASSEXW()
        classe.cbSize = ctypes.sizeof(WNDCLASSEXW)
        classe.lpfnWndProc = wndproc
        classe.hInstance = instancia
        classe.lpszClassName = "scrcpy-f-leitor-mouse"
        u.RegisterClassExW(ctypes.byref(classe))
        # Janela so de mensagens (pai HWND_MESSAGE): nunca aparece.
        hwnd = u.CreateWindowExW(0, "scrcpy-f-leitor-mouse", "", 0, 0, 0, 0, 0,
                                 ctypes.c_void_p(-3), None, instancia, None)
        self._id_thread = k.GetCurrentThreadId()
        if not hwnd:
            log.warning("nao consegui criar a janela do leitor do mouse")
            return
        pedido = RAWINPUTDEVICE(0x01, 0x02, 0x00000100, hwnd)   # INPUTSINK
        if not u.RegisterRawInputDevices(ctypes.byref(pedido), 1,
                                         ctypes.sizeof(RAWINPUTDEVICE)):
            log.warning("nao consegui ouvir o mouse cru")
            u.DestroyWindow(hwnd)
            return
        self._pronto.set()
        try:
            msg = wintypes.MSG()
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                u.TranslateMessage(ctypes.byref(msg))
                u.DispatchMessageW(ctypes.byref(msg))
        finally:
            fim = RAWINPUTDEVICE(0x01, 0x02, 0x00000001, None)    # REMOVE
            u.RegisterRawInputDevices(ctypes.byref(fim), 1,
                                      ctypes.sizeof(RAWINPUTDEVICE))
            u.DestroyWindow(hwnd)
            del wndproc


class Borda:
    """
    Uso:
        borda = Borda(pid, titulo, conf_da_borda, avisar, faixa)
        borda.iniciar()
        ...
        borda.definir(nova_conf)    # pela janela, a qualquer hora
        borda.parar()

    `avisar(evento, detalhe)` e chamado DA THREAD DO VIGIA -- quem recebe tem
    que so empilhar (o programa poe na fila de pedidos).
    Eventos: "pronta", "entrou", "voltou", "falhou", "sem_janela", "morreu".

    `faixa` (opcional) e a `faixa.Faixa` do programa: o vigia pede o risquinho
    no trecho enquanto esta ligado, e o tira quando um programa em tela cheia
    esta na frente daquele monitor.
    """

    def __init__(self, pid: int, titulo: str, conf: dict, avisar,
                 faixa=None, ler_celular=None, acordar=None,
                 volume=None) -> None:
        self.pid = pid
        self.titulo = titulo
        self._conf = dict(conf or {})
        self._avisar = avisar
        self._faixa = faixa
        self._trava = threading.Lock()
        self._parar = threading.Event()
        self._pedido_de_volta = threading.Event()
        self._thread: threading.Thread | None = None
        self.dentro = False
        self._gancho: GanchoDeTeclas | None = None
        # A janela que estava na frente antes de entrar: recebe a frente de
        # volta ao voltar (ver `_voltar`).
        self._anterior = None
        # Volta pela borda do celular: o que se sabe do celular (curva de
        # aceleracao e tamanho da tela, lidos dele por `ler_celular`, que
        # devolve o texto do `dumpsys input`), o calculo e o leitor do mouse.
        self._ler_celular = ler_celular
        self._celular = {"tela": TELA_PADRAO, "curva": CURVA_PADRAO,
                         "contagens_por_mm": CONTAGENS_POR_MM}
        self._lendo_celular = False
        self._anotou_celular = False
        self._estimativa: Estimativa | None = None
        self._leitor: LeitorDoMouse | None = None
        # Movimento cru gravado da hora que encostou na borda ate o celular
        # estar pronto (None = nao gravando). Ver REPETIR_ATE_S.
        self._gravando: list | None = None
        self._trava_mov = threading.Lock()
        self._motivo_da_volta = "2x Tab"
        self._primeira_entrada = True
        # Calibracao: `calibrada` e o que a janela mostra; `_precisa_calibrar`
        # e o que faz o vigia tentar de novo quando a mao parar.
        self.calibrada = False
        self._precisa_calibrar = True
        self._tentativas = 0
        self._ultimo_ponteiro = None
        self._parado_desde = 0.0
        self._proxima_calibracao = 0.0
        self._tempo_do_ajuste = AJUSTE_S
        # Onde o cursor do celular esta, pela conta (distancia da borda do
        # PC, posicao ao longo dela), guardado entre uma passagem e outra.
        # None = nao se sabe: a proxima entrada usa o empurrao forte.
        self._pos_celular = None
        self._lado = "direita"
        self._acordar = acordar
        self._volume = volume
        # Velocidade com que o ponteiro vinha em direcao a borda (px/s,
        # media suave das ultimas olhadas): da o "embalo" da volta.
        self._velocidade = VELOCIDADE_PADRAO
        self._retangulo_da_janela = (0, 0, 1, 1)

    def iniciar(self) -> bool:
        if not disponivel():
            return False
        self._atualizar_celular()
        self._thread = threading.Thread(target=self._rodar, daemon=True,
                                        name="borda")
        self._thread.start()
        return True

    def _atualizar_celular(self) -> None:
        """Pergunta ao celular (numa thread: adb demora) curva e tela."""
        if self._ler_celular is None or self._lendo_celular:
            return
        self._lendo_celular = True

        def trabalho():
            try:
                info = ler_celular(self._ler_celular() or "")
                if info:
                    with self._trava:
                        antes = dict(self._celular)
                        self._celular.update(info)
                        depois = dict(self._celular)
                    if depois != antes or not self._anotou_celular:
                        self._anotou_celular = True
                        self._aviso("celular", "tela %dx%d, curva %s" % (
                            depois["tela"][0], depois["tela"][1],
                            "lida" if "curva" in info else "padrao"))
                    # A TELA GIROU com o mouse no celular: a conta que esta
                    # rodando passa a usar as medidas novas na hora. (Antes
                    # isto estava no ramo errado e nunca acontecia: girar o
                    # celular no meio deixava a conta com a tela deitada.)
                    if depois.get("tela") != antes.get("tela"):
                        # Girou: o canto guardado era da tela de antes.
                        self._pos_celular = None
                        self._descalibrar("a tela do celular girou")
                    est = self._estimativa
                    if est is not None and depois.get("tela") != antes.get("tela"):
                        with self._trava_mov:
                            est.limite = max(1, self._largura_util(self._lado))
                            est.comprimento = max(
                                1, self._comprimento_util(self._lado))
                            est.distancia = min(est.distancia, float(est.limite))
                            est.ao_longo = min(est.ao_longo,
                                               float(est.comprimento))
                elif not self._anotou_celular:
                    self._anotou_celular = True
                    self._aviso("celular", "nao respondeu; usando o padrao")
            except Exception:
                log.exception("nao consegui ler o celular")
            finally:
                self._lendo_celular = False

        threading.Thread(target=trabalho, daemon=True,
                         name="ler-celular").start()

    def _largura_util(self, est_lado: str) -> int:
        """Quanto o cursor anda no celular, da borda do PC ate a oposta."""
        with self._trava:
            l, a = self._celular["tela"]
        return l if est_lado in ("direita", "esquerda") else a

    def _pedir_volta(self, motivo: str) -> None:
        self._motivo_da_volta = motivo
        self._pedido_de_volta.set()

    def _ao_mover(self, dx: int, dy: int, agora: float) -> None:
        """Da thread do leitor: cada movimento cru de um mouse de verdade."""
        with self._trava_mov:
            if self._gravando is not None:
                self._gravando.append((dx, dy, agora))
                return
            est = self._estimativa
            if est is None or est.disparou or not est.mover(dx, dy, agora):
                return
            est.disparou = True              # uma volta so
            # O numero fica no relatorio: e o que diz se a conta estava
            # atrasada quando a volta aconteceu.
            empurrou = est.empurrao
        self._pedir_volta("empurrou a borda, %d px" % round(empurrou))

    def definir(self, conf: dict) -> None:
        with self._trava:
            self._conf = dict(conf or {})

    def parar(self) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # -- a thread -------------------------------------------------------------

    def _aviso(self, evento: str, detalhe: str = "") -> None:
        try:
            self._avisar(evento, detalhe)
        except Exception:
            pass

    def _pedir_faixa(self, pedido) -> None:
        """`pedido` = (retangulo, opacidade) ou None."""
        if self._faixa is not None:
            if pedido:
                self._faixa.pedir("vigia", pedido[0], pedido[1])
            else:
                self._faixa.pedir("vigia", None)

    def _rodar(self) -> None:
        # O leitor do mouse fica ligado junto com o vigia (e nao so com o
        # mouse no celular): precisa gravar o movimento desde o instante em
        # que o mouse encosta na borda. Custo: uma mensagem por movimento do
        # mouse, descartada na hora quando nao ha nada a fazer.
        self._leitor = LeitorDoMouse(self._ao_mover)
        try:
            self._leitor.ligar()
        except Exception:
            log.exception("leitor do mouse")
        try:
            sistema.prioridade_da_thread()
            # RELOGIO FINO ENQUANTO A EXTENSAO DURA (21/set/2026): sem isto o
            # `sleep(0,016)` do laco virava ~31 ms na pratica -- o vigia
            # olhava a borda metade das vezes que devia, e a troca demorava o
            # dobro para ser percebida. O scrcpy ja roda com o relogio fino
            # enquanto espelha; aqui vale o mesmo custo.
            with relogio_fino(), mon.pixels_reais():
                self._laco(_Win())
        except Exception as erro:
            log.exception("o vigia da borda parou")
            self._aviso("morreu", str(erro))
        finally:
            self._pedir_faixa(None)
            if self._leitor is not None:
                self._leitor.desligar()
                self._leitor = None

    def _laco(self, w: _Win) -> None:
        from . import faixa as faixa_mod

        hwnd = None
        alvo = None
        ultimo_monitor = 0.0
        ultima_procura = 0.0
        pode_entrar_em = 0.0
        entrada = (0, 0)
        soltos = 0
        conf_usada = None
        tela = None
        faixa_pedida = "nada"
        inicio = time.monotonic()

        try:
            while not self._parar.is_set():
                agora = time.monotonic()

                with self._trava:
                    conf = self._conf
                if conf is not conf_usada or agora - ultimo_monitor > RELER_MONITORES_S:
                    lista = mon.listar(estrito=True)
                    # Falhou ao perguntar: fica com a borda que ja tinha.
                    if lista:
                        alvo = mon.trecho(lista, conf)
                        tela = (min(m["x"] for m in lista),
                                min(m["y"] for m in lista),
                                max(m["x"] + m["l"] for m in lista),
                                max(m["y"] + m["a"] for m in lista))
                    if conf_usada is not None and conf is not conf_usada:
                        # Celular em outro lado do monitor: o canto de onde a
                        # conta parte e outro.
                        self._descalibrar("o celular mudou de lugar")
                    ultimo_monitor = agora
                    conf_usada = conf

                # O risquinho da borda: some com programa em tela cheia na
                # frente daquele monitor, e com o mouse do lado do celular (ali
                # ele nao marca nada que se possa usar).
                if alvo is not None:
                    if w.tela_cheia_em(alvo[0]):
                        querida = None
                    else:
                        # Com o mouse no celular a faixa se APAGA devagar
                        # (alfa 0), sem soltar o lugar: na volta ela reacende
                        # no mesmo ponto.
                        querida = (faixa_mod.retangulo(alvo),
                                   0 if self.dentro else faixa_mod.OPACIDADE)
                    if querida != faixa_pedida:
                        self._pedir_faixa(querida)
                        faixa_pedida = querida

                if not w.existe(hwnd):
                    hwnd = None
                    if agora - ultima_procura > PROCURAR_JANELA_S:
                        ultima_procura = agora
                        hwnd = w.achar(self.pid, self.titulo)
                        if hwnd:
                            w.preparar(hwnd)
                            try:
                                w.aquecer(hwnd)
                            except Exception:
                                log.exception("aquecer a janelinha")
                            # A calibracao NAO acontece aqui: ela espera a mao
                            # parar (ver mais abaixo, no fim do laco).
                            self._descalibrar("a extensao ligou")
                            self._aviso("pronta")
                        elif agora - inicio > 15:
                            self._aviso("sem_janela")
                            inicio = float("inf")

                if self.dentro:
                    if self._pedido_de_volta.is_set():
                        self._pedido_de_volta.clear()
                        self._voltar(w, hwnd, alvo, entrada,
                                     self._motivo_da_volta)
                        pode_entrar_em = agora + ESPERA_ENTRE_ENTRADAS
                        soltos = 0
                    elif w.escondido() and w.na_frente() == hwnd:
                        # Ainda no celular: o scrcpy esconde o ponteiro e a
                        # janelinha continua na frente. A trava e re-afirmada a
                        # cada volta (ver `_entrar`); o SDL pode mexer nela.
                        # SO QUANDO ELA MUDA (21/set/2026): re-afirmar 60x por
                        # segundo era uma chamada ao Windows por quadro; agora
                        # confere antes -- se o SDL mexer, o proximo quadro ja
                        # poe de volta.
                        if w.trava() != self._retangulo_da_janela:
                            w.prender_em(self._retangulo_da_janela)
                        soltos = 0
                    else:
                        soltos += 1
                        # Duas olhadas seguidas soltas: nao e piscada.
                        if soltos >= 2:
                            self._voltar(w, hwnd, alvo, entrada, "soltou")
                            pode_entrar_em = agora + ESPERA_ENTRE_ENTRADAS
                            soltos = 0
                else:
                    # A janelinha tem que continuar escondida enquanto o mouse
                    # esta do lado do PC. Se algo a trouxe de volta, ela
                    # estaria segurando o teclado sem ninguem ver.
                    if hwnd and w.visivel(hwnd):
                        w.esconder(hwnd)
                pos = None
                if not self.dentro and alvo:
                    pos = w.ponteiro()
                    self._medir(pos, alvo, agora)
                    if (self._precisa_calibrar and hwnd
                            and self._tentativas < TENTATIVAS_DE_CALIBRAR
                            and agora >= self._proxima_calibracao
                            and self._mao_parada(pos, agora)
                            and not w.botao_apertado()):
                        self._proxima_calibracao = agora + ENTRE_CALIBRACOES_S
                        self._tentativas += 1
                        try:
                            self._calibrar(w, hwnd, alvo)
                        except Exception:
                            log.exception("calibrar")
                            w.soltar_trava()
                        self._ultimo_ponteiro = None
                if (pos is not None and hwnd and tela
                        and agora >= pode_entrar_em
                        and not w.botao_apertado() and w.livre(tela)):
                    if mon.tocou(pos, alvo) and not w.tela_cheia_em(alvo[0]):
                        if self._entrar(w, hwnd, alvo, pos):
                            entrada = pos
                        else:
                            pode_entrar_em = agora + ESPERA_DEPOIS_DE_FALHAR

                # Espera o que FALTA para o proximo quadro (o trabalho do
                # quadro ja passou), e acorda na hora se pedirem para parar.
                quadro = (INTERVALO_PERTO_S
                          if (self.dentro or self._perto_da_borda(pos, alvo))
                          else INTERVALO_S)
                self._parar.wait(max(0.001,
                                     quadro - (time.monotonic() - agora)))
        finally:
            # Desligou com o mouse do lado de la: devolve antes de sair.
            # (r165) Se a volta der erro no meio, o ponteiro NAO pode ficar
            # preso na janelinha: solta a trava de qualquer jeito.
            try:
                if self.dentro:
                    self._voltar(w, hwnd, alvo, entrada, "desligou")
                elif hwnd and w.existe(hwnd):
                    w.esconder(hwnd)
            except Exception:
                log.exception("borda: volta ao desligar")
                try:
                    w.soltar_trava()
                except Exception:
                    pass

    def _medir(self, pos, alvo, agora: float) -> None:
        """
        Quanto o ponteiro anda em direcao a borda, por segundo. E, se ele
        vem RAPIDO e ja perto do trecho, acende a tela do celular antes de o
        mouse chegar (pedido dele: "que ela acendesse assim que o mouse fosse
        jogado pra ela").
        """
        anterior = getattr(self, "_amostra", None)
        self._amostra = (pos, agora)
        if anterior is None:
            return
        (px, py), t0 = anterior
        dt = agora - t0
        if dt <= 0 or dt > 0.1:
            return
        self._talvez_acordar(pos, alvo, (pos[0] - px) / dt, (pos[1] - py) / dt)
        lado = alvo[1]
        if lado == "direita":
            rumo = pos[0] - px
        elif lado == "esquerda":
            rumo = px - pos[0]
        elif lado == "baixo":
            rumo = pos[1] - py
        else:
            rumo = py - pos[1]
        v = max(0.0, rumo / dt)
        if v > 0:
            self._velocidade = 0.6 * self._velocidade + 0.4 * v

    def _talvez_acordar(self, pos, alvo, vx: float, vy: float) -> None:
        m, lado, inicio, fim = alvo
        x, y = pos
        if lado == "direita":
            falta, rumo, ao_longo = m["x"] + m["l"] - 1 - x, vx, y
        elif lado == "esquerda":
            falta, rumo, ao_longo = x - m["x"], -vx, y
        elif lado == "baixo":
            falta, rumo, ao_longo = m["y"] + m["a"] - 1 - y, vy, x
        else:
            falta, rumo, ao_longo = y - m["y"], -vy, x
        # Chega na borda em menos de ~0,25 s, dentro do trecho (com folga).
        folga = (fim - inicio) // 4
        if (0 <= falta <= ACORDAR_A_PX and rumo > 0 and falta / rumo < 0.25
                and inicio - folga <= ao_longo < fim + folga):
            self._pedir_acordar()

    def _pedir_acordar(self) -> None:
        if self._acordar is not None:
            try:
                self._acordar()          # nunca espera (ver o programa)
            except Exception:
                log.exception("nao consegui acordar o celular")

    def _ponto_preso(self, alvo, pos) -> tuple[int, int]:
        """O meio da janelinha: onde o ponteiro fica preso no celular."""
        m = alvo[0]
        t = LADO_DA_JANELINHA
        x = min(max(pos[0], m["x"] + t // 2), m["x"] + m["l"] - t // 2)
        y = min(max(pos[1], m["y"] + t // 2), m["y"] + m["a"] - t // 2)
        return mon.para_dentro((x, y), alvo, t // 2)

    def _entrar(self, w: _Win, hwnd, alvo, pos) -> bool:
        """
        A janelinha (64 px, inteira dentro da tela, recortada num pontinho)
        vai para a borda, e o scrcpy recebe a tecla de captura: ele pega o
        mouse SEM clique (o clique de antes as vezes virava toque no
        celular).

        SEM PULO VISIVEL (pedido dele, 18/set/2026): o ponteiro NAO e levado
        ao pontinho antes -- ele fica onde encostou. Quem o leva e o proprio
        scrcpy, no instante em que pega o mouse e o esconde; so depois disso
        o vigia o prende no pontinho. O pulo de 32 px acontece com o ponteiro
        ja invisivel. (A tentativa de encostar o pontinho na borda, 6 px,
        falhou no teste dele: a janela precisa ficar inteira na tela.)
        """
        t, p = LADO_DA_JANELINHA, PONTO_VISIVEL
        cx, cy = self._ponto_preso(alvo, pos)
        x, y = cx - t // 2, cy - t // 2
        self._retangulo_da_janela = (cx - p // 2, cy - p // 2,
                                     cx - p // 2 + p, cy - p // 2 + p)
        self._pedir_acordar()        # a tela acende enquanto o resto anda
        with self._trava_mov:
            self._gravando = []      # a mao continua andando: grava
        frente = w.na_frente()
        self._anterior = frente if frente and frente != hwnd else None
        self._pedido_de_volta.clear()

        w.por_debaixo(hwnd, x, y)
        modo = None
        try:
            w.ativar(hwnd)
        except Exception:
            log.exception("nao consegui trazer a janelinha para a frente")
        time.sleep(0.008)            # o scrcpy recebe o foco antes da tecla
        if w.na_frente() == hwnd:
            # A PRIMEIRA ENTRADA depois de ligar falhava sempre (relatorio de
            # 19/set/2026: toda sessao comecava com "entrou (clique)" e uma
            # volta no mesmo segundo -- era o "mouse teleportando" que ele
            # via). O SDL, que o scrcpy usa, so liga a captura numa janela
            # que ja "viu" o mouse passar por cima; nas entradas seguintes
            # ele ainda lembra da anterior, na primeira nao. Um "o mouse
            # passou aqui" de mentira, mandado direto para a janelinha (o
            # ponteiro de verdade nao se mexe), resolve isso -- vai antes da
            # tecla, na mesma fila. Se ainda assim nao pegar, tenta mais uma
            # vez antes do clique de reserva.
            # Espera o scrcpy de fato receber o foco (na 1a entrada ele demora
            # mais: a tecla chegava antes e se perdia -- relatorio de 19/set).
            fim = time.monotonic() + 0.2
            while not w.tem_o_teclado(hwnd) and time.monotonic() < fim:
                time.sleep(0.005)
            for tentativa in range(2):
                w.passou_por_cima(hwnd)
                w.soltar_scrcpy(hwnd)    # a mesma tecla liga a captura
                if self._esperar_captura(w, 0.35, nossa=None):
                    modo = "tecla" if tentativa == 0 else "tecla, 2a vez"
                    break
                if w.escondido() or w.na_frente() != hwnd:
                    break
        if modo is None and not w.escondido():
            # Reserva: o jeito antigo. Aqui o ponteiro precisa ir ao pontinho
            # ANTES (e o pulo aparece), para o clique cair na janelinha.
            w.mover(cx, cy)
            w.prender_em(self._retangulo_da_janela)
            w.clicar()
            if self._esperar_captura(w, 0.35, nossa=self._retangulo_da_janela):
                modo = "clique"

        if modo is not None:
            self.dentro = True
            # PRIMEIRO o cursor do celular vai para a borda do PC, ja: cada
            # milissegundo aqui e movimento da mao que chega atrasado.
            gravados = self._comecar_a_contar(w, alvo, pos)
            # Ja escondido: agora sim o ponteiro vai ao pontinho e fica preso.
            # A TRAVA E NOSSA, NAO SO DO SDL: solto, o ponteiro escapava e o
            # foco ia embora.
            w.mover(cx, cy)
            w.prender_em(self._retangulo_da_janela)
            self._repetir(w, gravados, self._ajuste)
            self._gancho = GanchoDeTeclas(
                hwnd, lambda: self._pedir_volta("2x Tab"),
                ao_volume=self._volume)
            self._gancho.ligar()
            if self._faixa is not None:
                self._faixa.brilhar()
            self._aviso("entrou", modo)
            return True

        with self._trava_mov:
            self._gravando = None
        w.esconder(hwnd)
        w.soltar_trava()
        anterior, self._anterior = self._anterior, None
        if anterior and w.existe(anterior) and w.visivel(anterior):
            try:
                w.ativar(anterior)
            except Exception:
                pass
        w.mover(*mon.para_dentro(pos, alvo, RECUO_NA_VOLTA))
        self._aviso("falhou", "o scrcpy nao pegou o mouse")
        return False

    def _comecar_a_contar(self, w: _Win, alvo, pos) -> list:
        """
        Poe o cursor do celular no lugar EQUIVALENTE ao do mouse no PC e
        passa a calcular dali. Devolve o movimento gravado desde que o mouse
        encostou na borda, para `_repetir`. Ver "Volta pela borda do celular".

        Na borda do lado do PC (e o lugar natural para ele aparecer) e, ao
        longo dela, na mesma altura proporcional: encostou no alto do trecho,
        aparece no alto do celular (pedido dele, 18/set/2026). Como: numa
        rajada so, empurra o cursor ate o canto (posicao conhecida) e, logo
        em seguida, anda de volta o que falta. Nesse instante o Android esta
        no ganho maximo da curva (a rajada e rapidissima), entao a conta da
        distancia usa esse ganho. Parte do canto mais perto, para errar menos.
        """
        lado = alvo[1]
        self._lado = lado
        fora = {"direita": (-127, 0), "esquerda": (127, 0),
                "baixo": (0, -127), "cima": (0, 127)}[lado]
        vertical = lado in ("direita", "esquerda")
        inicio, fim = alvo[2], alvo[3]
        coord = pos[1] if vertical else pos[0]
        f = min(1.0, max(0.0, (coord - inicio) / max(1, fim - inicio - 1)))
        with self._trava:
            curva = self._celular["curva"]
            cpmm = self._celular.get("contagens_por_mm") or CONTAGENS_POR_MM
        largura = self._largura_util(lado)
        comprimento = self._comprimento_util(lado)
        est = Estimativa(lado, largura, curva, comprimento, cpmm)
        self._ajuste = None

        salto = abs(f * comprimento - (self._da_tela(lado, *self._pos_celular)[1]
                                       if self._pos_celular is not None else 0.0))
        if self._pos_celular is not None and salto <= SALTO_GRANDE * comprimento:
            # CAMINHO SUAVE (teste dele, 19/set/2026: "o mouse entra com muita
            # velocidade no android e ... para quase no meio da tela"). O
            # empurrao forte deixava o Android acelerando no maximo por um
            # instante, e o movimento de verdade da mao, logo depois, ia
            # longe demais. Com a posicao do cursor ja conhecida pela conta,
            # nada de empurrao: um AJUSTE de poucos pixels, espalhado no
            # tempo junto com o movimento da mao (ver `_repetir`).
            d0, y0 = self._da_tela(lado, *self._pos_celular)
            est.distancia = min(float(largura), max(0.0, d0))
            est.ao_longo = min(float(comprimento), max(0.0, y0))
            # Ate a borda do PC (e um pouco alem, para encostar de verdade
            # mesmo se a conta estiver devendo) e ate a altura equivalente.
            self._ajuste = (-(est.distancia + 30.0),
                            f * comprimento - est.ao_longo)
            # Quanto maior o caminho, mais tempo para percorre-lo: velocidade
            # constante e o que a conta do ganho acerta melhor.
            caminho = abs(self._ajuste[0]) + abs(self._ajuste[1])
            self._tempo_do_ajuste = min(AJUSTE_MAX_S, max(
                AJUSTE_S, caminho / VELOCIDADE_DO_AJUSTE))
            agora = time.perf_counter()
            with self._trava_mov:
                gravados, self._gravando = self._gravando or [], None
                self._estimativa = est
            self._aviso("conta", "lado %s, ate a borda %d, ao longo %d, "
                                 "cursor em %d/%d (suave)" % (
                                     lado, largura, comprimento,
                                     round(est.distancia), round(est.ao_longo)))
            self._atualizar_celular()
            return [g for g in gravados if agora - g[2] <= REPETIR_ATE_S]

        # Canto de partida ao longo da borda: o mais perto do destino.
        rumo_canto = -127 if f <= 0.5 else 127
        falta_px = (f if f <= 0.5 else 1 - f) * comprimento
        ganho_max = max(1.0, curva[-1][1])
        falta = int(round(falta_px / ganho_max))
        volta = []
        sinal = 1 if rumo_canto < 0 else -1      # do canto para o destino
        while falta > 0:
            n = min(127, falta)
            volta.append((0, sinal * n) if vertical else (sinal * n, 0))
            falta -= n
        canto = ((fora[0], rumo_canto) if vertical else (rumo_canto, fora[1]))
        try:
            if self._primeira_entrada:
                # PRIMEIRA ENTRADA DA SESSAO (teste dele, 19/set/2026: o
                # cursor aparecia "quase no meio" do celular em vez de no
                # canto): o mouse do scrcpy acabou de ser criado no celular e
                # o primeiro empurrao se perdia. Empurra, espera um instante e
                # empurra de novo; o que a mao fez nesse meio tempo continua
                # sendo gravado e e repetido logo depois, como sempre.
                w.movimentos([canto] * 24)
                time.sleep(0.12)
            w.movimentos([canto] * 24 + volta)
        except Exception:
            log.exception("nao consegui levar o cursor a borda")
        self._primeira_entrada = False
        # O empurrao levou o cursor ao canto: a conta voltou a ter um ponto
        # de partida certo, entao isto TAMBEM e uma calibracao -- e a janela
        # precisa saber, senao continua pedindo a mao parada a toa.
        if not self.calibrada:
            self._aviso("calibrou", "pela primeira passagem")
        self.calibrada = True
        self._precisa_calibrar = False
        self._tentativas = 0
        agora = time.perf_counter()
        est.semear(canto[0], canto[1], 24, agora)
        est.ao_longo = f * comprimento
        with self._trava_mov:
            gravados, self._gravando = self._gravando or [], None
            self._estimativa = est       # dali em diante, conta ao vivo
        # Para o relatorio: com que medidas a conta comecou desta vez.
        self._aviso("conta", "lado %s, ate a borda %d, ao longo %d, "
                             "cursor em %d/%d" % (
                                 lado, largura, comprimento,
                                 round(est.distancia), round(est.ao_longo)))
        self._atualizar_celular()        # tela girou desde a ultima vez?
        return [g for g in gravados if agora - g[2] <= REPETIR_ATE_S]

    def _perto_da_borda(self, pos, alvo) -> bool:
        """O ponteiro esta chegando na marca? (ai o vigia olha em dobro)"""
        if pos is None or not alvo:
            return False
        m, lado, inicio, fim = alvo
        if lado == "direita":
            falta = (m["x"] + m["l"]) - pos[0]
        elif lado == "esquerda":
            falta = pos[0] - m["x"]
        elif lado == "baixo":
            falta = (m["y"] + m["a"]) - pos[1]
        else:
            falta = pos[1] - m["y"]
        return -2 <= falta <= PERTO_DA_BORDA_PX

    def _mao_parada(self, pos, agora: float) -> bool:
        """O ponteiro esta parado ha `PARADO_S`? (mao quieta = hora de calibrar)"""
        if pos != self._ultimo_ponteiro:
            self._ultimo_ponteiro = pos
            self._parado_desde = agora
            return False
        return agora - self._parado_desde >= PARADO_S

    def _descalibrar(self, motivo: str) -> None:
        """A conta perdeu o ponto de partida: avisa e calibra quando der."""
        self.calibrada = False
        self._precisa_calibrar = True
        self._proxima_calibracao = 0.0
        self._tentativas = 0
        self._ultimo_ponteiro = None
        self._aviso("calibrar", motivo)

    def _calibrar(self, w: _Win, hwnd, alvo) -> None:
        """
        Logo que a extensao liga: pega o mouse por um instante SEM tirar o
        ponteiro do lugar (a janelinha vai para debaixo dele), empurra o
        cursor do celular ate o canto do lado do PC -- posicao conhecida -- e
        solta. Dura uns 0,3 s, numa hora em que ninguem esta passando o mouse
        para o celular.

        Por que (teste dele, 19/set/2026): o empurrao forte era a unica forma
        de saber onde o cursor do celular estava, e ele deixava o Android
        acelerando no maximo bem na hora em que a mao entrava. Feito aqui,
        uma vez, as entradas passam a partir de uma posicao conhecida e usam
        so um ajuste pequeno (ver `_comecar_a_contar`). A primeira ativacao
        da janelinha (a que dava o "bug grafico" da 1a passagem) tambem
        acontece aqui.
        """
        lado = alvo[1]
        fora = {"direita": (-127, 0), "esquerda": (127, 0),
                "baixo": (0, -127), "cima": (0, 127)}[lado]
        vertical = lado in ("direita", "esquerda")
        canto = (fora[0], -127) if vertical else (-127, fora[1])
        t = LADO_DA_JANELINHA
        pos = w.ponteiro()
        frente = w.na_frente()
        w.por_debaixo(hwnd, pos[0] - t // 2, pos[1] - t // 2)
        pegou = False
        try:
            w.ativar(hwnd)
            fim = time.monotonic() + 0.2
            while not w.tem_o_teclado(hwnd) and time.monotonic() < fim:
                time.sleep(0.003)
            for _vez in range(2):
                w.passou_por_cima(hwnd)
                w.soltar_scrcpy(hwnd)
                if self._esperar_captura(w, 0.22, nossa=None):
                    pegou = True
                    break
                if w.escondido():
                    break
            if pegou:
                # Duas rajadas: a primeira as vezes se perde enquanto o
                # scrcpy acaba de pegar o mouse. Com a mao parada nao ha
                # movimento de verdade no meio, entao as esperas sao curtas.
                w.movimentos([canto] * 24)
                time.sleep(0.05)
                w.movimentos([canto] * 24)
                time.sleep(0.03)
        finally:
            if w.escondido():
                w.soltar_scrcpy(hwnd)
                fim = time.monotonic() + 0.3
                while w.escondido() and time.monotonic() < fim:
                    time.sleep(0.01)
            w.esconder(hwnd)
            w.soltar_trava()
            w.mover(*pos)
            if frente and frente != hwnd and w.existe(frente):
                try:
                    w.ativar(frente)
                except Exception:
                    pass
        self.calibrada = bool(pegou)
        self._precisa_calibrar = not pegou
        if pegou:
            # O canto onde o cursor ficou, na TELA do celular (x, y).
            with self._trava:
                largura, altura = self._celular["tela"]
            self._pos_celular = (0.0 if canto[0] < 0 else float(largura),
                                 0.0 if canto[1] < 0 else float(altura))
            self._primeira_entrada = False
        self._aviso("calibrou" if pegou else "nao calibrou")

    # A POSICAO GUARDADA DO CURSOR E NA TELA DO CELULAR, NAO NA BORDA
    # (teste dele, 20/set/2026: mudou o celular de lado no mapa com a extensao
    # ligada -- esquerda, cima, direita -- e o mouse "ficou bem bugado",
    # entrando e voltando no mesmo segundo). Ela era guardada como "distancia
    # ate a borda do PC / posicao ao longo dela", e isso so tem sentido para
    # o lado em que foi medida: calibrado com o celular a direita, o canto de
    # cima a esquerda vira "encostado na borda"; com o celular em cima, a
    # borda do PC e a de BAIXO do celular, e o mesmo numero apontava para o
    # lugar errado. Agora guarda x, y da tela e converte para o lado da vez.

    def _para_tela(self, lado: str, distancia: float, ao_longo: float):
        with self._trava:
            largura, altura = self._celular["tela"]
        if lado == "direita":
            return (distancia, ao_longo)
        if lado == "esquerda":
            return (largura - distancia, ao_longo)
        if lado == "baixo":
            return (ao_longo, distancia)
        return (ao_longo, altura - distancia)              # cima

    def _da_tela(self, lado: str, x: float, y: float):
        with self._trava:
            largura, altura = self._celular["tela"]
        x = min(float(largura), max(0.0, x))
        y = min(float(altura), max(0.0, y))
        if lado == "direita":
            return (x, y)
        if lado == "esquerda":
            return (largura - x, y)
        if lado == "baixo":
            return (y, x)
        return (altura - y, x)                             # cima

    def _comprimento_util(self, lado: str) -> int:
        """Tamanho do celular AO LONGO da borda (a outra medida da tela)."""
        with self._trava:
            l, a = self._celular["tela"]
        return a if lado in ("direita", "esquerda") else l

    def _ponto_de_saida(self, alvo, entrada, est) -> tuple[int, int]:
        """
        Onde o mouse reaparece no PC: na borda, na altura proporcional a do
        cursor no celular (saiu pelo alto do celular -> alto do trecho).
        Sem conta (voltou sem ela), na altura em que entrou.
        """
        if est is None:
            return entrada
        m, lado, inicio, fim = alvo
        coord = int(round(inicio + est.fracao * max(0, fim - inicio - 1)))
        if lado in ("direita", "esquerda"):
            return (entrada[0], coord)
        return (coord, entrada[1])

    def _repetir(self, w: _Win, gravados: list, ajuste=None) -> None:
        """
        Manda ao celular o movimento que a mao fez enquanto a troca
        acontecia, no MESMO ritmo (o Android acelera pela velocidade: ritmo
        diferente daria outra distancia), e soma na conta.

        Junto, se houver `ajuste` (px do celular: rumo ao PC, ao longo da
        borda), leva o cursor do celular ate o ponto de entrada aos poucos,
        em `AJUSTE_S`: cada pedacinho e convertido em contagens pelo ganho
        que o Android esta usando naquele instante (a mesma conta da
        estimativa), para que chegue exatamente la sem disparar a
        aceleracao do celular.
        """
        est = self._estimativa
        if est is None:
            return
        tempo_ajuste = getattr(self, "_tempo_do_ajuste", AJUSTE_S)
        fila = list(gravados)
        inicio_gravado = fila[0][2] if fila else 0.0
        eixo, longo = est._eixo, est._longo
        total = list(ajuste) if ajuste else [0.0, 0.0]
        feito = [0.0, 0.0]
        with relogio_fino():
            inicio = time.perf_counter()
            while True:
                agora = time.perf_counter()
                decorrido = agora - inicio
                enviar = []
                while fila and fila[0][2] - inicio_gravado <= decorrido:
                    dx, dy, _q = fila.pop(0)
                    enviar.append((dx, dy, True))
                if ajuste:
                    parte = min(1.0, decorrido / max(0.05, tempo_ajuste))
                    falta = [total[k] * parte - feito[k] for k in (0, 1)]
                    g = max(0.5, ganho(est.curva, est.velocidade,
                                       est.contagens_por_mm))
                    # Tudo na medida "afastar do PC" (negativo = rumo ao PC).
                    c_perp = int(round(max(-40, min(40, falta[0] / g))))
                    c_long = int(round(max(-40, min(40, falta[1] / g))))
                    if c_perp or c_long:
                        dx = c_perp * eixo[0] + c_long * longo[0]
                        dy = c_perp * eixo[1] + c_long * longo[1]
                        enviar.append((dx, dy, False))
                for dx, dy, da_mao in enviar:
                    try:
                        w.rajada(dx, dy, 1)
                    except Exception:
                        return
                    with self._trava_mov:
                        if self._estimativa is not est:
                            return
                        voltar = est.mover(dx, dy, time.perf_counter(),
                                           empurra=da_mao)
                        if not da_mao:
                            gg = est.ultimo_ganho
                            feito[0] += (dx * eixo[0] + dy * eixo[1]) * gg
                            feito[1] += (dx * longo[0] + dy * longo[1]) * gg
                        if voltar and not est.disparou:
                            est.disparou = True
                        else:
                            voltar = False
                    if voltar:
                        self._pedir_volta("empurrou a borda")
                        return
                acabou_ajuste = (not ajuste or decorrido >= tempo_ajuste + 0.1
                                 or (abs(total[0] - feito[0]) < 1.5
                                     and abs(total[1] - feito[1]) < 1.5))
                if not fila and acabou_ajuste:
                    return
                time.sleep(0.006)

    def _esperar_captura(self, w: _Win, segundos: float, nossa) -> bool:
        fim = time.monotonic() + segundos
        while time.monotonic() < fim:
            time.sleep(0.002)            # olhar miudo: a troca fica mais rapida
            if w.capturado(nossa):
                return True
        return False

    def _voltar(self, w: _Win, hwnd, alvo, entrada, motivo: str) -> None:
        """
        Devolve o mouse ao PC, porque so esconder a janela nao basta (teste
        dele: o mouse "continuava no celular" e clicar no PC o mandava de
        volta):
        1. o scrcpy solta o mouse ele mesmo -- so se ainda estiver com ele
           (ponteiro escondido), senao a mesma tecla o faria pegar de novo;
        2. a janelinha some e a trava do ponteiro sai;
        3. a janela que estava na frente antes recebe a frente de volta: o
           scrcpy perde o foco e para de vez de ouvir o mouse;
        4. o ponteiro reaparece NA BORDA, onde entrou, e desliza para dentro
           (pedido dele: troca suave, com animacao), e a faixa brilha.
        """
        self.dentro = False
        with self._trava_mov:
            est, self._estimativa = self._estimativa, None
            self._gravando = None
        # A conta continua valendo na proxima entrada (ver `_calibrar`).
        self._pos_celular = (self._para_tela(self._lado, est.distancia,
                                             est.ao_longo)
                             if est is not None else None)
        if motivo.startswith("empurrou a borda") and est is not None:
            # A mao ainda vem naquela velocidade: a volta continua o gesto.
            self._velocidade = max(self._velocidade, est.velocidade)
        if self._gancho is not None:
            self._gancho.desligar()
            self._gancho = None
        existe = bool(hwnd) and w.existe(hwnd)
        if existe and w.escondido():
            w.soltar_scrcpy(hwnd)
            fim = time.monotonic() + 0.3
            while w.escondido() and time.monotonic() < fim:
                time.sleep(0.015)
        if existe:
            w.esconder(hwnd)
        w.soltar_trava()
        anterior, self._anterior = self._anterior, None
        if anterior and w.existe(anterior) and w.visivel(anterior):
            try:
                w.ativar(anterior)
            except Exception:
                log.exception("nao devolvi a frente a janela anterior")
        if alvo is not None:
            if self._faixa is not None:
                self._faixa.brilhar()
            saida = self._ponto_de_saida(alvo, entrada, est)
            if motivo.startswith("empurrou a borda") and est is not None:
                # A mao esta em movimento: nada de animacao por cima dela (a
                # animacao brigava com o mouse de verdade). O ponteiro
                # aparece na borda ja adiantado o que a mao passou do limite,
                # e o proprio movimento dela continua daqui.
                passou = int(round(min(40.0, max(3.0, est.empurrao_contagens))))
                w.mover(*mon.para_dentro(saida, alvo, passou))
            else:
                self._deslizar(w, alvo, saida, self._velocidade)
        # A conta, como ela estava na hora de voltar. E o que permite comparar
        # com o que ele VIU na tela do celular e acertar a regra (21/set/2026).
        if est is not None:
            motivo += " [conta: %d de %d da borda, %d de %d ao longo]" % (
                round(est.distancia), est.limite,
                round(est.ao_longo), est.comprimento)
        self._aviso("voltou", motivo)

    @staticmethod
    def _deslizar(w: _Win, alvo, entrada, velocidade: float) -> None:
        """
        O ponteiro reaparece colado na borda, na altura em que entrou, e
        freia ate parar -- desaceleracao constante a partir da velocidade de
        chegada, como um movimento de mao. Posicao calculada pelo RELOGIO, e
        nao por quadro: se um quadro atrasa, o proximo compensa, e a
        velocidade nunca parece mudar no meio (queixa dele: "tem horas que
        parece rapida e lenta em momentos diferentes").
        """
        v = max(150.0, min(velocidade, 4000.0))
        # Freando de v ate 0 em T segundos anda d = v*T/2.
        distancia = min(VOLTA_MAX_PX, max(VOLTA_MIN_PX, v * 0.012))
        duracao = min(VOLTA_MAX_S, max(VOLTA_MIN_S, 2 * distancia / v))
        de = mon.para_dentro(entrada, alvo, 0)
        para = mon.para_dentro(entrada, alvo, int(round(distancia)))
        with relogio_fino():
            inicio = time.perf_counter()
            ultimo = None
            while True:
                t = min(1.0, (time.perf_counter() - inicio) / duracao)
                f = 1 - (1 - t) ** 2            # desaceleracao constante
                ponto = (round(de[0] + (para[0] - de[0]) * f),
                         round(de[1] + (para[1] - de[1]) * f))
                if ponto != ultimo:
                    w.mover(*ponto)
                    ultimo = ponto
                if t >= 1.0:
                    break
                time.sleep(0.004)


@contextmanager
def relogio_fino():
    """
    Enquanto dura, o relogio do Windows bate de 1 em 1 ms em vez de ~16 ms:
    sem isso, cada `sleep` curto vira 16 ou 31 ms ao acaso, e a animacao
    anda aos trancos. Volta ao normal no fim (nao gastar bateria a toa).
    """
    winmm = None
    if NO_WINDOWS:
        try:
            import ctypes
            winmm = ctypes.WinDLL("winmm")
            winmm.timeBeginPeriod(1)
        except Exception:
            winmm = None
    try:
        yield
    finally:
        if winmm is not None:
            try:
                winmm.timeEndPeriod(1)
            except Exception:
                pass
