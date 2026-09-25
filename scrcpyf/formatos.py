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
    if apps.get("formatos_v") != 2:
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
    if apps.get("tela") == "pc" and not apps.get("formato"):
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
    return mudou
