"""
ANALISE DA INTERFACE DE CADA APP (08/out/2026, pedido dele: "verifique se os
apps tem uma interface de tablet ... qual dpi/resolucao a interface aplica"
e "garanta que a config vai funcionar, pegue informacoes so de lugares 100%
confiaveis").

A fonte e o PROPRIO APP instalado no celular (nao existe base confiavel na
internet com isso): todo APK traz a tabela de recursos (`resources.arsc`), e
cada tela (layout) vem marcada com os tamanhos para os quais ela foi feita --
"largura minima 600 dp" (sw600dp, o tablet), "largura 840 dp" (w840dp, a tela
grande de duas colunas), "deitado" (land). O shell le o APK (`unzip -p`) e a
tabela e lida aqui, sem baixar nada.

Cuidados:
- bibliotecas (AppCompat, Material...) tambem trazem algumas telas sw600dp
  (o snackbar, por exemplo): as de nome de biblioteca nao contam;
- apps de Compose desenham a tela em codigo e se adaptam sozinhos a largura:
  quase sem layouts na tabela -> "se adapta";
- so a tela de layout conta (valores e dimensoes sozinhos nao fazem tablet).

Formato do ResTable_config (frameworks/base ResourceTypes.h): size 0,
imsi 4, locale 8, screenType 12 (orientation 12, touchscreen 13, density 14),
input 16, screenSize 20, version 24, screenConfig 28 (screenLayout 28,
uiMode 29, smallestScreenWidthDp 30), screenSizeDp 32 (screenWidthDp 32,
screenHeightDp 34).
"""

from __future__ import annotations

import struct

TABLET_DP = 600                 # a largura minima do layout de tablet
# Prefixos das telas de bibliotecas (nao sao do app)
DE_BIBLIOTECA = ("abc_", "design_", "mtrl_", "material_", "m3_",
                 "notification_", "select_dialog", "support_", "exo_",
                 "preference", "browser_actions", "custom_dialog",
                 "com_facebook", "common_google", "fallback_", "test_",
                 "leak_canary", "mr_", "ime_", "media", "cast_", "places_",
                 "lb_", "fui_", "firebase", "admob", "gms_", "wallet_",
                 "image_frame", "ucrop", "zxing", "stripe", "braze",
                 "com_appboy", "appboy", "onesignal", "picker_", "sesl_",
                 "spen_", "tw_", "dialog_", "datepicker", "time_picker",
                 "date_picker", "navigation_", "bottom_sheet")
# Resultado
TABLET, SEM_TABLET, SE_ADAPTA = "tablet", "sem_tablet", "se_adapta"


def _string_pool(dados: bytes, ini: int):
    """Funcao (indice -> texto) de um ResStringPool que comeca em `ini`."""
    _t, hsz, _sz = struct.unpack_from("<HHI", dados, ini)
    n, _estilos, flags, comeco, _ = struct.unpack_from("<IIIII", dados, ini + 8)
    utf8 = bool(flags & 0x100)
    desloc = ini + hsz
    base = ini + comeco

    def ler(i: int) -> str:
        if i < 0 or i >= n:
            return ""
        p = base + struct.unpack_from("<I", dados, desloc + 4 * i)[0]
        try:
            if utf8:
                c = dados[p]
                p += 2 if c & 0x80 else 1          # tamanho em utf-16
                c = dados[p]
                if c & 0x80:
                    c = ((c & 0x7F) << 8) | dados[p + 1]
                    p += 2
                else:
                    p += 1
                return dados[p:p + c].decode("utf-8", "replace")
            c = struct.unpack_from("<H", dados, p)[0]
            p += 2
            if c & 0x8000:
                c = ((c & 0x7FFF) << 16) | struct.unpack_from("<H", dados, p)[0]
                p += 2
            return dados[p:p + 2 * c].decode("utf-16-le", "replace")
        except (IndexError, struct.error):
            return ""
    return ler


def ler_tabela(dados: bytes) -> dict:
    """Do resources.arsc: {"layouts": total de telas de layout do app,
    "telas": [(sw, w, orientacao, nome)] das telas marcadas com tamanho}."""
    telas = []
    total_layout = 0
    if len(dados) < 12:
        return {"layouts": 0, "telas": []}
    _t, hsz, _sz = struct.unpack_from("<HHI", dados, 0)
    i, n = hsz, len(dados)
    tipos = chaves = None
    while i + 8 <= n:
        t, hs, sz = struct.unpack_from("<HHI", dados, i)
        if sz < 8 or i + sz > n:
            break
        if t == 0x0200:                           # ResTable_package
            tipo_str, _ult_t, chave_str = struct.unpack_from(
                "<III", dados, i + 8 + 4 + 256)
            tipos = _string_pool(dados, i + tipo_str)
            chaves = _string_pool(dados, i + chave_str)
            i += hs                               # desce para os filhos
            continue
        if t == 0x0201 and tipos is not None:     # ResTable_type
            tid, flags = dados[i + 8], dados[i + 9]
            qtd, comeco = struct.unpack_from("<II", dados, i + 12)
            if tipos(tid - 1) == "layout":
                c = i + 20
                csz = struct.unpack_from("<I", dados, c)[0]
                orient = dados[c + 12] if csz > 12 else 0
                sw = struct.unpack_from("<H", dados, c + 30)[0] \
                    if csz >= 32 else 0
                w = struct.unpack_from("<H", dados, c + 32)[0] \
                    if csz >= 34 else 0
                esparso = bool(flags & 0x01)
                off16 = bool(flags & 0x02)
                tab = i + hs
                for k in range(qtd):
                    if esparso:
                        _idx, meio = struct.unpack_from("<HH", dados,
                                                        tab + 4 * k)
                        off = meio * 4
                    elif off16:
                        off = struct.unpack_from("<H", dados, tab + 2 * k)[0]
                        if off == 0xFFFF:
                            continue
                        off *= 4
                    else:
                        off = struct.unpack_from("<I", dados, tab + 4 * k)[0]
                        if off == 0xFFFFFFFF:
                            continue
                    e = i + comeco + off
                    if e + 8 > n:
                        continue
                    chave = struct.unpack_from("<I", dados, e + 4)[0]
                    nome = chaves(chave) if chaves else ""
                    if nome.startswith(DE_BIBLIOTECA):
                        continue
                    if not sw and not w and not orient:
                        total_layout += 1
                    elif sw or w:
                        telas.append((sw, w, orient, nome))
        i += sz
    return {"layouts": total_layout, "telas": telas}


def conclusao(tabela: dict) -> dict:
    """{"resultado", "dp" (a largura do layout de tablet), "dp_max",
    "deitado" (o tablet do app e so deitado), "telas" (quantas)}."""
    telas = [(sw, w, o) for sw, w, o, _n in tabela.get("telas") or []
             if max(sw, w) >= TABLET_DP]
    if len(telas) >= 2 or (telas and tabela.get("layouts", 0) < 40):
        larguras = sorted({max(sw, w) for sw, w, _o in telas})
        # a largura "de entrada" do tablet: a menor >= 600 que o app usa
        dp = larguras[0]
        so_deitado = all(o == 2 for _sw, _w, o in telas)
        return {"resultado": TABLET, "dp": dp, "dp_max": larguras[-1],
                "deitado": so_deitado, "telas": len(telas)}
    if tabela.get("layouts", 0) < 15:
        # quase sem layouts: tela desenhada em codigo (Compose, motor de
        # jogo, web) -- se adapta a largura sozinha
        return {"resultado": SE_ADAPTA, "dp": 0, "dp_max": 0,
                "deitado": False, "telas": 0}
    return {"resultado": SEM_TABLET, "dp": 0, "dp_max": 0, "deitado": False,
            "telas": 0}


# -- (08/out, relato dele: apps "de tablet" abrindo com a tela de celular
# esticada e deitada) A CONFERENCIA DE VERDADE: a tabela do APK so diz que
# EXISTEM telas de tablet (as vezes so um dialogo ou um ajuste). O programa
# abre o app escondido (tela virtual sem janela) no formato de celular e no
# de tablet e compara as telas que o Android montou (`dumpsys activity top`:
# as views com id e o lugar de cada uma). Medido no S22 (37 apps): o
# WhatsApp ganha nav_rail + conversa ao lado; Mercado Livre, iFood, Reddit,
# Play... montam a MESMA tela nos dois.
SIM, NAO, NAO_SEI = "sim", "nao", "?"
# pedacos de id que so existem em tela grande
IDS_DE_TABLET = ("tablet", "rail", "pane", "split", "large_screen",
                 "left_nav", "side_tab", "sidebar", "side_nav", "dual",
                 "two_col", "master", "detail", "expanded", "drawer_panel",
                 "scientific")
_LINHA_VIEW = None


def pecas_da_tela(texto: str, pacote: str, largura: int, altura: int) -> dict:
    """Do `dumpsys activity top`, a atividade do `pacote`: {"ids" visiveis,
    "colunas" (dois paineis grandes lado a lado: a tela de tablet de duas
    partes), "views", "cheia" (a janela do app enche a largura da tela; sem
    isso o app ficou com tarja -- o Facebook fica 405 de 1280)}. Vale com o
    celular dormindo: a tela e montada no tamanho certo ao abrir (so o
    conteudo da internet nao chega)."""
    import re
    global _LINHA_VIEW
    if _LINHA_VIEW is None:
        _LINHA_VIEW = re.compile(
            r"^(\s*)\S+\{[0-9a-f]+ (\S)\S* \S+ (-?\d+),(-?\d+)-(-?\d+),(-?\d+)"
            r"(?: #[0-9a-f]+ ([\w.]+:id/(\w+)))?")
    blocos = re.split(r"\n(?=TASK )", texto or "")
    bloco = next((b for b in blocos if ("ACTIVITY " + pacote + "/") in b), "")
    vazio = {"ids": set(), "colunas": False, "views": 0, "cheia": True,
             "achou": False}
    if not bloco:
        return vazio
    # so a 1a hierarquia (a da atividade de cima)
    ini = bloco.find("View Hierarchy:")
    linhas = bloco[ini:].splitlines()[1:] if ini >= 0 else []
    ids, paineis, views, geo = set(), [], 0, {}
    cheia = None
    pilha = []                       # (recuo, x, y, visivel)
    for linha in linhas:
        m = _LINHA_VIEW.match(linha)
        if not m:
            if linha.strip() and not linha.startswith(" " * 6):
                break                # acabou a hierarquia
            continue
        recuo = len(m.group(1))
        while pilha and pilha[-1][0] >= recuo:
            pilha.pop()
        px, py, pv = pilha[-1][1:] if pilha else (0, 0, True)
        l, t, r, b = (int(m.group(i)) for i in (3, 4, 5, 6))
        x0, y0, x1, y1 = px + l, py + t, px + r, py + b
        if cheia is None:            # a raiz: a janela do app
            if x1 - x0 <= 0:
                # (YouTube com o celular dormindo) janela ainda sem tamanho:
                # a tela nao foi montada
                break
            cheia = x1 - x0 >= 0.9 * largura
        # a raiz (DecorView) vem "I" com o celular apagado: nao conta
        vis = pv and (m.group(2) == "V" or not pilha)
        pilha.append((recuo, x0, y0, vis))
        if not vis or x1 <= 0 or y1 <= 0 or x0 >= largura or y0 >= altura:
            continue
        views += 1
        if m.group(8):
            ids.add(m.group(8))
            # o lugar na largura (fracao da tela), o 1o de cada id
            geo.setdefault(m.group(8), (max(0, x0) / float(largura),
                                        min(largura, x1) / float(largura)))
        # painel: dentro da tela na largura, >= 20% de largo, >= 50% de alto
        if x0 >= -2 and x1 <= largura + 2 and \
                0.2 * largura <= x1 - x0 <= 0.8 * largura and \
                min(y1, altura) - max(y0, 0) >= 0.5 * altura:
            paineis.append((x0, y0, x1, y1))
    colunas = any(a[2] <= b[0] + 4 and
                  min(a[3], b[3]) - max(a[1], b[1]) >= 0.5 * altura
                  for a in paineis for b in paineis if a is not b)
    return {"ids": ids, "colunas": colunas, "views": views, "geo": geo,
            "cheia": cheia is not False, "achou": cheia is not None}


def _redistribuiu(cel: dict, tab: dict) -> float:
    """Dos ids grandes (>= 30% da largura em algum dos dois), a fracao que
    mudou de lugar/largura na tela (> 25% da largura): a tela de celular so
    esticada fica igual em fracao; a que se adapta (painel ao lado, coluna
    no meio) muda."""
    gc, gt = cel.get("geo") or {}, tab.get("geo") or {}
    grandes = [i for i in set(gc) & set(gt)
               if max(gc[i][1] - gc[i][0], gt[i][1] - gt[i][0]) >= 0.3]
    if not grandes:
        return 0.0
    mudou = sum(1 for i in grandes
                if abs(gc[i][0] - gt[i][0]) > 0.25 or
                abs(gc[i][1] - gt[i][1]) > 0.25)
    return mudou / float(len(grandes))


def conferencia(cel: dict, tab: dict) -> str:
    """SIM (o app monta outra tela no tablet), NAO (a mesma do celular, ou
    com tarja) ou NAO_SEI (nao abriu, ou a tela e desenhada sem views com
    id: Compose, Flutter, web)."""
    if tab.get("achou") and not tab["cheia"]:
        return NAO                   # tarja: o app nao enche a tela
    if not tab.get("achou") or not cel.get("achou"):
        return NAO_SEI
    ids_c, col_c = cel["ids"], cel["colunas"]
    ids_t, col_t = tab["ids"], tab["colunas"]
    so_tab = ids_t - ids_c
    if col_t and not col_c:
        return SIM
    if any(p in i.lower() for i in so_tab for p in IDS_DE_TABLET):
        return SIM
    if _redistribuiu(cel, tab) >= 0.2:
        return SIM
    if len(ids_c) < 8 or len(ids_t) < 8:
        return NAO_SEI
    parecido = len(ids_c & ids_t) / float(len(ids_c | ids_t))
    if parecido >= 0.85:
        return NAO
    return SIM if parecido < 0.7 else NAO_SEI


def texto(analise: dict | None) -> str:
    """A frase curta da tela (com a fonte)."""
    if not analise:
        return ""
    r = analise.get("resultado")
    if r == TABLET and analise.get("real") == NAO:
        return ("as telas de tablet do app não aparecem ao abrir: mesma tela "
                "do celular (conferido abrindo o app)")
    if r == TABLET and analise.get("real") == NAO_SEI:
        return ("interface de tablet não confirmada ao abrir o app "
                "(tela desenhada sem peças com nome)")
    if r == TABLET and not analise.get("real"):
        return ("o app traz telas de tablet; falta conferir abrindo (feito "
                "sozinho com o celular acordado)")
    if r == TABLET:
        return "interface de tablet conferida abrindo o app (%d dp)" % (
            max(analise.get("dp") or 600,
                min(analise.get("dp_max") or 0, 840)))
    if r == SE_ADAPTA:
        return "a tela se adapta à largura sozinha (análise do app)"
    return "sem interface de tablet (análise do app)"
