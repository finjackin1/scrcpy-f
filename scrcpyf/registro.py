"""
O log do programa: `relatorios\\programa.txt`.

COMECA A ESCREVER ANTES DE QUALQUER COISA PODER FALHAR
-------------------------------------------------------
A abertura vai pro arquivo assim que o programa nasce, nao no fim. Se ele
travar ou for fechado na forca, o que ja aconteceu esta gravado. A versao
anterior deste programa so escrevia no encerramento -- e a primeira vez que
algo deu errado, nao havia log nenhum pra ler.

A ABERTURA E O DELIMITADOR, NAO O FECHAMENTO
---------------------------------------------
Sessao que travou nao tem linha de fechamento, e isso e normal. Por isso a
rotacao conta CABECALHOS DE ABERTURA: nada precisa ser consertado nem
inventado depois de um travamento -- a sessao incompleta fica registrada como
esta, que e a informacao util.

O ARQUIVO NAO ENGORDA
----------------------
Ficam 3 execucoes anteriores inteiras mais a atual. As mais velhas viram UMA
LINHA cada, no topo: data, versao e o que aconteceu. Duzentas execucoes viram
duzentas linhas, e a linha do tempo continua de pe -- e ela que permite dizer
"parou de funcionar na 0.3.0".
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback

# Quantas execucoes ficam com todo o detalhe (a atual conta como uma delas).
EXECUCOES_INTEIRAS = 4

# Teto de linhas por execucao. Um travamento em laco pode escrever a mesma
# linha milhares de vezes; passando disso, o MEIO e cortado -- o comeco mostra
# onde o problema nasce e o fim mostra onde ele morreu.
TETO_DE_LINHAS = 400

ABERTURA = "=== ABERTURA "
FECHAMENTO = "=== FECHAMENTO "
MARCA_DA_LINHA_DO_TEMPO = "--- linha do tempo (execucoes antigas, uma linha cada) ---"


class Registro:
    """O log de uma execucao, gravado enquanto ela acontece."""

    def __init__(self, caminho, versao: str) -> None:
        self.caminho = caminho
        self.versao = versao
        self._trava = threading.Lock()

    def capturar_erros(self) -> None:
        """
        ERRO ESCONDIDO VIRA LINHA NO LOG (r165, revisao da v1). No .exe nao
        ha console: `log.warning/exception` e o erro que mata uma thread iam
        para o nada -- um vigia podia morrer calado. Agora aviso e erro do
        `logging`, excecao solta em thread e excecao solta no programa vao
        para este arquivo, com o fim do rastro (so pra mim ler).
        """
        registro = self

        class _ParaOLog(logging.Handler):
            def emit(self, rec):
                try:
                    texto = "%s %s: %s" % (rec.levelname, rec.name,
                                           rec.getMessage())
                    if rec.exc_info:
                        texto += " | " + _rastro(*rec.exc_info)
                    registro.linha(texto[:1500])
                except Exception:
                    pass

        h = _ParaOLog(level=logging.WARNING)
        logging.getLogger().addHandler(h)

        def na_thread(args):
            if args.exc_type is SystemExit:
                return
            registro.linha("ERRO SOLTO na thread %s: %s"
                           % (getattr(args.thread, "name", "?"),
                              _rastro(args.exc_type, args.exc_value,
                                      args.exc_traceback))[:1500])

        def no_programa(tipo, valor, tb):
            registro.linha("ERRO SOLTO: %s" % _rastro(tipo, valor, tb)[:1500])

        threading.excepthook = na_thread
        sys.excepthook = no_programa

    # -- escrita -------------------------------------------------------------

    def abrir(self) -> None:
        """Rotaciona o arquivo e escreve o cabecalho desta execucao."""
        self._rotacionar()
        self._anexar("\n%s%s  scrcpy-f %s ==="
                     % (ABERTURA, time.strftime("%d/%m/%Y %H:%M:%S"), self.versao))

    def anotar_config(self, config) -> None:
        """
        A configuracao do momento, logo depois da abertura. Sem ela um
        resultado fica ambiguo depois: "nao pegou o som" com buffer 50 quer
        dizer outra coisa que com buffer 400.
        """
        self._anexar("\n".join([
            "  pasta do scrcpy : %s" % (config.pasta_scrcpy or "(nao definida)"),
            "  instalacao ok   : %s" % ("sim" if config.instalacao_ok else "NAO"),
            "  endereco reserva: %s" % (config.ip_reserva or "(nenhum)"),
            "  perfis          : %s" % ", ".join(sorted(config.perfis)),
            "  atalhos         : %s" % (config.atalhos or "(nenhum definido)"),
        ]))

    def linha(self, texto: str) -> None:
        """Uma linha no log desta execucao, com a hora na frente."""
        self._anexar("%s  %s" % (time.strftime("%H:%M:%S"), texto))

    def fechar(self, motivo: str = "") -> None:
        self._anexar("%s%s ===%s"
                     % (FECHAMENTO, time.strftime("%d/%m/%Y %H:%M:%S"),
                        ("  %s" % motivo) if motivo else ""))

    def _anexar(self, texto: str) -> None:
        try:
            with self._trava, open(self.caminho, "a", encoding="utf-8",
                                   errors="replace") as f:
                f.write(texto + "\n")
        except Exception:
            # Log que derruba o programa e pior que log nenhum.
            pass

    # -- rotacao -------------------------------------------------------------

    def _rotacionar(self) -> None:
        try:
            from pathlib import Path
            caminho = Path(self.caminho)
            if not caminho.exists():
                return
            texto = caminho.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        antigas, sessoes = self._separar(texto)

        # Abre espaco para a execucao que esta comecando.
        while len(sessoes) >= EXECUCOES_INTEIRAS:
            antigas.append(_resumir(sessoes.pop(0)))

        partes = [MARCA_DA_LINHA_DO_TEMPO] + antigas + [""]
        partes += [_com_teto(s) for s in sessoes]
        try:
            from pathlib import Path
            Path(self.caminho).write_text("\n".join(partes).rstrip() + "\n",
                                          encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _separar(texto: str):
        """Devolve (linhas da linha do tempo, lista de sessoes inteiras)."""
        antigas: list = []
        sessoes: list = []
        atual: list | None = None

        for linha in texto.splitlines():
            if linha.startswith(ABERTURA):
                if atual is not None:
                    sessoes.append("\n".join(atual))
                atual = [linha]
            elif atual is not None:
                atual.append(linha)
            elif linha.strip() and not linha.startswith("---"):
                antigas.append(linha)

        if atual is not None:
            sessoes.append("\n".join(atual))
        return antigas, sessoes


def _rastro(tipo, valor, tb) -> str:
    """O erro e as ultimas linhas de onde ele veio, numa linha so."""
    try:
        linhas = traceback.format_exception(tipo, valor, tb)
        return " / ".join(l.strip().replace("\n", " ")
                          for l in linhas[-6:])
    except Exception:
        return repr(valor)


def _resumir(sessao: str) -> str:
    """Uma execucao inteira virando uma linha da linha do tempo."""
    linhas = sessao.splitlines()
    cabecalho = linhas[0] if linhas else ""
    quando = cabecalho[len(ABERTURA):].split("===")[0].strip() if cabecalho else "?"
    fechou = any(l.startswith(FECHAMENTO) for l in linhas)

    marcas = []
    for chave, texto in (("no ar", "ligou"), ("NAO subiu", "falhou"),
                         ("terminou sozinha", "caiu")):
        quantas = sum(1 for l in linhas if chave in l)
        if quantas:
            marcas.append("%s=%d" % (texto, quantas))

    return "%s  %s  %s" % (
        quando,
        "encerrou normal" if fechou else "SEM FECHAMENTO (travou ou foi forcado)",
        " ".join(marcas) or "sem atividade",
    )


def _com_teto(sessao: str) -> str:
    """Corta o meio de uma sessao gigante, avisando quantas linhas sairam."""
    linhas = sessao.splitlines()
    if len(linhas) <= TETO_DE_LINHAS:
        return sessao
    metade = TETO_DE_LINHAS // 2
    omitidas = len(linhas) - TETO_DE_LINHAS
    return "\n".join(
        linhas[:metade]
        + ["", "   [ ... %d linhas omitidas do meio ... ]" % omitidas, ""]
        + linhas[-metade:]
    )
