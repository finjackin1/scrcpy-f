"""
O AVISO DE NOTIFICACAO NO CANTO DA TELA (01/out/2026, pedido dele).

Janelinha propria, no visual do programa, e nao o aviso do Windows: o do
Windows (pela bandeja) nao deixa o clique abrir o app de forma confiavel num
programa sem atalho registrado no Menu Iniciar. Esta:
  - nasce no canto de baixo a direita (acima da barra de tarefas), as
    novas embaixo, no maximo MAX_NA_TELA (a mais velha sai);
  - NAO rouba o foco (WS_EX_NOACTIVATE) nem aparece na barra de tarefas;
  - some sozinha em DURA_S; com o mouse em cima, espera;
  - clique abre o app numa janela do PC; o x so fecha o aviso;
  - respeita o "nao perturbe"/tela cheia do Windows
    (SHQueryUserNotificationState).
Roda na thread do Tk (a janela chama `mostrar`).
"""

from __future__ import annotations

import logging
import sys
import tkinter as tk

from . import estudio as E
from . import moldura

log = logging.getLogger(__name__)

DURA_S = 6.0
MAX_NA_TELA = 3
ENTRA_MS = 140          # esmaecer ao aparecer / sumir (animacoes do Windows)
SAI_MS = 120
TEXTO_MAX = 160
NO_WINDOWS = sys.platform == "win32"
QUNS_ACCEPTS_NOTIFICATIONS = 5


def windows_aceita() -> bool:
    """O Windows deixa avisar agora? (nao perturbe, tela cheia, apresentacao
    = nao). Na duvida, sim."""
    if not NO_WINDOWS:
        return True
    try:
        import ctypes
        estado = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(
                ctypes.byref(estado)) != 0:
            return True
        return estado.value == QUNS_ACCEPTS_NOTIFICATIONS
    except Exception:
        return True


def _sem_foco(janela: tk.Toplevel) -> None:
    """WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW: nao rouba o foco e nao vai para a
    barra de tarefas nem para o Alt+Tab."""
    if not NO_WINDOWS:
        return
    try:
        import ctypes
        u = ctypes.windll.user32
        janela.update_idletasks()
        hwnd = u.GetParent(janela.winfo_id()) or janela.winfo_id()
        GWL_EXSTYLE = -20
        estilo = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        u.SetWindowLongW(hwnd, GWL_EXSTYLE, estilo | 0x08000000 | 0x00000080)
    except Exception as erro:
        log.debug("aviso sem foco: %s", erro)


def _da_frente():
    """A janela que esta na frente agora (None fora do Windows/erro)."""
    if not NO_WINDOWS:
        return None
    try:
        import ctypes
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return None


def _devolver_frente(antes, janela: tk.Toplevel) -> None:
    """Se o aviso ficou com a frente, ela volta para `antes`."""
    if not NO_WINDOWS or not antes:
        return
    try:
        import ctypes
        u = ctypes.windll.user32
        agora = u.GetForegroundWindow()
        if agora == antes:
            return
        meu = u.GetParent(janela.winfo_id()) or janela.winfo_id()
        if agora in (meu, janela.winfo_id()):
            u.SetForegroundWindow(antes)
            log.debug("aviso: frente devolvida")
    except Exception as erro:
        log.debug("aviso: devolver a frente: %s", erro)


class Avisos:
    """Os avisos na tela. `icone(pai, app, nome, lado)` desenha o icone do
    app (o da janela); `ao_clicar(app)` abre o app."""

    def __init__(self, raiz: tk.Tk, icone, ao_clicar, anotar=None) -> None:
        self.raiz = raiz
        self.icone = icone
        self.ao_clicar = ao_clicar
        self.anotar = anotar or (lambda _t: None)
        self._na_tela: list[tk.Toplevel] = []
        self.largura = E.px(320)

    def mostrar(self, app: str, nome: str, titulo: str, texto: str,
                hora: str, dado=None, botoes=None) -> None:
        """`dado` volta no clique: ao_clicar(app, dado). `botoes` =
        [(rotulo, funcao)]: links embaixo (copiar codigo, telas)."""
        if not windows_aceita():
            self.anotar("aviso: o windows esta em nao perturbe/tela cheia")
            return
        self._montar(app, nome, ("%s  ·  %s" % (nome, hora)).upper(), titulo,
                     texto, dado, botoes or [], chamada=None)

    def mostrar_chamada(self, app: str, nome: str, titulo: str, texto: str,
                        atender, recusar) -> None:
        """(01/out) A CHAMADA TOCANDO: fica ate `fechar_chamada` (a chamada
        acabou ou foi atendida). Atender/recusar acontecem NO CELULAR."""
        self.fechar_chamada()
        self._montar(app, nome, ("chamada  ·  %s" % nome).upper(), titulo,
                     texto or "atender pelo pc atende no celular.", None, [],
                     chamada=(atender, recusar))

    def fechar_chamada(self) -> None:
        j, self._chamada = getattr(self, "_chamada", None), None
        if j is not None:
            self._fechar(j)

    def _montar(self, app, nome, cabecalho, titulo, texto, dado, botoes,
                chamada) -> None:
        while len(self._na_tela) >= MAX_NA_TELA:
            velhos = [v for v in self._na_tela
                      if v is not getattr(self, "_chamada", None)]
            if not velhos:
                break
            self._fechar(velhos[0], animar=False)
        j = tk.Toplevel(self.raiz)
        j.withdraw()
        j.overrideredirect(True)
        j.attributes("-topmost", True)
        j.configure(bg=E.LINHA_FORTE)
        caixa = tk.Frame(j, bg=E.FUNDO)
        caixa.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Frame(caixa, bg=E.VERDE if chamada else E.ACENTO,
                 width=E.px(3)).pack(side="left", fill="y")
        dentro = tk.Frame(caixa, bg=E.FUNDO, cursor="hand2")
        dentro.pack(side="left", fill="both", expand=True,
                    padx=E.px(10), pady=E.px(8))
        topo = tk.Frame(dentro, bg=E.FUNDO, cursor="hand2")
        topo.pack(side="top", fill="x")
        ic = self.icone(topo, app, nome, E.px(16))
        ic.configure(cursor="hand2")
        ic.pack(side="left")
        rot = tk.Label(topo, text=cabecalho,
                       bg=E.FUNDO, fg=E.APAGADO, font=E.fonte(E.ROTULO),
                       anchor="w", cursor="hand2")
        rot.pack(side="left", fill="x", expand=True, padx=(E.px(6), 0))
        x = tk.Label(topo, text="×", bg=E.FUNDO, fg=E.APAGADO,
                     font=E.fonte(E.CORPO), cursor="hand2", padx=E.px(2))
        x.pack(side="right")
        pecas = [dentro, topo, ic, rot]
        if titulo:
            t = tk.Label(dentro, text=titulo[:80], bg=E.FUNDO, fg=E.TEXTO,
                         font=E.fonte(E.PEQUENA, "bold"), anchor="w",
                         cursor="hand2")
            t.pack(side="top", fill="x", pady=(E.px(4), 0))
            pecas.append(t)
        if texto:
            if len(texto) > TEXTO_MAX:
                texto = texto[:TEXTO_MAX - 1] + "…"
            c = tk.Label(dentro, text=texto, bg=E.FUNDO, fg=E.TEXTO_2,
                         font=E.fonte(E.ROTULO), anchor="w", justify="left",
                         wraplength=self.largura - E.px(30), cursor="hand2")
            c.pack(side="top", fill="x", pady=(E.px(2), 0))
            pecas.append(c)
        if botoes:
            fila = tk.Frame(dentro, bg=E.FUNDO)
            fila.pack(side="top", fill="x", pady=(E.px(6), 0))
            for rotulo, funcao in botoes:
                b = tk.Label(fila, text=rotulo, bg=E.FUNDO, fg=E.TEXTO_2,
                             font=E.fonte(E.PEQUENA), cursor="hand2")
                b.pack(side="left", padx=(0, E.px(12)))
                b.bind("<Enter>", lambda _e, w=b: w.configure(fg=E.ACENTO))
                b.bind("<Leave>", lambda _e, w=b: w.configure(fg=E.TEXTO_2))
                b.bind("<Button-1>", lambda _e, f=funcao, jj=j: (
                    f(), self._fechar(jj), "break")[2])
        if chamada:
            fila = tk.Frame(dentro, bg=E.FUNDO)
            fila.pack(side="top", fill="x", pady=(E.px(8), 0))
            for rotulo, cor, funcao in (("atender", E.VERDE, chamada[0]),
                                        ("recusar", E.ERRO, chamada[1])):
                b = tk.Label(fila, text=rotulo.upper(), bg=cor, fg=E.FUNDO,
                             font=E.fonte(E.PEQUENA, "bold"), cursor="hand2",
                             padx=E.px(14), pady=E.px(5))
                b.pack(side="left", padx=(0, E.px(8)))
                b.bind("<Button-1>", lambda _e, f=funcao: (f(), "break")[1])

        j._parado = False
        if chamada:
            self._chamada = j
        else:
            for w in pecas:
                w.bind("<Button-1>", lambda _e, a=app, jj=j: (
                    self._fechar(jj), self.ao_clicar(a, dado)))
        x.bind("<Button-1>", lambda _e, jj=j: self._fechar(jj))
        x.bind("<Enter>", lambda _e: x.configure(fg=E.ERRO))
        x.bind("<Leave>", lambda _e: x.configure(fg=E.APAGADO))
        j.bind("<Enter>", lambda _e, jj=j: setattr(jj, "_parado", True))
        j.bind("<Leave>", lambda _e, jj=j: (
            setattr(jj, "_parado", False),
            None if jj is getattr(self, "_chamada", None)
            else self._agendar(jj)))

        j.update_idletasks()
        j.geometry("%dx%d" % (self.largura, j.winfo_reqheight()))
        self._na_tela.append(j)
        self._arrumar()
        animar = moldura.animacoes_ligadas()
        if animar:
            j.attributes("-alpha", 0.0)
        antes = _da_frente()
        j.deiconify()
        _sem_foco(j)
        j.lift()
        # (02/out, revisao) O `deiconify` do Tk ativa a janela ANTES do
        # NOACTIVATE valer: com o scrcpy-f na frente (digitando na busca,
        # por exemplo) o aviso levava o foco. Levou -> devolve.
        _devolver_frente(antes, j)
        if animar:
            self._esmaecer(j, 0.0, 1.0, ENTRA_MS)
        if not chamada:
            self._agendar(j)              # a da chamada nao some sozinha

    def _esmaecer(self, j, de: float, ate: float, ms: int, fim=None) -> None:
        """Opacidade de `de` a `ate` pelo RELOGIO (como as animacoes da
        janela): um quadro atrasado nao estica a animacao."""
        import time
        inicio = time.monotonic()

        def passo():
            try:
                if not j.winfo_exists():
                    return
                t = min(1.0, (time.monotonic() - inicio) * 1000.0 / ms)
                t = 1 - (1 - t) ** 2            # desacelera no fim
                j.attributes("-alpha", de + (ate - de) * t)
                if t < 1.0:
                    j.after(10, passo)
                elif fim is not None:
                    fim()
            except tk.TclError:
                if fim is not None:
                    fim()
        passo()

    def _agendar(self, j) -> None:
        anterior = getattr(j, "_sumir_id", None)
        if anterior is not None:
            try:
                j.after_cancel(anterior)
            except tk.TclError:
                pass
        try:
            j._sumir_id = j.after(int(DURA_S * 1000), lambda: (
                None if getattr(j, "_parado", False) else self._fechar(j)))
        except tk.TclError:
            pass

    def _arrumar(self) -> None:
        """Empilha de baixo para cima: a mais nova embaixo."""
        folga = E.px(12)
        y_base = None
        for j in reversed(self._na_tela):
            try:
                altura = j.winfo_reqheight()
                x, y = moldura.canto_da_bandeja(self.raiz, self.largura,
                                                altura, folga)
                if y_base is not None:
                    y = y_base - altura - E.px(8)
                j.geometry("%dx%d+%d+%d" % (self.largura, altura, x, y))
                y_base = y
            except tk.TclError:
                pass

    def _fechar(self, j, animar: bool = True) -> None:
        if j not in self._na_tela:
            return
        self._na_tela.remove(j)

        def sumir():
            try:
                j.destroy()
            except tk.TclError:
                pass
            self._arrumar()

        if animar and moldura.animacoes_ligadas():
            try:
                self._esmaecer(j, float(j.attributes("-alpha")), 0.0,
                               SAI_MS, sumir)
                return
            except tk.TclError:
                pass
        sumir()

    def fechar_todos(self) -> None:
        for j in list(self._na_tela):
            self._fechar(j, animar=False)
