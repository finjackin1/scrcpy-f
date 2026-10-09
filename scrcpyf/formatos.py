"""
FORMATO E RESOLUCAO DO APP EM JANELA (r184, pedido dele 25/set/2026).

Substitui o "modo jogo" (que so seguia o monitor a risca) por duas escolhas
por app: o FORMATO da tela virtual (celular -- o padrao, primeiro --, 4:3,
16:9 ou 21:9) e a RESOLUCAO (celular = a do aparelho, ou 2160p a 480p).
(r185, pedido dele: saiu o "automatico"; "celular" e o padrao nos dois.) So aparecem as
resolucoes que o CODIFICADOR DE VIDEO do celular aguenta naquele formato
(lido dos media_codecs*.xml do aparelho; sem isso, a tela do celular manda).

- celular: em pe, na proporcao da tela do aparelho (guardado como "").
- a densidade da tela virtual acompanha a resolucao (o app fica com a
  mesma cara, so mais ou menos nitido).
"""

from __future__ import annotations

import re

PADRAO = ""                 # = o do celular
CELULAR = "celular"         # nome antigo do mesmo "celular"
FORMATOS = [(PADRAO, "celular"), ("4:3", "4:3"), ("16:9", "16:9"),
            ("21:9", "21:9")]
RESOLUCOES = [2160, 1440, 1080, 720, 480]

# Larguras (tela deitada) de cada formato, nos valores de mercado. O 854
# vira 856 por dentro: o codificador quer multiplo de 8.
LARGURAS = {
    "4:3": {2160: 2880, 1440: 1920, 1080: 1440, 720: 960, 480: 640},
    "16:9": {2160: 3840, 1440: 2560, 1080: 1920, 720: 1280, 480: 856},
    "21:9": {2160: 5120, 1440: 3440, 1080: 2560, 720: 1680, 480: 1120},
}


def _oito(v: float) -> int:
    return max(8, int(round(v / 8.0)) * 8)


def e_celular(formato) -> bool:
    return formato in (None, PADRAO, CELULAR) or formato not in LARGURAS


def rotulo(formato: str) -> str:
    return "celular" if e_celular(formato) else formato


def rotulos_de_resolucao(lista) -> list:
    return [(PADRAO, "celular")] + [(p, "%dp" % p) for p in lista]


def tela_do_celular(cel: dict):
    """(curto, longo) da tela do celular, ou None."""
    t = (cel or {}).get("tela_cel")
    if t and len(t) == 2 and t[0] > 0 and t[1] > 0:
        return (min(t), max(t))
    return None


def limite(cel: dict):
    """(longo, curto) maximos que o celular transmite, ou None."""
    lim = (cel or {}).get("limite_video")
    if lim and len(lim) == 2 and lim[0] > 0 and lim[1] > 0:
        return (max(lim), min(lim))
    t = tela_do_celular(cel)
    return (t[1], t[0]) if t else None


def tamanho(formato: str, p: int, cel: dict):
    """(largura, altura) da tela virtual; None = nao da para calcular."""
    if formato in LARGURAS:
        return (LARGURAS[formato][p], p)
    if e_celular(formato):
        t = tela_do_celular(cel)
        if not t:
            return None
        return (_oito(p), _oito(p * t[1] / float(t[0])))       # em pe
    return None


def cabe(l: int, a: int, cel: dict) -> bool:
    lim = limite(cel)
    if not lim:
        return True                 # sem saber, nao corta nada
    return max(l, a) <= lim[0] and min(l, a) <= lim[1]


def possiveis(formato: str, cel: dict) -> list:
    """As resolucoes deste formato que o celular aguenta (maior primeiro)."""
    saida = []
    for p in RESOLUCOES:
        t = tamanho(formato, p, cel)
        if t is None or cabe(t[0], t[1], cel):
            saida.append(p)
    return saida or [RESOLUCOES[-1]]


def densidade(p: int, cel: dict):
    """Densidade da tela virtual na resolucao p (mesma cara do celular)."""
    t = tela_do_celular(cel)
    dpi = (cel or {}).get("dpi")
    if not t or not dpi:
        return None
    return max(72, int(round(dpi * p / float(t[0]))))


# ============================================================================
# (07/out, pedido dele) MODO DAS JANELAS DOS APPS: "pc" (de fabrica) ou
# "celular".
#
# - celular: como sempre -- o formato, a resolucao e a densidade do aparelho.
# - pc: tela virtual 16:9 EM PE com densidade de TABLET. O que faz um app
#   mostrar o layout de tablet e a "largura minima" da tela em dp (>= 600),
#   e dp = px * 160 / dpi: em 720 x 1280 com 192 dpi a tela tem 600 dp, como
#   um tablet (o DeX faz o mesmo no monitor). No Android 16 os apps novos nao
#   travam mais a orientacao em tela >= 600 dp (enchem a tela); os JOGOS sao
#   a excecao e ficariam pequenos com tarja. Esses o programa reconhece pela
#   forma da janela do app e reabre a tela deitada (16:9), guardando a
#   escolha para a proxima vez (apps["orientacao"]).
# ============================================================================

MODOS = [("pc", "pc / tablet"), ("celular", "celular")]
MODO_PADRAO = "pc"
# Tamanho dos itens no modo pc = a largura minima da tela em dp. 600 e o
# minimo do layout de tablet (letra maior); mais dp = itens menores.
ITENS = [("normal", "normal"), ("compacto", "compacto"), ("denso", "denso")]
DP_DOS_ITENS = {"normal": 600, "compacto": 720, "denso": 840}
ITENS_PADRAO = "normal"
RESOLUCOES_PC = [720, 1080, 1440]
RESOLUCAO_PC_PADRAO = 720


# (07/out, pedido dele) A ORIENTACAO tambem se escolhe: automatica (o
# programa reconhece, como acima), em pe ou deitada. Vale nos dois modos.
AUTO = "auto"
FORMAS = [(AUTO, "automática"), ("em_pe", "em pé"), ("deitado", "deitada")]


def forma_de(deste: dict, apps: dict) -> str:
    f = (deste or {}).get("forma") or (apps or {}).get("forma") or AUTO
    return f if f in dict(FORMAS) else AUTO


def modo_de(deste: dict, apps: dict) -> str:
    """O modo que vale para o app: o dele, senao o de todos, senao pc."""
    m = (deste or {}).get("modo") or (apps or {}).get("modo") or MODO_PADRAO
    return m if m in dict(MODOS) else MODO_PADRAO


def possiveis_pc(cel: dict) -> list:
    """As resolucoes do modo pc que o codificador do celular aguenta."""
    saida = [p for p in RESOLUCOES_PC
             if cabe(LARGURAS["16:9"][p], p, cel)]
    return saida or [RESOLUCOES_PC[0]]


def tela_pc(p: int, deitado: bool, itens: str, largura_dp: int = 0):
    """(largura, altura, dpi) da tela virtual do modo pc. (08/out)
    `largura_dp` = a largura do layout de tablet do app (a analise), no
    lugar dos itens. A densidade SEMPRE sai da resolucao: dpi = p * 160 / dp
    (o elemento tem o mesmo tamanho em qualquer resolucao)."""
    longo = LARGURAS["16:9"].get(p) or _oito(p * 16 / 9.0)
    dp = largura_dp if largura_dp and largura_dp >= 320 else \
        (DP_DOS_ITENS.get(itens) or DP_DOS_ITENS[ITENS_PADRAO])
    # para BAIXO: arredondar para cima deixava a largura em 599 dp e o app
    # mostrava a tela de celular (o limite do tablet e >= 600)
    dpi = max(72, int(p * 160.0 / dp))
    return ((longo, p, dpi) if deitado else (p, longo, dpi))


# (08/out/2026, pedido dele: "ambos vao definir a dpi com base na resolucao
# selecionada pro app abrir com a interface adaptada") A TELA VIRTUAL DE
# QUALQUER APP sai de tres coisas: o MODO, a RESOLUCAO (o nivel: 540, 720 ou
# 1080 de lado curto) e a ORIENTACAO. A densidade SEMPRE sai da resolucao:
# - pc / tablet: 16:9 (960x540, 1280x720, 1920x1080) com a largura minima de
#   TABLET (600 dp): dpi = p * 160 / 600 -> 144, 192, 288. Deitado, a janela
#   tem 1067 dp de largura (o tablet deitado: duas colunas onde o app tem).
# - celular: a proporcao da tela do aparelho com a MESMA largura em dp dele
#   (o S22 tem 384): dpi = dpi do celular * p / lado curto -> 225, 300, 450.
# Arredondado para BAIXO: para cima a largura caia abaixo do limite.
TABLET_DP = 600
P_DOS_NIVEIS = (1080, 720, 540)


TAMANHOS = {"menor": 0.9, "normal": 1.0, "maior": 1.15, "bem_maior": 1.3}


def tela_app(modo: str, p: int, deitado: bool, cel: dict,
             largura_dp: int = 0, escala: float = 1.0):
    """(largura, altura, dpi, p usado). Se o codificador do celular nao
    aguenta o tamanho, desce para o nivel de baixo que cabe. `largura_dp` =
    a largura do tablet do app (a verificacao; >= 600), no modo pc.
    `escala` (08/out, pedido dele): o "tamanho nos apps" -- multiplica o dpi
    (elementos maiores/menores) em qualquer resolucao."""
    l, a, dpi, pp = _tela_app(modo, p, deitado, cel, largura_dp)
    return l, a, max(72, int(dpi * (escala or 1.0))), pp


def _tela_app(modo: str, p: int, deitado: bool, cel: dict,
              largura_dp: int = 0):
    dp = largura_dp if largura_dp and largura_dp >= TABLET_DP else TABLET_DP
    for pp in [p] + [x for x in P_DOS_NIVEIS if x < p]:
        if modo == "pc":
            longo = LARGURAS["16:9"].get(pp) or _oito(pp * 16 / 9.0)
            curto = pp
            dpi = max(72, int(pp * 160.0 / dp))
        else:
            t = tela_do_celular(cel)
            dpi_cel = (cel or {}).get("dpi")
            if t:
                longo = _oito(pp * t[1] / float(t[0]))
            else:
                longo = _oito(pp * 19.5 / 9.0)
            curto = _oito(pp)
            if t and dpi_cel:
                dpi = max(72, int(dpi_cel * pp / float(t[0])))
            else:
                dpi = max(72, int(pp * 160.0 / 384))
        l, a = (longo, curto) if deitado else (curto, longo)
        if cabe(l, a, cel) or pp == P_DOS_NIVEIS[-1]:
            return l, a, dpi, pp
    return l, a, dpi, pp


def do_monitor(l: int, a: int) -> str:
    """O formato da lista mais perto do monitor (para a conversao)."""
    r = max(l, a) / float(max(1, min(l, a)))
    return min(("4:3", "16:9", "21:9"),
               key=lambda f: abs(r - LARGURAS[f][1080] / 1080.0))


def ler_limite_do_codificador(texto: str):
    """
    Dos media_codecs*.xml (so as linhas <MediaCodec, <Type, <Limit size,
    </MediaCodec): o maior "size" dos CODIFICADORES h264. (longo, curto)
    ou None.
    """
    melhor = None
    nome, tipo, dentro = "", "", False
    for linha in texto.splitlines():
        s = linha.strip()
        m = re.search(r'<MediaCodec\b[^>]*name="([^"]+)"', s)
        if m:
            nome, dentro = m.group(1).lower(), True
            t = re.search(r'type="([^"]+)"', s)
            tipo = t.group(1).lower() if t else ""
            continue
        if "</MediaCodec" in s:
            dentro = False
            continue
        if not dentro:
            continue
        t = re.search(r'<Type\b[^>]*name="([^"]+)"', s)
        if t:
            tipo = t.group(1).lower()
            continue
        m = re.search(r'<Limit\b[^>]*name="size"[^>]*max="(\d+)x(\d+)"', s)
        if m and tipo == "video/avc" and ("enc" in nome):
            a, b = int(m.group(1)), int(m.group(2))
            par = (max(a, b), min(a, b))
            if melhor is None or par[0] * par[1] > melhor[0] * melhor[1]:
                melhor = par
    return melhor


def migrar(apps: dict, formato_monitor: str) -> bool:
    """
    Marcas antigas -> formato. "jogo: True" e "tela: pc" viram o formato do
    monitor; "jogo: False" vira celular (o padrao, nada guardado); a fileira
    "resolucao" antiga do app sai (agora e a resolucao da tela). (r185) Uma
    vez so: os jogos que o celular tinha detectado (e que abriam no formato
    do monitor pelo "automatico") ficam com o formato do monitor guardado.
    True = mudou algo.
    """
    mudou = False
    if apps.get("formato") == CELULAR:
        apps.pop("formato")
        mudou = True
    if apps.get("formatos_v") not in (2, 3):
        por = apps.setdefault("por_app", {})
        for pac in apps.get("jogos") or []:
            conf = por.setdefault(pac, {})
            if isinstance(conf, dict) and conf.get("jogo") is not False \
                    and not conf.get("formato") and conf.get("tela") != \
                    "celular":
                conf["formato"] = formato_monitor
        apps.pop("jogos", None)
        apps["formatos_v"] = 2
        mudou = True
    if apps.get("tela") == "pc" and not apps.get("formato") and \
            apps.get("formatos_v") != 3:
        apps["formato"] = formato_monitor
    if "tela" in apps:
        apps.pop("tela")
        mudou = True
    for conf in (apps.get("por_app") or {}).values():
        if not isinstance(conf, dict):
            continue
        antes = dict(conf)
        tela = conf.pop("tela", None)
        jogo = conf.pop("jogo", None)
        if not conf.get("formato") and (tela == "pc" or jogo is True):
            conf["formato"] = formato_monitor
        if conf.get("formato") == CELULAR:
            conf.pop("formato")
        fino = conf.get("video_fino")
        if isinstance(fino, dict) and "resolucao_max" in fino:
            fino.pop("resolucao_max")
            if not fino:
                conf.pop("video_fino")
        if conf != antes:
            mudou = True
    por = apps.get("por_app") or {}
    for pac in [k for k, v in por.items() if not v]:
        por.pop(pac)
    if migrar_modo(apps):
        mudou = True
    return mudou


def migrar_modo(apps: dict) -> bool:
    """(07/out) O formato saiu (virou o modo pc/celular). Uma vez: o app que
    tinha formato deitado (4:3, 16:9, 21:9) fica no modo pc (o de fabrica)
    ja sabido DEITADO; a resolucao dele vira a do modo pc se for uma delas.
    O formato geral sai (o modo de fabrica e o pc). True = mudou algo."""
    if apps.get("formatos_v") == 3:
        return False
    apps.pop("formato", None)
    orient = apps.setdefault("orientacao", {})
    por = apps.get("por_app") or {}
    for pac, conf in list(por.items()):
        if not isinstance(conf, dict):
            continue
        fmt = conf.pop("formato", None)
        if fmt in LARGURAS:
            orient[pac] = "deitado"
            res = conf.pop("resolucao", None)
            if res in RESOLUCOES_PC:
                conf["res_pc"] = res
        if not conf:
            por.pop(pac)
    if not orient:
        apps.pop("orientacao", None)
    apps["formatos_v"] = 3
    return True
