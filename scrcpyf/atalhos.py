"""
Os atalhos de teclado: quais acoes existem e como elas ficam guardadas.

Porta do `atalhos.py` do LightWireless -- so a lista de ACOES e deste
programa; o formato, as tabelas de tecla e as recusas sao as mesmas, para um
atalho gravado la valer do mesmo jeito aqui.

QUEM SABE DAS ACOES E ESTE MODULO
----------------------------------
O `config.py` so guarda o dicionario; quem sabe quais acoes existem, como cada
uma se chama na tela e em que ordem aparecem e este arquivo. Quem desenha e a
janela (`janela.py`) e quem escuta o teclado com o programa em segundo
plano e o `motor_atalhos.py`.

O FORMATO E TEXTO, NAO CODIGO DE TECLA
---------------------------------------
Um atalho e guardado como "Ctrl+Alt+J": legivel por quem abrir o config.json
na mao, e independente de como o sistema registra a combinacao.
"""

from __future__ import annotations

# As acoes que podem receber atalho, na ordem em que aparecem na lista.
#
# "Sair do programa" fica de fora pelo mesmo motivo do LightWireless: atalho
# global que fecha tudo e facil de apertar sem querer, e sair ja tem gesto
# proprio (segurar o X). Aqui ainda derrubaria o espelhamento no meio do jogo.
# Visual novo (21/set/2026): espelhar e som viraram UM modo, entao o atalho
# do som saiu -- um "alternar_audio" gravado num config antigo e so ignorado.
ACOES: dict[str, str] = {
    "alternar_jogo": "Espelhar / parar",
    "so_tela": "Espelhar só a tela / parar",
    "so_som": "Espelhar só o som / parar",
    "alternar_extensao": "Extensão / parar",
    "mostrar_janela": "Abrir / fechar a janela",
    "fixar_espelhamento": "Espelhamento por cima / solto",
    "trocar_janelas": "Trocar entre as janelas do celular",
}

# Os atalhos de fabrica: os numeros da lista de modos da janela (1 e 2) SAO
# estes atalhos. So entram quando a pessoa ainda nao tem nenhum.
DE_FABRICA: dict[str, str] = {
    "alternar_jogo": "Ctrl+Alt+1",
    "alternar_extensao": "Ctrl+Alt+2",
}


# -- as teclas -------------------------------------------------------------
#
# O Tk chama cada tecla por um nome proprio (`keysym`). Estas tabelas
# traduzem esses nomes para o que aparece na tela e fica no arquivo -- e sao
# a UNICA parte do programa que precisa saber como o Tk chama as coisas.

MODIFICADORES = {
    "Control_L": "Ctrl", "Control_R": "Ctrl",
    "Alt_L": "Alt", "Alt_R": "Alt",
    "Shift_L": "Shift", "Shift_R": "Shift",
    "Win_L": "Win", "Win_R": "Win",
    "Super_L": "Win", "Super_R": "Win",
    "Meta_L": "Win", "Meta_R": "Win",
}

# Sempre nesta ordem, venham apertados na ordem que vierem. Assim a mesma
# combinacao tem uma escrita so -- se cada gravacao saisse numa ordem, duas
# iguais nao se reconheceriam e a conferencia de conflito falharia.
ORDEM = ("Ctrl", "Alt", "Shift", "Win")

# Nome amigavel para as teclas cujo `keysym` e feio ou obscuro.
#
# AS DE PONTUACAO VIRAM O PROPRIO CARACTERE, e nao um nome. O Tk chama a
# barra invertida de "backslash", e um nome desses nao diz nada para quem
# le a lista e nao serve para o motor achar a tecla no Windows -- foi
# exatamente isso que fez `Ctrl+Alt+\` ser aceito e nao funcionar
# (06/set/2026). Virando "\", o nome fica curto na tela E o motor consegue
# perguntar ao Windows qual tecla e essa no teclado que a pessoa usa.
APELIDOS = {
    "Prior": "PgUp",
    "Next": "PgDn",
    "Return": "Enter",
    "KP_Enter": "Enter",
    "BackSpace": "Backspace",
    "Delete": "Del",
    "space": "Espaco",
    "Left": "Esquerda",
    "Right": "Direita",
    "Up": "Cima",
    "Down": "Baixo",

    # pontuacao e simbolos
    "backslash": "\\",
    "slash": "/",
    "comma": ",",
    "period": ".",
    "semicolon": ";",
    "colon": ":",
    "apostrophe": "'",
    "quoteright": "'",
    "quoteleft": "`",
    "grave": "`",
    "bracketleft": "[",
    "bracketright": "]",
    "braceleft": "{",
    "braceright": "}",
    "minus": "-",
    "plus": "+",
    "equal": "=",
    "asterisk": "*",
    "numbersign": "#",
    "dollar": "$",
    "percent": "%",
    "ampersand": "&",
    "at": "@",
    "exclam": "!",
    "question": "?",
    "less": "<",
    "greater": ">",
    "bar": "|",
    "underscore": "_",
    "asciitilde": "~",
    "asciicircum": "^",
    "acute": "´",
    "ccedilla": "Ç",
    "Ccedilla": "Ç",
    "cedilla": "Ç",
}

# As teclas de nome comprido que o motor sabe registrar. Tem que bater com a
# tabela `CODIGOS` do `motor_atalhos.py`: nome que estiver so aqui vira
# atalho que nao funciona, que e o pior dos mundos.
TECLAS_ESPECIAIS = {
    "Esquerda", "Direita", "Cima", "Baixo",
    "Espaco", "Enter", "Backspace", "Del", "Insert",
    "Home", "End", "PgUp", "PgDn",
}
TECLAS_ESPECIAIS.update("F%d" % n for n in range(1, 25))


def da_para_registrar(nome: str) -> bool:
    """
    O motor consegue transformar esta tecla num atalho do Windows?

    Uma tecla so passa se for UM caractere (letra, numero, pontuacao -- o
    motor pergunta ao Windows onde ela fica no teclado atual) ou uma das
    especiais conhecidas. Qualquer outro nome de tecla do Tk seria aceito
    aqui e recusado la, e o atalho ficaria gravado sem funcionar.
    """
    return len(nome) == 1 or nome in TECLAS_ESPECIAIS

# Teclas que nao podem FECHAR uma combinacao. Esc cancela a gravacao, e as
# de trava mudam de estado sozinhas -- nenhuma serve de atalho.
NAO_SERVEM = {
    "Escape", "Caps_Lock", "Num_Lock", "Scroll_Lock",
    "Tab", "Menu",
}


def e_modificador(keysym: str) -> bool:
    return keysym in MODIFICADORES


def nome_de_tecla(keysym: str) -> str:
    """Como a tecla aparece na tela e no arquivo."""
    if keysym in MODIFICADORES:
        return MODIFICADORES[keysym]
    if keysym in APELIDOS:
        return APELIDOS[keysym]
    if len(keysym) == 1:
        return keysym.upper()
    return keysym


def escrever(modificadores, keysym: str = "") -> str:
    """
    A combinacao como texto, VALIDA OU NAO.

    Escreve o que esta apertado AGORA, mesmo que aquilo nao possa virar
    atalho: e ver a tecla proibida escrita em vermelho que explica a recusa.
    Quem diz se serve e o `porque_nao`, nao esta funcao.
    """
    presos = {MODIFICADORES[k] for k in modificadores if k in MODIFICADORES}
    partes = [m for m in ORDEM if m in presos]
    if keysym and not e_modificador(keysym):
        partes.append(nome_de_tecla(keysym))
    return "+".join(partes)


def porque_nao(modificadores, keysym: str = "") -> str:
    """
    Por que esta combinacao nao pode ser atalho? Texto vazio = pode.

    Uma frase curta e direta, porque ela vai aparecer embaixo da caixa
    enquanto a pessoa ainda esta com os dedos nas teclas.
    """
    if not keysym or e_modificador(keysym):
        return "Falta a tecla principal."
    if keysym in NAO_SERVEM:
        return "%s nao serve de atalho." % nome_de_tecla(keysym)
    if not da_para_registrar(nome_de_tecla(keysym)):
        return "O Windows nao aceita %s como atalho." % nome_de_tecla(keysym)
    if not tem_modificador(escrever(modificadores, keysym)):
        return "Falta Ctrl, Alt ou Win: sem eles o atalho roubaria a tecla do computador inteiro."
    return ""


def tem_modificador(teclas: str) -> bool:
    """
    A combinacao tem pelo menos um Ctrl / Alt / Shift / Win?

    Atalho GLOBAL sem modificador sequestraria a tecla no computador
    inteiro: gravar "J" ligaria o espelhamento no meio de qualquer coisa que
    a pessoa estivesse escrevendo. Por isso o gravador recusa.
    """
    partes = {p.strip() for p in teclas.split("+")}
    return any(m in partes for m in ORDEM)


def rotulo(acao: str) -> str:
    """Como a acao aparece na tela. Acao desconhecida devolve o proprio nome."""
    if acao.startswith(APP):
        pacote = acao[len(APP):]
        return "Abrir %s" % NOMES_DE_APP.get(pacote, pacote)
    return ACOES.get(acao, acao)


# ATALHO POR APP (pedido dele, 23/set/2026): "app:<pacote>" abre aquele app
# numa janela propria (ou traz a janela dele para a frente). O nome que
# aparece na tela vem daqui -- a janela preenche com o que esta no config.
APP = "app:"
NOMES_DE_APP: dict[str, str] = {}


def _conhecida(acao: str) -> bool:
    return acao in ACOES or (acao.startswith(APP) and len(acao) > len(APP))


def guardados(config) -> dict[str, str]:
    """
    Os atalhos gravados, so os de acao conhecida.

    Filtrar na leitura, e nao na hora de desenhar: assim um config vindo de
    uma versao futura (ou editado na mao) nao faz aparecer linha de uma acao
    que este programa nao sabe executar.

    COMBINACAO VAZIA CONTINUA NA LISTA: e o atalho recem-adicionado, esperando
    as teclas. Quem nao aparece e a acao desconhecida ou o valor que nem texto
    e.
    """
    crus = getattr(config, "atalhos", None) or {}
    return {
        acao: teclas
        for acao, teclas in crus.items()
        if _conhecida(acao) and isinstance(teclas, str)
    }


def em_ordem(config) -> list[tuple[str, str]]:
    """Os atalhos gravados na ordem de `ACOES` (os dos apps no fim, por nome),
    e nao na ordem do arquivo."""
    salvos = guardados(config)
    fixos = [(acao, salvos[acao]) for acao in ACOES if acao in salvos]
    dos_apps = sorted(((a, t) for a, t in salvos.items() if a.startswith(APP)),
                      key=lambda par: rotulo(par[0]).lower())
    return fixos + dos_apps


def livres(config) -> list[str]:
    """As acoes que ainda nao tem atalho -- as que o botao de adicionar oferece."""
    salvos = guardados(config)
    return [acao for acao in ACOES if acao not in salvos]


def quem_usa(config, teclas: str, menos: str = "") -> str | None:
    """
    Qual acao ja usa esta combinacao? `None` se estiver livre.

    `menos` e a acao que esta sendo regravada -- ela nao conflita consigo
    mesma. Quem chama isto e o gravador, no `janela.py`; mora aqui porque a
    pergunta e sobre a lista, nao sobre a captura.
    """
    alvo = teclas.strip().lower()
    if not alvo:
        return None
    for acao, valor in guardados(config).items():
        if acao != menos and valor.strip().lower() == alvo:
            return acao
    return None
