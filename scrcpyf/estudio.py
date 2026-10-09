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

import logging
import sys
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

log = logging.getLogger(__name__)


def ouvir(acao: Callable, valor) -> bool:
    """(08/out, pedido dele: "a interface pre-desenhada escuta a funcao")
    O controle ja mudou na hora do clique; a funcao e chamada e, se ela
    falhar (excecao) ou recusar (devolver False), o controle volta ao que
    era. Devolve se ficou."""
    try:
        return acao(valor) is not False
    except Exception:
        log.exception("a funcao do controle falhou (%r): volta ao que era",
                      valor)
        return False

# -- cores ---------------------------------------------------------------------
FUNDO = "#16161A"
FUNDO_FUNDO = "#101013"
LINHA = "#2C2C33"
LINHA_FORTE = "#3A3A42"
TEXTO = "#E9E6DF"
TEXTO_2 = "#9A978F"
APAGADO = "#6F6D68"
ACENTO = "#FF5A1F"
# (03/out/2026, pedido dele: "basico e bonito, sem encher de cores") Foco e
# mouse por cima NAO pintam de laranja: clareiam a borda cinza (a borda
# inteira, cantos juntos). O laranja fica para acao e estado (LIGAR, chave
# ligada, progresso, app aberto).
FOCO = "#8E8B93"
SOBRE_BORDA = "#4A4952"
# (03/out, pedido dele: o menu "parecer que esta acima") No escuro a sombra
# some; o que flutua e uma SUPERFICIE mais clara que o fundo, com a borda
# um pouco mais clara tambem (menus do botao direito, dica).
# CAMADAS (03/out, pedido dele: "voce entende a hierarquia de camadas?").
# Cada nivel acima e um pouco mais claro, com a borda tambem mais clara:
#   0  FUNDO        a janela
#   1  CAMADA_1     o conteudo sobre o fundo (cartoes de notificacao,
#                   linhas do historico)
#   2  CAMADA_2     o que FLUTUA sobre o conteudo (barra "no celular agora",
#                   buscas flutuantes, botao atualizar, balao de aviso)
#   3  SUPERFICIE   janelinhas por cima de tudo (menus, dica, aviso do canto)
CAMADA_1 = "#1D1D22"
BORDA_1 = "#2F2F37"
BORDA_1_SOBRE = "#4A4A54"            # o cartao com o mouse em cima
CAMADA_2 = "#25252C"
BORDA_2 = "#3D3D47"
SUPERFICIE = "#2C2C34"               # camada 3
SUPERFICIE_SOBRE = "#3A3A43"
SUPERFICIE_BORDA = "#4C4C57"
ACENTO_ESCURO = "#3A1C12"
SOBRE_ACENTO = "#16161A"
VERDE = "#57C27A"
AZUL = "#5AA9FF"         # (07/out) o indicador do som
ERRO = "#FF5A5A"
ALERTA = "#E8C15A"
# (08/out, pedido dele: o padrao da aba qualidade no app todo) O PAINEL de
# cada segmento: meio tom acima do fundo (abaixo dos cartoes: a ordem das
# camadas continua), borda que quase nao aparece; a linha fina entre itens
# de um mesmo painel no tom da borda dele.
PAINEL = "#19191E"
PAINEL_BORDA = "#232329"
PAINEL_LINHA = "#24242A"

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
LARGURA_BASE, ALTURA_BASE = 680, 34 + 1 + 316     # a janela em 100%


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
# (r198, pedido dele 30/set/2026: "aumente um pouco em geral") +10% so na
# letra -- ~1 ponto em cada tamanho; as medidas e a janela ficam iguais.
AUMENTO_LETRA = 1.1
ESCALA_LETRA = ESCALA * AUMENTO_LETRA


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


_familia_ui = None


def familia_ui() -> str:
    """(08/out, pedido dele: a mono ficava "rustica" nos cartoes novos) A
    letra de interface do Windows: Segoe UI Variable (11), senao Segoe UI."""
    global _familia_ui
    if _familia_ui is None:
        try:
            disponiveis = set(tkfont.families())
        except Exception:
            disponiveis = set()
        _familia_ui = next((f for f in ("Segoe UI Variable Text", "Segoe UI")
                            if f in disponiveis), familia())
    return _familia_ui


def fonte_ui(tamanho: int, peso: str = "normal"):
    """Como `fonte`, na letra de interface. peso: normal, semibold ou
    bold."""
    chave = ("ui", familia_ui(), max(1, round(tamanho * ESCALA_LETRA)), peso)
    f = _FONTES.get(chave)
    if f is None:
        fam, peso_tk = chave[1], "bold" if peso == "bold" else "normal"
        if peso == "semibold":
            semi = {"Segoe UI Variable Text": "Segoe UI Variable Text Semibold",
                    "Segoe UI": "Segoe UI Semibold"}.get(fam)
            try:
                existe = semi in set(tkfont.families())
            except Exception:
                existe = False
            fam, peso_tk = (semi, "normal") if existe else (fam, "bold")
        try:
            f = tkfont.Font(family=fam, size=chave[2], weight=peso_tk)
        except Exception:
            return (fam, chave[2], peso_tk)
        _FONTES[chave] = f
    return f.name


def fonte(tamanho: int, peso: str = "normal"):
    """(08/out, pedido dele: "corrija a fonte de todo app") O app todo na
    letra de interface; o negrito vira o semibold (mais fino, o do Windows
    11). A mono da casa ficou em `fonte_mono` (teclas, codigos)."""
    return fonte_ui(tamanho, "semibold" if peso == "bold" else peso)


def fonte_mono(tamanho: int, peso: str = "normal"):
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


# (08/out, relato dele: "algumas palavras ficam bugadas" nas notificacoes)
# O Tk do Windows DESENHA caracteres que deviam ser invisiveis: o WhatsApp
# poe U+2068/U+2069 (isolar a direcao do texto) em volta dos nomes e saiam
# caixinhas "FSI"/"PDI" grudadas na palavra; o seletor de emoji (U+FE0F, o
# "❤️") abria um buraco; o juntador (U+200D) sobrepunha os emojis de
# familia; o tom de pele saia como um quadrado a parte. Tudo isso sai do
# texto MOSTRADO (o guardado fica como veio).
_INVISIVEIS = dict.fromkeys(
    [0x00AD, 0x061C, 0x180E, 0xFEFF, 0xFFFC]
    + list(range(0x200B, 0x2010))         # espacos zero, ZWJ, LRM/RLM
    + list(range(0x202A, 0x202F))         # embutir/sobrepor direcao
    + list(range(0x2060, 0x2070))         # juntador de palavra, isolar
    + list(range(0xFE00, 0xFE10))         # seletores de variacao
    + list(range(0x1F3FB, 0x1F400))       # tons de pele
    + list(range(0xE0000, 0xE0080)))      # etiquetas (bandeiras regionais)


def texto_limpo(texto: str) -> str:
    """O texto sem os caracteres que o Tk desenharia como lixo."""
    if not texto:
        return texto or ""
    return texto.translate(_INVISIVEIS)


# Tamanhos (pontos do Tk)
ROTULO = 7          # rotulos em caixa alta
PEQUENA = 8
CORPO = 9
GRANDE = 17         # o estado ("no ar.")
MEDIDA = 11

# -- medidas --------------------------------------------------------------------
LARGURA = px(680)
ALTURA_BARRA = px(34)
ALTURA_CORPO = px(316)       # (01/out) +30: o item NOTIFICACOES
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
# Cantos arredondados (03/out/2026, pedido dele: "pegue todas as interfaces que
# tem canto reto e coloque uma curvinha")
# ==============================================================================
# O Tk nao arredonda widget, e a curva desenhada no canvas sai serrilhada. O
# jeito: QUATRO CANTINHOS (imagens lisas, feitas maiores e reduzidas) colados
# por cima dos cantos da peca -- com a cor de fora, a de dentro e a borda dela.
# A peca continua a mesma (Frame, Label...); `cantos(w)` le as cores atuais
# dela e pode ser chamado de novo quando as cores mudam (selecionado, mouse).

RAIO = px(6)
_IMAGENS_CANTOS: dict = {}


def _imagens_cantos(r: int, fora: str, dentro: str, borda: str, esp: int):
    chave = (r, fora, dentro, borda, esp)
    if chave in _IMAGENS_CANTOS:
        return _IMAGENS_CANTOS[chave]
    from PIL import Image, ImageDraw, ImageTk
    k = 4
    lado = 2 * r * k
    img = Image.new("RGB", (lado, lado), fora)
    ImageDraw.Draw(img).rounded_rectangle(
        (0, 0, lado - 1, lado - 1), radius=r * k, fill=dentro,
        outline=borda if esp else None, width=esp * k if esp else 0)
    filtro = getattr(Image, "Resampling", Image).BOX
    img = img.resize((2 * r, 2 * r), filtro)
    quartos = [img.crop(c) for c in ((0, 0, r, r), (r, 0, 2 * r, r),
                                     (0, r, r, 2 * r), (r, r, 2 * r, 2 * r))]
    fotos = [ImageTk.PhotoImage(q) for q in quartos]
    if len(_IMAGENS_CANTOS) > 400:
        _IMAGENS_CANTOS.clear()
    _IMAGENS_CANTOS[chave] = fotos
    return fotos


_IMAGENS_CHAVE: dict = {}


def _mistura(cor: str, outra: str, f: float) -> str:
    """f=1: cor; f=0: outra."""
    a = [int(cor[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(outra[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02X%02X%02X" % tuple(round(y + (x - y) * f) for x, y in zip(a, b))


def _imagem_chave(larg: int, alt: int, ligado, travada: bool,
                  fundo: str):
    """`ligado` True/False ou um numero de 0 a 1 (07/out: o meio do
    caminho, a chave deslizando)."""
    p = 1.0 if ligado is True else 0.0 if ligado is False else \
        round(max(0.0, min(1.0, float(ligado))) * 12) / 12.0
    chave = (larg, alt, p, travada, fundo)
    if chave in _IMAGENS_CHAVE:
        return _IMAGENS_CHAVE[chave]
    try:
        from PIL import Image, ImageDraw, ImageTk
    except Exception:
        return None
    k = 4
    L, A = larg * k, alt * k
    img = Image.new("RGB", (L, A), fundo)
    d = ImageDraw.Draw(img)
    cheio = "#7A3A22" if travada else ACENTO
    bola_lig = "#B9A79E" if travada else TEXTO
    contorno = LINHA_FORTE if travada else APAGADO
    if p >= 1.0:
        bola = bola_lig
        d.rounded_rectangle((0, 0, L - 1, A - 1), radius=A // 2, fill=cheio)
    elif p <= 0.0:
        bola = contorno
        d.rounded_rectangle((k, k, L - 1 - k, A - 1 - k), radius=A // 2 - k,
                            outline=contorno, width=max(k, int(1.5 * k)))
    else:
        # o trilho enche de laranja enquanto a bolinha anda
        bola = _mistura(bola_lig, contorno, p)
        d.rounded_rectangle((0, 0, L - 1, A - 1), radius=A // 2,
                            fill=_mistura(cheio, fundo, p))
        d.rounded_rectangle((k, k, L - 1 - k, A - 1 - k), radius=A // 2 - k,
                            outline=_mistura(cheio, contorno, p),
                            width=max(k, int(1.5 * k)))
    m = int(A * 0.22)
    raio = A // 2 - m
    cx = A // 2 + (L - A) * p
    d.ellipse((cx - raio, A // 2 - raio, cx + raio, A // 2 + raio), fill=bola)
    filtro = getattr(Image, "Resampling", Image).BOX
    foto = ImageTk.PhotoImage(img.resize((larg, alt), filtro))
    _IMAGENS_CHAVE[chave] = foto
    return foto


def imagem_redonda(lado: int, cor: str, fundo: str, raio: int):
    """Um quadrado de cantos redondos, liso (as amostras de cor)."""
    chave = ("quadro", lado, cor, fundo, raio)
    if chave in _IMAGENS_CHAVE:
        return _IMAGENS_CHAVE[chave]
    try:
        from PIL import Image, ImageDraw, ImageTk
    except Exception:
        return None
    k = 4
    img = Image.new("RGB", (lado * k, lado * k), fundo)
    ImageDraw.Draw(img).rounded_rectangle(
        (0, 0, lado * k - 1, lado * k - 1), radius=raio * k, fill=cor)
    filtro = getattr(Image, "Resampling", Image).BOX
    foto = ImageTk.PhotoImage(img.resize((lado, lado), filtro))
    _IMAGENS_CHAVE[chave] = foto
    return foto


def imagem_amostra(lado: int, cor: str, fundo: str, anel: str | None = None):
    """(07/out) Amostra de cor com o anel de "escolhida" JUNTO, numa imagem
    lisa (antes o anel era a borda do Tk + cantinhos por cima, que cortavam
    a amostra). `lado` = o quadro todo; a amostra fica 3 px para dentro."""
    chave = ("amostra", lado, cor, fundo, anel)
    if chave in _IMAGENS_CHAVE:
        return _IMAGENS_CHAVE[chave]
    try:
        from PIL import Image, ImageDraw, ImageTk
    except Exception:
        return None
    k = 4
    L = lado * k
    img = Image.new("RGB", (L, L), fundo)
    d = ImageDraw.Draw(img)
    raio = max(2, lado // 4) * k
    if anel:
        d.rounded_rectangle((0, 0, L - 1, L - 1), radius=raio + k,
                            outline=anel, width=max(k, int(1.25 * k)))
    m = 3 * k
    d.rounded_rectangle((m, m, L - 1 - m, L - 1 - m), radius=raio - k,
                        fill=cor)
    filtro = getattr(Image, "Resampling", Image).BOX
    foto = ImageTk.PhotoImage(img.resize((lado, lado), filtro))
    _IMAGENS_CHAVE[chave] = foto
    return foto


def imagem_x(lado: int, cor: str, fundo: str, bolha: str | None = None):
    """(07/out) O "x" da casa: duas diagonais de 7 a 17 numa grade de 24,
    traco de 2 unidades com ponta redonda (padrao dos icones de linha);
    `bolha` = o circulo do realce atras."""
    chave = ("x", lado, cor, fundo, bolha)
    if chave in _IMAGENS_CHAVE:
        return _IMAGENS_CHAVE[chave]
    try:
        from PIL import Image, ImageDraw, ImageTk
    except Exception:
        return None
    k = 4
    L = lado * k
    u = L / 24.0
    g = max(k, int(round(2 * u)))
    img = Image.new("RGB", (L, L), fundo)
    d = ImageDraw.Draw(img)
    if bolha:
        d.ellipse((0, 0, L - 1, L - 1), fill=bolha)
    a0, a1 = 7 * u, 17 * u
    for p, q in (((a0, a0), (a1, a1)), ((a1, a0), (a0, a1))):
        d.line(p + q, fill=cor, width=g)
        for x, y in (p, q):
            d.ellipse((x - g / 2, y - g / 2, x + g / 2, y + g / 2), fill=cor)
    filtro = getattr(Image, "Resampling", Image).BOX
    foto = ImageTk.PhotoImage(img.resize((lado, lado), filtro))
    _IMAGENS_CHAVE[chave] = foto
    return foto


def botao_x(pai, fundo: str, acao, lado: int | None = None) -> tk.Label:
    """O botao "x" da casa (fechar, tirar, limpar): so o icone; com o mouse,
    a bolha discreta atras e o icone clareia."""
    lado = lado or px(18)
    b = tk.Label(pai, bd=0, highlightthickness=0, bg=fundo, cursor="hand2",
                 image=imagem_x(lado, APAGADO, fundo))

    def pintar(ativo):
        b.configure(image=imagem_x(lado, TEXTO if ativo else APAGADO, fundo,
                                   SUPERFICIE_SOBRE if ativo else None))
    b.bind("<Button-1>", lambda _e: (acao(), "break")[1])
    b.bind("<Enter>", lambda _e: pintar(True))
    b.bind("<Leave>", lambda _e: pintar(False))
    return b


def _imagem_bola(lado: int, cor: str, fundo: str):
    """Uma bolinha lisa (a pegada do Deslizador)."""
    chave = ("bola", lado, cor, fundo)
    if chave in _IMAGENS_CHAVE:
        return _IMAGENS_CHAVE[chave]
    try:
        from PIL import Image, ImageDraw, ImageTk
    except Exception:
        return None
    k = 4
    img = Image.new("RGB", (lado * k, lado * k), fundo)
    ImageDraw.Draw(img).ellipse((0, 0, lado * k - 1, lado * k - 1), fill=cor)
    filtro = getattr(Image, "Resampling", Image).BOX
    foto = ImageTk.PhotoImage(img.resize((lado, lado), filtro))
    _IMAGENS_CHAVE[chave] = foto
    return foto


def _cor_de_fora(w) -> str:
    """A cor em volta de `w`. (07/out) `w._cor_fora` quando o pai nao e o
    que aparece (caixa dentro de um cartao desenhado num canvas)."""
    try:
        return getattr(w, "_cor_fora", None) or w.master.cget("bg")
    except Exception:
        return FUNDO


def recorte_redondo(w, raio: int | None = None) -> None:
    """(07/out, gravado: o balao "buscando os icones" nascia QUADRADO e com
    uma faixa escura) Para o que FLUTUA E SE MOVE sobre conteudo que muda:
    o proprio widget e recortado redondo pelo Windows (SetWindowRgn) e o
    que esta atras aparece de verdade nos cantos. Os cantinhos de `cantos`
    sao pecas pintadas com a cor de tras -- servem para o que fica parado
    sobre um fundo liso, nao para isto. Refeito a cada mudanca de tamanho."""
    if sys.platform != "win32":
        return
    r = raio or RAIO

    def aplicar(_e=None):
        try:
            larg, alt = w.winfo_width(), w.winfo_height()
            if larg < 2 or alt < 2 or getattr(w, "_rgn_tam", None) == \
                    (larg, alt):
                return
            w._rgn_tam = (larg, alt)
            import ctypes
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(
                0, 0, larg + 1, alt + 1, 2 * r, 2 * r)
            ctypes.windll.user32.SetWindowRgn(w.winfo_id(), rgn, True)
        except Exception:
            pass

    if not getattr(w, "_rgn_ligado", False):
        w._rgn_ligado = True
        w.bind("<Configure>", aplicar, add="+")
    aplicar()


def cantos(w, raio: int | None = None, dentro: str | None = None,
           dentro_dir: str | None = None, borda: str | None = None) -> None:
    """Arredonda os cantos de `w` (com as cores dele AGORA). `dentro` quando
    o fundo visivel nao e o `bg` do proprio widget; `dentro_dir` quando o
    lado direito tem outra cor (a ultima opcao de um Segmentado); `borda`
    quando a linha em volta nao e o highlight do widget (tabela feita de
    celulas sobre um fundo de linha: borda de 1 px dessa cor)."""
    borda_pedida = borda
    try:
        if not w.winfo_exists():
            return
        r = raio or RAIO
        try:
            esp = int(w.cget("highlightthickness"))
        except Exception:
            esp = 0
        cor = dentro or w.cget("bg")
        # Com o FOCO o Tk pinta a borda com a highlightcolor (laranja): o
        # cantinho acompanha (antes so os cantos ficavam sem o laranja).
        try:
            focado = w.focus_get() is w
        except Exception:
            focado = False
        hl = esp                         # a borda de verdade do widget
        if borda is not None:
            esp = max(esp, 1)
        else:
            borda = (w.cget("highlightcolor") if focado else
                     w.cget("highlightbackground")) if esp else cor
        fora = _cor_de_fora(w)
        fotos = _imagens_cantos(r, fora, cor, borda, esp)
        if dentro_dir and dentro_dir != cor:
            dir_ = _imagens_cantos(r, fora, dentro_dir, borda, esp)
            fotos = [fotos[0], dir_[1], fotos[2], dir_[3]]
    except Exception:
        return
    pecas = getattr(w, "_cantos", None)
    if pecas is None:
        pecas = []
        # O `place` conta a partir de DENTRO da borda (bd + highlight): o
        # cantinho volta essa medida para cair no canto de verdade.
        # (07/out, medido) No CANVAS o `place` conta da borda de FORA (o Tk
        # nao poe o highlight na borda interna dele): la o desvio e zero --
        # antes os cantinhos das amostras de cor e dos mapas saiam 1 px para
        # fora, com um degrau na curva.
        try:
            ib = 0 if isinstance(w, tk.Canvas) else \
                int(float(w.cget("bd") or 0)) + hl
        except Exception:
            ib = esp
        for i, (rx, ry, anc) in enumerate(((0, 0, "nw"), (1, 0, "ne"),
                                           (0, 1, "sw"), (1, 1, "se"))):
            # (07/out, relato dele: "quadrados brancos", depois "pretos", ao
            # redesenhar) Redesenhando, o Windows pinta o FUNDO do Label
            # antes da imagem: sem bg era branco; com a cor de fora, um
            # quadrado escuro sobre o controle. ~80% do cantinho e o lado de
            # DENTRO da curva: com essa cor o instante fica igual ao fim.
            c = tk.Label(w.master, image=fotos[i], bd=0, highlightthickness=0,
                         padx=0, pady=0, cursor=w.cget("cursor"))
            c.place(in_=w, relx=rx, rely=ry, anchor=anc,
                    x=ib if rx else -ib, y=ib if ry else -ib)
            # o clique no cantinho e o clique na peca
            for ev in ("<Button-1>", "<Button-3>"):
                c.bind(ev, lambda e, ev=ev: w.event_generate(
                    ev, x=0, y=0, rootx=e.x_root, rooty=e.y_root))
            pecas.append(c)
        w._cantos = pecas
        w.bind("<Destroy>", lambda e: e.widget is w and [
            p.destroy() for p in pecas if p.winfo_exists()], add="+")
        if esp:
            for ev in ("<FocusIn>", "<FocusOut>"):
                w.bind(ev, lambda _e: w.after_idle(
                    lambda: w.winfo_exists() and cantos(w, *w._cantos_args)),
                    add="+")
    w._cantos_args = (raio, dentro, dentro_dir, borda_pedida)  # da ultima vez
    for i, (c, foto) in enumerate(zip(pecas, fotos)):
        fundo_peca = dentro_dir if (dentro_dir and i in (1, 3)) else cor
        c.configure(image=foto, bg=fundo_peca)
        c.lift(w)


# ==============================================================================
# Controles
# ==============================================================================

class Rotulo(tk.Label):
    """Rotulo de secao. (08/out, padrao da qualidade) sem caixa alta: o
    nome em semibold, um degrau abaixo do titulo do painel."""

    def __init__(self, pai, texto: str, **kw) -> None:
        super().__init__(pai, text=texto, bg=kw.pop("bg", FUNDO),
                         fg=kw.pop("fg", TEXTO_2),
                         font=fonte(PEQUENA, "bold"), anchor="w", **kw)


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
        # (07/out, camadas) o botao segue a camada em que esta (um botao num
        # cartao tem o fundo do cartao); com o mouse, clareia um pouco
        self._fundo = kw.pop("bg", FUNDO)
        self._fundo_sobre = _mistura("#FFFFFF", self._fundo, 0.05)
        # (08/out, padrao da qualidade) sem caixa alta, como o resto
        super().__init__(pai, text=texto, font=fonte(PEQUENA, "bold")
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
            self.configure(bg=self._fundo, fg=APAGADO,
                           highlightbackground=LINHA, highlightcolor=LINHA,
                           cursor="arrow")
            cantos(self)
            return
        if self._tipo == "acao":
            self.configure(bg="#FF7440" if sobre else ACENTO, fg=SOBRE_ACENTO,
                           highlightbackground=ACENTO, highlightcolor=TEXTO,
                           cursor="hand2")
        elif self._tipo == "contorno":
            self.configure(bg=self._fundo_sobre if sobre else self._fundo,
                           fg=TEXTO, highlightbackground=TEXTO,
                           highlightcolor=FOCO, cursor="hand2")
        else:
            self.configure(bg=self._fundo_sobre if sobre else self._fundo,
                           fg=TEXTO_2, highlightbackground=LINHA_FORTE,
                           highlightcolor=FOCO, cursor="hand2")
        cantos(self)

    def _clicou(self):
        if self._ligado:
            self._acao()
        return "break"

    def definir(self, texto: str | None = None, tipo: str | None = None,
                ligado: bool | None = None) -> None:
        if texto is not None:
            self.configure(text=texto)
        if tipo is not None:
            self._tipo = tipo
            self.configure(font=fonte(PEQUENA, "bold") if tipo == "acao"
                           else fonte(PEQUENA),
                           pady=px(8) if tipo == "acao" else px(5))
        if ligado is not None:
            self._ligado = ligado
        self._pintar()


# (08/out/2026, rework da qualidade; pedido dele: "nao precisa usar essas
# pilulas") CARTOES DE ESCOLHA (radio tiles). Da pesquisa (08/out):
# - opcao curta que PRECISA de uma linha de explicacao fica melhor num
#   cartao do que numa pilula (Salt "selectable card", USWDS "tile"): alvo
#   grande, titulo + medida + o que significa;
# - a escolhida NAO so pela cor: borda + a marca cheia com o ✓ (as outras
#   com o anel vazio, como um radio);
# - a TRAVADA continua a vista, com cadeado e o motivo, e o caminho para
#   liberar fica PERTO dela (Cloudscape; Smashing "hidden vs disabled");
# - a troca anima em ~200 ms (One UI "basic"), a borda e a marca juntas.
# Tudo num Canvas so: o cartao e uma imagem lisa (PIL, reduzida com BOX --
# sem o anel escuro do LANCZOS, r48) e os textos sao do proprio canvas. Sem
# cantinhos pintados por cima, nada a desalinhar ao redesenhar.

def _imagem_cartao(larg: int, alt: int, fora: str, cheio: str, borda: str,
                   esp: float, marca, raio: int):
    """`marca`: None, ("radio", k, fundo_marca) com k de 0 (anel vazio) a 1
    (cheio com ✓), ou ("cadeado", cor)."""
    k_r = None
    if marca and marca[0] == "radio":
        k_r = round(max(0.0, min(1.0, marca[1])) * 12) / 12.0
        marca = ("radio", k_r)
    chave = ("cartao", larg, alt, fora, cheio, borda, esp, marca, raio)
    if chave in _IMAGENS_CHAVE:
        return _IMAGENS_CHAVE[chave]
    try:
        from PIL import Image, ImageDraw, ImageTk
    except Exception:
        return None
    k = 4
    L, A = larg * k, alt * k
    img = Image.new("RGB", (L, A), fora)
    d = ImageDraw.Draw(img)
    e = max(k, int(round(esp * k)))
    d.rounded_rectangle((0, 0, L - 1, A - 1), radius=raio * k, fill=borda)
    d.rounded_rectangle((e, e, L - 1 - e, A - 1 - e),
                        radius=max(1, raio * k - e), fill=cheio)
    if marca:
        lado = px(16) * k
        m = px(10) * k
        x0, y0 = L - m - lado, m
        if marca[0] == "radio":
            # o anel vazio (k 0) enche de laranja ate o disco (k 1)
            kk = marca[1]
            d.ellipse((x0, y0, x0 + lado, y0 + lado),
                      fill=_mistura(ACENTO, LINHA_FORTE, kk))
            dentro = 1.5 * k + (lado / 2.0 - 1.5 * k) * kk
            if dentro < lado / 2.0 - 0.5:
                d.ellipse((x0 + dentro, y0 + dentro, x0 + lado - dentro,
                           y0 + lado - dentro), fill=cheio)
            if kk > 0.5:
                # o ✓ (grade de 24: 6,12 -> 10,16 -> 18,8), escuro sobre o
                # laranja, aparecendo na segunda metade da troca
                u = lado / 24.0
                cor = _mistura(SOBRE_ACENTO, ACENTO, (kk - 0.5) * 2)
                pts = [(x0 + 6.5 * u, y0 + 12.5 * u), (x0 + 10.5 * u,
                                                       y0 + 16.5 * u),
                       (x0 + 17.5 * u, y0 + 8.5 * u)]
                g = max(k, int(round(2.4 * u)))
                d.line(pts, fill=cor, width=g, joint="curve")
                for x, y in (pts[0], pts[-1]):
                    d.ellipse((x - g / 2, y - g / 2, x + g / 2, y + g / 2),
                              fill=cor)
        else:
            # cadeado: arco (alca) e corpo, em linha (grade de 24)
            cor = marca[1]
            u = lado / 24.0
            g = max(k, int(round(2 * u)))
            d.arc((x0 + 8 * u, y0 + 3 * u, x0 + 16 * u, y0 + 13 * u), 180,
                  360, fill=cor, width=g)
            d.line((x0 + 8 * u + g / 2, y0 + 8 * u, x0 + 8 * u + g / 2,
                    y0 + 11 * u), fill=cor, width=g)
            d.line((x0 + 16 * u - g / 2, y0 + 8 * u, x0 + 16 * u - g / 2,
                    y0 + 11 * u), fill=cor, width=g)
            d.rounded_rectangle((x0 + 5 * u, y0 + 11 * u, x0 + 19 * u,
                                 y0 + 21 * u), radius=2 * u, fill=cor)
    filtro = getattr(Image, "Resampling", Image).BOX
    foto = ImageTk.PhotoImage(img.resize((larg, alt), filtro))
    if len(_IMAGENS_CHAVE) > 600:
        _IMAGENS_CHAVE.clear()
    _IMAGENS_CHAVE[chave] = foto
    return foto


class Escolha(tk.Canvas):
    """
    Cartoes lado a lado, um escolhido (radio). `opcoes`: lista de dicts
    {"valor", "titulo", "sub", "detalhe", "selo", "travada"} (so "valor" e
    "titulo" sao obrigatorios). Clique ou setas escolhem; a travada chama
    `ao_travada(valor)` (se houver) em vez de escolher.
    """

    GAP = px(8)
    PAD = px(10)

    def __init__(self, pai, opcoes, valor, ao_escolher: Callable,
                 ao_travada: Callable | None = None, compacto: bool = False,
                 chips: bool = False, **kw) -> None:
        import tkinter.font as tkfont
        fundo = kw.pop("bg", FUNDO)
        # (08/out, pedido dele: "remover todas as pilulas antigas") CHIPS =
        # os cartoes em uma linha so, sem a bolinha (o lugar das pilulas):
        # escolhido = borda laranja + o tom do cartao + o texto claro
        self._chips = chips
        if chips:
            self.PAD, self.GAP = px(6), px(6)
        # (08/out) compacto = cartoes estreitos (coluna do modo): titulo menor,
        # senao "1080p" encostava na bolinha
        if compacto:
            self.PAD = px(8)
        self._f_titulo = fonte_ui(PEQUENA if compacto else MEDIDA, "semibold")
        if chips:
            self._f_titulo = fonte_ui(PEQUENA)
            self._f_tit_sel = fonte_ui(PEQUENA, "semibold")
        self._f_sub = fonte_ui(PEQUENA)
        self._f_det = fonte_ui(ROTULO)
        self._opcoes = [dict(o) for o in opcoes]
        alt = self.PAD * 2
        try:
            linha = lambda f: tkfont.Font(root=pai, font=f).metrics(
                "linespace")
            alt += linha(self._f_titulo)
            if any(o.get("sub") for o in self._opcoes):
                alt += px(1) + linha(self._f_sub)
            if any(o.get("detalhe") or o.get("selo") for o in self._opcoes):
                alt += px(2) + linha(self._f_det)
        except Exception:
            alt += px(48)
        if chips and "width" not in kw:
            try:
                med = tkfont.Font(root=pai, font=fonte_ui(PEQUENA, "semibold"))
                kw["width"] = sum(med.measure(str(o["titulo"])) + px(24)
                                  for o in self._opcoes) + \
                    self.GAP * max(0, len(self._opcoes) - 1)
            except Exception:
                pass
        super().__init__(pai, bg=fundo, height=alt, highlightthickness=0,
                         bd=0, takefocus=1, cursor="hand2", **kw)
        self._fundo = fundo
        self._valor = valor
        self._acao = ao_escolher
        self._ao_travada = ao_travada
        self._ligado = True
        self._sobre = None
        self._k = {i: (1.0 if _mesmo(o["valor"], valor) else 0.0)
                   for i, o in enumerate(self._opcoes)}
        self._caixas = []
        self.bind("<Configure>", lambda _e: self._desenhar(), add="+")
        self.bind("<Motion>", self._mexeu)
        self.bind("<Leave>", lambda _e: self._pairar(None))
        self.bind("<Button-1>", self._clicou)
        for tecla, passo in (("<Left>", -1), ("<Up>", -1), ("<Right>", 1),
                             ("<Down>", 1)):
            self.bind(tecla, lambda _e, p=passo: self._andar(p))
        self.bind("<FocusIn>", lambda _e: self._desenhar(), add="+")
        self.bind("<FocusOut>", lambda _e: self._desenhar(), add="+")

    # -- estado ---------------------------------------------------------------

    def _indice(self):
        for i, o in enumerate(self._opcoes):
            if _mesmo(o["valor"], self._valor):
                return i
        return None

    def definir(self, valor) -> None:
        if _mesmo(valor, self._valor):
            return
        self._valor = valor
        self._animar()

    def habilitar(self, ligado: bool) -> None:
        self._ligado = ligado
        self.configure(takefocus=1 if ligado else 0,
                       cursor="hand2" if ligado else "arrow")
        self._desenhar()

    def _escolher(self, i: int) -> None:
        o = self._opcoes[i]
        if not self._ligado:
            return
        if o.get("travada"):
            if self._ao_travada is not None:
                self._ao_travada(o["valor"])
            return
        if _mesmo(o["valor"], self._valor):
            return
        antes = self._valor
        self._valor = o["valor"]
        self._animar()
        if not ouvir(self._acao, o["valor"]):
            self.definir(antes)

    def _animar(self) -> None:
        from . import movimento as mov
        alvo = self._indice()
        de = dict(self._k)

        def a_cada(t):
            for i in self._k:
                fim = 1.0 if i == alvo else 0.0
                self._k[i] = de[i] + (fim - de[i]) * t
            self._desenhar()
        mov.animar(self, "escolha", mov.MS_CONTROLE, a_cada)

    # -- mouse e teclado ------------------------------------------------------

    def _no_ponto(self, x, y):
        for i, (x0, y0, x1, y1) in enumerate(self._caixas):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return i
        return None

    def _mexeu(self, e) -> None:
        self._pairar(self._no_ponto(e.x, e.y))

    def _pairar(self, i) -> None:
        if i == self._sobre:
            return
        self._sobre = i
        trav = i is not None and self._opcoes[i].get("travada")
        self.configure(cursor="hand2" if self._ligado and i is not None and
                       not (trav and self._ao_travada is None) else "arrow")
        self._desenhar()

    def _clicou(self, e):
        i = self._no_ponto(e.x, e.y)
        if i is not None:
            self._escolher(i)
        return "break"

    def _andar(self, passo: int):
        i = self._indice()
        n = len(self._opcoes)
        j = i if i is not None else (-1 if passo > 0 else n)
        while True:
            j += passo
            if not 0 <= j < n:
                return "break"
            if not self._opcoes[j].get("travada"):
                self._escolher(j)
                return "break"

    # -- desenho --------------------------------------------------------------

    def _desenhar(self) -> None:
        try:
            larg, alt = self.winfo_width(), int(self.cget("height"))
        except tk.TclError:
            return
        n = len(self._opcoes)
        if larg < 20 or not n:
            return
        self.delete("all")
        self._fotos = []
        self._caixas = []
        cada = (larg - self.GAP * (n - 1)) / float(n)
        try:
            focado = self.focus_get() is self
        except Exception:
            focado = False
        escolhido = self._indice()
        if self._chips:
            self._desenhar_chips(larg, alt, focado, escolhido)
            return
        # titulo que encosta na bolinha: todos os cartoes com o titulo menor
        f_tit = self._f_titulo
        livre = int(cada) - self.PAD - px(10) - px(16) - px(6)
        try:
            import tkinter.font as tkfont
            medida = tkfont.Font(root=self, font=f_tit)
            if any(medida.measure(o["titulo"]) > livre for o in self._opcoes):
                f_tit = fonte_ui(PEQUENA, "semibold")
        except Exception:
            pass
        for i, o in enumerate(self._opcoes):
            x0 = int(round(i * (cada + self.GAP)))
            x1 = int(round(i * (cada + self.GAP) + cada))
            w = x1 - x0
            self._caixas.append((x0, 0, x1, alt))
            k = self._k.get(i, 0.0)
            trav = bool(o.get("travada")) or not self._ligado
            sobre = self._sobre == i and self._ligado and not o.get("travada")
            if o.get("travada"):
                cheio, borda, esp = self._fundo, LINHA, 1.0
                marca = ("cadeado", APAGADO)
            else:
                base = BORDA_1_SOBRE if sobre else BORDA_1
                if focado and i == (escolhido if escolhido is not None
                                    else 0):
                    base = FOCO
                cheio = _mistura(CAMADA_2, CAMADA_1, k)
                borda = _mistura(ACENTO, base, k) if self._ligado else LINHA
                esp = 1.0 + 0.5 * k
                marca = ("radio", k if self._ligado else 0.0)
            foto = _imagem_cartao(w, alt, self._fundo, cheio, borda, esp,
                                  marca, RAIO)
            if foto is not None:
                self._fotos.append(foto)
                self.create_image(x0, 0, image=foto, anchor="nw")
            # textos
            tx = x0 + self.PAD
            limite = w - self.PAD * 2 - px(20)
            y = self.PAD
            cor_t = APAGADO if trav else _mistura(TEXTO, TEXTO_2, k)
            self.create_text(tx, y, text=o["titulo"], anchor="nw",
                             font=f_tit, fill=cor_t)
            y += self._linha(self._f_titulo)
            if o.get("sub"):
                y += px(1)
                self.create_text(tx, y, text=o["sub"], anchor="nw",
                                 font=self._f_sub, width=limite + px(20),
                                 fill=APAGADO if trav else
                                 _mistura(TEXTO_2, APAGADO, k))
                y += self._linha(self._f_sub)
            if o.get("detalhe") or o.get("selo"):
                y = alt - self.PAD - self._linha(self._f_det)
                # sem espaco para os dois na linha: o selo fica, o detalhe sai
                cabe = not (o.get("detalhe") and o.get("selo")) or \
                    self._largura(o["detalhe"]) + px(8) + self._largura(
                        caixa_alta(o["selo"])) <= w - self.PAD * 2
                if o.get("detalhe") and cabe:
                    self.create_text(tx, y, text=o["detalhe"], anchor="nw",
                                     font=self._f_det, fill=APAGADO,
                                     width=w - self.PAD * 2)
                if o.get("selo"):
                    self.create_text(x1 - self.PAD, y,
                                     text=caixa_alta(o["selo"]), anchor="ne",
                                     font=self._f_det,
                                     fill=APAGADO if trav else
                                     _mistura(ACENTO, TEXTO_2, k))

    def _desenhar_chips(self, larg, alt, focado, escolhido) -> None:
        import tkinter.font as tkfont
        n = len(self._opcoes)
        try:
            med = tkfont.Font(root=self, font=self._f_tit_sel)
            precisa = [med.measure(str(o["titulo"])) + px(16)
                       for o in self._opcoes]
        except Exception:
            precisa = [px(60)] * n
        livre = larg - self.GAP * (n - 1)
        # fatias iguais quando cabem; senao, na medida do texto (nada cortado)
        if max(precisa) * n <= livre:
            largs = [livre / float(n)] * n
        else:
            soma = float(sum(precisa)) or 1.0
            largs = [livre * p / soma for p in precisa]
        x = 0.0
        for i, o in enumerate(self._opcoes):
            x0, x1 = int(round(x)), int(round(x + largs[i]))
            x += largs[i] + self.GAP
            w = x1 - x0
            self._caixas.append((x0, 0, x1, alt))
            k = self._k.get(i, 0.0)
            sobre = self._sobre == i and self._ligado
            base = BORDA_1_SOBRE if sobre else BORDA_1
            if focado and i == (escolhido if escolhido is not None else 0):
                base = FOCO
            if self._ligado:
                cheio = _mistura(CAMADA_2, CAMADA_1, k)
                borda = _mistura(ACENTO, base, k)
                cor_t = _mistura(TEXTO, TEXTO_2, k)
            else:
                cheio, borda = self._fundo, LINHA
                cor_t = APAGADO if k > 0.5 else LINHA_FORTE
            foto = _imagem_cartao(w, alt, self._fundo, cheio, borda,
                                  1.0 + 0.5 * k, None, RAIO)
            if foto is not None:
                self._fotos.append(foto)
                self.create_image(x0, 0, image=foto, anchor="nw")
            self.create_text(x0 + w / 2.0, alt / 2.0, text=str(o["titulo"]),
                             anchor="center", fill=cor_t,
                             font=self._f_tit_sel if k > 0.5 else
                             self._f_titulo)

    def _largura(self, texto: str) -> int:
        import tkinter.font as tkfont
        try:
            return tkfont.Font(root=self, font=self._f_det).measure(texto)
        except Exception:
            return px(7) * len(texto)

    def _linha(self, f) -> int:
        cache = self.__dict__.setdefault("_linhas", {})
        if f not in cache:
            import tkinter.font as tkfont
            try:
                cache[f] = tkfont.Font(root=self, font=f).metrics("linespace")
            except Exception:
                cache[f] = px(14)
        return cache[f]


class Segmentado(Escolha):
    """(08/out, pedido dele: "remover todas as pilulas antigas") A fileira
    de opcoes fechadas agora e uma linha de CHIPS (`Escolha(chips=True)`),
    com a mesma chamada de antes: `opcoes` = lista de (valor, rotulo)."""

    def __init__(self, pai, opcoes, valor, ao_escolher: Callable, **kw):
        super().__init__(pai, [{"valor": v, "titulo": str(r)}
                               for v, r in opcoes], valor, ao_escolher,
                         chips=True, **kw)


class Chave(tk.Canvas):
    """Interruptor quadrado: laranja ligado, cinza desligado."""

    L, A = px(30), px(14)

    def __init__(self, pai, ligado: bool, ao_virar: Callable[[bool], None],
                 travada: bool = False, **kw) -> None:
        fundo = kw.pop("bg", FUNDO)      # (08/out) a borda na mesma cor
        super().__init__(pai, width=self.L, height=self.A, bg=fundo,
                         highlightthickness=1, highlightbackground=fundo,
                         highlightcolor=FOCO,
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
        self._deslizar()
        if not ouvir(self._acao, self._ligado):
            self.definir(not self._ligado)
        return "break"

    def definir(self, ligado: bool) -> None:
        mudou = bool(ligado) != bool(self._ligado)
        self._ligado = ligado
        if mudou and self.winfo_viewable():
            self._deslizar()
        else:
            self._pintar()

    def _deslizar(self) -> None:
        """(07/out, padrao de animacao) A bolinha anda e o trilho enche ou
        esvazia (200 ms, a curva padrao do Android)."""
        from . import movimento as mov
        de = getattr(self, "_pos", 1.0 if not self._ligado else 0.0)
        para = 1.0 if self._ligado else 0.0

        def a_cada(k):
            self._pos = de + (para - de) * k
            self._pintar(self._pos)
        mov.animar(self, "chave", mov.MS_CONTROLE, a_cada)

    def travar(self, travada: bool) -> None:
        """(r180) Trava/destrava NO LUGAR, sem remontar a tela (remontar
        dava uma piscada a cada chave)."""
        self._travada = travada
        self.configure(takefocus=0 if travada else 1,
                       cursor="arrow" if travada else "hand2")
        self._pintar()

    def _pintar(self, pos: float | None = None) -> None:
        """(03/out, pedido dele: cantos arredondados) Interruptor em pilula,
        liso (imagem feita maior e reduzida): ligado = trilho laranja cheio e
        bolinha clara a direita; desligado = trilho contornado e bolinha a
        esquerda; travada = as mesmas cores, apagadas. `pos` = o meio do
        caminho (deslizando)."""
        if pos is None:
            pos = 1.0 if self._ligado else 0.0
            self._pos = pos
        self.delete("all")
        foto = _imagem_chave(self.L, self.A, pos if 0.0 < pos < 1.0 else
                             pos >= 1.0, self._travada, self.cget("bg"))
        if foto is not None:
            self.create_image(0, 0, anchor="nw", image=foto)
            self._foto = foto
            return
        cor = ACENTO if self._ligado else APAGADO
        self.create_rectangle(0, 0, self.L - 1, self.A - 1, outline=cor)


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
                         highlightcolor=FOCO, takefocus=1, cursor="hand2",
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
        self.create_line(m, meio, l - m, meio, fill=LINHA_FORTE, width=px(2),
                         capstyle="round")
        self.create_line(m, meio, x, meio, fill=ACENTO, width=px(2),
                         capstyle="round")
        # (03/out) a pegada redonda e lisa (era um quadradinho)
        bola = _imagem_bola(px(13), TEXTO, self.cget("bg"))
        if bola is not None:
            self.create_image(x, meio, image=bola)
            self._bola = bola
        else:
            self.create_oval(x - px(6), meio - px(6), x + px(6), meio + px(6),
                             fill=TEXTO, outline=TEXTO)


class Item(tk.Frame):
    """
    Uma linha da lista da esquerda: nome, e a direita o atalho (o numero) ou
    o sinal de conectado. O ponto laranja aparece quando o modo esta no ar.
    """

    def __init__(self, pai, nome: str, ao_clicar: Callable[[], None],
                 tecla: str = "", marca: str = "", rodape: bool = False) -> None:
        super().__init__(pai, bg=FUNDO, highlightthickness=1,
                         highlightbackground=FUNDO if rodape else LINHA,
                         highlightcolor=FOCO, takefocus=1, cursor="hand2")
        self._rodape = rodape
        self._marca_tipo = marca        # "" | "conexao"
        self._sel = False
        self._vivo = False
        self._ok = False
        self._nome = tk.Label(self, text=nome, font=fonte(PEQUENA),
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
        trocou = selecionado is not None and bool(selecionado) != self._sel \
            and not self._rodape
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
        if trocou and self.winfo_viewable():
            # (07/out, padrao de animacao) clareia/apaga em 200 ms
            from . import movimento as mov
            ir = 1.0 if self._sel else 0.0
            de = 1.0 - ir
            mov.animar(self, "sel", mov.MS_CONTROLE,
                       lambda k: self._pintar(de + (ir - de) * k))
        else:
            self._pintar()

    def _pintar(self, s: float | None = None) -> None:
        """`s` = quanto esta selecionado (0 a 1; no meio = trocando)."""
        if s is None:
            s = 1.0 if self._sel else 0.0
        # (07/out, medido) em 8 degraus: cada cor nova gerava os cantinhos
        # de novo (PIL) a cada quadro, o quadro atrasava e o nome ficava
        # com a cor de um quadro e o fundo com a de outro. Com degraus os
        # cantinhos saem do guardado.
        s = round(s * 8) / 8.0
        chave = (s, self._sel, self._vivo, self._ok,
                 getattr(self, "_travado", False), self._tecla.cget("text"))
        if getattr(self, "_pintado", None) == chave:
            return                       # mesmo degrau: nada a refazer
        self._pintado = chave
        sel = s >= 0.5
        if self._rodape:
            fundo, cor = FUNDO, (TEXTO if self._sel else TEXTO_2)
            borda = FUNDO
        else:
            fundo = _mistura(TEXTO, FUNDO, s)
            cor = _mistura(FUNDO, TEXTO, s)
            borda = _mistura(TEXTO, LINHA, s)
        if getattr(self, "_travado", False) and not self._sel:
            cor = LINHA_FORTE
        self.configure(bg=fundo, highlightbackground=borda)
        self._nome.configure(bg=fundo, fg=cor)
        self._tecla.configure(bg=fundo, fg=(FUNDO if sel else APAGADO),
                              highlightbackground=("#55535A" if sel
                                                   else LINHA_FORTE))
        for c in (self._ponto, self._sinal):
            c.configure(bg=fundo)
            c.delete("all")
        # (07/out) os sinais sao bolinhas (eram quadradinhos)
        if self._vivo or (self._rodape and self._sel):
            self._ponto.create_oval(1, 1, px(7), px(7), fill=ACENTO,
                                    outline=ACENTO)
        if self._marca_tipo == "conexao":
            cor_s = VERDE if self._ok else (FUNDO if sel else TEXTO_2)
            self._sinal.create_oval(1, 1, px(7), px(7), outline=cor_s,
                                    fill=VERDE if self._ok else fundo)
        if not self._rodape:
            cantos(self)
            cantos(self._tecla, raio=px(3))


class Aba(tk.Label):
    """Aba da barra de cima: texto em caixa alta, sublinhado laranja quando escolhida."""

    def __init__(self, pai, texto: str, ao_clicar: Callable[[], None]) -> None:
        super().__init__(pai, text=texto, font=fonte(PEQUENA),
                         bg=FUNDO, cursor="hand2", takefocus=1, padx=px(2),
                         highlightthickness=1, highlightbackground=FUNDO,
                         highlightcolor=FOCO)
        self._sel = False
        self.bind("<Button-1>", lambda _e: ao_clicar())
        self.bind("<Return>", lambda _e: ao_clicar())
        self.bind("<space>", lambda _e: ao_clicar())

    def definir(self, sel: bool) -> None:
        self._sel = sel
        self.configure(fg=TEXTO if sel else APAGADO)


def camada(raiz, cor: str = PAINEL, de: str = FUNDO) -> None:
    """(08/out, padrao da qualidade no app todo) Pinta tudo DENTRO de `raiz`
    que esta na cor do fundo (`de`) com a cor do painel: frames, textos,
    canvas, e os controles da casa (botao, cartoes, chave, deslizador) se
    redesenham na camada nova. A linha fina de separacao (LINHA, 1 px) vira a
    linha do painel. Depois refaz os cantinhos (eles levam a cor de fora)."""
    com_cantos = []

    def troca(c):
        return cor if str(c).upper() == de.upper() else None

    def anda(w):
        for f in w.winfo_children():
            if getattr(f, "_camada", None):
                continue                   # outro painel: tem a cor dele
            try:
                if isinstance(f, tk.Frame) and str(f.cget("bg")).upper() == \
                        LINHA.upper() and \
                        1 <= int(float(f.cget("height"))) <= 2:
                    f.configure(bg=PAINEL_LINHA)
                for op in ("bg", "highlightbackground"):
                    try:
                        nova = troca(f.cget(op))
                    except tk.TclError:
                        continue
                    if nova:
                        f.configure(**{op: nova})
                # imagem com o fundo desenhado dentro: quem fez sabe refazer
                if callable(getattr(f, "_recamada", None)):
                    f._recamada(cor)
                if getattr(f, "_fundo", None) and troca(f._fundo):
                    f._fundo = cor
                    if hasattr(f, "_fundo_sobre"):
                        f._fundo_sobre = _mistura("#FFFFFF", cor, 0.05)
                for nome in ("_pintar", "_desenhar"):
                    m = getattr(f, nome, None)
                    if callable(m) and isinstance(f, (Botao, Escolha, Chave,
                                                      Deslizador)):
                        m()
                        break
                if getattr(f, "_cantos", None):
                    com_cantos.append(f)
            except tk.TclError:
                continue
            anda(f)
    try:
        anda(raiz)
    except tk.TclError:
        return
    for f in com_cantos:
        try:
            if f.winfo_exists() and isinstance(f, Botao):
                f._pintar()               # o botao refaz os dele
            elif f.winfo_exists():
                cantos(f, *f._cantos_args)
        except Exception:
            pass


def painel(pai, cor: str = PAINEL, raio: int | None = None,
           **pack) -> tk.Frame:
    """Um painel (a caixa sutil de cada segmento): fundo `cor`, borda de 1
    px quase invisivel, cantos redondos. Devolve o proprio painel; chame
    `camada(p)` (ou deixe o `after_idle` daqui) depois de encher."""
    p = tk.Frame(pai, bg=cor, highlightthickness=1,
                 highlightbackground=PAINEL_BORDA,
                 highlightcolor=PAINEL_BORDA)
    p._camada = cor
    if pack:
        p.pack(**pack)
    cantos(p, raio=raio or px(8))
    try:
        p.after_idle(lambda: p.winfo_exists() and camada(p, cor))
    except tk.TclError:
        pass
    return p


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
