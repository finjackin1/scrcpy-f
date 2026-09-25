"""
O visual "painel de estudio" (visual novo, 21/set/2026) -- tokens e os poucos
controles que a janela usa.

POR QUE UM ARQUIVO NOVO, E NAO O `tema.py`
------------------------------------------
Ele pediu um visual com personalidade, e escolheu a direcao A: cara de
equipamento de audio. Letra de maquina (monoespacada), caixa alta nos
rotulos, cantos retos, linhas de 1 px separando as areas e UMA cor de
destaque (laranja). Isso e uma familia visual propria (familia B); o
`tema.py` continua servindo o Configurar antigo e a bandeja.

Tudo aqui e Tk puro -- Frame, Label e Canvas --, sem transparencia nem
desfoque: o que foi desenhado no mockup e exatamente o que aparece.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

# -- cores ---------------------------------------------------------------------
FUNDO = "#16161A"
FUNDO_FUNDO = "#101013"
LINHA = "#2C2C33"
LINHA_FORTE = "#3A3A42"
TEXTO = "#E9E6DF"
TEXTO_2 = "#9A978F"
APAGADO = "#6F6D68"
ACENTO = "#FF5A1F"
ACENTO_ESCURO = "#3A1C12"
SOBRE_ACENTO = "#16161A"
VERDE = "#57C27A"
ERRO = "#FF5A5A"
ALERTA = "#E8C15A"

# Cores prontas para a marca na tela (aba personalizar).
CORES_DA_MARCA = ["#FF5A1F", "#E9E6DF", "#3D8BFF", "#2FD07A", "#FF3D8B",
                  "#B48CFF"]

# -- escala ---------------------------------------------------------------------
# TUDO passa por aqui (pedido dele, 21/set/2026: "estava pequeno demais pra
# ler", 150%; depois ele ajustou para 130%). Letra, medidas, espacos e
# desenhos crescem juntos; so as linhas de 1 px ficam finas.
#
# QUALQUER TELA E QUALQUER ESCALA DO WINDOWS (pedido dele, 21/set/2026):
# - DPI: com o Windows em 125%/150% e o programa ciente do DPI, o Tk ja cresce
#   a LETRA (ela e em pontos), mas nao as medidas em pixel -- a letra ficaria
#   maior que as caixas. Por isso `px` multiplica tambem pelo DPI do sistema.
#   Sem ciencia de DPI o Windows responde 96 (fator 1) e amplia a janela
#   inteira sozinho: tudo continua proporcional.
# - Tela pequena: a escala baixa ate a janela caber na area util (menos a
#   barra de tarefas), com folga.
ESCALA_PEDIDA = 1.3
LARGURA_BASE, ALTURA_BASE = 680, 34 + 1 + 286     # a janela em 100%


def _dpi_do_sistema() -> float:
    """Pixels por polegada que o Windows informa a ESTE programa (96 = 100%)."""
    try:
        import ctypes
        u = ctypes.windll.user32
        try:
            return float(u.GetDpiForSystem() or 96)
        except AttributeError:                     # Windows 7/8
            dc = u.GetDC(0)
            try:
                return float(ctypes.windll.gdi32.GetDeviceCaps(dc, 88) or 96)
            finally:
                u.ReleaseDC(0, dc)
    except Exception:
        return 96.0


def _area_de_trabalho():
    """(largura, altura) da area util do monitor principal, ou None."""
    try:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0,
                                                      ctypes.byref(r), 0):
            return r.right - r.left, r.bottom - r.top
    except Exception:
        pass
    return None


def _escala_que_cabe(dpi: float) -> float:
    area = _area_de_trabalho()
    if not area:
        return ESCALA_PEDIDA
    lu, au = area
    cabe = min((lu - 40) / (LARGURA_BASE * dpi),
               (au - 60) / (ALTURA_BASE * dpi))
    return max(0.8, min(ESCALA_PEDIDA, cabe))


DPI = max(1.0, _dpi_do_sistema() / 96.0)
ESCALA = _escala_que_cabe(DPI)
# A letra: o Tk ja multiplica pontos pelo DPI; aqui entra so a escala.
ESCALA_LETRA = ESCALA


def px(n: float) -> int:
    """Uma medida do desenho original (em 100%) ja na escala e no DPI."""
    if -1 <= n <= 1:
        return int(n)
    v = n * ESCALA * DPI
    return int(v + (0.5 if v > 0 else -0.5))


# -- letra ----------------------------------------------------------------------
_familia = None


def familia() -> str:
    """A monoespacada da casa: Cascadia Mono (Windows 11), senao Consolas."""
    global _familia
    if _familia is None:
        try:
            disponiveis = set(tkfont.families())
        except Exception:
            disponiveis = set()
        _familia = next((f for f in ("Cascadia Mono", "Cascadia Code",
                                     "Consolas", "Courier New")
                         if f in disponiveis), "Courier")
    return _familia


_FONTES: dict = {}


def fonte(tamanho: int, peso: str = "normal"):
    """
    `tamanho` e o do desenho original; a escala entra aqui.

    FONTE COM NOME (23/set/2026, velocidade): antes cada widget recebia uma
    tupla (familia, tamanho, peso) e o Tk resolvia a letra de novo a cada
    Label -- ~1 ms cada, e a lista de apps tem centenas. Agora cada
    combinacao vira UMA fonte com nome, criada uma vez; os widgets so
    apontam para ela. Sem janela ainda (nao da para criar fonte), volta a
    tupla de antes.
    """
    chave = (familia(), max(1, round(tamanho * ESCALA_LETRA)), peso)
    f = _FONTES.get(chave)
    if f is None:
        try:
            f = tkfont.Font(family=chave[0], size=chave[1],
                            weight="bold" if peso == "bold" else "normal")
        except Exception:
            return chave
        _FONTES[chave] = f
    return f.name


# Tamanhos (pontos do Tk)
ROTULO = 7          # rotulos em caixa alta
PEQUENA = 8
CORPO = 9
GRANDE = 17         # o estado ("no ar.")
MEDIDA = 11

# -- medidas --------------------------------------------------------------------
LARGURA = px(680)
ALTURA_BARRA = px(34)
ALTURA_CORPO = px(286)
LARGURA_LISTA = px(150)
LARGURA_GRANDE = px(960)
ALTURA_GRANDE_CORPO = px(520)
PADDING = px(14)


def caixa_alta(texto: str) -> str:
    return texto.upper()


def espacado(texto: str) -> str:
    """Rotulo de painel: caixa alta com respiro entre as letras."""
    return " ".join(texto.upper()) if len(texto) <= 3 else texto.upper()


# ==============================================================================
# Controles
# ==============================================================================

class Rotulo(tk.Label):
    """Rotulo de secao: pequeno, caixa alta, apagado."""

    def __init__(self, pai, texto: str, **kw) -> None:
        super().__init__(pai, text=texto.upper(), bg=kw.pop("bg", FUNDO),
                         fg=kw.pop("fg", APAGADO), font=fonte(ROTULO),
                         anchor="w", **kw)


class Texto(tk.Label):
    def __init__(self, pai, texto: str, cor: str = TEXTO_2,
                 tamanho: int = PEQUENA, largura: int = 0, **kw) -> None:
        super().__init__(pai, text=texto, bg=kw.pop("bg", FUNDO), fg=cor,
                         font=fonte(tamanho), anchor="w", justify="left",
                         wraplength=largura or 0, **kw)


class Botao(tk.Label):
    """
    Botao do painel. `tipo`: "acao" (laranja cheio, o principal da tela),
    "contorno" (linha clara) ou "discreto" (linha apagada). Teclado: Tab chega
    nele, Enter/Espaco aciona.
    """

    def __init__(self, pai, texto: str, ao_clicar: Callable[[], None],
                 tipo: str = "contorno", largura: int = 0, **kw) -> None:
        self._tipo = tipo
        self._acao = ao_clicar
        self._ligado = True
        super().__init__(pai, text=texto.upper(), font=fonte(PEQUENA, "bold")
                         if tipo == "acao" else fonte(PEQUENA),
                         padx=px(10), pady=px(5) if tipo != "acao" else px(8),
                         cursor="hand2", takefocus=1, highlightthickness=1,
                         width=largura or 0, **kw)
        self._pintar()
        self.bind("<Button-1>", lambda _e: self._clicou())
        self.bind("<Return>", lambda _e: self._clicou())
        self.bind("<space>", lambda _e: self._clicou())
        self.bind("<Enter>", lambda _e: self._pintar(sobre=True))
        self.bind("<Leave>", lambda _e: self._pintar())

    def _pintar(self, sobre: bool = False) -> None:
        if not self._ligado:
            self.configure(bg=FUNDO, fg=APAGADO, highlightbackground=LINHA,
                           highlightcolor=LINHA, cursor="arrow")
            return
        if self._tipo == "acao":
            self.configure(bg="#FF7440" if sobre else ACENTO, fg=SOBRE_ACENTO,
                           highlightbackground=ACENTO, highlightcolor=TEXTO,
                           cursor="hand2")
        elif self._tipo == "contorno":
            self.configure(bg="#22222A" if sobre else FUNDO, fg=TEXTO,
                           highlightbackground=TEXTO, highlightcolor=ACENTO,
                           cursor="hand2")
        else:
            self.configure(bg="#22222A" if sobre else FUNDO, fg=TEXTO_2,
                           highlightbackground=LINHA_FORTE,
                           highlightcolor=ACENTO, cursor="hand2")

    def _clicou(self):
        if self._ligado:
            self._acao()
        return "break"

    def definir(self, texto: str | None = None, tipo: str | None = None,
                ligado: bool | None = None) -> None:
        if texto is not None:
            self.configure(text=texto.upper())
        if tipo is not None:
            self._tipo = tipo
            self.configure(font=fonte(PEQUENA, "bold") if tipo == "acao"
                           else fonte(PEQUENA),
                           pady=px(8) if tipo == "acao" else px(5))
        if ligado is not None:
            self._ligado = ligado
        self._pintar()


class Segmentado(tk.Frame):
    """
    Fileira de opcoes fechadas (a escolhida fica clara). `opcoes` e uma lista
    de (valor, rotulo). Setas esquerda/direita trocam com o teclado.
    """

    def __init__(self, pai, opcoes, valor, ao_escolher: Callable, **kw) -> None:
        super().__init__(pai, bg=LINHA, takefocus=1, highlightthickness=1,
                         highlightbackground=LINHA, highlightcolor=ACENTO, **kw)
        self._opcoes = list(opcoes)
        self._valor = valor
        self._acao = ao_escolher
        self._ligado = True
        self._pecas: list[tk.Label] = []
        for i, (v, r) in enumerate(self._opcoes):
            p = tk.Label(self, text=str(r), font=fonte(PEQUENA), padx=px(4), pady=px(3),
                         cursor="hand2")
            p.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 1, 0))
            # SEM TEXTO CORTADO (pedido dele, 23/set/2026): cada opcao ganha
            # espaco na medida do proprio texto, em vez de fatias iguais --
            # com fatias iguais, "espelhar" ao lado de "leve" era cortado.
            self.grid_columnconfigure(i, weight=max(1, len(str(r))))
            p.bind("<Button-1>", lambda _e, vv=v: self._escolher(vv))
            self._pecas.append(p)
        self.bind("<Left>", lambda _e: self._andar(-1))
        self.bind("<Right>", lambda _e: self._andar(+1))
        self._pintar()

    def _indice(self):
        for i, (v, _r) in enumerate(self._opcoes):
            if _mesmo(v, self._valor):
                return i
        return None

    def _andar(self, passo: int):
        i = self._indice()
        i = 0 if i is None else max(0, min(len(self._opcoes) - 1, i + passo))
        self._escolher(self._opcoes[i][0])
        return "break"

    def _escolher(self, valor) -> None:
        if not self._ligado or _mesmo(valor, self._valor):
            return
        self._valor = valor
        self._pintar()
        self._acao(valor)

    def definir(self, valor) -> None:
        self._valor = valor
        self._pintar()

    def habilitar(self, ligado: bool) -> None:
        self._ligado = ligado
        self._pintar()

    def _pintar(self) -> None:
        i = self._indice()
        for j, p in enumerate(self._pecas):
            if not self._ligado:
                p.configure(bg=FUNDO, fg=LINHA_FORTE if j != i else APAGADO,
                            cursor="arrow")
            elif j == i:
                p.configure(bg=TEXTO, fg=FUNDO, cursor="hand2")
            else:
                p.configure(bg=FUNDO, fg=TEXTO_2, cursor="hand2")


class Chave(tk.Canvas):
    """Interruptor quadrado: laranja ligado, cinza desligado."""

    L, A = px(30), px(14)

    def __init__(self, pai, ligado: bool, ao_virar: Callable[[bool], None],
                 travada: bool = False, **kw) -> None:
        super().__init__(pai, width=self.L, height=self.A, bg=kw.pop("bg", FUNDO),
                         highlightthickness=1, highlightbackground=kw.get(
                             "bg", FUNDO), highlightcolor=ACENTO,
                         takefocus=0 if travada else 1,
                         cursor="arrow" if travada else "hand2", **kw)
        self._ligado = ligado
        self._acao = ao_virar
        self._travada = travada
        self.bind("<Button-1>", lambda _e: self._virar())
        self.bind("<Return>", lambda _e: self._virar())
        self.bind("<space>", lambda _e: self._virar())
        self._pintar()

    def _virar(self):
        if self._travada:
            return "break"
        self._ligado = not self._ligado
        self._pintar()
        self._acao(self._ligado)
        return "break"

    def definir(self, ligado: bool) -> None:
        self._ligado = ligado
        self._pintar()

    def travar(self, travada: bool) -> None:
        """(r180) Trava/destrava NO LUGAR, sem remontar a tela (remontar
        dava uma piscada a cada chave)."""
        self._travada = travada
        self.configure(takefocus=0 if travada else 1,
                       cursor="arrow" if travada else "hand2")
        self._pintar()

    def _pintar(self) -> None:
        self.delete("all")
        cor = ACENTO if self._ligado else APAGADO
        if self._travada:
            cor = "#7A3A22" if self._ligado else LINHA_FORTE
        self.create_rectangle(0, 0, self.L - 1, self.A - 1, outline=cor)
        x = self.L - px(12) if self._ligado else px(3)
        self.create_rectangle(x, px(3), x + px(8), self.A - px(4), fill=cor,
                              outline=cor)


class Deslizador(tk.Canvas):
    """
    Barra deslizante de 0 a 1. `ao_mudar` a cada movimento (previa ao vivo),
    `ao_soltar` no fim (grava). Setas mudam de 2% em 2%.
    """

    def __init__(self, pai, valor: float, ao_mudar: Callable[[float], None],
                 ao_soltar: Callable[[float], None] | None = None,
                 largura: int | None = None, **kw) -> None:
        largura = largura or px(200)
        super().__init__(pai, width=largura, height=px(16), bg=kw.pop("bg", FUNDO),
                         highlightthickness=1, highlightbackground=FUNDO,
                         highlightcolor=ACENTO, takefocus=1, cursor="hand2",
                         **kw)
        self._v = min(1.0, max(0.0, valor))
        self._mudar = ao_mudar
        self._soltar = ao_soltar or ao_mudar
        self._larg = largura
        self.bind("<Button-1>", self._mexeu)
        self.bind("<B1-Motion>", self._mexeu)
        self.bind("<ButtonRelease-1>", lambda _e: self._soltar(self._v))
        self.bind("<Left>", lambda _e: self._passo(-0.02))
        self.bind("<Right>", lambda _e: self._passo(+0.02))
        self.bind("<Configure>", lambda e: self._ajustar(e.width))
        self._pintar()

    def _ajustar(self, largura: int) -> None:
        self._larg = max(px(40), largura)
        self._pintar()

    def _mexeu(self, e) -> None:
        self._v = min(1.0, max(0.0, (e.x - px(7)) / max(1, self._larg - px(14))))
        self._pintar()
        self._mudar(self._v)

    def _passo(self, d: float):
        """Setas: previa na hora; o "soltar" (que grava) so quando parar."""
        self._v = min(1.0, max(0.0, self._v + d))
        self._pintar()
        self._mudar(self._v)
        if getattr(self, "_soltar_id", None) is not None:
            self.after_cancel(self._soltar_id)
        self._soltar_id = self.after(350, self._soltar_agora)
        return "break"

    def _soltar_agora(self) -> None:
        self._soltar_id = None
        self._soltar(self._v)

    def definir(self, valor: float) -> None:
        self._v = min(1.0, max(0.0, valor))
        self._pintar()

    def _pintar(self) -> None:
        self.delete("all")
        l = self._larg
        m, meio = px(7), px(8)
        x = m + self._v * (l - 2 * m)
        self.create_line(m, meio, l - m, meio, fill=LINHA_FORTE, width=px(2))
        self.create_line(m, meio, x, meio, fill=ACENTO, width=px(2))
        self.create_rectangle(x - px(6), px(2), x + px(6), px(14), fill=TEXTO,
                              outline=TEXTO)


class Item(tk.Frame):
    """
    Uma linha da lista da esquerda: nome, e a direita o atalho (o numero) ou
    o sinal de conectado. O ponto laranja aparece quando o modo esta no ar.
    """

    def __init__(self, pai, nome: str, ao_clicar: Callable[[], None],
                 tecla: str = "", marca: str = "", rodape: bool = False) -> None:
        super().__init__(pai, bg=FUNDO, highlightthickness=1,
                         highlightbackground=FUNDO if rodape else LINHA,
                         highlightcolor=ACENTO, takefocus=1, cursor="hand2")
        self._rodape = rodape
        self._marca_tipo = marca        # "" | "conexao"
        self._sel = False
        self._vivo = False
        self._ok = False
        self._nome = tk.Label(self, text=nome.upper(), font=fonte(PEQUENA),
                              anchor="w", cursor="hand2")
        self._nome.pack(side="left", padx=(px(8), px(0)), pady=px(6))
        self._ponto = tk.Canvas(self, width=px(8), height=px(8), highlightthickness=0,
                                cursor="hand2")
        self._ponto.pack(side="left", padx=(px(6), px(0)))
        self._tecla = tk.Label(self, text=tecla, font=fonte(ROTULO), padx=px(3),
                               cursor="hand2", highlightthickness=1)
        if tecla:
            self._tecla.pack(side="right", padx=(px(0), px(8)))
        self._sinal = tk.Canvas(self, width=px(8), height=px(8), highlightthickness=0,
                                cursor="hand2")
        if marca == "conexao":
            self._sinal.pack(side="right", padx=(px(0), px(10)))
        for w in (self, self._nome, self._ponto, self._tecla, self._sinal):
            w.bind("<Button-1>", lambda _e: ao_clicar())
        self.bind("<Return>", lambda _e: ao_clicar())
        self.bind("<space>", lambda _e: ao_clicar())
        self._pintar()

    def travar(self, travado: bool) -> None:
        """(r180) Sem o scrcpy o item fica apagado e nao abre."""
        if getattr(self, "_travado", False) == travado:
            return
        self._travado = travado
        cursor = "arrow" if travado else "hand2"
        self.configure(takefocus=0 if travado else 1, cursor=cursor)
        for w in (self._nome, self._ponto, self._tecla, self._sinal):
            w.configure(cursor=cursor)
        self._pintar()

    def definir(self, selecionado: bool | None = None, vivo: bool | None = None,
                ok: bool | None = None, tecla: str | None = None) -> None:
        if selecionado is not None:
            self._sel = selecionado
        if vivo is not None:
            self._vivo = vivo
        if ok is not None:
            self._ok = ok
        if tecla is not None:
            self._tecla.configure(text=tecla)
            if tecla and not self._tecla.winfo_manager():
                self._tecla.pack(side="right", padx=(px(0), px(8)))
            elif not tecla and self._tecla.winfo_manager():
                self._tecla.pack_forget()
        self._pintar()

    def _pintar(self) -> None:
        if self._rodape:
            fundo, cor = FUNDO, (TEXTO if self._sel else TEXTO_2)
            borda = FUNDO
        elif self._sel:
            fundo, cor, borda = TEXTO, FUNDO, TEXTO
        else:
            fundo, cor, borda = FUNDO, TEXTO, LINHA
        if getattr(self, "_travado", False) and not self._sel:
            cor = LINHA_FORTE
        self.configure(bg=fundo, highlightbackground=borda)
        self._nome.configure(bg=fundo, fg=cor)
        self._tecla.configure(bg=fundo, fg=(FUNDO if self._sel else APAGADO),
                              highlightbackground=("#55535A" if self._sel
                                                   else LINHA_FORTE))
        for c in (self._ponto, self._sinal):
            c.configure(bg=fundo)
            c.delete("all")
        if self._vivo or (self._rodape and self._sel):
            self._ponto.create_rectangle(1, 1, px(7), px(7), fill=ACENTO,
                                         outline=ACENTO)
        if self._marca_tipo == "conexao":
            cor_s = VERDE if self._ok else (FUNDO if self._sel else TEXTO_2)
            self._sinal.create_rectangle(1, 1, px(7), px(7), outline=cor_s,
                                         fill=VERDE if self._ok else fundo)


class Aba(tk.Label):
    """Aba da barra de cima: texto em caixa alta, sublinhado laranja quando escolhida."""

    def __init__(self, pai, texto: str, ao_clicar: Callable[[], None]) -> None:
        super().__init__(pai, text=texto.upper(), font=fonte(ROTULO + 1),
                         bg=FUNDO, cursor="hand2", takefocus=1, padx=px(2),
                         highlightthickness=1, highlightbackground=FUNDO,
                         highlightcolor=ACENTO)
        self._sel = False
        self.bind("<Button-1>", lambda _e: ao_clicar())
        self.bind("<Return>", lambda _e: ao_clicar())
        self.bind("<space>", lambda _e: ao_clicar())

    def definir(self, sel: bool) -> None:
        self._sel = sel
        self.configure(fg=TEXTO if sel else APAGADO)


def linha_h(pai, **pack) -> tk.Frame:
    f = tk.Frame(pai, bg=LINHA, height=1)
    f.pack(side="top", fill="x", **pack)
    return f


def _mesmo(a, b) -> bool:
    if a == b:
        return True
    try:
        return str(a).strip().lower() == str(b).strip().lower() or \
            float(a) == float(b)
    except (TypeError, ValueError):
        return False
