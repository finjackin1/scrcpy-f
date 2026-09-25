"""
Ponto de entrada do scrcpy-f.

Uso:
    duplo clique em scrcpy-f.bat   (sem console nenhum na tela)
    python app.py                  (com console, para ver o registro correndo)

O programa fica de fundo, na bandeja ao lado do relogio. Botao direito no
icone abre o menu; o clique no icone abre a janela (qualidade, atalhos), que
tambem abre por atalho ou abrindo o programa de novo.
"""

from __future__ import annotations

import logging
import sys

from scrcpyf import VERSAO, sistema

# ANTES DE QUALQUER OUTRO IMPORT DO PROGRAMA: sem console, `sys.stdout` e
# `sys.stderr` valem None, e biblioteca que imprime na hora do import
# levantaria excecao aqui.
sistema.garantir_saida()

from scrcpyf import caminhos  # noqa: E402  (depois do garantir_saida)
from scrcpyf.bandeja import Bandeja  # noqa: E402
from scrcpyf.motor_atalhos import Motor  # noqa: E402
from scrcpyf.programa import Programa  # noqa: E402
from scrcpyf.registro import Registro  # noqa: E402

log = logging.getLogger("scrcpyf")

ARQUIVO_DE_LOG = "programa.txt"


def preparar_registro_na_tela() -> None:
    """
    Registro na saida padrao -- visivel so quando o programa e aberto por
    `python app.py`. O que vale entre sessoes vai para o arquivo de log, que
    e escrito em paralelo.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> int:
    preparar_registro_na_tela()
    sistema.identidade_do_programa()        # (r161) antes de qualquer janela
    caminhos.ocultar_pasta_interna()

    # Segundo duplo clique nao abre um segundo programa: CHAMA o que ja esta
    # aberto, que mostra a janela. Quem abre de novo quase sempre quer a
    # janela; uma caixa de "ja esta aberto" so daria mais um clique.
    #
    # ANTES do log, de proposito: abrir o log gira o arquivo, e a instancia
    # duplicada girando o log da que esta viva embaralharia o registro dela.
    # A duplicada nao escreve nada -- quem anota o chamado e a que atende.
    # (r159) ATALHO DE APP NA AREA DE TRABALHO: "--app <pacote> --nome X".
    from scrcpyf import atalho_desktop
    app_pedido, app_nome = atalho_desktop.ler_argumentos(sys.argv[1:])
    if not sistema.instancia_unica():
        # Subiu pelo Windows e ja tem um aberto: sai quieto (nada de janela).
        if "--inicio" in sys.argv[1:]:
            return 0
        # O pedido vai ANTES do sinal: quem atende le e abre so o app. Sem
        # atalho, um pedido VAZIO -- apaga qualquer sobra antiga.
        sistema.deixar_pedido("app\t%s\t%s" % (app_pedido, app_nome)
                              if app_pedido else "")
        if sistema.chamar_a_outra():
            return 0
        # `esperar` porque o programa sai logo depois: em thread, a caixa
        # morreria junto com o processo sem chegar a aparecer.
        sistema.avisar("O scrcpy-f ja esta aberto.\n\n"
                       "Procure o icone dele na bandeja, ao lado do relogio.",
                       esperar=True)
        return 0

    # PRIMEIRA ABERTURA (pedido dele, 19/set/2026): sem o scrcpy apontado,
    # quem abre e o Configurar -- pasta do scrcpy, depois o celular -- e ELE
    # abre este programa no fim (`--depois-abrir`). O scrcpy nao vai mais
    # junto no pacote: cada um baixa o seu.
    # VISUAL NOVO (21/set/2026): o Configurar separado nao abre mais aqui --
    # a propria janela nasce em "opcoes" (pasta do scrcpy) ou "parear".

    # O log comeca ANTES de qualquer coisa que possa falhar. Se o programa
    # travar ou for fechado na forca, o que ja aconteceu esta gravado.
    registro = Registro(caminhos.pasta_relatorios() / ARQUIVO_DE_LOG, VERSAO)
    registro.abrir()
    registro.capturar_erros()           # (r165) erro escondido vai pro log

    programa = Programa(registro)
    _atalhos_de_fabrica(programa)
    registro.anotar_config(programa.config)
    if programa.config.ilegivel:
        registro.linha("config.json ILEGIVEL: rodando com o de fabrica, "
                       "sem gravar nada")
        sistema.avisar(
            "O config.json esta com defeito e nao deu para ler.\n\n"
            "O scrcpy-f vai abrir com os ajustes de fabrica e NAO vai gravar "
            "nada por cima do seu arquivo, para voce nao perder o que tinha.\n\n"
            "Para voltar ao normal: corrija o arquivo, ou apague-o para o "
            "programa criar um novo.")
    bandeja = Bandeja(programa)
    programa.bandeja = bandeja
    tem_bandeja = bandeja.iniciar()
    if not tem_bandeja:
        registro.linha("bandeja indisponivel (falta pystray/Pillow)")

    motor = Motor()
    janela = _abrir_janela(programa, motor, registro)

    # Atalhos e o chamado da segunda instancia so fazem sentido com a janela:
    # e ela quem os ouve. Sem ela (plano B, so bandeja), nenhum dos dois sobe
    # -- melhor nao existir do que existir sem ninguem escutando.
    if janela is not None:
        if motor.disponivel:
            motor.iniciar()
        sistema.ouvir_chamado()

    if janela is None and not tem_bandeja:
        # Sem janela e sem bandeja nao sobra jeito nenhum de comandar o
        # programa: melhor dizer o que falta do que ficar invisivel.
        registro.linha("PAREI: sem janela e sem bandeja")
        registro.fechar("sem interface")
        sistema.avisar(
            "Nao consegui criar o icone na bandeja.\n\n"
            "Faltam as bibliotecas pystray e Pillow. Instale com:\n\n"
            "    python -m pip install -r publicacao\\requirements.txt",
            esperar=True)
        return 1

    programa.anotar("programa no ar; esperando comando")
    # (r168) Voltou de uma atualizacao do proprio programa? Avisa o resultado.
    try:
        programa.avisar_atualizacao_feita()
    except Exception:
        log.exception("aviso da atualizacao")
    try:
        if janela is not None:
            # Sem bandeja, a janela e o unico jeito de comandar: ela abre
            # sempre, e o X vira minimizar (ver `Janela.esconder`).
            # A JANELA SO APARECE SE ELE PEDIU (relato dele, 23/set/2026: no
            # pacote ela aparecia no logon com a opcao desligada). Antes
            # bastava faltar o scrcpy -- e no logon a pasta dele pode nem
            # estar pronta ainda. Agora a excecao e uma so: a primeira
            # execucao de todas, quando nao ha nem config.json.
            primeira_vez = (programa.config.novo
                            and not programa.config.instalacao_ok)
            if app_pedido and not primeira_vez:
                # (r159) Aberto pelo atalho de um app: fica SO na bandeja e
                # abre o app (sem celular: avisa e fecha no OK).
                sistema.ler_pedido()          # sobra de chamado antigo
                programa.abrir_pelo_atalho(app_pedido, app_nome,
                                           sair_se_falhar=True)
                janela.mainloop()
                return 0
            if primeira_vez:
                # Sem o scrcpy apontado nada funciona: a janela abre sozinha,
                # direto onde se escolhe a pasta.
                janela.abrir_em("opcoes")
            if primeira_vez or not tem_bandeja or programa.config.opcao(
                    "abrir_janela_ao_iniciar"):
                janela.after(150, janela.mostrar)
            janela.mainloop()
        else:
            programa.rodar()
    except KeyboardInterrupt:
        programa.anotar("interrompido pelo teclado")
    finally:
        # Qualquer saida -- normal, Ctrl+C ou erro -- derruba as sessoes: um
        # scrcpy orfao continuaria espelhando sem ninguem para desligar.
        try:
            programa.desligar_tudo()
        except Exception:
            pass
        try:
            programa.parar_adb()        # (r173) o adb nao fica rodando
        except Exception:
            pass
        motor.encerrar()
        bandeja.encerrar()
        registro.fechar()

    return 0


def _abrir_janela(programa, motor, registro):
    """
    A janela, ou None se o Tk nao abrir. Nesse caso o programa continua so com
    a bandeja, como era na v0.2.0 -- perder a janela nao pode custar o resto.
    """
    try:
        from scrcpyf.janela import Janela
        janela = Janela(programa, motor)
        # (r165) Erro dentro de um clique/timer da janela: o Tk so imprimia
        # no console (que o .exe nao tem). Agora vai pro log.
        janela.report_callback_exception = (
            lambda tipo, valor, tb: log.error("erro na janela",
                                              exc_info=(tipo, valor, tb)))
        return janela
    except Exception as erro:
        log.exception("a janela nao abriu")
        registro.linha("janela indisponivel: %s -- seguindo so com a bandeja"
                       % erro)
        return None


def _atalhos_de_fabrica(programa) -> None:
    """
    Os numeros da lista de modos (1 e 2) sao os atalhos Ctrl+Alt+1 e
    Ctrl+Alt+2. Quem ainda nao tem nenhum atalho ganha esses; quem ja montou
    os seus fica como esta.
    """
    from scrcpyf import atalhos
    cfg = programa.config
    if atalhos.guardados(cfg):
        return
    for acao, teclas in atalhos.DE_FABRICA.items():
        cfg.atalhos[acao] = teclas
    if not cfg.ilegivel:
        cfg.gravar()
    programa.anotar("atalhos de fabrica: %s" % ", ".join(
        "%s=%s" % par for par in atalhos.DE_FABRICA.items()))


if __name__ == "__main__":
    sys.exit(main())
