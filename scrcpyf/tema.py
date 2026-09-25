"""
Os tokens visuais do programa. Nenhuma cor, medida ou fonte escrita a mao em
qualquer outro arquivo -- valor que faltar vira token novo aqui.

O nome diz o PAPEL, nao a aparencia: `SUPERFICIE_FUNDA`, nunca `CINZA_ESCURO`.
Assim, mudar o visual e mexer neste arquivo, e nao cacar cor pelo codigo.

O ACENTO E O QUE SEPARA UM PROGRAMA DO OUTRO
---------------------------------------------
Mesma estrutura, mesma escala de superficie, mesmas medidas que o DSE, o
AmbiSync e o LightWireless -- muda so o acento, e sempre o mesmo par de
numeros com os canais girados: DSE `#E2FF5D`, AmbiSync `#5DE1FF`,
LightWireless `#FF5DE1`. Aqui: `#E15DFF`, roxo. De relance nao se confunde com
nenhum dos tres.
"""

from __future__ import annotations

# -- superficie, do fundo para a frente --------------------------------------
SUPERFICIE_FUNDA = "#0E0F11"
SUPERFICIE_JANELA = "#16181C"
SUPERFICIE_BARRA = "#1E2026"
SUPERFICIE_SOB_MOUSE = "#2A2D35"
RISCO = "#2A2D35"
CONTORNO_APAGADO = "#343841"

# -- texto -------------------------------------------------------------------
TEXTO = "#E8EAED"
TEXTO_SECUNDARIO = "#A8AEBA"
TEXTO_APAGADO = "#8A91A0"
TEXTO_SOBRE_ACENTO = "#0E0F11"

# -- estados -----------------------------------------------------------------
SUCESSO = "#5DFF9A"
ALERTA = "#E2C55D"
ERRO = "#FF5D5D"
ERRO_FORTE = "#E23D3D"

# -- acento ------------------------------------------------------------------
ACENTO = "#E15DFF"
ACENTO_FUNDO = "#3C1247"

# O logo do Windows no botao de iniciar com o Windows. E a cor da marca dele,
# e nao o acento: o botao fala de outro programa (o Windows), nao deste.
AZUL_WINDOWS = "#0078D4"

# Quanto um controle apagado (desligado, indisponivel) se mistura com o fundo.
OPACIDADE_APAGADO = 0.35

# -- tipografia --------------------------------------------------------------
FONTE = "Segoe UI"
FONTE_MONO = "Consolas"
TITULO = (FONTE, 15, "bold")
SECAO = (FONTE, 12, "bold")
CORPO = (FONTE, 11)
CORPO_FORTE = (FONTE, 11, "bold")
PEQUENA = (FONTE, 10)
MICRO = (FONTE, 9)
ROTULO = (FONTE, 9, "bold")

# -- espaco (escala de 4 em 4; nada fora desta lista) ------------------------
E1, E2, E3, E4, E5, E6, E7, E8 = 4, 8, 12, 16, 20, 24, 32, 40
RESPIRO_LATERAL = 24

# -- forma -------------------------------------------------------------------
RAIO_PEQUENO = 4
RAIO_BOTAO = 8
RAIO_JANELA = 12
RISCO_PX = 1

# -- barra de titulo ---------------------------------------------------------
ALTURA_BARRA = 48
ALVO_BOTAO = 38
VAO_BOTAO = 2
ICONE_NA_BARRA = 20
TOQUE_LONGO_S = 1.0
TOQUE_LONGO_MS = 1000

# -- janela ------------------------------------------------------------------
# Largura fixa: o conteudo tem tamanho conhecido, e esticar so criaria vazio.
# 380 e o que cabe uma fileira de cinco opcoes ("Original" inclusive) sem
# apertar o texto.
LARGURA_JANELA = 380

# Distancia da janela ate a borda da area util quando ela nasce ao lado da
# bandeja -- o mesmo respiro que o Windows deixa nos proprios paineis dali.
FOLGA_DA_BANDEJA = 12

# Os controles de escolha (fileiras de opcoes) e o botao do cartao.
ALTURA_OPCAO = 32
ALTURA_ABA = 36
ALTURA_BOTAO = 32
LADO_MARCA = 22

# A barra de rolagem do corpo, quando a tela nao cabe: fina e sem setas, como
# a do Windows 11 em repouso.
LARGURA_ROLAGEM = 4

# Anel de foco: 1 px de acento, afastado 2 px da borda do controle.
FOCO_PX = 1
FOCO_AFASTAMENTO = 2

# -- animacao ----------------------------------------------------------------
# ~110 ms no total: rapida o bastante para nao virar espera.
QUADROS = 8
MS_POR_QUADRO = 14
SALTO_PX = 10


def canais(cor: str) -> tuple:
    """`#RRGGBB` -> (r, g, b)."""
    cor = cor.lstrip("#")
    return tuple(int(cor[i:i + 2], 16) for i in (0, 2, 4))


def hexa(rgb) -> str:
    """(r, g, b) -> `#RRGGBB`."""
    return "#%02X%02X%02X" % tuple(int(max(0, min(255, c))) for c in rgb)


def escurecer(cor: str, fator: float) -> str:
    """A mesma cor mais escura. `fator` 0.8 = 20% mais escura."""
    return hexa(tuple(c * fator for c in canais(cor)))


def contraste(a: str, b: str) -> float:
    """Razao de contraste WCAG entre duas cores (1 a 21)."""
    def luz(cor):
        def canal(v):
            x = v / 255.0
            return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
        r, g, b = (canal(c) for c in canais(cor))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    la, lb = luz(a), luz(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def misturar(frente: str, fundo: str, opacidade: float) -> str:
    """
    Achata `frente` sobre `fundo` com uma opacidade. Existe porque o Canvas do
    Tk nao tem transparencia: onde se pediria 30% de branco, entra a cor ja
    misturada.
    """
    f, t = canais(frente), canais(fundo)
    return hexa(tuple(t[i] + (f[i] - t[i]) * opacidade for i in range(3)))
