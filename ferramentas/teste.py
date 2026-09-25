"""
Banco de testes do nucleo, por terminal. Nao tem interface: e so pra confirmar
que achar o celular, montar a linha e subir/derrubar funcionam antes de haver
qualquer janela em cima disso.

COMO USAR
---------
    teste.bat            confere tudo sem subir nada (seguro, rapido)
    teste.bat jogo       sobe o espelhamento e espera voce apertar Enter
    teste.bat audio      sobe so o som e espera voce apertar Enter

O relatorio de cada execucao fica em `relatorios\\ultimo.txt`, e o historico
acumulado em `relatorios\\historico.txt`.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrcpyf import VERSAO, caminhos, celular, config as cfg, sessao as ses

LINHAS = []


def anota(texto: str = "") -> None:
    """Escreve na tela e guarda pro relatorio."""
    print(texto)
    LINHAS.append(texto)


def cabecalho(titulo: str) -> None:
    anota("")
    anota("--- %s " % titulo + "-" * max(0, 60 - len(titulo)))


def resumo_da_config(config) -> None:
    """A configuracao do momento vai junto: sem ela, um resultado fica
    ambiguo depois."""
    cabecalho("configuracao no momento do teste")
    anota("pasta do scrcpy : %s" % (config.scrcpy or "(nao definida)"))
    anota("instalacao ok   : %s" % ("sim" if config.instalacao_ok else "NAO"))
    anota("endereco reserva: %s" % (config.ip_reserva or "(nenhum)"))
    anota("perfis          : %s" % ", ".join(sorted(config.perfis)))
    anota("atalhos         : %s" % (config.atalhos or "(nenhum definido)"))


def mostrar_linhas(config, serial: str) -> None:
    cabecalho("linha de comando montada para cada perfil")
    for nome in sorted(config.perfis):
        linha = ses.montar(config.scrcpy_exe or "scrcpy.exe", serial,
                           config.perfil(nome))
        anota("[%s]" % nome)
        anota("  " + " ".join(linha[1:]))


def subir(config, nome: str, serial: str) -> None:
    cabecalho("subindo o perfil '%s'" % nome)
    sessao = ses.Sessao(nome)
    ok = sessao.iniciar(config.scrcpy_exe, serial, config.perfil(nome),
                        caminhos.pasta_relatorios())
    if not ok:
        anota("RESULTADO: o processo nem chegou a nascer.")
        return

    espelhando = bool(config.perfil(nome)["video"]["ligado"])
    anota("processo no ar. Confira: %s" % (
        "a janela do espelhamento apareceu?" if espelhando
        else "o som do celular esta saindo no PC?"))
    anota("")

    # A ordem de parar tem que estar escrita na tela desde o comeco: quem
    # esta olhando pro celular ou pra janela do espelhamento nao adivinha que
    # o terminal atras dela e quem manda encerrar.
    print()
    print("   ------------------------------------------------------------")
    print("    Aperte Enter para parar o %s e voltar ao menu."
          % ("espelhamento" if espelhando else "audio"))
    print("   ------------------------------------------------------------")
    try:
        input("   >>> ")
    except (EOFError, KeyboardInterrupt):
        pass

    # Saida 0 quer dizer que o scrcpy encerrou por bem -- normalmente porque
    # a janela do espelhamento foi fechada no X, que e um jeito legitimo de
    # terminar. So codigo diferente de zero e sinal de problema.
    if sessao.terminou_sozinho and sessao.codigo_saida == 0:
        anota("o scrcpy foi encerrado pela propria janela (normal).")
    elif sessao.terminou_sozinho:
        anota("ATENCAO: o scrcpy caiu sozinho antes de voce encerrar "
              "(codigo %s)." % sessao.codigo_saida)
    else:
        anota("encerrando com jeito...")

    sessao.parar()
    time.sleep(0.5)
    anota("sessao encerrada. Fim do log:")
    for linha in sessao.ultimas_linhas_do_log().splitlines():
        anota("  | " + linha)


def gravar_relatorio() -> None:
    pasta = caminhos.pasta_relatorios()
    texto = "\n".join(LINHAS) + "\n"
    try:
        (pasta / "ultimo.txt").write_text(texto, encoding="utf-8")
        with open(pasta / "historico.txt", "a", encoding="utf-8") as f:
            f.write(texto + "\n" + "=" * 70 + "\n\n")
        print("\nRelatorio gravado em relatorios\\ultimo.txt")
    except Exception as erro:
        print("\nNao consegui gravar o relatorio: %s" % erro)


def main() -> int:
    pedido = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()

    anota("=== teste do nucleo do scrcpy-f %s === %s"
          % (VERSAO, time.strftime("%d/%m/%Y %H:%M:%S")))
    anota("pedido: %s" % (pedido or "conferencia sem subir nada"))

    config = cfg.Config.carregar()
    resumo_da_config(config)

    if not config.instalacao_ok:
        cabecalho("observacoes")
        anota("PAREI AQUI: nao achei o adb.exe e o scrcpy.exe na pasta acima.")
        anota("Corrija o campo 'scrcpy' no config.json (ou o caminho-scrcpy.txt).")
        gravar_relatorio()
        return 1

    cabecalho("procurando o celular")
    serial = celular.achar(config.adb_exe, config.ip_reserva, anotar=anota)
    anota("escolhido: %s" % (serial or "(nenhum)"))

    if serial:
        endereco = celular.endereco_na_rede(config.adb_exe, serial)
        if endereco:
            anota("endereco na rede: %s" % endereco)
            config.lembrar_ip(endereco)

    mostrar_linhas(config, serial)

    if not serial:
        cabecalho("observacoes")
        anota("PAREI AQUI: nenhum celular acessivel.")
        anota("Confira se ele esta ligado, na mesma rede do PC, e com a")
        anota("'Depuracao sem fio' ligada nas Opcoes do desenvolvedor.")
        gravar_relatorio()
        return 1

    if pedido in ("jogo", "audio"):
        subir(config, pedido, serial)
    elif pedido:
        cabecalho("observacoes")
        anota("Nao conheco o perfil '%s'. Perfis: %s"
              % (pedido, ", ".join(sorted(config.perfis))))
    else:
        cabecalho("observacoes")
        anota("Conferencia so de leitura: nada foi subido.")
        anota("Para subir de verdade: teste.bat jogo  ou  teste.bat audio")

    gravar_relatorio()
    return 0


if __name__ == "__main__":
    sys.exit(main())
