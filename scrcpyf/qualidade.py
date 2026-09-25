"""
O que a janela oferece para ajustar a qualidade, e como cada escolha vira
campo do perfil.

QUEM SABE DAS OPCOES E ESTE MODULO
-----------------------------------
Mesma divisao do `config.py` com o `sessao.py`: o config so guarda, o sessao
so monta a linha de comando, e aqui mora o que a PESSOA ve -- quais valores
existem, como cada um se chama na tela e quais combinacoes viram um nivel
pronto ("Leve", "Padrao"...). A janela nao escreve nenhum desses valores; ela
pergunta para ca.

SO VALOR PRONTO, NUNCA CAMPO DE DIGITAR
----------------------------------------
Cada ajuste e uma fileira de opcoes fechadas. Digitar "16m" ou "60fps" daria
um scrcpy que nao sobe, e o erro so apareceria na proxima vez que ele fosse
ligar -- longe de quem digitou. Com valor pronto nao existe valor invalido.

NIVEL PRONTO E ATALHO, NAO OUTRO LUGAR
---------------------------------------
Escolher "Leve" so escreve varios campos de uma vez. Quem manda continua
sendo cada campo: mexer num deles depois faz o nivel virar "Personalizado"
sozinho, porque a janela reconhece o nivel comparando os campos, e nao
guardando qual foi clicado. Assim nao existe estado escondido para mentir.

O "PADRAO" E O DE FABRICA
--------------------------
O nivel "Padrao" de imagem e o mesmo do `PERFIL_BASE` do config: h264,
8 Mb/s, 60 quadros, 1280, sem atraso (ate 19/set/2026 era 16 Mb/s na
resolucao do celular -- saiu quando as fileiras desceram).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# As opcoes de cada campo: (valor gravado, rotulo na tela)
# ---------------------------------------------------------------------------

# Imagem
CODEC_VIDEO = [("h264", "H.264"), ("h265", "H.265")]
# 19/set/2026: fileiras descidas a pedido dele (foco em latencia e
# estabilidade, nitidez por ultimo). Sairam 32 Mb/s, Original e 1920; o
# config antigo com esses valores so fica sem opcao marcada.
TAXA_VIDEO = [("2M", "2"), ("4M", "4"), ("8M", "8"), ("16M", "16"),
              ("24M", "24")]
QUADROS = [(30, "30"), (60, "60"), (90, "90"), (120, "120")]
RESOLUCAO = [(1600, "1600"), (1280, "1280"), (1024, "1024"),
             (800, "800"), (720, "720")]
ATRASO_VIDEO = [(0, "0"), (20, "20"), (50, "50"), (100, "100")]

# Som
# O "raw" do scrcpy (som sem compressao nenhuma) fica de fora de proposito:
# e som de estudio por Wi-Fi, pesado demais para a rede e sem ganho que se
# ouca sobre o FLAC, que ja e sem perda. Quem quiser, poe a mao no config.
CODEC_AUDIO = [("opus", "Opus"), ("aac", "AAC"), ("flac", "FLAC")]
TAXA_AUDIO = [("64K", "64"), ("128K", "128"), ("192K", "192"),
              ("256K", "256")]
ATRASO_AUDIO = [(20, "20"), (50, "50"), (100, "100"), (200, "200")]

# A origem do som junta dois campos do perfil (`fonte` e `duplicar`) numa
# escolha so, porque para quem usa e uma pergunta so: "onde o som toca?".
ORIGEM = [("output", "Só no PC"), ("playback", "PC e celular"),
          ("mic", "Microfone")]

# Codecs sem compressao nao tem taxa de bits: a fileira da taxa fica apagada
# com eles, em vez de oferecer um ajuste que nao faz nada.
SEM_TAXA = {"flac", "raw"}


# ---------------------------------------------------------------------------
# Cada ajuste da tela: onde ele mora no perfil, as opcoes e as explicacoes
# ---------------------------------------------------------------------------
#
# `dica` e o texto curto que aparece do lado do nome, na mesma linha -- tem
# que caber em ~28 caracteres, que e o que sobra numa janela de 380.

AJUSTES_VIDEO = [
    {"secao": "video", "campo": "codec", "nome": "Codec",
     "dica": "H.264 responde mais rápido", "opcoes": CODEC_VIDEO},
    {"secao": "video", "campo": "bitrate", "nome": "Taxa de bits",
     "dica": "Mb/s  ·  mais = mais nítido", "opcoes": TAXA_VIDEO},
    {"secao": "video", "campo": "fps_max", "nome": "Quadros por segundo",
     "dica": "limite, não garantia", "opcoes": QUADROS},
    {"secao": "video", "campo": "resolucao_max", "nome": "Resolução",
     "dica": "lado maior, em pixels", "opcoes": RESOLUCAO},
    {"secao": "video", "campo": "buffer_ms", "nome": "Atraso da imagem",
     "dica": "ms  ·  sobe se picotar", "opcoes": ATRASO_VIDEO},
]

AJUSTES_AUDIO = [
    {"secao": "audio", "campo": "origem", "nome": "Onde o som toca",
     "dica": "PC e celular: Android 13+", "opcoes": ORIGEM},
    {"secao": "audio", "campo": "codec", "nome": "Codec",
     "dica": "troque se o som não vier", "opcoes": CODEC_AUDIO},
    {"secao": "audio", "campo": "bitrate", "nome": "Taxa de bits",
     "dica": "kb/s", "opcoes": TAXA_AUDIO},
    {"secao": "audio", "campo": "buffer_ms", "nome": "Atraso do som",
     "dica": "ms  ·  sobe se estalar", "opcoes": ATRASO_AUDIO},
]


# ---------------------------------------------------------------------------
# Niveis prontos
# ---------------------------------------------------------------------------

NIVEIS_VIDEO = [
    # "Leve" = o ajuste DELE para jogar (19/set/2026): menor atraso e sem
    # travar, nitidez por ultimo. Antes era 30 quadros/1280/50 ms.
    ("leve", "Leve", "Menor atraso, sem travar. Imagem mais simples.",
     {"codec": "h264", "bitrate": "4M", "fps_max": 60,
      "resolucao_max": 1024, "buffer_ms": 0}),
    ("padrao", "Padrão", "Resposta rápida, imagem melhor. Pede Wi-Fi bom.",
     {"codec": "h264", "bitrate": "8M", "fps_max": 60,
      "resolucao_max": 1280, "buffer_ms": 0}),
    ("nitido", "Nítido", "Imagem mais limpa, com um pouco mais de atraso.",
     {"codec": "h265", "bitrate": "24M", "fps_max": 60,
      "resolucao_max": 1600, "buffer_ms": 20}),
]

NIVEIS_AUDIO = [
    # Idem: o ajuste dele (19/set/2026). Antes era 64 kb/s e 50 ms.
    ("leve", "Leve", "Menor atraso. Suba o atraso se estalar.",
     {"codec": "opus", "bitrate": "128K", "buffer_ms": 20}),
    ("padrao", "Padrão", "O equilíbrio de fábrica do scrcpy.",
     {"codec": "opus", "bitrate": "128K", "buffer_ms": 50}),
    ("alta", "Alta", "Som mais cheio, para música.",
     {"codec": "opus", "bitrate": "256K", "buffer_ms": 50}),
]

TEXTO_PERSONALIZADO = "Personalizado: ajustado à mão, no ajuste fino."


# ---------------------------------------------------------------------------
# Leitura e escrita no perfil
# ---------------------------------------------------------------------------

def ler(perfil: dict, secao: str, campo: str):
    """O valor de um ajuste no perfil, ja no formato das opcoes."""
    parte = perfil.get(secao, {}) or {}
    if secao == "audio" and campo == "origem":
        if parte.get("duplicar"):
            return "playback"
        fonte = str(parte.get("fonte", "output"))
        if fonte == "output":
            return "output"
        if fonte.startswith("mic"):
            return "mic"
        # Uma fonte posta a mao que nao e nenhuma das tres ("playback" sem
        # duplicar, "voice-call"...): nenhuma opcao marcada, em vez de fingir.
        return None
    return parte.get(campo)


def escrever(perfil: dict, secao: str, campo: str, valor) -> None:
    """Grava um ajuste no perfil (em memoria; quem grava em disco e o config)."""
    parte = perfil.setdefault(secao, {})
    if secao == "audio" and campo == "origem":
        parte["fonte"] = "playback" if valor == "playback" else valor
        parte["duplicar"] = valor == "playback"
        return
    parte[campo] = valor


def nivel_atual(perfil: dict, secao: str) -> str | None:
    """
    Qual nivel pronto bate com os campos de agora, ou None (personalizado).

    Compara com `_mesmo`, e nao com `==`: o config pode ter sido editado a
    mao com "16m" ou 60.0, e isso continua sendo o nivel Padrao.
    """
    niveis = NIVEIS_VIDEO if secao == "video" else NIVEIS_AUDIO
    parte = perfil.get(secao, {}) or {}
    for chave, _rotulo, _texto, campos in niveis:
        if all(_mesmo(parte.get(c), v) for c, v in campos.items()):
            return chave
    return None


def aplicar_nivel(perfil: dict, secao: str, chave: str) -> bool:
    """Escreve todos os campos de um nivel. False se o nivel nao existe."""
    niveis = NIVEIS_VIDEO if secao == "video" else NIVEIS_AUDIO
    for c, _rotulo, _texto, campos in niveis:
        if c == chave:
            parte = perfil.setdefault(secao, {})
            parte.update(campos)
            return True
    return False


def texto_do_nivel(secao: str, chave: str | None) -> str:
    niveis = NIVEIS_VIDEO if secao == "video" else NIVEIS_AUDIO
    for c, _rotulo, texto, _campos in niveis:
        if c == chave:
            return texto
    return TEXTO_PERSONALIZADO


def rotulos_dos_niveis(secao: str) -> list[tuple[str, str]]:
    niveis = NIVEIS_VIDEO if secao == "video" else NIVEIS_AUDIO
    return [(c, r) for c, r, _t, _v in niveis]


def indice(opcoes, valor) -> int | None:
    """Posicao do valor nas opcoes, ou None se ele nao for nenhuma delas."""
    for i, (v, _r) in enumerate(opcoes):
        if _mesmo(v, valor):
            return i
    return None


def _mesmo(a, b) -> bool:
    """Igualdade tolerante: "16M" == "16m", 60 == 60.0 == "60"."""
    if a == b:
        return True
    try:
        return str(a).strip().lower() == str(b).strip().lower() or \
            float(a) == float(b)
    except (TypeError, ValueError):
        return False


# ============================================================================
# QUALIDADE UNICA (pedido dele, 23/set/2026)
# ============================================================================
#
# Uma qualidade so, em OPCOES > qualidade, vale para espelhar, extensao e
# apps. Tres predefinicoes FIXAS (nao mudam) e ate tres DELE (so existem se
# ele criar). Uma predefinicao e imagem + som juntos.
#
# Guardado no config como:
#   {"video": {...}, "audio": {...}, "escolhida": id ou None,
#    "minhas": [{"id": "p1", "nome": "...", "video": {...}, "audio": {...}}]}
# `escolhida` = a que ele clicou por ultimo. Mexer numa fileira com uma DELE
# escolhida grava nela; com uma fixa escolhida, `escolhida` vira None e a
# tela oferece "salvar como predefinicao".

CAMPOS_VIDEO = ["codec", "bitrate", "fps_max", "resolucao_max", "buffer_ms"]
CAMPOS_AUDIO = ["codec", "bitrate", "buffer_ms"]
MAX_MINHAS = 3


def _nivel(niveis, chave) -> dict:
    for c, _r, _t, campos in niveis:
        if c == chave:
            return dict(campos)
    return {}


PREDEF_FIXAS = [
    ("leve", "leve", _nivel(NIVEIS_VIDEO, "leve"), _nivel(NIVEIS_AUDIO, "leve")),
    ("equilibrado", "equilibrado", _nivel(NIVEIS_VIDEO, "padrao"),
     _nivel(NIVEIS_AUDIO, "padrao")),
    ("nitido", "nítido", _nivel(NIVEIS_VIDEO, "nitido"),
     _nivel(NIVEIS_AUDIO, "alta")),
]
PREDEF_INICIAL = "equilibrado"


def qualidade_de_fabrica() -> dict:
    for c, _n, v, a in PREDEF_FIXAS:
        if c == PREDEF_INICIAL:
            return {"video": dict(v), "audio": dict(a),
                    "escolhida": PREDEF_INICIAL, "minhas": []}
    return {"video": {}, "audio": {}, "escolhida": None, "minhas": []}


def todas_predef(q: dict) -> list:
    """[(id, nome, video, audio, fixa)] -- as fixas e depois as dele."""
    saida = [(c, n, v, a, True) for c, n, v, a in PREDEF_FIXAS]
    for m in (q.get("minhas") or [])[:MAX_MINHAS]:
        if isinstance(m, dict) and m.get("id"):
            saida.append((m["id"], str(m.get("nome") or m["id"]),
                          dict(m.get("video") or {}),
                          dict(m.get("audio") or {}), False))
    return saida


def valores_da_predef(q: dict, ident: str):
    """(video, audio) de uma predefinicao, ou (None, None)."""
    for c, _n, v, a, _f in todas_predef(q):
        if c == ident:
            return v, a
    return None, None


def predef_atual(q: dict):
    """A escolhida, se os campos ainda batem com ela; senao a primeira que
    bate; senao None (ajustada a mao)."""
    video, audio = q.get("video") or {}, q.get("audio") or {}

    def bate(v, a):
        return all(_mesmo(video.get(c), v.get(c)) for c in CAMPOS_VIDEO) and \
            all(_mesmo(audio.get(c), a.get(c)) for c in CAMPOS_AUDIO)

    lista = todas_predef(q)
    escolhida = q.get("escolhida")
    for c, _n, v, a, _f in lista:
        if c == escolhida and bate(v, a):
            return c
    for c, _n, v, a, _f in lista:
        if bate(v, a):
            return c
    return None


def aplicar_no_perfil(perfil: dict, video: dict | None,
                      audio: dict | None) -> None:
    """Poe os campos de qualidade no perfil (sem mexer em 'ligado' etc.)."""
    if video:
        parte = perfil.setdefault("video", {})
        for c in CAMPOS_VIDEO:
            if c in video:
                parte[c] = video[c]
    if audio:
        parte = perfil.setdefault("audio", {})
        for c in CAMPOS_AUDIO:
            if c in audio:
                parte[c] = audio[c]


# ONDE O SOM TOCA (um nome so em todo o programa, 23/set/2026).
# "celular" = o som fica no celular (nada vem); "pc" = so no PC;
# "ambos" = no PC e no celular (Android 13+).
ONDE = [("celular", "celular"), ("pc", "pc"), ("ambos", "pc e celular")]


def aplicar_onde(perfil: dict, onde: str) -> None:
    audio = perfil.setdefault("audio", {})
    if onde == "celular":
        audio["ligado"] = False
        return
    audio["ligado"] = True
    audio["fonte"] = "playback" if onde == "ambos" else "output"
    audio["duplicar"] = onde == "ambos"


def onde_do_perfil(perfil: dict) -> str:
    audio = perfil.get("audio") or {}
    if not audio.get("ligado", True):
        return "celular"
    return "ambos" if audio.get("duplicar") else "pc"
