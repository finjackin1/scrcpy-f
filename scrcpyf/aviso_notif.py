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
# (03/out, pedido dele: "na velocidade das do celular") os tempos do aviso
# "heads-up" do Android (SystemUI StackStateAnimator): entra 400 ms subindo e
# aparecendo; sai 400 ms de lado, esmaecendo; os outros andam 360 ms.
ENTRA_MS = 400
SAI_MS = 400
ANDA_MS = 360
TEXTO_MAX = 160
NO_WINDOWS = sys.platform == "win32"
QUNS_ACCEPTS_NOTIFICATIONS = 5


def em_linhas(texto: str, fonte, largura: int, maximo: int) -> str:
    """(08/out, relato dele: o titulo do aviso saia cortado no meio da
    palavra -- o Label nao quebrava) O texto quebrado ENTRE PALAVRAS em ate
    `maximo` linhas da `largura`; sobrou, a ultima termina em "…" (no fim de
    uma palavra, se der). Palavra maior que a linha e cortada nela."""
    import tkinter.font as tkfont
    try:
        medir = tkfont.nametofont(fonte).measure
    except (tk.TclError, TypeError):
        def medir(t):
            return len(t) * E.px(6)
    linhas: list = []
    for paragrafo in E.texto_limpo(texto or "").strip().split("\n"):
        atual = ""
        for palavra in paragrafo.split():
            tentativa = (atual + " " + palavra) if atual else palavra
            if medir(tentativa) <= largura:
                atual = tentativa
                continue
            if atual:
                linhas.append(atual)
            while medir(palavra) > largura and len(palavra) > 1:
                corte = len(palavra)
                while corte > 1 and medir(palavra[:corte]) > largura:
                    corte -= 1
                linhas.append(palavra[:corte])
                palavra = palavra[corte:]
            atual = palavra
        if atual:
            linhas.append(atual)
        if len(linhas) > maximo:
            break
    if len(linhas) <= maximo:
        return "\n".join(linhas)
    ultima = linhas[maximo - 1]
    while ultima and medir(ultima + "…") > largura:
        ultima = ultima[:-1]
    espaco = ultima.rfind(" ")
    if espaco >= len(ultima) * 2 // 3:
        ultima = ultima[:espaco]
    return "\n".join(linhas[:maximo - 1] + [ultima.rstrip(" ,;:·-–—") + "…"])


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


def _pilula(fila, rotulo: str) -> tk.Label:
    """(07/out, One UI) Um botao do aviso: pilula um tom acima da
    superficie, texto inteiro em minusculas; o mouse clareia."""
    from .visual_notif import misturar
    parado = misturar(E.TEXTO, E.SUPERFICIE, 0.08)
    sobre = misturar(E.TEXTO, E.SUPERFICIE, 0.16)
    b = tk.Label(fila, text=rotulo.strip().lower(), bg=parado, fg=E.TEXTO,
                 font=E.fonte(E.PEQUENA, "bold"), cursor="hand2",
                 padx=E.px(12), pady=E.px(5))
    b.pack(side="left", padx=(0, E.px(6)))
    raio = E.px(12)
    E.cantos(b, raio=raio)

    def pintar(cor):
        b.configure(bg=cor)
        E.cantos(b, raio=raio)
    b.bind("<Enter>", lambda _e: pintar(sobre))
    b.bind("<Leave>", lambda _e: pintar(parado))
    return b


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


def _com_foco(janela: tk.Toplevel) -> None:
    """(03/out) Para responder: o aviso passa a aceitar o teclado (tira o
    NOACTIVATE) e vem para a frente."""
    if not NO_WINDOWS:
        return
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = u.GetParent(janela.winfo_id()) or janela.winfo_id()
        GWL_EXSTYLE = -20
        estilo = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        u.SetWindowLongW(hwnd, GWL_EXSTYLE, estilo & ~0x08000000)
        u.SetForegroundWindow(hwnd)
    except Exception as erro:
        log.debug("aviso com foco: %s", erro)


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
        # (07/out) botao direito no aviso: ao_menu(app, dado, evento) -- o
        # mesmo menu da notificacao na janela
        self.ao_menu = None
        self.anotar = anotar or (lambda _t: None)
        self._na_tela: list[tk.Toplevel] = []
        self.largura = E.px(320)

    def mostrar(self, app: str, nome: str, titulo: str, texto: str,
                hora: str, dado=None, botoes=None, responder=None,
                rosto=None) -> None:
        """`dado` volta no clique: ao_clicar(app, dado). `botoes` =
        [(rotulo, funcao)]: links embaixo (copiar codigo, telas).
        (03/out) `responder` = (rotulo, enviar): o link abre uma caixa NO
        AVISO; enviar(texto, ao_fim) e ao_fim(ok, motivo) volta na thread do
        Tk. `rosto` = imagem (Tk) de quem mandou, ao lado do titulo."""
        if not windows_aceita():
            self.anotar("aviso: o windows esta em nao perturbe/tela cheia")
            return
        self._montar(app, nome, "%s  ·  %s" % (nome, hora), titulo,
                     texto, dado, botoes or [], chamada=None,
                     responder=responder, rosto=rosto)

    def mostrar_chamada(self, app: str, nome: str, titulo: str, texto: str,
                        atender, recusar) -> None:
        """(01/out) A CHAMADA TOCANDO: fica ate `fechar_chamada` (a chamada
        acabou ou foi atendida). Atender/recusar acontecem NO CELULAR."""
        self.fechar_chamada()
        self._montar(app, nome, "chamada  ·  %s" % nome, titulo,
                     texto or "atender pelo pc atende no celular.", None, [],
                     chamada=(atender, recusar))

    def fechar_chamada(self) -> None:
        j, self._chamada = getattr(self, "_chamada", None), None
        if j is not None:
            self._fechar(j)

    def _montar(self, app, nome, cabecalho, titulo, texto, dado, botoes,
                chamada, responder=None, rosto=None) -> None:
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
        j.configure(bg=E.SUPERFICIE)          # a borda e a do Windows (arredondar)
        caixa = tk.Frame(j, bg=E.SUPERFICIE)
        caixa.pack(fill="both", expand=True)
        # (03/out, regra dele: laranja so para acao/estado) a faixa colorida
        # ficou so na CHAMADA (verde = tocando); o aviso comum e liso.
        if chamada:
            tk.Frame(caixa, bg=E.VERDE, width=E.px(3)).pack(side="left",
                                                           fill="y")
        dentro = tk.Frame(caixa, bg=E.SUPERFICIE, cursor="hand2")
        dentro.pack(side="left", fill="both", expand=True,
                    padx=E.px(14), pady=E.px(12))      # (07/out) One UI
        topo = tk.Frame(dentro, bg=E.SUPERFICIE, cursor="hand2")
        topo.pack(side="top", fill="x")
        try:                                # o aviso e a superficie clara
            ic = self.icone(topo, app, nome, E.px(16), fundo=E.SUPERFICIE)
        except TypeError:
            ic = self.icone(topo, app, nome, E.px(16))
            ic.configure(bg=E.SUPERFICIE)
        ic.configure(cursor="hand2")
        ic.pack(side="left")
        rot = tk.Label(topo, text=E.texto_limpo(cabecalho),
                       bg=E.SUPERFICIE, fg=E.APAGADO, font=E.fonte(E.ROTULO),
                       anchor="w", cursor="hand2")
        rot.pack(side="left", fill="x", expand=True, padx=(E.px(6), 0))
        # (07/out) o x da casa (icone de linha), o mesmo da janela
        x = E.botao_x(topo, E.SUPERFICIE, lambda jj=j: self._fechar(jj))
        x.pack(side="right")
        pecas = [dentro, topo, ic, rot]
        # (08/out) a largura de dentro (o aviso menos as margens e a faixa da
        # chamada); titulo em ate 2 linhas e texto em ate 4, quebrados entre
        # palavras (`em_linhas`), como o cartao do Android
        util = self.largura - 2 * E.px(14) - (E.px(3) if chamada else 0) \
            - E.px(2)
        if titulo:
            fonte_t = E.fonte(E.PEQUENA, "bold")
            larg_t = util - ((rosto.width() + E.px(6)) if rosto else 0)
            t = tk.Label(dentro, text=(" " if rosto else "") + em_linhas(
                             titulo, fonte_t, larg_t, 2),
                         bg=E.SUPERFICIE, fg=E.TEXTO, font=fonte_t,
                         anchor="w", justify="left", cursor="hand2",
                         image=rosto or "", compound="left")
            t._img = rosto                   # a imagem vive com o rotulo
            t.pack(side="top", fill="x", pady=(E.px(4), 0))
            pecas.append(t)
        if texto:
            if len(texto) > TEXTO_MAX:
                texto = texto[:TEXTO_MAX - 1] + "…"
            fonte_c = E.fonte(E.ROTULO)
            c = tk.Label(dentro, text=em_linhas(texto, fonte_c, util, 4),
                         bg=E.SUPERFICIE, fg=E.TEXTO_2, font=fonte_c,
                         anchor="w", justify="left", cursor="hand2")
            c.pack(side="top", fill="x", pady=(E.px(2), 0))
            pecas.append(c)
        if botoes or responder:
            # (07/out, pedido dele: One UI) os botoes em PILULAS, o rotulo
            # inteiro, como os do cartao da janela
            fila = tk.Frame(dentro, bg=E.SUPERFICIE)
            fila.pack(side="top", fill="x", pady=(E.px(8), 0))
            if responder:
                b = _pilula(fila, responder[0])
                b.bind("<Button-1>", lambda _e, jj=j: (
                    self._caixa(jj, dentro, responder[1]), "break")[1])
            for rotulo, funcao in botoes:
                b = _pilula(fila, rotulo)
                b.bind("<Button-1>", lambda _e, f=funcao, jj=j: (
                    f(), self._fechar(jj), "break")[2])
        if chamada:
            fila = tk.Frame(dentro, bg=E.SUPERFICIE)
            fila.pack(side="top", fill="x", pady=(E.px(8), 0))
            for rotulo, cor, funcao in (("atender", E.VERDE, chamada[0]),
                                        ("recusar", E.ERRO, chamada[1])):
                b = tk.Label(fila, text=rotulo, bg=cor, fg=E.FUNDO,
                             font=E.fonte(E.PEQUENA, "bold"), cursor="hand2",
                             padx=E.px(14), pady=E.px(5))
                b.pack(side="left", padx=(0, E.px(8)))
                E.cantos(b, raio=E.px(6))    # (07/out) canto redondo
                b.bind("<Button-1>", lambda _e, f=funcao: (f(), "break")[1])

        j._parado = False
        if chamada:
            self._chamada = j
        else:
            for w in pecas:
                w.bind("<Button-1>", lambda _e, a=app, jj=j: (
                    self._fechar(jj), self.ao_clicar(a, dado)))
                if dado is not None:
                    w.bind("<Button-3>", lambda e, a=app, jj=j: (
                        setattr(jj, "_parado", True),
                        self.ao_menu and self.ao_menu(a, dado, e), "break")[2])
        j.bind("<Enter>", lambda _e, jj=j: setattr(jj, "_parado", True))
        j.bind("<Leave>", lambda _e, jj=j: (
            setattr(jj, "_parado", False),
            None if jj is getattr(self, "_chamada", None)
            else self._agendar(jj)))

        j.update_idletasks()
        j.geometry("%dx%d" % (self.largura, j.winfo_reqheight()))
        animar = moldura.animacoes_ligadas()
        j._entrando = animar
        self._na_tela.append(j)
        self._arrumar()
        if animar:
            j.attributes("-alpha", 0.0)
        antes = _da_frente()
        j.deiconify()
        _sem_foco(j)
        moldura.arredondar_ao_mostrar(j, borda=E.SUPERFICIE_BORDA)   # (03/out)
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
        from .lista_animada import PADRAO, SAIDA
        curva = PADRAO if ate > de else SAIDA
        inicio = time.monotonic()

        def passo():
            try:
                if not j.winfo_exists():
                    return
                t = min(1.0, (time.monotonic() - inicio) * 1000.0 / ms)
                j.attributes("-alpha", de + (ate - de) * curva(t))
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
                None if getattr(j, "_parado", False) or
                getattr(j, "_respondendo", False) else self._fechar(j)))
        except tk.TclError:
            pass

    # -- responder no proprio aviso (03/out, pedido dele) ---------------------

    def _caixa(self, j, dentro, enviar) -> None:
        """Abre a caixa de resposta no aviso. O aviso para de sumir e passa
        a aceitar o teclado (ele nasce sem foco de proposito)."""
        if getattr(j, "_campo", None) is not None:
            j._campo.focus_set()
            return
        j._respondendo = True
        linha = tk.Frame(dentro, bg=E.SUPERFICIE)
        linha.pack(side="top", fill="x", pady=(E.px(6), 0))
        moldura_c = tk.Frame(linha, bg=E.FUNDO_FUNDO, highlightthickness=1,
                             highlightbackground=E.FOCO)
        moldura_c.pack(side="left", fill="x", expand=True)
        E.cantos(moldura_c)              # (07/out) canto arredondado
        campo = tk.Entry(moldura_c, font=E.fonte(E.ROTULO), bg=E.FUNDO_FUNDO,
                         fg=E.TEXTO, insertbackground=E.TEXTO, relief="flat",
                         highlightthickness=0, bd=0,
                         disabledbackground=E.FUNDO_FUNDO,
                         disabledforeground=E.APAGADO)
        campo.pack(fill="x", ipady=E.px(3), padx=E.px(5))
        ir = tk.Label(linha, text="enviar", bg=E.SUPERFICIE, fg=E.TEXTO_2,
                      font=E.fonte(E.PEQUENA), cursor="hand2")
        ir.pack(side="right", padx=(E.px(8), 0))
        recado = tk.Label(dentro, text="", bg=E.SUPERFICIE, fg=E.APAGADO,
                          font=E.fonte(E.ROTULO), anchor="w", justify="left",
                          wraplength=self.largura - E.px(30))
        j._campo = campo

        def mostrar_recado(texto, erro=False):
            recado.configure(text=texto, fg=E.ERRO if erro else E.APAGADO)
            if not recado.winfo_manager():
                recado.pack(side="top", fill="x", pady=(E.px(3), 0))
            j.update_idletasks()
            self._arrumar()

        def fim(ok, motivo):
            try:
                if not j.winfo_exists():
                    return
                if ok:
                    mostrar_recado("enviado.")
                    j.after(1200, lambda: self._fechar(j))
                else:
                    campo.configure(state="normal")
                    mostrar_recado("não foi: %s." % motivo, erro=True)
                    campo.focus_set()
            except tk.TclError:
                pass

        def mandar(_e=None):
            texto = campo.get().strip()
            if texto and str(campo.cget("state")) == "normal":
                campo.configure(state="disabled")
                mostrar_recado("enviando…")
                enviar(texto, fim)
            return "break"

        campo.bind("<Return>", mandar)
        campo.bind("<Escape>", lambda _e: (self._fechar(j), "break")[1])
        ir.bind("<Button-1>", mandar)
        ir.bind("<Enter>", lambda _e: ir.configure(fg=E.TEXTO))
        ir.bind("<Leave>", lambda _e: ir.configure(fg=E.TEXTO_2))
        j.update_idletasks()
        self._arrumar()
        _com_foco(j)
        campo.focus_force()

    def _arrumar(self) -> None:
        """Empilha de baixo para cima: a mais nova embaixo."""
        folga = E.px(12)
        y_base = None
        # (03/out) o que ja ocupa o canto (o mini player): os avisos
        # empilham ACIMA dele em vez de cobri-lo. `reserva()` -> altura.
        reservado = 0
        try:
            reservado = int(self.reserva()) if callable(
                getattr(self, "reserva", None)) else 0
        except Exception:
            reservado = 0
        animar = moldura.animacoes_ligadas()
        for j in reversed(self._na_tela):
            try:
                altura = j.winfo_reqheight()
                x, y = moldura.canto_da_bandeja(self.raiz, self.largura,
                                                altura, folga)
                if y_base is None and reservado:
                    y -= reservado + E.px(8)
                if y_base is not None:
                    y = y_base - altura - E.px(8)
                if getattr(j, "_entrando", False):
                    # entra subindo um pouco, como o heads-up desce no celular
                    j._entrando = False
                    self._por(j, x, y + E.px(28), altura)
                    self._deslizar(j, x, y, altura, ENTRA_MS)
                elif animar and getattr(j, "_xy", None) is not None and \
                        j._xy != (x, y):
                    self._deslizar(j, x, y, altura, ANDA_MS)
                else:
                    self._por(j, x, y, altura)
                y_base = y
            except tk.TclError:
                pass

    def _por(self, j, x, y, altura) -> None:
        j.geometry("%dx%d+%d+%d" % (self.largura, altura, int(x), int(y)))
        j._xy = (int(x), int(y))

    def _deslizar(self, j, x, y, altura, ms: int, curva=None) -> None:
        """Leva o aviso de onde esta ate (x, y) pelo relogio."""
        import time
        from .lista_animada import PADRAO
        curva = curva or PADRAO
        de = getattr(j, "_xy", None) or (x, y)
        inicio = time.monotonic()
        j._anda = inicio                       # um deslize novo para o velho

        def passo():
            try:
                if not j.winfo_exists() or getattr(j, "_anda", None) != inicio:
                    return
                t = min(1.0, (time.monotonic() - inicio) * 1000.0 / ms)
                k = curva(t)
                self._por(j, de[0] + (x - de[0]) * k,
                          de[1] + (y - de[1]) * k, altura)
                if t < 1.0:
                    j.after(10, passo)
            except tk.TclError:
                pass
        passo()

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
                from .lista_animada import SAIDA
                xy = getattr(j, "_xy", None)
                if xy is not None:
                    self._deslizar(j, xy[0] + E.px(60), xy[1],
                                   j.winfo_height(), SAI_MS, SAIDA)
                self._esmaecer(j, float(j.attributes("-alpha")), 0.0,
                               SAI_MS, sumir)
                return
            except tk.TclError:
                pass
        sumir()

    def fechar_todos(self) -> None:
        for j in list(self._na_tela):
            self._fechar(j, animar=False)
