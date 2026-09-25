"""
Os monitores do PC e a "borda" onde o celular fica.

PIXEL DE VERDADE, NAO O DO TK
------------------------------
A janela (Tk) roda sem saber de escala de tela: com o Windows em 125%, ela
enxerga um monitor de 1920 como se tivesse 1536. Para a borda isso seria
desastre -- o vigia compararia a posicao do mouse numa medida com a borda
noutra, e a borda nunca seria alcancada. Por isso tudo aqui e perguntado com a
thread em modo "ciente de escala por monitor": sao os pixels reais, os mesmos
que o vigia usa.

O QUE E UMA BORDA
------------------
    {"monitor": "\\\\.\\DISPLAY2", "lado": "direita", "centro": 0.5,
     "tamanho": 0.5}

`lado` e um de esquerda/direita/cima/baixo. `centro` e `tamanho` sao fracoes
do comprimento daquele lado: o trecho que dispara a passagem para o celular e
o pedaco da borda onde o celular esta desenhado na tela de posicionamento --
como no arranjo de telas do proprio Windows.

LADO LIVRE
-----------
So vale lado que da para "fora": se outro monitor encosta naquele lado, o
mouse passa direto para ele e nunca para na borda. `lados_livres` diz quais
servem.
"""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager

log = logging.getLogger(__name__)

NO_WINDOWS = sys.platform == "win32"
LADOS = ("esquerda", "direita", "cima", "baixo")

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
_CIENTE_V2 = -4


@contextmanager
def pixels_reais():
    """
    Enquanto dura o bloco, ESTA THREAD enxerga pixels reais. Volta ao que era
    no fim. Em Windows antigo (sem a chamada), segue do jeito que der.
    """
    anterior = None
    if NO_WINDOWS:
        try:
            ctypes, user32, _p, _m = _api()
            anterior = user32.SetThreadDpiAwarenessContext(
                ctypes.c_void_p(_CIENTE_V2))
        except Exception as erro:
            log.debug("sem troca de escala na thread: %s", erro)
    try:
        yield
    finally:
        if anterior:
            try:
                ctypes, user32, _p, _m = _api()
                user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(anterior))
            except Exception:
                pass


def listar(reserva=None, estrito: bool = False) -> list[dict]:
    """
    Os monitores: [{"nome", "x", "y", "l", "a", "principal"}], em pixels reais.

    `reserva` e (largura, altura) para quando nao da para perguntar ao
    Windows (fora dele): vira um monitor so. Com `estrito`, falhar devolve
    lista VAZIA em vez da reserva -- e o que o vigia usa: um monitor
    inventado poria a borda num lugar onde ela nao existe.
    """
    if NO_WINDOWS:
        try:
            with pixels_reais():
                lista = _listar_windows()
            if lista:
                return lista
        except Exception as erro:
            log.warning("nao consegui listar os monitores: %s", erro)
        if estrito:
            return []
    l, a = reserva or (1920, 1080)
    return [{"nome": "PRINCIPAL", "x": 0, "y": 0, "l": int(l), "a": int(a),
             "principal": True}]


_API = None


def _api():
    """
    As chamadas deste modulo, montadas UMA vez e numa copia PROPRIA do
    user32. A copia importa: `ctypes.windll.user32` e um objeto so para o
    programa inteiro, e outro modulo declarando os tipos da mesma funcao de
    outro jeito (o `moldura.py` usa GetMonitorInfoW com outra estrutura), na
    hora errada, faria esta chamada falhar -- e a lista de monitores cairia no
    monitor de reserva, que e justamente o que nao pode acontecer com o vigia.
    """
    global _API
    if _API is not None:
        return _API
    import ctypes
    from ctypes import wintypes

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32)]

    user32 = ctypes.WinDLL("user32")
    PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.POINTER(wintypes.RECT), ctypes.c_void_p)
    user32.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                           PROC, ctypes.c_void_p]
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p,
                                       ctypes.POINTER(MONITORINFOEXW)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    _API = (ctypes, user32, PROC, MONITORINFOEXW)
    return _API


def _listar_windows() -> list[dict]:
    ctypes, user32, PROC, MONITORINFOEXW = _api()
    lista: list[dict] = []

    def cada(monitor, _hdc, _ret, _dado):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.rcMonitor
            lista.append({"nome": info.szDevice, "x": r.left, "y": r.top,
                          "l": r.right - r.left, "a": r.bottom - r.top,
                          "principal": bool(info.dwFlags & 1)})
        return True

    user32.EnumDisplayMonitors(None, None, PROC(cada), None)
    # Da esquerda para a direita, de cima para baixo: a ordem em que a
    # pessoa numera os monitores de cabeca.
    lista.sort(key=lambda m: (m["x"], m["y"]))
    return lista


# ---------------------------------------------------------------------------
# Geometria da borda
# ---------------------------------------------------------------------------

def _encosta(m: dict, lado: str, outro: dict) -> bool:
    """O `outro` monitor encosta no `lado` de `m`, com algum trecho em comum?"""
    if lado == "direita":
        return (outro["x"] == m["x"] + m["l"]
                and outro["y"] < m["y"] + m["a"] and outro["y"] + outro["a"] > m["y"])
    if lado == "esquerda":
        return (outro["x"] + outro["l"] == m["x"]
                and outro["y"] < m["y"] + m["a"] and outro["y"] + outro["a"] > m["y"])
    if lado == "baixo":
        return (outro["y"] == m["y"] + m["a"]
                and outro["x"] < m["x"] + m["l"] and outro["x"] + outro["l"] > m["x"])
    return (outro["y"] + outro["a"] == m["y"]
            and outro["x"] < m["x"] + m["l"] and outro["x"] + outro["l"] > m["x"])


def lados_livres(monitores: list[dict]) -> list[tuple[int, str]]:
    """(indice do monitor, lado) de cada lado que da para fora."""
    livres = []
    for i, m in enumerate(monitores):
        for lado in LADOS:
            if not any(_encosta(m, lado, o) for j, o in enumerate(monitores)
                       if j != i):
                livres.append((i, lado))
    return livres


def indice_do_monitor(monitores: list[dict], nome: str) -> int | None:
    for i, m in enumerate(monitores):
        if m["nome"] == nome:
            return i
    return None


def borda_padrao(monitores: list[dict]) -> dict:
    """O lado direito do monitor mais a direita -- o lugar mais comum."""
    livres = lados_livres(monitores)
    candidatos = [(i, l) for i, l in livres if l == "direita"] or livres
    i, lado = max(candidatos, key=lambda c: monitores[c[0]]["x"]
                  + monitores[c[0]]["l"]) if candidatos else (0, "direita")
    return {"monitor": monitores[i]["nome"], "lado": lado, "centro": 0.5,
            "tamanho": 0.5}


def resolver(monitores: list[dict], borda: dict | None) -> dict:
    """
    A borda gravada, conferida contra os monitores de AGORA. Monitor que sumiu
    ou lado que deixou de ser livre (outro monitor foi posto ali) cai na
    padrao, em vez de deixar uma borda que o mouse nunca alcanca.
    """
    if not monitores:
        return {}
    borda = dict(borda or {})
    i = indice_do_monitor(monitores, borda.get("monitor", ""))
    if i is None or (i, borda.get("lado")) not in lados_livres(monitores):
        return borda_padrao(monitores)
    tamanho = min(1.0, max(0.15, _numero(borda.get("tamanho"), 0.5)))
    centro = _numero(borda.get("centro"), 0.5)
    centro = min(1 - tamanho / 2, max(tamanho / 2, centro))
    return {"monitor": monitores[i]["nome"], "lado": borda["lado"],
            "centro": centro, "tamanho": tamanho}


def _numero(valor, padrao: float) -> float:
    """Valor escrito a mao no config pode ser qualquer coisa."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        return padrao


def trecho(monitores: list[dict], borda: dict):
    """
    O trecho da borda em pixels: (monitor, lado, inicio, fim), com inicio/fim
    na coordenada que corre AO LONGO do lado (y para esquerda/direita, x para
    cima/baixo). None se a borda nao se resolve.
    """
    borda = resolver(monitores, borda)
    if not borda:
        return None
    m = monitores[indice_do_monitor(monitores, borda["monitor"])]
    vertical = borda["lado"] in ("esquerda", "direita")
    base = m["y"] if vertical else m["x"]
    comprimento = m["a"] if vertical else m["l"]
    meio = borda["tamanho"] / 2
    inicio = base + int(comprimento * (borda["centro"] - meio))
    fim = base + int(comprimento * (borda["centro"] + meio))
    return (m, borda["lado"], inicio, fim)


def tocou(pos: tuple[int, int], alvo) -> bool:
    """O ponteiro esta encostado no trecho?"""
    if alvo is None:
        return False
    m, lado, inicio, fim = alvo
    x, y = pos
    # `fim` fica de fora: com o trecho inteiro, `fim` ja e o primeiro pixel
    # do monitor vizinho.
    if lado == "direita":
        return x >= m["x"] + m["l"] - 1 and inicio <= y < fim
    if lado == "esquerda":
        return x <= m["x"] and inicio <= y < fim
    if lado == "baixo":
        return y >= m["y"] + m["a"] - 1 and inicio <= x < fim
    return y <= m["y"] and inicio <= x < fim


def para_dentro(pos: tuple[int, int], alvo, recuo: int) -> tuple[int, int]:
    """O ponto um pouco para dentro do monitor, na altura de `pos`."""
    m, lado, _i, _f = alvo
    x, y = pos
    if lado == "direita":
        x = m["x"] + m["l"] - 1 - recuo
    elif lado == "esquerda":
        x = m["x"] + recuo
    elif lado == "baixo":
        y = m["y"] + m["a"] - 1 - recuo
    else:
        y = m["y"] + recuo
    return (x, y)
