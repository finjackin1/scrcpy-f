"""
Janela sem a moldura do Windows.

Porta do `moldura.py` do LightWireless -- o mesmo aparato, pelos mesmos
motivos. Resumo do porque (o detalhe esta la):

A moldura do Windows nao aceita tema. Tirando ela (`overrideredirect`), a
barra de titulo vira conteudo nosso, e tres coisas precisam ser repostas:

1. a janela some da barra de tarefas e do Alt+Tab -> `_fixar_barra_de_tarefas`
2. os cantos ficam retos -> `arredondar` (Windows 11; no 10 fica reto)
3. nao da para arrastar -> `Arrasto`

O QUE E SO DESTE PROGRAMA
--------------------------
- `canto_da_bandeja`: a janela nasce no canto de baixo a direita, acima do
  relogio, porque e de la que ela e chamada -- como os paineis do proprio
  Windows (volume, rede) que saem do mesmo lugar.
- `animacoes_ligadas`: a pergunta ao Windows se a pessoa desligou as
  animacoes. Com elas desligadas, a janela aparece e muda de tamanho num
  corte seco.

Nada aqui e obrigatorio: fora do Windows, ou se alguma chamada falhar, a
janela continua funcionando -- sem canto redondo, no meio da tela, com
animacao. Uma janela feia e melhor que uma janela que nao abre.
"""

from __future__ import annotations

import logging
import sys
import tkinter as tk

log = logging.getLogger(__name__)

NO_WINDOWS = sys.platform == "win32"

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2

# SPI_GETCLIENTAREAANIMATION: e o interruptor "Efeitos de animacao" das
# configuracoes de acessibilidade do Windows.
SPI_GETCLIENTAREAANIMATION = 0x1042


def _identificador(janela: tk.Misc) -> int | None:
    """O HWND real da janela (o `winfo_id` e o de uma janela filha)."""
    try:
        import ctypes

        janela.update_idletasks()
        return ctypes.windll.user32.GetParent(janela.winfo_id())
    except Exception as erro:
        log.debug("nao consegui o identificador da janela: %s", erro)
        return None


def pintar_icone(janela: tk.Tk, estado: str = "parado") -> None:
    """
    Poe o celular na barra de tarefas e no Alt+Tab, no desenho do estado.

    O icone ACOMPANHA O ESTADO, igual ao da bandeja: de relance, na barra de
    tarefas, da para ver se esta espelhando sem abrir nada.

    As imagens ficam presas na janela: o Tk nao segura referencia, e o icone
    sumiria na primeira coleta de lixo.
    """
    try:
        from PIL import ImageTk

        from . import icone
    except ImportError:
        return

    try:
        # Quatro estados, quatro tamanhos: desenhar de novo a cada troca era
        # trabalho jogado fora (21/set/2026). Guardados por estado.
        guardados = getattr(janela, "_icones_por_estado", None)
        if guardados is None:
            guardados = {}
            janela._icones_por_estado = guardados  # type: ignore[attr-defined]
        imagens = guardados.get(estado)
        if imagens is None:
            desenho = icone.desenhar(estado)
            imagens = [ImageTk.PhotoImage(desenho.resize((lado, lado)))
                       for lado in (16, 32, 48, 64)]
            guardados[estado] = imagens
        janela._icones_da_barra = imagens  # type: ignore[attr-defined]
        janela.iconphoto(True, *imagens)
    except Exception as erro:
        log.debug("nao consegui pintar o icone da janela: %s", erro)


def preparar(janela: tk.Tk) -> None:
    """
    Tira a moldura. A correcao da barra de tarefas fica para a primeira vez
    que a janela aparecer (`fixar_barra_de_tarefas`): o programa nasce na
    bandeja, e a correcao esconde e mostra a janela -- feita agora, poria a
    janela na tela por um instante.
    """
    janela.overrideredirect(True)
    janela.after(20, lambda: pintar_icone(janela))


def fixar_barra_de_tarefas(janela: tk.Tk) -> None:
    """
    Devolve a janela para a barra de tarefas e para o Alt+Tab, e arredonda
    os cantos. Chamar com a janela JA na tela.

    O esconde-e-mostra no fim nao e enfeite: o Windows so re-avalia o
    estilo estendido quando a janela e escondida e mostrada de novo.

    FEITO DIRETO NO WINDOWS, NA MESMA HORA (18/set/2026): antes era o
    `withdraw` do Tk e um `deiconify` 10 ms depois. Na abertura junto com o
    programa, o relatorio mostrou a janela ATIVA mas INVISIVEL 1,2 s depois
    -- o `deiconify` atrasado se perdia, e ele via so o botao na barra de
    tarefas ("abre so minimizada"). Esconder e mostrar em seguida pelo
    proprio Windows nao deixa janela nenhuma de tempo para isso.
    """
    if not NO_WINDOWS:
        return

    identificador = _identificador(janela)
    if not identificador:
        return

    try:
        import ctypes

        user32 = ctypes.windll.user32
        estilo = user32.GetWindowLongW(identificador, GWL_EXSTYLE)
        estilo = (estilo & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
        user32.SetWindowLongW(identificador, GWL_EXSTYLE, estilo)

        if user32.IsWindowVisible(identificador):
            user32.ShowWindow(identificador, 0)           # SW_HIDE
            # O Tk ve o SW_HIDE e se marca como "retirada" -- e ai desfaz o
            # SW_SHOW logo depois (o relatorio mostrou as duas janelas,
            # programa e Configurar, ATIVAS mas INVISIVEIS). O deiconify
            # acerta a conta do Tk antes de mostrar.
            janela.deiconify()
            user32.ShowWindow(identificador, 5)           # SW_SHOW
    except Exception as erro:
        log.debug("nao consegui devolver a janela a barra de tarefas: %s", erro)

    arredondar(janela)


def arredondar(janela: tk.Tk) -> None:
    """Pede cantos arredondados ao compositor. Falha calada no Windows 10."""
    if not NO_WINDOWS:
        return
    identificador = _identificador(janela)
    if not identificador:
        return
    try:
        import ctypes

        preferencia = ctypes.c_int(DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(identificador),
            ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(preferencia),
            ctypes.sizeof(preferencia),
        )
    except Exception as erro:
        log.debug("cantos arredondados indisponiveis: %s", erro)


def minimizar(janela: tk.Tk) -> bool:
    """
    Minimiza pela API do Windows: numa janela `overrideredirect` o Tk recusa
    o `iconify`.
    """
    if not NO_WINDOWS:
        try:
            janela.iconify()
            return True
        except Exception:
            return False

    identificador = _identificador(janela)
    if not identificador:
        return False
    try:
        import ctypes

        ctypes.windll.user32.ShowWindow(identificador, 6)  # SW_MINIMIZE
        return True
    except Exception as erro:
        log.debug("nao consegui minimizar: %s", erro)
        return False


def situacao(janela: tk.Tk) -> tuple[bool, bool]:
    """
    (minimizada?, na frente?) -- o atalho da janela usa para decidir se
    abre ou devolve (pedido dele, 21/set/2026). Fora do Windows: nunca
    minimizada, sempre na frente.
    """
    if not NO_WINDOWS:
        return (False, True)
    try:
        _ct, _wt, u, _k = _api_de_frente()
        hwnd = _hwnd(janela, u)
        if not hwnd:
            return (False, True)
        return (bool(u.IsIconic(hwnd)), u.GetForegroundWindow() == hwnd)
    except Exception as erro:
        log.debug("nao consegui ler a situacao da janela: %s", erro)
        return (False, True)


# Montar esta API custa duas cargas de DLL e uma duzia de declaracoes; ela
# era refeita a cada chamada, e a abertura da janela chama varias vezes
# (21/set/2026). Agora e montada uma vez so.
_API_FRENTE = None


def _api_de_frente():
    global _API_FRENTE
    if _API_FRENTE is not None:
        return _API_FRENTE

    import ctypes
    from ctypes import wintypes

    u = ctypes.WinDLL("user32")              # copia propria: tipos nossos
    k = ctypes.WinDLL("kernel32")
    H = ctypes.c_void_p
    u.GetParent.argtypes = [H]
    u.GetParent.restype = H
    u.IsIconic.argtypes = [H]
    u.IsWindowVisible.argtypes = [H]
    u.ShowWindow.argtypes = [H, ctypes.c_int]
    u.GetForegroundWindow.restype = H
    u.GetWindowThreadProcessId.argtypes = [H, ctypes.c_void_p]
    u.GetWindowThreadProcessId.restype = ctypes.c_uint
    u.AttachThreadInput.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_int]
    u.BringWindowToTop.argtypes = [H]
    u.SetForegroundWindow.argtypes = [H]
    u.GetWindowRect.argtypes = [H, ctypes.POINTER(wintypes.RECT)]
    u.GetClassNameW.argtypes = [H, ctypes.c_wchar_p, ctypes.c_int]
    u.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD,
                              ctypes.c_size_t]
    k.GetCurrentThreadId.restype = ctypes.c_uint
    _API_FRENTE = (ctypes, wintypes, u, k)
    return _API_FRENTE


def _hwnd(janela: tk.Tk, u):
    janela.update_idletasks()
    return u.GetParent(janela.winfo_id())


def trazer_para_frente(janela: tk.Tk) -> tuple[str, bool]:
    """
    Garante a janela NA FRENTE e ativa. Devolve (como estava, ficou na
    frente?). "Como estava" e "ok", "minimizada" ou "atras".

    Por que existe (relato dele, 18/set/2026: marcou abrir a janela ao iniciar
    e ela nascia "so minimizada", so na barra de tarefas): o Windows nao deixa
    um programa que acabou de abrir, sem clique nenhum, tomar a frente da
    tela -- a janela fica debaixo da ativa e o botao pisca na barra. Tres
    tentativas, da mais educada para a mais firme:
    1. juntar-se por um instante a fila de entrada da janela ativa
       (AttachThreadInput) e pedir a frente -- nao bastou no teste dele;
    2. o mesmo com a tecla Alt "apertada" durante o pedido: com Alt em baixo
       o Windows libera a troca de frente (e o truque conhecido; a Alt e
       solta na mesma hora e nao chega a abrir menu nenhum);
    3. se nem assim, ao menos fica POR CIMA de tudo (sem foco) -- a janela
       aparece; o foco vem no primeiro clique.
    """
    if not NO_WINDOWS:
        return ("ok", True)
    try:
        ctypes, _wt, u, k = _api_de_frente()
        hwnd = _hwnd(janela, u)
        if not hwnd:
            return ("ok", True)
        estava = "ok"
        if u.IsIconic(hwnd):
            estava = "minimizada"
            u.ShowWindow(hwnd, 9)                     # SW_RESTORE
        if u.GetForegroundWindow() == hwnd:
            return (estava, True)
        if estava == "ok":
            estava = "atras"

        frente = u.GetForegroundWindow()
        minha = k.GetCurrentThreadId()
        dela = u.GetWindowThreadProcessId(frente, None) if frente else 0
        juntou = bool(dela and dela != minha
                      and u.AttachThreadInput(minha, dela, True))
        try:
            u.BringWindowToTop(hwnd)
            u.SetForegroundWindow(hwnd)
            if u.GetForegroundWindow() != hwnd:
                VK_MENU, SOLTA = 0x12, 0x0002
                u.keybd_event(VK_MENU, 0, 0, 0)
                try:
                    u.SetForegroundWindow(hwnd)
                finally:
                    u.keybd_event(VK_MENU, 0, SOLTA, 0)
        finally:
            if juntou:
                u.AttachThreadInput(minha, dela, False)
        conseguiu = u.GetForegroundWindow() == hwnd
        if not conseguiu:
            try:
                janela.attributes("-topmost", True)
                janela.after(400, lambda: janela.attributes("-topmost", False))
            except Exception:
                pass
        return (estava, conseguiu)
    except Exception as erro:
        log.debug("nao consegui trazer a janela para a frente: %s", erro)
        return ("ok", True)


def garantir_visivel(janela: tk.Tk) -> bool:
    """
    Se o Windows esta com a janela ESCONDIDA enquanto o programa acha que ela
    esta na tela, mostra de novo. True se precisou. Rede de seguranca para o
    caso descrito em `fixar_barra_de_tarefas`.
    """
    if not NO_WINDOWS:
        return False
    try:
        _ct, _wt, u, _k = _api_de_frente()
        hwnd = _hwnd(janela, u)
        if hwnd and not u.IsWindowVisible(hwnd):
            janela.deiconify()
            u.ShowWindow(hwnd, 5)                         # SW_SHOW
            return True
    except Exception as erro:
        log.debug("nao consegui garantir a janela visivel: %s", erro)
    return False


def retrato(janela: tk.Tk) -> str:
    """
    Uma linha com o estado da janela para o relatorio: onde esta, tamanho,
    se aparece, se esta minimizada, quem esta na frente. Existe para o
    problema da janela ao iniciar (ver `trazer_para_frente`): o relatorio
    tem que dizer o que aconteceu, sem depender de descricao.
    """
    if not NO_WINDOWS:
        return "(fora do Windows)"
    try:
        ctypes, wt, u, _k = _api_de_frente()
        hwnd = _hwnd(janela, u)
        r = wt.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        frente = u.GetForegroundWindow()
        classe = ctypes.create_unicode_buffer(64)
        if frente:
            u.GetClassNameW(frente, classe, 64)
        try:
            alfa = float(janela.attributes("-alpha"))
        except Exception:
            alfa = -1.0
        return ("visivel=%s minimizada=%s na_frente=%s (frente: %s) "
                "lugar=%dx%d%+d%+d alfa=%.2f" % (
                    "sim" if u.IsWindowVisible(hwnd) else "NAO",
                    "SIM" if u.IsIconic(hwnd) else "nao",
                    "sim" if frente == hwnd else "NAO",
                    classe.value or "nenhuma",
                    r.right - r.left, r.bottom - r.top, r.left, r.top, alfa))
    except Exception as erro:
        return "(sem retrato: %s)" % erro


def area_util(janela: tk.Misc, ponto: tuple[int, int] | None = None
              ) -> tuple[int, int, int, int]:
    """
    (x, y, largura, altura) da tela SEM a barra de tarefas.

    Com `ponto`, e a area do MONITOR onde esse ponto esta -- a janela pode ter
    sido arrastada para um segundo monitor, e prende-la na area do principal a
    faria pular de tela a cada troca de aba. Sem `ponto`, o monitor principal.
    """
    if NO_WINDOWS and ponto is not None:
        area = _area_do_monitor(ponto)
        if area is not None:
            return area
    if NO_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes

            retangulo = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(
                    0x0030, 0, ctypes.byref(retangulo), 0):  # SPI_GETWORKAREA
                return (retangulo.left, retangulo.top,
                        retangulo.right - retangulo.left,
                        retangulo.bottom - retangulo.top)
        except Exception as erro:
            log.debug("nao consegui a area util: %s", erro)
    return (0, 0, janela.winfo_screenwidth(), janela.winfo_screenheight())


_API_MONITOR = None


def _api_do_monitor():
    """Os tipos do monitor, montados uma vez so (eram refeitos por chamada)."""
    global _API_MONITOR
    if _API_MONITOR is None:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p,
                                           ctypes.POINTER(MONITORINFO)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        _API_MONITOR = (ctypes, wintypes, user32, MONITORINFO)
    return _API_MONITOR


def _area_do_monitor(ponto: tuple[int, int]):
    """A area util do monitor mais perto do ponto, ou None se nao der."""
    try:
        ctypes, wintypes, user32, MONITORINFO = _api_do_monitor()

        monitor = user32.MonitorFromPoint(
            wintypes.POINT(int(ponto[0]), int(ponto[1])), 2)  # o mais perto
        if not monitor:
            return None
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        r = info.rcWork
        return (r.left, r.top, r.right - r.left, r.bottom - r.top)
    except Exception as erro:
        log.debug("nao consegui a area do monitor: %s", erro)
        return None


def canto_da_bandeja(janela: tk.Misc, largura: int, altura: int,
                     folga: int) -> tuple[int, int]:
    """
    Onde a janela nasce: encostada no canto de baixo a direita da area util,
    com uma folga. E o canto da bandeja na barra de tarefas padrao.

    Com a barra de tarefas em cima ou do lado, a area util ja desconta ela, e
    o canto de baixo a direita continua sendo um lugar razoavel.
    """
    x0, y0, lu, au = area_util(janela)
    x = x0 + lu - largura - folga
    y = y0 + au - altura - folga
    return (max(x0, x), max(y0, y))


def animacoes_ligadas() -> bool:
    """
    O Windows esta com os efeitos de animacao ligados?

    Na duvida (fora do Windows, chamada que falhou), responde que sim: errar
    para esse lado custa uma animacao de um decimo de segundo; para o outro,
    tirar dela quem nao pediu.
    """
    if not NO_WINDOWS:
        return True
    try:
        import ctypes

        ligado = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(ligado), 0):
            return bool(ligado.value)
    except Exception as erro:
        log.debug("nao consegui perguntar sobre as animacoes: %s", erro)
    return True


class Arrasto:
    """
    Deixa a janela ser arrastada por um widget, guardando o deslocamento entre
    o ponteiro e o canto da janela -- sem isso ela pula para debaixo do
    cursor no primeiro pixel de movimento.
    """

    def __init__(self, janela: tk.Tk, ao_mover=None):
        self.janela = janela
        self._dx = 0
        self._dy = 0
        self._ao_mover = ao_mover

    def ligar(self, widget: tk.Misc) -> None:
        widget.bind("<Button-1>", self._pegou, add="+")
        widget.bind("<B1-Motion>", self._moveu, add="+")

    def _pegou(self, evento) -> None:
        self._dx = evento.x_root - self.janela.winfo_x()
        self._dy = evento.y_root - self.janela.winfo_y()

    def _moveu(self, evento) -> None:
        x, y = evento.x_root - self._dx, evento.y_root - self._dy
        self.janela.geometry(f"+{x}+{y}")
        if self._ao_mover is not None:
            self._ao_mover()
