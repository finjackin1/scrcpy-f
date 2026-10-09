"""
LISTA ANIMADA (03/out/2026, pedido dele: "a tela pisca ao redesenhar" e
"animacoes suaves, na velocidade das do celular").

A lista inteira e desenhada num Canvas so (o Tk pinta o canvas de uma vez,
sem o piscar de uma janela do Windows por cartao). Cada item e um BLOCO: uma
funcao que desenha (`desenhar(p)` -> altura) e uma assinatura (mudou =
redesenha). A lista cuida do resto, com os numeros do Android (SystemUI,
docs/contexto/animacoes.md):
  - item novo: abre espaco e aparece esmaecendo (464 ms); os de baixo descem
    (360 ms, FAST_OUT_SLOW_IN);
  - item que sai: esmaece e o espaco fecha (360 ms);
  - mudou de altura (abrir/fechar o cartao): a altura anda (360 ms);
  - arrastar para o lado tira (como no celular): segue o mouse, esmaece com
    1 - progresso/0.6; solto longe sai em 200 ms (FAST_OUT_LINEAR_IN), perto
    volta com um leve quique.
Janelas de verdade (o player, a caixa de resposta) entram como item "window"
e so andam: nunca sao refeitas no meio de uma animacao.
"""

from __future__ import annotations

import time
import tkinter as tk

from . import estudio as E

MS_QUADRO = 10
MS_PADRAO = 360           # StackStateAnimator.ANIMATION_DURATION_STANDARD
MS_APARECER = 464         # ANIMATION_DURATION_APPEAR_DISAPPEAR
MS_SWIPE = 200            # ANIMATION_DURATION_SWIPE
MS_VOLTA = 320            # volta do arraste (mola baixa do SwipeHelper)
FADE_FIM = 0.6            # SwipeHelper.SWIPE_PROGRESS_FADE_END


def bezier(x1: float, y1: float, x2: float, y2: float):
    """Curva cubica como a PathInterpolator do Android: f(t) para t em 0..1."""
    def eixo(a, b, s):
        return 3 * a * (1 - s) ** 2 * s + 3 * b * (1 - s) * s * s + s ** 3

    def f(t: float) -> float:
        if t <= 0.0:
            return 0.0
        if t >= 1.0:
            return 1.0
        baixo, alto = 0.0, 1.0
        s = t
        for _ in range(24):              # acha s com x(s) = t (bissecao)
            x = eixo(x1, x2, s)
            if abs(x - t) < 1e-4:
                break
            if x < t:
                baixo = s
            else:
                alto = s
            s = (baixo + alto) / 2.0
        return eixo(y1, y2, s)
    return f


PADRAO = bezier(0.4, 0.0, 0.2, 1.0)        # FAST_OUT_SLOW_IN
SAIDA = bezier(0.4, 0.0, 1.0, 1.0)         # FAST_OUT_LINEAR_IN
ENTRADA_ONEUI = bezier(0.22, 0.25, 0.0, 1.0)   # One UI "basic"


def quique(t: float) -> float:
    """A volta do arraste: passa um tiquinho do lugar e assenta (mola)."""
    if t >= 1.0:
        return 1.0
    s = 1.70158 * 0.6
    t -= 1.0
    return t * t * ((s + 1) * t + s) + 1.0


def misturar(cor: str, fundo: str, f: float) -> str:
    """f=1: a cor; f=0: o fundo."""
    if f >= 0.999 or not cor or not cor.startswith("#"):
        return cor
    try:
        a = [int(cor[i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(fundo[i:i + 2], 16) for i in (1, 3, 5)]
    except (ValueError, IndexError):
        return cor
    f = max(0.0, f)
    return "#%02X%02X%02X" % tuple(round(y + (x - y) * f) for x, y in zip(a, b))


class Pincel:
    """O que o `desenhar` de um bloco recebe: onde desenhar e as cores ja
    esmaecidas. Todo item criado leva a tag do bloco (e as `extra`)."""

    def __init__(self, lista: "ListaAnimada", bloco: dict, y: int) -> None:
        self.lista = lista
        self.c = lista.c
        self.bloco = bloco
        self.tag = bloco["tag"]
        self.x0 = lista.margem_lados
        self.largura = lista.largura()
        self.x1 = self.x0 + self.largura
        self.y = y
        self.vis = bloco["vis"]
        self.corte = bloco["corte"]              # altura cortada (animando)
        self.sobre = bloco.get("sobre")          # sub-item com o mouse em cima
        self.est = bloco["est"]                  # valores animados (giro...)
        self.janelas_usadas: set = set()

    def cor(self, cor: str, fundo: str | None = None) -> str:
        return misturar(cor, fundo or self.lista.fundo, self.vis)

    def tags(self, *extra) -> tuple:
        return (self.tag,) + tuple(extra)

    def texto(self, x, y, texto, fonte, cor, largura=None, anchor="nw",
              extra=(), justify="left"):
        """Cria um texto; devolve (item, altura)."""
        kw = {}
        if largura:
            kw["width"] = largura
        it = self.c.create_text(x, y, text=E.texto_limpo(texto), font=fonte,
                                fill=self.cor(cor), anchor=anchor,
                                justify=justify, tags=self.tags(*extra), **kw)
        caixa = self.c.bbox(it)
        return it, (caixa[3] - caixa[1]) if caixa else 0

    def imagem(self, x, y, foto, anchor="nw", extra=()):
        if foto is None or self.vis < 0.5:      # imagem nao esmaece: entra no meio
            return None
        # o bloco segura a imagem: o cache de quem a fez pode ser esvaziado
        # e o Tk apagaria a figura que ainda esta na tela
        self.bloco.setdefault("fotos", []).append(foto)
        return self.c.create_image(x, y, image=foto, anchor=anchor,
                                   tags=self.tags(*extra))

    def icone_x(self, cx, cy, lado, cor, fundo, bolha=None, extra=()):
        """(07/out) O "x" da casa (o mesmo desenho do icone de linha: duas
        diagonais de traco 2 u e ponta redonda), em linhas do canvas para
        esmaecer junto com o cartao. `bolha` = o circulo do realce. A area
        inteira (quadrado de `lado`) e clicavel."""
        u = lado / 24.0
        tg = self.tags(*extra)
        r = lado / 2.0
        self.c.create_rectangle(cx - r, cy - r, cx + r, cy + r,
                                fill=self.cor(fundo), width=0, tags=tg)
        if bolha:
            self.c.create_oval(cx - r, cy - r, cx + r, cy + r,
                               fill=self.cor(bolha), width=0, tags=tg)
        a = 5 * u                         # de 7 a 17 numa grade de 24
        larg = max(1.5, 2 * u)
        for p, q in (((-a, -a), (a, a)), ((a, -a), (-a, a))):
            self.c.create_line(cx + p[0], cy + p[1], cx + q[0], cy + q[1],
                               fill=self.cor(cor), width=larg,
                               capstyle="round", tags=tg)

    def janela(self, widget, x, y, largura=None, altura=None, anchor="nw"):
        """Uma janela de verdade (player, caixa de texto): o item e
        reaproveitado entre os desenhos (refazer = piscar)."""
        itens = self.bloco.setdefault("janelas", {})
        it = itens.get(str(widget))
        kw = {}
        if largura is not None:
            kw["width"] = largura
        if altura is not None:
            kw["height"] = altura
        if it is None or not self.c.type(it):
            it = self.c.create_window(x, y, window=widget, anchor=anchor,
                                      tags=self.tags("janela"), **kw)
            itens[str(widget)] = it
        else:
            self.c.coords(it, x, y)
            if kw:
                self.c.itemconfigure(it, **kw)
            self.c.itemconfigure(it, state="normal")
        self.janelas_usadas.add(str(widget))
        return it

    def cartao(self, y0, y1, fundo, borda, raio=None, extra=()):
        """O fundo arredondado (canto liso, de imagem) de x0 a x1."""
        raio = raio or E.px(8)
        x0, x1 = self.x0, self.x1
        y1 = max(y1, y0 + 2 * raio)
        f, b = self.cor(fundo), self.cor(borda)
        tg = self.tags("fundo", *extra)
        c = self.c
        c.create_rectangle(x0 + raio, y0, x1 - raio, y1, fill=f, width=0,
                           tags=tg)
        c.create_rectangle(x0, y0 + raio, x1, y1 - raio, fill=f, width=0,
                           tags=tg)
        c.create_line(x0 + raio, y0, x1 - raio, y0, fill=b, tags=tg)
        c.create_line(x0 + raio, y1 - 1, x1 - raio, y1 - 1, fill=b, tags=tg)
        c.create_line(x0, y0 + raio, x0, y1 - raio, fill=b, tags=tg)
        c.create_line(x1 - 1, y0 + raio, x1 - 1, y1 - raio, fill=b, tags=tg)
        cantos = self.lista.cantos(raio, f, b)
        for img, x, y, anc in ((cantos[0], x0, y0, "nw"),
                               (cantos[1], x1, y0, "ne"),
                               (cantos[2], x0, y1, "sw"),
                               (cantos[3], x1, y1, "se")):
            c.create_image(x, y, image=img, anchor=anc, tags=tg)


class ListaAnimada:
    """A lista num canvas. `ao_clicar(chave, sub, evento)`,
    `ao_menu(chave, evento)`, `ao_dispensar(chave)` (arrastou para o lado),
    `arrastavel(chave)` -> bool, `clicavel(chave, sub)` -> bool."""

    def __init__(self, canvas: tk.Canvas, fundo: str, margem_topo: int = 0,
                 margem_lados: int = 0, margem_base: int = 0) -> None:
        self.c = canvas
        self.fundo = fundo
        self.margem_topo = margem_topo
        self.margem_lados = margem_lados
        self.margem_base = margem_base
        self.blocos: dict = {}           # chave -> bloco
        self.ordem: list = []            # chaves, na ordem da tela
        self._seq = 0
        self._tique_id = None
        self._largura_desenhada = None
        self._cantos: dict = {}
        self._apertado = None
        self.ao_clicar = None
        self.ao_menu = None
        self.ao_dispensar = None
        self.arrastavel = lambda chave: False
        self.clicavel = lambda chave, sub: True
        self.animar = True
        c = canvas
        c.bind("<Motion>", self._moveu, add="+")
        c.bind("<Leave>", lambda _e: self._sobre(None, None), add="+")
        c.bind("<ButtonPress-1>", self._apertou, add="+")
        c.bind("<B1-Motion>", self._arrastou, add="+")
        c.bind("<ButtonRelease-1>", self._soltou, add="+")
        c.bind("<Button-3>", self._direito, add="+")
        c.bind("<Configure>", self._mudou_largura, add="+")

    # -- medidas ---------------------------------------------------------------

    def largura(self) -> int:
        return max(E.px(120), self.c.winfo_width() - 2 * self.margem_lados)

    def cantos(self, raio: int, fundo: str, borda: str) -> list:
        """Os 4 cantos lisos (PIL 4x) sobre o fundo da lista; guardados."""
        chave = (raio, fundo, borda, self.fundo)
        if chave in self._cantos:
            return self._cantos[chave]
        from PIL import Image, ImageDraw, ImageTk
        k = 4
        lado = raio * 2 * k
        img = Image.new("RGB", (lado, lado), self.fundo)
        ImageDraw.Draw(img).ellipse((0, 0, lado - 1, lado - 1), fill=fundo,
                                    outline=borda, width=k)
        img = img.resize((raio * 2, raio * 2), Image.BOX)
        q = [img.crop((0, 0, raio, raio)), img.crop((raio, 0, 2 * raio, raio)),
             img.crop((0, raio, raio, 2 * raio)),
             img.crop((raio, raio, 2 * raio, 2 * raio))]
        fotos = [ImageTk.PhotoImage(p, master=self.c) for p in q]
        if len(self._cantos) > 400:
            self._cantos.clear()
        self._cantos[chave] = fotos
        return fotos

    # -- a lista ---------------------------------------------------------------

    def definir(self, itens: list, animar: bool = True) -> None:
        """`itens` = [(chave, desenhar, assinatura, espaco)] na ordem. O que
        mudou anda; o resto fica."""
        animar = animar and self.animar
        agora = time.monotonic()
        novas = [i[0] for i in itens]
        quer = set(novas)
        # Saem: esmaecem e fecham o espaco (ficam na ordem ate o fim).
        for chave in list(self.ordem):
            b = self.blocos[chave]
            if chave not in quer and not b.get("saindo"):
                self._tirar(b, animar, agora)
        for chave, desenhar, assin, espaco in itens:
            b = self.blocos.get(chave)
            if b is not None and b.get("saindo") and not b.get("dispensado"):
                # Voltou antes de acabar de sair: fica.
                b["saindo"] = False
                self._animar(b, "vis", b["vis"], 1.0, MS_PADRAO, PADRAO, agora)
            if b is None:
                b = self._novo(chave, desenhar, assin, espaco)
                natural = self._desenhar(b, medir=True)
                b["altura"] = natural
                if animar and self._largura_desenhada is not None:
                    b["vis"], b["corte"] = 0.0, 0
                    self._animar(b, "corte", 0, natural, MS_PADRAO, PADRAO,
                                 agora)
                    self._animar(b, "vis", 0.0, 1.0, MS_APARECER, PADRAO,
                                 agora)
                    self._desenhar(b)
                continue
            b["desenhar"], b["espaco"] = desenhar, espaco
            if b["assin"] != assin:
                b["assin"] = assin
                antes = self._altura_visivel(b)
                natural = self._desenhar(b, medir=True)
                b["altura"] = natural
                if animar and natural != antes and not b.get("saindo"):
                    b["corte"] = antes
                    self._animar(b, "corte", antes, natural, MS_PADRAO,
                                 PADRAO, agora)
                    self._desenhar(b)
        # A ordem nova, com quem esta saindo no lugar de antes.
        ordem = list(novas)
        for i, chave in enumerate(self.ordem):
            if chave not in quer and chave in self.blocos:
                antes = self.ordem[i - 1] if i else None
                pos = ordem.index(antes) + 1 if antes in ordem else 0
                ordem.insert(pos, chave)
        self.ordem = ordem
        self._largura_desenhada = self.largura()
        self._arrumar(animar, agora)

    def _novo(self, chave, desenhar, assin, espaco) -> dict:
        self._seq += 1
        b = {"chave": chave, "desenhar": desenhar, "assin": assin,
             "espaco": espaco, "tag": "b%d" % self._seq, "vis": 1.0,
             "corte": None, "dx": 0, "y": None, "y_alvo": 0, "altura": 0,
             "anims": {}, "est": {}, "sobre": None, "desenhado_dx": 0}
        self.blocos[chave] = b
        return b

    def _tirar(self, b: dict, animar: bool, agora: float) -> None:
        b["saindo"] = True
        if not animar:
            self._apagar(b)
            return
        self._animar(b, "corte", self._altura_visivel(b), 0, MS_PADRAO,
                     PADRAO, agora)
        if b["vis"] > 0:
            self._animar(b, "vis", b["vis"], 0.0, MS_SWIPE, SAIDA, agora)

    def _apagar(self, b: dict) -> None:
        self.c.delete(b["tag"])
        self.blocos.pop(b["chave"], None)
        if b["chave"] in self.ordem:
            self.ordem.remove(b["chave"])

    def _altura_visivel(self, b: dict) -> int:
        return b["altura"] if b["corte"] is None else int(b["corte"])

    def _alvo_altura(self, b: dict) -> int:
        if b.get("saindo"):
            return 0
        return b["altura"]

    def _arrumar(self, animar: bool, agora: float) -> None:
        """Poe cada bloco no seu y (andando, se animar)."""
        y = self.margem_topo
        for chave in self.ordem:
            b = self.blocos[chave]
            b["y_alvo"] = y
            if b["y"] is None:
                b["y"] = y
                self._desenhar(b)
            elif int(b["y"]) != y and "y" not in b["anims"]:
                if animar:
                    self._animar(b, "y", b["y"], y, MS_PADRAO, PADRAO, agora)
                else:
                    self._mover(b, y)
            elif "y" in b["anims"]:
                de = b["y"]
                self._animar(b, "y", de, y, MS_PADRAO, PADRAO, agora)
            alto = self._alvo_altura(b)
            if alto > 0:
                y += alto + b["espaco"]
        self._regiao()

    def _regiao(self) -> None:
        fim = self.margem_topo
        for chave in self.ordem:
            b = self.blocos[chave]
            alto = self._altura_visivel(b)
            if b["y"] is not None and alto > 0:
                fim = max(fim, int(b["y"]) + alto + b["espaco"])
        try:
            self.c.configure(scrollregion=(0, 0, self.c.winfo_width(),
                                           fim + self.margem_base))
        except tk.TclError:
            pass

    # -- desenho -----------------------------------------------------------------

    def _desenhar(self, b: dict, medir: bool = False) -> int:
        """Refaz o bloco no y atual. `medir`: so para saber a altura natural
        (desenha no lugar mesmo assim). Devolve a altura natural."""
        c = self.c
        janelas = b.get("janelas") or {}
        fixos = set(janelas.values())
        for it in c.find_withtag(b["tag"]):
            if it not in fixos:
                c.delete(it)
        y = int(b["y"] if b["y"] is not None else b["y_alvo"])
        b["fotos"] = []
        p = Pincel(self, b, y)
        try:
            natural = int(b["desenhar"](p) or 0)
        except tk.TclError:
            natural = 0
        for nome, it in list(janelas.items()):
            if nome not in p.janelas_usadas:
                c.delete(it)
                janelas.pop(nome, None)
        b["desenhado_dx"] = 0
        corte = b["corte"]
        if corte is not None and corte < natural:
            limite = y + max(0, int(corte))
            for it in c.find_withtag(b["tag"]):
                if "fundo" in c.gettags(it):
                    continue
                caixa = c.bbox(it)
                if caixa and caixa[3] > limite - E.px(3):
                    c.itemconfigure(it, state="hidden")
        if b["dx"]:
            c.move(b["tag"], b["dx"], 0)
            b["desenhado_dx"] = b["dx"]
        b["desenhado_y"] = y
        return natural

    def _mover(self, b: dict, y: float) -> None:
        dy = int(y) - int(b.get("desenhado_y", y))
        b["y"] = y
        if dy:
            self.c.move(b["tag"], 0, dy)
            b["desenhado_y"] = int(y)

    def redesenhar(self, chave: str) -> None:
        """Refaz um bloco (hora, cronometro, progresso) sem mexer na altura."""
        b = self.blocos.get(chave)
        if b is not None and not b["anims"] and not b.get("saindo"):
            natural = self._desenhar(b)
            if natural != b["altura"]:
                b["altura"] = natural
                self._arrumar(self.animar, time.monotonic())

    # -- animacao ----------------------------------------------------------------

    def _animar(self, b, nome, de, ate, ms, curva, agora=None) -> None:
        b["anims"][nome] = (float(de), float(ate),
                            agora or time.monotonic(), ms / 1000.0, curva)
        self._ligar()

    def animar_estado(self, chave: str, nome: str, de: float, ate: float,
                      ms: int = MS_PADRAO, curva=PADRAO) -> None:
        """Um valor do desenho (o giro da seta...) andando."""
        b = self.blocos.get(chave)
        if b is None:
            return
        b["est"][nome] = de
        if not self.animar:
            b["est"][nome] = ate
            return
        self._animar(b, "est:" + nome, de, ate, ms, curva)

    def _ligar(self) -> None:
        if self._tique_id is None:
            try:
                self._tique_id = self.c.after(MS_QUADRO, self._tique)
            except tk.TclError:
                self._tique_id = None

    def _tique(self) -> None:
        self._tique_id = None
        try:
            if not self.c.winfo_exists():
                return
        except tk.TclError:
            return
        agora = time.monotonic()
        algum = False
        regiao = False
        for chave in list(self.ordem):
            b = self.blocos.get(chave)
            if b is None or not b["anims"]:
                continue
            refazer = False
            for nome, (de, ate, t0, dur, curva) in list(b["anims"].items()):
                t = min(1.0, (agora - t0) / dur) if dur > 0 else 1.0
                v = de + (ate - de) * curva(t)
                if t >= 1.0:
                    v = ate
                    del b["anims"][nome]
                if nome == "y":
                    self._mover(b, v)
                    regiao = True
                elif nome == "dx":
                    b["dx"] = v
                    d = int(v) - int(b["desenhado_dx"])
                    if d:
                        self.c.move(b["tag"], d, 0)
                        b["desenhado_dx"] = int(v)
                elif nome.startswith("est:"):
                    b["est"][nome[4:]] = v
                    refazer = True
                else:
                    b[nome] = v
                    refazer = True
                    regiao = regiao or nome == "corte"
            if refazer:
                self._desenhar(b)
            if not b["anims"]:
                if b.get("saindo"):
                    self._apagar(b)
                    regiao = True
                elif b["corte"] is not None and b["corte"] >= b["altura"]:
                    b["corte"] = None
                    self._desenhar(b)
            if b["anims"]:
                algum = True
        if regiao:
            self._regiao()
        if algum:
            self._ligar()

    # -- mouse ---------------------------------------------------------------------

    def _onde(self, evento=None):
        """(chave, sub) debaixo do mouse."""
        try:
            its = self.c.find_withtag("current")
        except tk.TclError:
            return None, None
        if not its:
            return None, None
        tags = self.c.gettags(its[0])
        tag = next((t for t in tags if t.startswith("b") and t[1:].isdigit()),
                   None)
        sub = next((t[2:] for t in tags if t.startswith("s:")), None)
        chave = next((k for k, b in self.blocos.items() if b["tag"] == tag),
                     None)
        return chave, sub

    def _sobre(self, chave, sub) -> None:
        antes = getattr(self, "_sobre_de", (None, None))
        if antes == (chave, sub):
            return
        self._sobre_de = (chave, sub)
        for k in {antes[0], chave} - {None}:
            b = self.blocos.get(k)
            if b is None:
                continue
            novo = (sub if sub is not None else "") if k == chave else None
            if b.get("sobre") != novo:
                b["sobre"] = novo
                if not b["anims"]:
                    self._desenhar(b)
        try:
            mao = chave is not None and self.clicavel(chave, sub)
            self.c.configure(cursor="hand2" if mao else "")
        except tk.TclError:
            pass

    def _moveu(self, evento) -> None:
        if self._apertado is None:
            self._sobre(*self._onde(evento))

    def _apertou(self, evento) -> None:
        chave, sub = self._onde(evento)
        self._apertado = None if chave is None else {
            "chave": chave, "sub": sub, "x": evento.x, "y": evento.y,
            "t": time.monotonic(), "arrastando": False, "hist": []}

    def _arrastou(self, evento) -> None:
        a = self._apertado
        if a is None:
            return
        dx, dy = evento.x - a["x"], evento.y - a["y"]
        b = self.blocos.get(a["chave"])
        if b is None:
            return
        if not a["arrastando"]:
            if abs(dx) > E.px(8) and abs(dx) > abs(dy) and \
                    a["sub"] is None and self.arrastavel(a["chave"]):
                a["arrastando"] = True
                b["anims"].pop("dx", None)
            else:
                return
        a["hist"] = (a["hist"] + [(time.monotonic(), dx)])[-5:]
        b["dx"] = dx
        b["vis"] = max(0.0, 1.0 - min(1.0, abs(dx) / (FADE_FIM *
                                                      self.largura())))
        self._desenhar(b)

    def _soltou(self, evento) -> None:
        a, self._apertado = self._apertado, None
        if a is None:
            return
        b = self.blocos.get(a["chave"])
        if a["arrastando"] and b is not None:
            dx = evento.x - a["x"]
            vel = 0.0
            if len(a["hist"]) >= 2:
                (t0, x0), (t1, x1) = a["hist"][0], a["hist"][-1]
                vel = (x1 - x0) / max(1e-3, t1 - t0)          # px/s
            larg = self.largura()
            # SwipeHelper: passou de 40% da largura, ou soltou "jogando"
            # (velocidade de escape, ~500 dp/s) para o lado do arraste
            sai = abs(dx) > larg * 0.4 or (abs(vel) > E.px(600) and
                                           vel * dx > 0)
            agora = time.monotonic()
            if sai:
                lado = 1 if dx > 0 else -1
                b["dispensado"] = True
                self._animar(b, "dx", dx, lado * (larg + E.px(20)), MS_SWIPE,
                             SAIDA, agora)
                self._animar(b, "vis", b["vis"], 0.0, MS_SWIPE, SAIDA, agora)
                b["saindo"] = True
                self._animar(b, "corte", self._altura_visivel(b), 0,
                             MS_PADRAO, PADRAO, agora + MS_SWIPE / 1000.0)
                self._arrumar_depois(MS_SWIPE)
                if self.ao_dispensar is not None:
                    self.ao_dispensar(a["chave"])
            else:
                self._animar(b, "dx", dx, 0, MS_VOLTA, quique, agora)
                self._animar(b, "vis", b["vis"], 1.0, MS_VOLTA, PADRAO, agora)
            return
        chave, sub = self._onde(evento)
        if chave == a["chave"] and sub == a["sub"] and \
                abs(evento.x - a["x"]) < E.px(6) and \
                abs(evento.y - a["y"]) < E.px(6) and self.ao_clicar:
            self.ao_clicar(chave, sub, evento)

    def _arrumar_depois(self, ms: int) -> None:
        """Depois que o arrastado saiu de lado, os de baixo sobem."""
        def fazer():
            self._arrumar(self.animar, time.monotonic())
        try:
            self.c.after(ms, fazer)
        except tk.TclError:
            pass

    def dispensar(self, chave: str, lado: int = 1) -> None:
        """O x: sai para o lado como no arraste, e o espaco fecha."""
        b = self.blocos.get(chave)
        if b is None or b.get("saindo"):
            return
        agora = time.monotonic()
        b["dispensado"] = b["saindo"] = True
        if not self.animar:
            self._apagar(b)
            self._arrumar(False, agora)
            return
        self._animar(b, "dx", 0, lado * (self.largura() + E.px(20)),
                     MS_SWIPE, SAIDA, agora)
        self._animar(b, "vis", b["vis"], 0.0, MS_SWIPE, SAIDA, agora)
        self._animar(b, "corte", self._altura_visivel(b), 0, MS_PADRAO,
                     PADRAO, agora + MS_SWIPE / 1000.0)
        self._arrumar_depois(MS_SWIPE)

    def _direito(self, evento) -> str | None:
        chave, _sub = self._onde(evento)
        if chave is not None and self.ao_menu is not None:
            self.ao_menu(chave, evento)
            return "break"
        return None

    def _mudou_largura(self, _e=None) -> None:
        larg = self.largura()
        if self._largura_desenhada is None or larg == self._largura_desenhada:
            return
        self._largura_desenhada = larg
        for chave in self.ordem:
            b = self.blocos[chave]
            if not b["anims"]:
                b["altura"] = self._desenhar(b)
        self._arrumar(False, time.monotonic())

    def esvaziar(self) -> None:
        for chave in list(self.ordem):
            self._apagar(self.blocos[chave])
        self.blocos.clear()
        self.ordem = []
