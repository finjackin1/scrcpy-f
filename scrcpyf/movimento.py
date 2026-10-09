"""
MOVIMENTO DA CASA (07/out/2026, pedido dele: "padronizar a animacao no
programa todo").

Um lugar so para as curvas e os tempos (os do Android -- SystemUI e One UI,
docs/contexto/animacoes.md) e para os movimentos que se repetem:
  - `animar(w, chave, ms, a_cada, fim, curva)`: roda a_cada(k) com k de 0 a 1
    pelo RELOGIO (quadro atrasado nao estica); a mesma chave no mesmo widget
    cancela a anterior;
  - `entrar(janelinha)` / `sair(janelinha, fim)`: as janelinhas por cima
    (menus, dica, seletor, identificar telas) aparecem esmaecendo e descendo
    uns pixels, e somem esmaecendo;
  - `mudar_cor(...)`: troca de cor suave (chave, segmentado).
Com as animacoes do Windows desligadas (acessibilidade), tudo vai direto ao
fim.
"""

from __future__ import annotations

import time
import tkinter as tk

from .lista_animada import (PADRAO, SAIDA, bezier, misturar,   # noqa: F401
                            MS_PADRAO, MS_APARECER, MS_SWIPE)

# LINEAR_OUT_SLOW_IN do Android: o que ENTRA chega rapido e pousa devagar.
ENTRADA = bezier(0.0, 0.0, 0.2, 1.0)

MS_QUADRO = 10
# (07/out) um intervalo entre quadros maior que isto (s) = o Tk engasgou
# (pintura, montagem): a animacao pausa em vez de pular (ver `animar`)
ENGASGO = 0.045
PASSO_NO_ENGASGO = 0.033   # o quanto a animacao anda num engasgo (2 quadros)
MS_POPUP_ENTRA = 200      # menu/dica (Material: 150-250; One UI >= 100)
MS_POPUP_SAI = 150
MS_CONTROLE = 200         # chave, segmentado (One UI "basic" ~200)
MS_EXPANDIR = MS_PADRAO   # abrir/fechar um grupo (StackStateAnimator 360)


def ligadas() -> bool:
    try:
        from . import moldura
        return moldura.animacoes_ligadas()
    except Exception:
        return True


def parar(w, chave: str) -> None:
    ids = getattr(w, "_mov_ids", None)
    if not ids:
        return
    ident = ids.pop(chave, None)
    if ident is not None:
        try:
            w.after_cancel(ident)
        except Exception:
            pass


def animar(w, chave: str, ms: float, a_cada, fim=None, curva=PADRAO) -> None:
    """a_cada(k) com k = curva(t), t de 0 a 1 em `ms`; depois fim()."""
    parar(w, chave)
    if not ligadas() or ms <= 0:
        try:
            a_cada(1.0)
        except tk.TclError:
            return
        if fim is not None:
            fim()
        return
    if not hasattr(w, "_mov_ids"):
        try:
            w._mov_ids = {}
        except Exception:
            a_cada(1.0)
            if fim is not None:
                fim()
            return
    # O relogio comeca no PRIMEIRO QUADRO LIVRE (07/out, medido): montar
    # e pintar uma janelinha nova segura o Tk uns 50-500 ms, e contando
    # desde a chamada o esmaecer ja nascia no fim (pulava de 0 para 1).
    inicio = [None]
    ultimo = [None]

    def passo():
        if inicio[0] is None:
            # a pintura pendente (a tela/janelinha nova) acontece AGORA,
            # antes de o relogio comecar: senao ela comia o comeco
            try:
                w.update_idletasks()
            except tk.TclError:
                return
        agora = time.monotonic()
        if inicio[0] is None:
            inicio[0] = agora
        elif ultimo[0] is not None and agora - ultimo[0] > ENGASGO:
            # (07/out, varredura: o menu "pulava" o comeco -- o 1o quadro
            # visivel custava 80-330 ms de pintura) o Tk engasgou: o
            # relogio da animacao PAUSA nesse tempo, em vez de ela saltar.
            # (07/out, gravado na partida: com o Tk ocupado por segundos o
            # balao subia em camera lenta e ficava meio para fora, "uma
            # aba") Cada engasgo ainda anda ATE 2 QUADROS (~33 ms): sem salto
            # grande e sem virar espera.
            inicio[0] += (agora - ultimo[0]) - min(
                agora - ultimo[0], PASSO_NO_ENGASGO)
        ultimo[0] = agora
        t = min(1.0, (agora - inicio[0]) * 1000.0 / ms)
        try:
            if not w.winfo_exists():
                return
            a_cada(curva(t))
        except tk.TclError:
            w._mov_ids.pop(chave, None)
            return
        if t < 1.0:
            w._mov_ids[chave] = w.after(MS_QUADRO, passo)
        else:
            w._mov_ids.pop(chave, None)
            if fim is not None:
                fim()

    try:
        a_cada(curva(0.0))               # o ponto de partida, ja
    except tk.TclError:
        return
    w._mov_ids[chave] = w.after(MS_QUADRO, passo)


def entrar(j, dy: int = 6) -> None:
    """Janelinha (Toplevel ja com a geometria "+x+y" final) aparece
    esmaecendo e descendo `dy` px ate o lugar."""
    try:
        j.update_idletasks()
        geo = j.geometry()
        _tam, _, pos = geo.partition("+")
        x, y = (int(v) for v in pos.split("+")[:2])
    except Exception:
        return
    if not ligadas():
        return
    try:
        j.attributes("-alpha", 0.0)
    except tk.TclError:
        return

    def a_cada(k):
        j.attributes("-alpha", k)
        j.geometry("+%d+%d" % (x, round(y - dy * (1.0 - k))))

    animar(j, "entrar", MS_POPUP_ENTRA, a_cada, curva=ENTRADA)


def sair(j, fim=None) -> None:
    """Some esmaecendo e chama fim() (em geral o destroy)."""
    def acabar():
        if fim is not None:
            try:
                fim()
            except tk.TclError:
                pass
    try:
        if not j.winfo_exists() or not j.winfo_viewable():
            acabar()
            return
        a0 = float(j.attributes("-alpha"))
    except (tk.TclError, ValueError):
        acabar()
        return
    parar(j, "entrar")
    j._saindo = True
    animar(j, "sair", MS_POPUP_SAI,
           lambda k: j.attributes("-alpha", a0 * (1.0 - k)), acabar,
           curva=SAIDA)


def cor_entre(de: str, para: str, k: float) -> str:
    """A cor no ponto k (0 = de, 1 = para)."""
    return misturar(para, de, k)
