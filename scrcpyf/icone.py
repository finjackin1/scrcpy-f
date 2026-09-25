"""
O icone da bandeja, desenhado -- nao um arquivo de imagem.

POR QUE DESENHAR EM VEZ DE CARREGAR UM .ICO
--------------------------------------------
O icone precisa MOSTRAR o estado: parado, espelhando ou tocando som. Tres
imagens prontas seriam tres arquivos para manter em sincronia com o tema, e o
tom teria que ser reeditado a mao a cada ajuste de cor. Desenhado, ele
acompanha o token sozinho e escala sem borrar.

O que aparece e sempre a mesma silhueta de celular. O que muda e o preenchimento
da tela e o que ha ao lado:

    parado       contorno apagado, tela vazia
    espelhando   contorno e tela no acento -- a imagem esta indo pro PC
    audio        contorno no acento e duas ondas saindo do aparelho
    extensao     contorno no acento e uma seta entrando nele pela esquerda --
                 o mouse do PC indo para o celular
"""

from __future__ import annotations

from . import tema

# Desenhado grande e reduzido pelo Windows: em 64 as bordas ficam limpas
# depois da reducao para 16 ou 24 da bandeja.
LADO = 64



def gravar_para_janela(pasta, scrcpy_exe=None) -> "object | None":
    """
    (r158) A PASTA do icone da janela do espelhamento (e o padrao dos apps
    sem icone), para o scrcpy usar no lugar do robo verde dele.

    O scrcpy 4.0 le SCRCPY_ICON_DIR -- uma pasta com "scrcpy.png" (a antiga
    SCRCPY_ICON_PATH ele ignora: foi por isso que o icone nunca pegou;
    achado nas strings do exe, sonda_icone de 25/set/2026). Fica em
    dados\\janelas\\icones\\_scrcpyf. Nunca quebra a partida: falhou, None.

    Uma vez por execucao (r139): a cor do tema so muda entre execucoes.
    """
    try:
        from pathlib import Path
        pasta_icone = Path(pasta) / "janelas" / "icones" / "_scrcpyf"
        caminho = pasta_icone / "scrcpy.png"
        if _JA_GRAVADO.get(str(caminho)) and caminho.exists():
            return pasta_icone
        pasta_icone.mkdir(parents=True, exist_ok=True)
        desenhar("jogo").resize((256, 256)).save(caminho)
        if scrcpy_exe is not None:
            import shutil
            desligado = Path(scrcpy_exe).parent / "disconnected.png"
            if desligado.exists():
                shutil.copy2(desligado, pasta_icone / "disconnected.png")
        _JA_GRAVADO[str(caminho)] = True
        return pasta_icone
    except Exception:
        return None


_JA_GRAVADO: dict = {}


VERDE = "#57C27A"       # o mesmo verde do nome pareado na janela


def desenhar(estado: str = "parado"):
    """Devolve a imagem do icone para o estado dado (Pillow `Image`)."""
    from PIL import Image, ImageDraw

    imagem = Image.new("RGBA", (LADO, LADO), (0, 0, 0, 0))
    lapis = ImageDraw.Draw(imagem)

    # "+par" = celular pareado: a borda do aparelho fica verde (pedido dele,
    # 23/set/2026); sem celular, cinza. O de dentro segue o modo.
    estado, _, marca = estado.partition("+")
    ativo = estado in ("jogo", "audio", "extensao")
    cor = tema.canais(tema.ACENTO if ativo else tema.TEXTO_APAGADO)
    borda = tema.canais(VERDE) if marca == "par" else cor
    traco = 4

    # O corpo do celular. Deslocado para a esquerda no modo audio, para caber
    # as ondas sem encolher o aparelho.
    esquerda = {"audio": 8, "extensao": 26}.get(estado, 14)
    corpo = (esquerda, 8, esquerda + 30, 56)
    lapis.rounded_rectangle(corpo, radius=6, outline=borda, width=traco)

    if estado == "jogo":
        # Tela acesa: o retangulo de dentro cheio, com uma folga de um traco.
        lapis.rounded_rectangle(
            (corpo[0] + traco + 2, corpo[1] + traco + 2,
             corpo[2] - traco - 2, corpo[3] - traco - 2),
            radius=3, fill=cor,
        )
    elif estado == "extensao":
        # Seta da esquerda para o aparelho: haste e ponta, no traco do corpo.
        lapis.line((2, 32, esquerda - 5, 32), fill=cor, width=traco)
        lapis.line((esquerda - 13, 24, esquerda - 5, 32, esquerda - 13, 40),
                   fill=cor, width=traco, joint="curve")
    elif estado == "audio":
        # Duas ondas a direita, a maior mais afastada -- som saindo do
        # aparelho. Arcos abertos, no mesmo traco do corpo.
        for raio, largura in ((12, 3), (22, 3)):
            caixa = (corpo[2] - raio, 32 - raio, corpo[2] + raio, 32 + raio)
            lapis.arc(caixa, start=-50, end=50, fill=cor, width=largura)

    return imagem
