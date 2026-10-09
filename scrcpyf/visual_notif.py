"""
CORES E IMAGENS DAS NOTIFICACOES E DO PLAYER (02/out/2026, pedido dele:
"os players tem que ser tematizados igual no Android, com a capa do album
de fundo").

Como o Android 13+ faz o player: a capa ocupa o cartao inteiro, coberta por
um degrade na cor tirada da propria capa (escuro e forte a esquerda, onde
fica o texto; mais leve a direita, onde a capa aparece), e o botao de tocar
e a barra ganham um tom claro da mesma cor. Sem capa: superficie neutra e o
acento do programa.

Notificacao com cor (Notification.color): o Android usa essa cor nos
detalhes (nome do app, botoes); a "colorida" (setColorized: navegacao,
chamada, cronometro) pinta o cartao inteiro. Aqui a cor e sempre ajustada
para ser legivel no fundo escuro do programa.

So conta e Pillow -- nada de Tk (da para testar sozinho).
"""

from __future__ import annotations

import colorsys
import io


def canais(cor: str) -> tuple:
    cor = cor.lstrip("#")
    return tuple(int(cor[i:i + 2], 16) for i in (0, 2, 4))


def hexa(rgb) -> str:
    return "#%02X%02X%02X" % tuple(int(max(0, min(255, round(c))))
                                   for c in rgb)


def misturar(frente: str, fundo: str, opacidade: float) -> str:
    f, t = canais(frente), canais(fundo)
    return hexa(tuple(t[i] + (f[i] - t[i]) * opacidade for i in range(3)))


def _luz(cor: str) -> float:
    def canal(v):
        x = v / 255.0
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(c) for c in canais(cor))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: str, b: str) -> float:
    la, lb = _luz(a), _luz(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def cor_legivel(cor: str, fundo: str, minimo: float = 3.0) -> str:
    """A mesma cor, clareada ate ter `minimo` de contraste no `fundo`
    (escuro) -- como o Android faz com a cor do app no tema escuro."""
    if not cor:
        return ""
    atual = cor
    for passo in range(1, 11):
        if contraste(atual, fundo) >= minimo:
            return atual
        atual = misturar("#FFFFFF", cor, passo / 10.0)
    return atual


def cores_colorida(cor: str) -> dict:
    """Cartao colorido: fundo na cor do app (escurecido ate o texto branco
    ficar legivel), texto e texto secundario."""
    fundo = cor
    for passo in range(1, 11):
        if contraste("#FFFFFF", fundo) >= 4.5:
            break
        fundo = misturar("#000000", cor, passo / 10.0)
    return {"fundo": fundo, "texto": "#FFFFFF",
            "texto2": misturar("#FFFFFF", fundo, 0.75),
            "linha": misturar("#FFFFFF", fundo, 0.25)}


def _cor_da_capa(img) -> tuple:
    """A cor que manda na capa: a mais frequente entre as que tem cor
    (cinza so se a capa inteira for cinza). (r, g, b)."""
    pequena = img.convert("RGB").resize((48, 48))
    try:
        q = pequena.quantize(colors=8)
        paleta = q.getpalette()[:24]
        contagem = sorted(q.getcolors(), reverse=True)
    except Exception:
        return pequena.resize((1, 1)).getpixel((0, 0))
    melhor, nota_melhor = None, -1.0
    for n, i in contagem:
        rgb = tuple(paleta[i * 3:i * 3 + 3])
        if len(rgb) < 3:
            continue
        _h, s, v = colorsys.rgb_to_hsv(*(c / 255.0 for c in rgb))
        nota = n * (0.25 + s) * (0.3 + min(v, 0.8))
        if nota > nota_melhor:
            melhor, nota_melhor = rgb, nota
    return melhor or (90, 90, 100)


def tema_da_capa(jpeg: bytes | None, acento: str, superficie: str) -> dict:
    """
    As cores do player: {"fundo", "texto", "texto2", "acento",
    "sobre_acento", "trilho", "cor"}. Sem capa: a superficie e o acento do
    programa.
    """
    if not jpeg:
        return {"fundo": superficie, "texto": "#FFFFFF",
                "texto2": misturar("#FFFFFF", superficie, 0.65),
                "acento": acento, "sobre_acento": superficie,
                "trilho": misturar("#FFFFFF", superficie, 0.22),
                "cor": None}
    from PIL import Image
    with Image.open(io.BytesIO(jpeg)) as img:
        r, g, b = _cor_da_capa(img)
    h, s, _v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    # Fundo: a cor da capa bem escura (onde o texto fica); acento: a mesma
    # cor clara e viva (botao de tocar, barra) -- o "tom" do Material You.
    fundo = hexa(c * 255 for c in colorsys.hsv_to_rgb(h, min(s, 0.75), 0.22))
    claro = hexa(c * 255 for c in colorsys.hsv_to_rgb(
        h, min(max(s, 0.25), 0.55), 0.95))
    return {"fundo": fundo, "texto": "#FFFFFF",
            "texto2": misturar("#FFFFFF", fundo, 0.72),
            "acento": claro, "sobre_acento": fundo,
            "trilho": misturar("#FFFFFF", fundo, 0.28),
            "cor": (r, g, b)}


def fundo_do_player(jpeg: bytes | None, largura: int, altura: int,
                    cor_fundo: str):
    """
    A imagem de fundo do player (PIL, RGB, largura x altura): a capa
    cortada para cobrir o cartao, com o degrade da cor do tema por cima --
    forte a esquerda (texto legivel), mais aberto a direita. None = sem capa.
    """
    if not jpeg or largura < 8 or altura < 8:
        return None
    from PIL import Image
    filtro = getattr(Image, "Resampling", Image).LANCZOS
    with Image.open(io.BytesIO(jpeg)) as img:
        capa = img.convert("RGB")
    # cobrir: escala pelo lado que falta e corta o meio
    escala = max(largura / capa.width, altura / capa.height)
    nova = capa.resize((max(1, round(capa.width * escala)),
                        max(1, round(capa.height * escala))), filtro)
    x0 = (nova.width - largura) // 2
    y0 = (nova.height - altura) // 2
    nova = nova.crop((x0, y0, x0 + largura, y0 + altura))
    camada = Image.new("RGB", (largura, altura), canais(cor_fundo))
    # mascara: opacidade da cor de 0,93 (esquerda) a 0,45 (direita)
    mascara = Image.new("L", (largura, 1))
    mascara.putdata([int(237 - (237 - 115) * x / max(1, largura - 1))
                     for x in range(largura)])
    mascara = mascara.resize((largura, altura))
    return Image.composite(camada, nova, mascara)
