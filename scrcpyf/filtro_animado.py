"""
FILTRO ANIMADO (09/out/2026, pedido dele: "ao pesquisar a lista pisca
atualizando; ela deve ter uma animacao de remocao e mover os icones conforme
as letras sao digitadas").

Uma lista (ou grade) de widgets com CHAVE, postos com `place` num `pai`
(o `dentro` de uma rolagem). `Arranjo.aplicar(layout)` leva a lista ao
layout novo, como a gaveta de apps do Android:
  - o que SAI esmaece no lugar (os primeiros ~45% do tempo) e e destruido;
  - o que FICA anda do lugar velho ao novo (o tempo todo, FAST_OUT_SLOW_IN);
  - o que ENTRA nasce no lugar novo e aparece esmaecendo (a 2a metade).
So anima o que esta (ou vai estar) a vista; o resto vai direto.

(09/out, "as animacoes estao muito travadas") Quem anda e esmaece e uma
COPIA (`Espelho`) dos itens num canvas so, por cima da vista; a lista de
verdade ja vai direto ao fim, embaixo, e aparece de uma vez quando a copia
sai. Mover dezenas de janelas do Windows a cada quadro era o que travava.
ESMAECER na copia: as cores andam continuas da cor do fundo a de verdade e
as imagens sao misturadas com o PIL (`ImageTk.getimage`), em 8 niveis
guardados. Conferido pixel a pixel: a copia parada = a lista (t_espelho).
"""

from __future__ import annotations

import logging
import tkinter as tk

from . import movimento as mov

log = logging.getLogger(__name__)

MS = 300                  # o filtro inteiro (gaveta do Android ~300)
SAI_ATE = 0.45            # o que sai some nesse pedaco do tempo
ENTRA_DE = 0.40           # o que entra comeca a aparecer daqui
NIVEIS = 10
NIVEIS_IMG = 8           # passos das imagens na copia (cores sao continuas;
                          # 16 engasgava com muitos icones novos: ~0,5 ms cada)
MAX_ANIMADOS = 90         # passou disso (a vista inteira mudou): direto

_ANIMANDO: set = set()    # os Arranjos no meio de uma animacao


def animando() -> bool:
    """Algum filtro andando agora? (os lotes esperam: montar no meio dos
    quadros fazia a animacao engasgar)"""
    return bool(_ANIMANDO)


def _hex(w, cor: str) -> str | None:
    try:
        r, g, b = w.winfo_rgb(cor)
    except (tk.TclError, TypeError):
        return None
    return "#%02x%02x%02x" % (r >> 8, g >> 8, b >> 8)


def _mistura(a: str, b: str, k: float) -> str:
    """a -> b em k (0 = a, 1 = b); a e b em #rrggbb."""
    ra, ga, ba = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    rb, gb, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    return "#%02x%02x%02x" % (round(ra + (rb - ra) * k),
                              round(ga + (gb - ga) * k),
                              round(ba + (bb - ba) * k))


class _Ref:
    """Uma imagem do Tk pelo nome, para o `ImageTk.getimage`."""

    def __init__(self, w, nome: str) -> None:
        self.tk = w.tk
        self._nome = nome

    def __str__(self) -> str:
        return self._nome

    def width(self) -> int:
        return int(self.tk.call("image", "width", self._nome))

    def height(self) -> int:
        return int(self.tk.call("image", "height", self._nome))


_FOTOS: dict = {}          # (nome, fundo_da_peca, fundo, nivel) -> foto
_PIL: dict = {}            # (nome, fundo_da_peca) -> imagem RGB sobre o fundo


def _foto_esmaecida(w, nome: str, sob: str, fundo: str, nivel: int,
                    niveis: int = NIVEIS):
    chave = (nome, sob, fundo, nivel, niveis)
    foto = _FOTOS.get(chave)
    if foto is not None:
        return foto
    try:
        from PIL import Image, ImageTk
        base = _PIL.get((nome, sob))
        if base is None:
            rgba = ImageTk.getimage(_Ref(w, nome)).convert("RGBA")
            base = Image.new("RGB", rgba.size, sob)
            base.paste(rgba, (0, 0), rgba)
            _PIL[(nome, sob)] = base
        liso = Image.new("RGB", base.size, fundo)
        foto = ImageTk.PhotoImage(Image.blend(liso, base, nivel / niveis),
                                  master=w)
    except Exception:
        log.debug("sem esmaecer a imagem %s", nome, exc_info=True)
        return None
    if len(_FOTOS) > 3000:
        _FOTOS.clear()
        _PIL.clear()
    _FOTOS[chave] = foto
    return foto


_FINO = [0]


def _relogio_fino(ligar: bool) -> None:
    """(09/out) O relogio do Windows anda de ~15,6 em 15,6 ms: os quadros
    da animacao (pedidos a cada 10 ms) saiam a cada 16-31 ms, aos trancos.
    Durante a animacao ele vai a 1 ms (timeBeginPeriod, como os
    navegadores fazem) e volta no fim."""
    try:
        import ctypes
        if ligar:
            if _FINO[0] == 0:
                ctypes.windll.winmm.timeBeginPeriod(1)
            _FINO[0] += 1
        elif _FINO[0] > 0:
            _FINO[0] -= 1
            if _FINO[0] == 0:
                ctypes.windll.winmm.timeEndPeriod(1)
    except Exception:
        pass

_ANCORAS = {"nw": (0, 0), "n": (.5, 0), "ne": (1, 0), "w": (0, .5),
            "center": (.5, .5), "e": (1, .5), "sw": (0, 1), "s": (.5, 1),
            "se": (1, 1)}


_FONTES: dict = {}
_CORTES: dict = {}           # (imagem, corte) -> foto cortada (fica viva)


def _fonte(w, fonte):
    """tkfont.Font de uma fonte de widget, guardada (medir e barato)."""
    import tkinter.font as tkfont
    chave = str(fonte)
    f = _FONTES.get(chave)
    if f is None:
        f = _FONTES[chave] = tkfont.Font(root=w, font=fonte)
    return f


def _num(w, op: str) -> int:
    try:
        return int(float(str(w.cget(op)) or 0))
    except (tk.TclError, ValueError):
        return 0


class Espelho:
    """
    (09/out, pedido dele: "as animacoes estao muito travadas") A COPIA de um
    widget -- e de tudo dentro dele -- em itens de UM canvas (`c`): fundos,
    bordas, textos (mesma fonte do Tk), imagens e os itens dos canvas de
    dentro. Andar e esmaecer a copia custa quase nada (um canvas so),
    enquanto mover janelas de verdade do Windows engasgava. `ox, oy` = o
    canto do canvas na tela (rootx/rooty): a copia nasce onde o widget esta.
    """

    def __init__(self, c, raiz, ox: int, oy: int, fundo: str,
                 tag: str) -> None:
        self.c = c
        self.tag = tag
        self.fundo = _hex(c, fundo) or "#000000"
        self.itens = []          # (id, opcao, cor | (imagem, sob))
        self._nivel = None
        self.x0 = raiz.winfo_rootx() - ox
        self.y0 = raiz.winfo_rooty() - oy
        self._ox, self._oy = ox, oy
        self._copiar(raiz)
        for p in getattr(raiz, "_cantos", None) or []:
            self._copiar(p)

    def _guardar(self, item, op, valor) -> None:
        self.itens.append((item, op, valor))

    def _ret(self, x0, y0, x1, y1, cor) -> None:
        if x1 <= x0 or y1 <= y0 or not cor:
            return
        i = self.c.create_rectangle(x0, y0, x1, y1, fill=cor, width=0,
                                    tags=self.tag)
        self._guardar(i, "fill", cor)

    def _copiar(self, w) -> None:
        try:
            if not w.winfo_ismapped():
                return
            x = w.winfo_rootx() - self._ox
            y = w.winfo_rooty() - self._oy
            larg, alt = w.winfo_width(), w.winfo_height()
        except tk.TclError:
            return
        try:
            bg = _hex(w, w.cget("bg"))
        except tk.TclError:
            bg = None
        hl = _num(w, "highlightthickness")
        bd = _num(w, "bd")
        self._ret(x, y, x + larg, y + alt, bg)
        if hl:
            try:
                foco = w.focus_get() is w
            except (tk.TclError, KeyError):
                foco = False
            cor = _hex(w, w.cget("highlightcolor" if foco
                                else "highlightbackground"))
            self._ret(x, y, x + larg, y + hl, cor)
            self._ret(x, y + alt - hl, x + larg, y + alt, cor)
            self._ret(x, y + hl, x + hl, y + alt - hl, cor)
            self._ret(x + larg - hl, y + hl, x + larg, y + alt - hl, cor)
        if isinstance(w, tk.Label):
            self._label(w, x, y, larg, alt, bd + hl, bg)
        elif isinstance(w, tk.Canvas):
            self._canvas(w, x, y, bg)
        for filho in w.winfo_children():
            self._copiar(filho)
            for p in getattr(filho, "_cantos", None) or []:
                if p.master is w:
                    self._copiar(p)

    def _label(self, w, x, y, larg, alt, ins, bg) -> None:
        px, py = _num(w, "padx"), _num(w, "pady")
        cx0, cy0 = x + ins + px, y + ins + py
        cl, ca = larg - 2 * (ins + px), alt - 2 * (ins + py)
        try:
            anc = str(w.cget("anchor")) or "center"
        except tk.TclError:
            anc = "center"
        fx, fy = _ANCORAS.get(anc, (.5, .5))
        ax, ay = cx0 + cl * fx, cy0 + ca * fy
        imagem = str(w.cget("image") or "")
        if imagem:
            i = self.c.create_image(ax, ay, image=imagem, anchor=anc,
                                    tags=self.tag)
            self._guardar(i, "image", (imagem, bg or self.fundo))
            return
        texto = w.cget("text")
        if not texto:
            return
        cor = _hex(w, w.cget("fg"))
        largura = _num(w, "wraplength")
        fonte = w.cget("font")
        if "\n" not in str(texto) and not largura:
            # uma linha: o canto do texto calculado como o Tk faz no rotulo
            # (inteiro, sobra dividida por 2) -- pelo centro, a copia
            # saia 1 px abaixo
            try:
                f = _fonte(w, fonte)
                tl = f.measure(texto)
                ta = f.metrics("linespace")
                tx = cx0 + int((cl - tl) * fx)
                ty = cy0 + int((ca - ta) * fy)
                i = self.c.create_text(tx, ty, text=texto, font=fonte,
                                       fill=cor, anchor="nw", tags=self.tag)
                self._guardar(i, "fill", cor)
                return
            except tk.TclError:
                pass
        i = self.c.create_text(ax, ay, text=texto, font=fonte,
                               fill=cor, anchor=anc,
                               justify=w.cget("justify"),
                               width=largura or 0, tags=self.tag)
        self._guardar(i, "fill", cor)

    def _canvas(self, w, x, y, bg) -> None:
        # (medido) o Tk desenha os itens a partir do canto de FORA do canvas
        # e CORTA o que cai na borda (highlight + bd): a chave (highlight 1)
        # perde 1 px de cada lado -- a copia corta igual (`_cortar`)
        ins = _num(w, "highlightthickness") + _num(w, "bd")
        try:
            dx = x - w.canvasx(0)
            dy = y - w.canvasy(0)
        except tk.TclError:
            return
        for i in w.find_all():
            try:
                if w.itemcget(i, "state") == "hidden":
                    continue
                tipo = w.type(i)
                coords = w.coords(i)
                if not coords:
                    continue
                pts = [v + (dx if k % 2 == 0 else dy)
                       for k, v in enumerate(coords)]
                if tipo == "image":
                    nome = str(w.itemcget(i, "image"))
                    if not nome:
                        continue
                    n = self.c.create_image(*pts, image=nome,
                                            anchor=w.itemcget(i, "anchor"),
                                            tags=self.tag)
                    # o canvas de verdade CORTA o que passa da borda dele (a
                    # chave: 1 px): a copia corta igual
                    nome = self._cortar(n, nome, x + ins, y + ins,
                                        x + w.winfo_width() - ins,
                                        y + w.winfo_height() - ins)
                    self._guardar(n, "image", (nome, bg or self.fundo))
                elif tipo == "text":
                    cor = _hex(w, w.itemcget(i, "fill"))
                    n = self.c.create_text(
                        *pts, text=w.itemcget(i, "text"),
                        font=w.itemcget(i, "font"), fill=cor,
                        anchor=w.itemcget(i, "anchor"),
                        justify=w.itemcget(i, "justify"),
                        width=w.itemcget(i, "width"), tags=self.tag)
                    self._guardar(n, "fill", cor)
                elif tipo in ("rectangle", "oval", "polygon", "line",
                              "arc"):
                    op = {}
                    for nome in ("fill", "outline", "width", "capstyle",
                                 "joinstyle", "smooth", "start", "extent",
                                 "style"):
                        try:
                            v = w.itemcget(i, nome)
                        except tk.TclError:
                            continue
                        if v not in ("", None):
                            op[nome] = v
                    for cor_op in ("fill", "outline"):
                        if cor_op in op:
                            op[cor_op] = _hex(w, op[cor_op]) or op[cor_op]
                    n = getattr(self.c, "create_" + tipo)(
                        *pts, tags=self.tag, **op)
                    for cor_op in ("fill", "outline"):
                        if cor_op in op:
                            self._guardar(n, cor_op, op[cor_op])
            except tk.TclError:
                continue

    def _cortar(self, item, nome: str, x0, y0, x1, y1) -> str:
        """A imagem do item cortada no retangulo (se passar dele); devolve
        o nome da imagem que ficou no item."""
        caixa = self.c.bbox(item)
        if not caixa or (caixa[0] >= x0 and caixa[1] >= y0 and
                         caixa[2] <= x1 and caixa[3] <= y1):
            return nome
        corte = (max(0, int(x0 - caixa[0])), max(0, int(y0 - caixa[1])),
                 int(min(caixa[2], x1) - caixa[0]),
                 int(min(caixa[3], y1) - caixa[1]))
        chave = (nome, corte)
        foto = _CORTES.get(chave)
        if foto is None:
            try:
                from PIL import ImageTk
                im = ImageTk.getimage(_Ref(self.c, nome)).crop(corte)
                foto = _CORTES[chave] = ImageTk.PhotoImage(im, master=self.c)
            except Exception:
                return nome
        self.c.itemconfigure(item, image=foto, anchor="nw")
        self.c.coords(item, caixa[0] + corte[0], caixa[1] + corte[1])
        return str(foto)

    def k(self, k: float) -> None:
        """Opacidade: 0 = a cor do fundo, 1 = a de verdade. As cores andam
        continuas; as imagens, em NIVEIS_IMG passos guardados."""
        k = max(0.0, min(1.0, k))
        nivel = int(round(k * NIVEIS_IMG))
        cheio = k >= 0.999
        for item, op, valor in self.itens:
            try:
                if op == "image":
                    nome, sob = valor
                    if cheio:
                        self.c.itemconfigure(item, image=nome)
                    elif nivel != self._nivel:
                        foto = _foto_esmaecida(self.c, nome, sob, self.fundo,
                                               nivel, NIVEIS_IMG)
                        if foto is not None:
                            self.c.itemconfigure(item, image=foto)
                elif valor:
                    self.c.itemconfigure(item, **{
                        op: valor if cheio else
                        _mistura(self.fundo, valor, k)})
            except tk.TclError:
                continue
        self._nivel = nivel

    def mover(self, x: float, y: float) -> None:
        """Leva o canto da copia para (x, y)."""
        self.c.move(self.tag, x - self.x0, y - self.y0)
        self.x0, self.y0 = x, y


def _vivo(w) -> bool:
    try:
        return bool(w.winfo_exists())
    except tk.TclError:
        return False


def destruir(w) -> None:
    """O widget e os cantinhos dele (irmaos, ver E.cantos)."""
    for p in list(getattr(w, "_cantos", None) or []):
        try:
            p.destroy()
        except tk.TclError:
            pass
    try:
        w.destroy()
    except tk.TclError:
        pass


def _travar(w, travar: bool) -> None:
    """Pinta o quadro de uma vez (Windows): trava a pintura de `w` e, ao
    soltar, repinta ele e os filhos juntos."""
    try:
        import ctypes
        u = ctypes.windll.user32
        h = w.winfo_id()
        u.SendMessageW(h, 0x000B, 0 if travar else 1, 0)   # WM_SETREDRAW
        if not travar:
            # INVALIDATE | ALLCHILDREN | UPDATENOW (sem ERASE: nada de fundo
            # liso entre o apagar e o pintar)
            u.RedrawWindow(h, None, None, 0x0001 | 0x0080 | 0x0100)
    except Exception:
        pass


class Arranjo:
    """
    Os itens de uma lista com chave, postos com `place` em `pai`. `canvas` =
    o da rolagem (a vista; e o que trava a pintura no quadro).
    """

    def __init__(self, pai, canvas, fundo: str) -> None:
        self.pai = pai
        self.canvas = canvas
        self.fundo = fundo
        self.w: dict = {}            # chave -> widget
        self.pos: dict = {}          # chave -> (x, y, larg, alt)
        self.altura = 0
        self._saindo: list = []      # widgets esmaecendo para sumir
        self._anim = None            # o estado da animacao em curso
        self._recem: set = set()     # criados pelo `empilhar` (para medir)
        # guardar = o que sai so e escondido (place_forget) e volta igual
        # quando entra de novo (linhas caras de montar, com estado vivo)
        self.guardar = False
        self.guardados: dict = {}
        # (09/out, medido: esconder ~80 linhas = 157 ms antes da animacao)
        # o que sai FORA da vista fica onde esta (ninguem ve) e e escondido
        # / destruido aos poucos, depois: chave -> widget
        self._esconder: dict = {}
        self._lixo: list = []        # escondidos, a destruir aos poucos
        self._lixo_id = None
        self._prontos: dict = {}     # criados para medir, a por no lugar

    def _recolher(self) -> None:
        """Esconde (guardar) ou destroi o que saiu fora da vista, em
        pedacos e fora das animacoes."""
        if self._lixo_id is not None:
            return

        def passo():
            self._lixo_id = None
            if not (self._esconder or self._lixo):
                return
            if animando():
                self._lixo_id = self.pai.after(60, passo)
                return
            if self._esconder:
                for c in list(self._esconder)[:10]:
                    self._largar_ja(c, self._esconder.pop(c))
            else:
                for w in self._lixo[:10]:
                    destruir(w)
                del self._lixo[:10]
            if self._esconder or self._lixo:
                self._lixo_id = self.pai.after(15, passo)
        try:
            self._lixo_id = self.pai.after(30, passo)
        except tk.TclError:
            self._lixo_id = None

    # -- consulta ---------------------------------------------------------

    def tem(self, chave) -> bool:
        w = self.w.get(chave)
        try:
            return w is not None and bool(w.winfo_exists())
        except tk.TclError:
            return False

    def widget(self, chave):
        return self.w.get(chave) if self.tem(chave) else None

    def trocar(self, chave, novo) -> None:
        """Um item refeito no mesmo lugar (abriu/fechou o app)."""
        velho = self.w.get(chave)
        self.w[chave] = novo
        x, y, l, a = self.pos.get(chave, (0, 0, 0, 0))
        self._por(novo, x, y, l, a)
        if velho is not None and velho is not novo:
            destruir(velho)

    def esvaziar(self) -> None:
        self._acabar()
        for w in list(self.w.values()) + self._saindo + \
                list(self.guardados.values()) + list(self._esconder.values()):
            destruir(w)
        for w in self._lixo + list(self._prontos.values()):
            destruir(w)
        self._lixo = []
        self._prontos.clear()
        self._esconder.clear()
        self.w.clear()
        self.pos.clear()
        self.guardados.clear()
        self._saindo = []

    def _largar(self, chave, w, agora: bool = True) -> None:
        """O que saiu: `agora` (estava/vai estar a vista) sai ja; senao fica
        onde esta, invisivel, e sai aos poucos depois (`_recolher`)."""
        if agora:
            self._largar_ja(chave, w)
            return
        self._esconder[chave] = w
        self._recolher()

    def _largar_ja(self, chave, w) -> None:
        """Escondido JA; depois destruido aos poucos (destruir custa o
        dobro), ou (guardar) guardado, pronto para entrar de novo."""
        try:
            w.place_forget()
        except tk.TclError:
            return
        if self.guardar:
            self.guardados[chave] = w
        else:
            self._lixo.append(w)
            self._recolher()

    # -- layout -------------------------------------------------------------

    def _por(self, w, x, y, l, a) -> None:
        jeito = {"x": int(round(x)), "y": int(round(y))}
        if l is None:
            jeito.update(relwidth=1.0, width=0)
        else:
            jeito["width"] = int(l)
        if a is not None:
            jeito["height"] = int(a)
        w.place(**jeito)

    def _vista(self) -> tuple:
        try:
            topo = self.canvas.canvasy(0)
            return topo, topo + self.canvas.winfo_height()
        except tk.TclError:
            return 0, 0

    def _largura(self) -> int:
        try:
            return max(1, self.pai.winfo_width())
        except tk.TclError:
            return 1

    def _a_vista(self, caixa, vista, folga: int = 40) -> bool:
        if caixa is None:
            return False
        y, a = caixa[1], caixa[3] or 0
        return y + a >= vista[0] - folga and y <= vista[1] + folga

    def criar_adiado(self, chave, criar) -> None:
        """Um item adiado (`aplicar(adiar=True)`) chega agora: reaproveita
        o que ainda nao foi escondido/guardado; senao `criar(chave)`."""
        if chave not in self.pos or self.tem(chave):
            return
        guardado = self.guardados.pop(chave, None)
        w = self._prontos.pop(chave, None)
        if w is None or not _vivo(w):
            w = self._esconder.pop(chave, None)
        if w is None or not _vivo(w):
            w = guardado
        if w is None or not _vivo(w):
            w = criar(chave)
        if w is not None:
            self.por_item(chave, w)

    def por_item(self, chave, w) -> None:
        """Um item adiado (`pendentes`) criado agora, direto no lugar."""
        p = self.pos.get(chave)
        if p is None:
            destruir(w)
            return
        self.w[chave] = w
        self._por(w, *p)

    def aplicar(self, layout, criar, animar: bool = True,
                altura: int | None = None, ao_fim=None,
                adiar: bool = False, topo: bool = False) -> list:
        """
        `layout` = [(chave, x, y, larg, alt)] (larg None = a largura toda;
        alt None = a do widget). `criar(chave)` -> o widget (filho de
        `pai`), so para as chaves que ainda nao existem. `adiar`: o que
        entra FORA da vista nao e criado agora -- devolve essas chaves (na
        ordem) para quem chama criar em lotes (`por_item`). `topo`: a lista
        volta ao comeco da rolagem (a busca mudou) -- a copia anda junto.

        (09/out, "as animacoes estao muito travadas") A ANIMACAO NAO MEXE
        NAS JANELAS DE VERDADE: a lista real vai direto ao fim, embaixo de
        um canvas que cobre a vista (`_cobre`) com a COPIA de cada item
        (`Espelho`, igual pixel a pixel); a copia anda e esmaece (um canvas
        so: barato e liso) e no fim o canvas sai de uma vez.
        """
        self._acabar()
        adiadas = []
        novas = {}
        for chave, x, y, l, a in layout:
            novas[chave] = (x, y, l, a)
        sai = [c for c in self.w if c not in novas]
        # prontos de antes (criados, nunca postos) que a lista nova nao quer
        for c in [c for c in self._prontos if c not in novas]:
            w = self._prontos.pop(c)
            if self.guardar:
                self.guardados[c] = w
            else:
                self._lixo.append(w)
                self._recolher()
        recem, self._recem = self._recem, set()
        entra = [c for c in novas if not self.tem(c) or c in recem]
        fica = [c for c in novas if c not in entra]
        vista = self._vista()
        larg = self._largura()

        def caixa(p):
            if p is None:
                return None
            x, y, l, a = p
            return (x, y, l if l is not None else larg, a)

        try:
            a_mostra = bool(self.canvas.winfo_viewable())
        except tk.TclError:
            a_mostra = False
        animar = animar and a_mostra and mov.ligadas()
        alt_vista = vista[1] - vista[0]
        vista_nova = (0, alt_vista) if topo else vista
        if animar:
            vistos = sum(1 for c in sai
                         if self._a_vista(caixa(self.pos.get(c)), vista))
            vistos += sum(1 for c in novas
                          if self._a_vista(caixa(novas[c]), vista_nova))
            if vistos > MAX_ANIMADOS:
                animar = False

        # 1) A COPIA do que se ve AGORA (antes de mexer em nada)
        copias_sai, copias_fica = [], {}
        cobre = None
        if animar:
            cobre = self._cobertura()
            ox, oy = self.canvas.winfo_rootx(), self.canvas.winfo_rooty()
            n = 0
            for c in sai:
                if self._a_vista(caixa(self.pos.get(c)), vista, folga=0):
                    n += 1
                    copias_sai.append(Espelho(cobre, self.w[c], ox, oy,
                                              self.fundo, "s%d" % n))
            for c in fica:
                if self._a_vista(caixa(self.pos.get(c)), vista, folga=0) or \
                        self._a_vista(caixa(novas[c]), vista_nova, folga=0):
                    n += 1
                    copias_fica[c] = Espelho(cobre, self.w[c], ox, oy,
                                             self.fundo, "f%d" % n)
            self._mostrar_cobertura(cobre)

        # 2) A LISTA DE VERDADE direto no fim (embaixo da copia)
        for c in sai:
            w = self.w.pop(c)
            p = caixa(self.pos.pop(c, None))
            self._largar(c, w, agora=self._a_vista(p, vista) or
                         self._a_vista(p, vista_nova))
        for c in entra:
            pend = self._esconder.pop(c, None)    # saiu e nem foi escondido
            if pend is not None and not _vivo(pend):
                pend = None
            if adiar and pend is None and \
                    not self._a_vista(caixa(novas[c]), vista_nova,
                                      folga=120):
                if c in recem and self.tem(c):
                    # ja criado (para medir), so falta por no lugar: depois
                    self._prontos[c] = self.w.pop(c)
                adiadas.append(c)
                continue
            try:
                self.guardados.pop(c, None)
                if c in recem and self.tem(c):
                    w = self.w[c]
                elif pend is not None:
                    w = pend
                else:
                    w = criar(c)
            except Exception:
                log.exception("filtro: nao criei %r", c)
                novas.pop(c, None)
                continue
            if w is None:
                novas.pop(c, None)
                continue
            self.w[c] = w
            self._por(w, *novas[c])
        for c in fica:
            self._por(self.w[c], *novas[c])
        self.pos = novas
        nova_alt = altura if altura is not None else self._medir_altura()
        self._definir_altura(nova_alt)
        if topo:
            try:
                self.canvas.yview_moveto(0)
            except tk.TclError:
                pass
        if not animar:
            if ao_fim is not None:
                ao_fim()
            return adiadas

        # 3) a copia do que ENTRA (ja no lugar novo) e o destino de cada uma
        try:
            self.pai.update_idletasks()
        except tk.TclError:
            pass
        ox, oy = self.canvas.winfo_rootx(), self.canvas.winfo_rooty()
        copias_entra = []
        n = 0
        for c in entra:
            w = self.widget(c)
            if w is None or not self._a_vista(caixa(novas.get(c)),
                                              vista_nova, folga=0):
                continue
            n += 1
            e = Espelho(cobre, w, ox, oy, self.fundo, "e%d" % n)
            e.k(0.0)
            copias_entra.append(e)
        andando = []
        for c, e in copias_fica.items():
            w = self.w.get(c)
            try:
                destino = (w.winfo_rootx() - ox, w.winfo_rooty() - oy)
            except (tk.TclError, AttributeError):
                continue
            andando.append((e, (e.x0, e.y0), destino))
        if not (copias_sai or copias_entra or
                any(de != para for _e, de, para in andando)):
            self._esconder_cobertura()
            if ao_fim is not None:
                ao_fim()
            return adiadas

        def quadro(t):
            k_sai = max(0.0, 1.0 - t / SAI_ATE)
            for e in copias_sai:
                e.k(k_sai)
            k_entra = max(0.0, (t - ENTRA_DE) / (1.0 - ENTRA_DE))
            for e in copias_entra:
                e.k(mov.ENTRADA(k_entra))
            k = mov.PADRAO(t)
            for e, de, para in andando:
                e.mover(de[0] + (para[0] - de[0]) * k,
                        de[1] + (para[1] - de[1]) * k)

        def fim():
            self._anim = None
            _ANIMANDO.discard(id(self))
            _relogio_fino(False)
            self._esconder_cobertura()
            if ao_fim is not None:
                ao_fim()

        self._anim = (quadro, fim)
        _ANIMANDO.add(id(self))
        _relogio_fino(True)
        mov.animar(cobre, "filtro", MS, quadro, fim, curva=lambda t: t)
        return adiadas

    # -- o canvas que cobre a vista durante a animacao ------------------------

    def _cobertura(self):
        c = getattr(self, "_cobre", None)
        try:
            if c is not None and c.winfo_exists():
                c.delete("all")
                return c
        except tk.TclError:
            pass
        c = tk.Canvas(self.canvas.master, bg=self.fundo, highlightthickness=0,
                      bd=0)
        self._cobre = c
        return c

    def _mostrar_cobertura(self, c) -> None:
        """Por cima da vista da lista e LOGO acima dela na pilha (a busca e
        o que flutua continuam por cima)."""
        try:
            c.place(in_=self.canvas, x=0, y=0, relwidth=1.0, relheight=1.0)
            c.tk.call("raise", c._w, self.canvas._w)
        except tk.TclError:
            pass

    def _esconder_cobertura(self) -> None:
        """Tira a copia DE UMA VEZ: a lista de verdade (ja no fim) aparece
        inteira no mesmo quadro, sem pedaco pintando por vez."""
        c = getattr(self, "_cobre", None)
        if c is None:
            return
        dono = self.canvas.master
        _travar(dono, True)
        try:
            c.place_forget()
            c.delete("all")
            try:
                dono.update_idletasks()
            except tk.TclError:
                pass
        except tk.TclError:
            pass
        finally:
            _travar(dono, False)

    def _acabar(self) -> None:
        """Uma animacao no meio: vai direto ao fim (a nova parte dali)."""
        anim, self._anim = self._anim, None
        if anim is None:
            return
        c = getattr(self, "_cobre", None)
        if c is not None:
            mov.parar(c, "filtro")
        try:
            anim[1]()
        except tk.TclError:
            pass

    def _medir_altura(self) -> int:
        fim = 0
        for c, (x, y, l, a) in self.pos.items():
            if a is None:
                w = self.w.get(c)
                try:
                    a = w.winfo_reqheight() if w is not None else 0
                except tk.TclError:
                    a = 0
            fim = max(fim, int(y + a))
        return fim

    def _definir_altura(self, alt: int) -> None:
        self.altura = alt
        try:
            self.pai.configure(height=max(1, alt))
        except tk.TclError:
            pass


def empilhar(arranjo: Arranjo, chaves, criar, espaco, x: int = 0,
             y0: int = 0, largura=None) -> list:
    """Layout de LISTA: uma chave por linha, na ordem, com a altura de cada
    widget (os que ainda nao existem sao criados para medir). `espaco` =
    numero ou funcao(chave) -> (antes, depois)."""
    saida = []
    y = y0
    # os que faltam sao criados (ou reaproveitados) PRIMEIRO e medidos
    # numa atualizacao so (uma por linha custava ~150 ms em 80 linhas)
    widgets = {}
    novos = False
    for c in chaves:
        w = arranjo.widget(c)
        if w is None:
            w = arranjo._prontos.pop(c, None) or arranjo._esconder.get(c)
            if w is None or not _vivo(w):
                try:
                    w = criar(c)
                except Exception:
                    log.exception("filtro: nao criei %r", c)
                    continue
            if w is None:
                continue
            arranjo.w[c] = w
            arranjo._recem.add(c)
            novos = True
        widgets[c] = w
    if novos:
        try:
            arranjo.pai.update_idletasks()
        except tk.TclError:
            pass
    for c in chaves:
        w = widgets.get(c)
        if w is None:
            continue
        antes, depois = espaco(c) if callable(espaco) else (0, espaco)
        y += antes
        try:
            a = w.winfo_reqheight()
        except tk.TclError:
            a = 0
        saida.append((c, x, y, largura, a))
        y += a + depois
    return saida
