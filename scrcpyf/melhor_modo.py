"""
MELHOR MODO DE CADA APP (08/out/2026, pedido dele: "detectar se e melhor
mostrado (formato de tela, orientacao, resolucao, dpi, bitrate) ... e deteccao
de jogo, tudo automatizado, mas com a opcao de escolher cada um").

Os SINAIS vem do celular, uma vez por app/versao (guardados em
`<celular>\\sinais.json`):
- a lista de jogos do proprio Android (`dumpsys game`: o GameManager conhece
  os jogos instalados, mesmo os que nao declaram categoria -- o PUBG nao
  declara e esta la);
- a CATEGORIA do app (ApplicationInfo.category: manifesto, a do sistema ou a
  que a pessoa escolheu): 0 jogo, 1 audio, 2 video, 3 imagem, 4 social,
  5 noticias, 6 mapas, 7 produtividade;
- o MOTOR do jogo pelas bibliotecas (Unity, Unreal, Cocos, Godot).

A RECOMENDACAO (por que cada uma, pesquisado em 08/out):
- JOGO: modo celular, deitado. No Android 16 os apps em tela >= 600 dp
  (o modo pc) perdem a trava de orientacao e enchem a tela -- MENOS os jogos,
  que ficam com tarja; e jogo foi feito para a tela do celular. Quadros 60
  (o que a maioria roda; mais custa banda sem ganho) e taxa alta.
- VIDEO: modo pc deitado em 1080 (o video enche a janela) e taxa alta.
- O resto: o padrao de hoje (modo pc em pe, layout de tablet) -- nada muda.

Por cima de tudo, o que ELE escolheu no personalizado do app (`mesclar`):
o automatico so preenche o que ele nao escolheu.
"""

from __future__ import annotations

JOGO, VIDEO, COMUM = "jogo", "video", "comum"
TABLET_APP, CELULAR_APP = "tablet", "celular"      # (08/out) pela analise
NOMES = {JOGO: "jogo", VIDEO: "vídeo", COMUM: "app comum",
         TABLET_APP: "tablet", CELULAR_APP: "só celular"}

CATEGORIAS = {0: "jogo", 1: "áudio", 2: "vídeo", 3: "imagem", 4: "social",
              5: "notícias", 6: "mapas", 7: "produtividade"}
# Apps de video que nao declaram a categoria (YouTube e cia.). Comparados
# com os PEDACOS do pacote (08/out, teste real: "searcHBOx" do Google e
# "com.MAXmpz" do Poweramp casavam como substring).
DICAS_DE_VIDEO = ("youtube", "netflix", "primevideo", "avod", "disney",
                  "disneyplus", "twitch", "globoplay", "hbo", "hbomax",
                  "crunchyroll", "plutotv", "vlc", "mxtech", "paramount",
                  "starplus", "tubi", "kick")
FORA_DE_VIDEO = ("music", "creator", "studio")


def _pedacos(pacote: str) -> set:
    import re
    return {p for p in re.split(r"[._]", pacote.lower()) if p}
MOTORES = (("libunity", "Unity"), ("libil2cpp", "Unity"), ("libue4", "Unreal"),
           ("libunreal", "Unreal"), ("libcocos", "Cocos"),
           ("libgodot", "Godot"), ("libgdx", "libGDX"))

# O campo que ele escolhe por cima do automatico (o resto e escondido).
CAMPOS_JANELA = ("modo",)


def roteiro_de_leitura(pacotes) -> str:
    """O shell que le os sinais de `pacotes` numa conversa so. Saida:
    "@s <pacote>|<linha da categoria>|<biblioteca do motor>" por app e
    "@g <jogos do Android>" no fim."""
    lista = " ".join(p for p in pacotes if p and " " not in p and "'" not in p)
    libs = "|".join(m for m, _n in MOTORES)
    return (
        "for p in %s; do "
        "c=$(dumpsys package $p 2>/dev/null | grep -m1 'category='); "
        "a=$(pm path $p 2>/dev/null | head -1); a=${a#package:}; "
        "l=$(ls ${a%%/*}/lib/*/ 2>/dev/null | grep -i -m1 -E '%s'); "
        "echo \"@s $p|$c|$l\"; done; "
        "echo \"@g $(dumpsys game 2>/dev/null | grep -o 'Name:[^ ]*' | "
        "sort -u | tr '\\n' ' ')\"" % (lista, libs))


def _categoria(linha: str) -> int:
    """'category=manifest: 0, override: 0, by user: -1' -> a que vale:
    a da pessoa, senao a do sistema, senao a do manifesto; -1 = nenhuma."""
    import re
    valores = {}
    for nome, v in re.findall(r"(manifest|override|by user)\s*:\s*(-?\d+)",
                              linha or ""):
        valores[nome] = int(v)
    for nome in ("by user", "override", "manifest"):
        if valores.get(nome, -1) >= 0:
            return valores[nome]
    m = re.search(r"category=(-?\d+)", linha or "")
    return int(m.group(1)) if m else -1


def ler_saida(texto: str, versoes: dict) -> dict:
    """A saida do `roteiro_de_leitura` -> {pacote: sinal}. `versoes` =
    {pacote: versao} (a assinatura do cache), guardada no sinal."""
    jogos = set()
    sinais = {}
    for linha in (texto or "").splitlines():
        linha = linha.strip()
        if linha.startswith("@g "):
            jogos = {x[5:] for x in linha[3:].split() if x.startswith("Name:")}
        elif linha.startswith("@s "):
            partes = linha[3:].split("|")
            if len(partes) < 3 or not partes[0]:
                continue
            lib = partes[2].strip().lower()
            motor = next((n for m, n in MOTORES if lib.startswith(m)), "")
            sinais[partes[0]] = {"v": versoes.get(partes[0], ""),
                                 "cat": _categoria(partes[1]),
                                 "motor": motor}
    for p, s in sinais.items():
        s["jogo_android"] = p in jogos
    return sinais


def tipo_do_app(pacote: str, sinal: dict | None) -> tuple:
    """(tipo, porque) -- o porque e a frase curta que a tela mostra."""
    s = sinal or {}
    base = pacote.split("@")[0].lower()
    if s.get("jogo_android"):
        extra = " (%s)" % s["motor"] if s.get("motor") else ""
        return JOGO, "o android reconhece como jogo" + extra
    if s.get("cat") == 0:
        return JOGO, "o app se declara jogo"
    if s.get("motor") in ("Unity", "Unreal", "Godot", "Cocos"):
        return JOGO, "feito com o motor de jogo %s" % s["motor"]
    if s.get("cat") == 2:
        return VIDEO, "o app se declara de vídeo"
    pedacos = _pedacos(base)
    if pedacos & set(DICAS_DE_VIDEO) and not pedacos & set(FORA_DE_VIDEO):
        return VIDEO, "app de vídeo conhecido"
    cat = CATEGORIAS.get(s.get("cat", -1))
    return COMUM, ("app de %s" % cat) if cat else "app comum"


# (08/out, teste no S22 com fotos: o WhatsApp declara telas de tablet de 600
# a 840 dp e so usa o layout de tablet com a tela de >= 840 dp; em 600 ele
# mostra o de celular, em pe e deitado) A largura da tela virtual e a MAIOR
# largura de tablet que o app declara, com teto: alguns declaram 1200-1400
# (Gmail, Play, Maps, Spotify) e ai a letra ficaria minuscula. 840 dp e a
# largura "expandida" das diretrizes do Android (duas colunas).
TABLET_MAX_DP = 840


def largura_do_tablet(analise: dict) -> int:
    dp = int((analise or {}).get("dp") or 600)
    dp_max = int((analise or {}).get("dp_max") or dp)
    return max(dp, min(dp_max, TABLET_MAX_DP))


def recomendacao(pacote: str, sinal: dict | None, cel: dict,
                 conexao: str, analise: dict | None = None) -> dict:
    """{"tipo", "porque", "janela": {campo: valor}, "video": {campo: valor},
    "analise": a frase da analise do app (ou "")}. Vazio em janela/video =
    segue o padrao de hoje.

    (08/out, pedido dele) Com a ANALISE da interface (analise_app.py):
    - tem tablet: modo pc com a LARGURA do tablet do app (`sw_dp`: a
      densidade sai dela e da resolucao, dpi = resolucao * 160 / largura --
      o mesmo tamanho de elemento em qualquer resolucao) e deitado se o
      tablet dele e so deitado;
    - sem tablet: modo celular (a tela de celular dele, sem esticar);
    - se adapta: o padrao (modo pc)."""
    # (08/out, rework pedido dele) O MODO PC/TABLET so existe para o app que
    # a VERIFICACAO achou com tela de tablet (`pc`), e ai ele e o indicado
    # (na largura do tablet dele, `sw_dp`); sem tablet, nao verificado ou
    # "se adapta" = so o modo celular. Jogo: indicado celular. A imagem e o
    # som sao os do nivel (nada mais aqui). A orientacao e sempre automatica:
    # `forma_auto` e so o 1o palpite, conferido ao abrir.
    from . import analise_app
    tipo, porque = tipo_do_app(pacote, sinal)
    frase = analise_app.texto(analise)
    pc = (analise or {}).get("resultado") == analise_app.TABLET
    # (08/out, relato dele: apps "em modo tablet" abrindo com a tela de
    # celular mal dimensionada) a CONFERENCIA DE VERDADE (o app aberto
    # escondido na tela de tablet: `real`) manda mais que a tabela do APK:
    # so "sim" (outra tela no tablet) ou "?" (tela sem pecas com nome: fica a
    # tabela) liberam o modo pc; ainda nao conferido = celular
    # (08/out, relato dele: o WhatsApp travado no celular antes de ser
    # conferido) nao conferido = pc LIBERADO para ele escolher, mas o
    # indicado continua o celular ate a conferencia dizer "sim"
    real = (analise or {}).get("real")
    indicado_pc = pc and real in ("sim", "?")
    # (08/out, pedido dele: "remova a trava do modo tablet") o modo pc fica
    # LIBERADO em todo app (o DeepCine precisa da tela 16:9 para o video
    # encher o monitor); a verificacao so decide o INDICADO
    tem_tablet = pc
    pc = True
    # (08/out, pedido dele: "jogos nao sao detectados para modo pc/tablet")
    # jogo desenha a imagem sozinho em qualquer tamanho: o modo pc dele e a
    # tela 16:9 deitada, do formato do monitor (o indicado)
    if tipo == JOGO:
        janela = {"modo": "pc"}
        indicado_pc = True
    else:
        janela = {"modo": "pc" if indicado_pc else "celular"}
    if tem_tablet and tipo != JOGO:
        janela["sw_dp"] = largura_do_tablet(analise)
    if tipo in (JOGO, VIDEO) or (tem_tablet and analise.get("deitado")):
        # (08/out, teste real: o Mercado Livre tem telas de tablet deitado
        # mas TRAVA em pe) so o palpite: `_conferir_orientacao` corrige
        janela["forma_auto"] = "deitado"
    pc_indicado = indicado_pc
    if tipo == COMUM and pc_indicado:
        tipo = TABLET_APP
    elif tipo == COMUM and analise:
        tipo = CELULAR_APP
    return {"tipo": tipo, "porque": porque, "janela": janela, "pc": pc,
            "analise": frase}


def mesclar(deste: dict, rec: dict | None, modo_geral: str = "pc") -> dict:
    """A configuracao que vale para o app. MODO: o dele (se pc, so com o pc
    liberado), senao o geral -- e o geral "pc" so vale onde o app indica pc
    (`rec["janela"]["modo"]`). Sem recomendacao (DeX) = celular."""
    saida = dict(deste or {})
    rec = rec or {}
    j = rec.get("janela") or {}
    modo = saida.get("modo") or (
        "pc" if modo_geral == "pc" and j.get("modo") == "pc" else "celular")
    if modo == "pc" and not rec.get("pc"):
        modo = "celular"
    saida["modo"] = modo
    for campo in ("sw_dp", "forma_auto"):
        if j.get(campo):
            saida[campo] = j[campo]
    return saida


def resumo(rec: dict) -> str:
    """'pc / tablet indicado · layout de 600 dp' (o que a verificacao diz)."""
    j = rec.get("janela") or {}
    if not rec.get("pc"):
        return "só o modo celular"
    if j.get("modo") != "pc" and not j.get("sw_dp"):
        return "celular indicado · pc / tablet (16:9) disponível"
    partes = ["pc / tablet" + (" disponível" if j.get("modo") != "pc"
                               else " indicado")]
    if j.get("sw_dp"):
        partes.append("layout de %d dp" % j["sw_dp"])
    return " · ".join(partes)
