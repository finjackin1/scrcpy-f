"""
Montar a linha de comando do scrcpy a partir de um perfil, subir e derrubar.

TODA CONFIGURACAO PASSA POR AQUI
---------------------------------
`montar` e a unica funcao que sabe traduzir um perfil do `config.json` nas
opcoes do scrcpy. Ela nao roda nada, o que a torna a peca mais facil de
conferir: da pra imprimir a linha e ler antes de deixar subir.

O NOME DE CADA OPCAO E DO SCRCPY, NAO MEU
------------------------------------------
Os nomes das opcoes valem para o scrcpy 3.x/4.x. Versao mais velha reclama de
opcao que nao conhece e nao sobe -- e por isso que uma linha que nao subiu
aparece inteira no relatorio: da pra ver qual opcao ele nao engoliu.

FECHAR COM JEITO ANTES DE FORCAR
---------------------------------
Encerrar pede primeiro que o scrcpy saia sozinho, e so depois derruba na
forca. A diferenca importa: saindo sozinho ele roda a propria limpeza, que
inclui devolver o tempo de tela original do celular. `/T` leva junto o que ele
tiver aberto.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)

SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# O scrcpy nasce um degrau acima do normal: e ele quem leva o mouse, o
# teclado e o som ate o celular, e atraso ali aparece na mao (21/set/2026).
ACIMA_DO_NORMAL = 0x00008000 if os.name == "nt" else 0

# Quanto esperar o scrcpy sair sozinho antes de derrubar na forca. 1,5 s foi o
# valor que se mostrou suficiente na versao de scripts.
ESPERA_PARA_SAIR = 1.5


def montar(scrcpy_exe, serial: str, perfil: dict) -> list:
    """
    A linha de comando completa, ja como lista de argumentos (nada de juntar
    tudo numa string: caminho com espaco no meio quebra desse jeito).
    """
    video = perfil.get("video", {})
    audio = perfil.get("audio", {})
    janela = perfil.get("janela", {})
    controle = perfil.get("controle", {})
    sessao = perfil.get("sessao", {})

    linha = [str(scrcpy_exe)]

    # Aponta o aparelho escolhido. Com isso, ter o cabo plugado ao mesmo tempo
    # nao causa mais o erro de "mais de um dispositivo".
    if serial:
        linha += ["-s", serial]

    # -- imagem --------------------------------------------------------------
    if video.get("ligado", True):
        if video.get("codec"):
            linha.append("--video-codec=%s" % video["codec"])
        if video.get("bitrate"):
            linha.append("--video-bit-rate=%s" % video["bitrate"])
        if _numero(video.get("fps_max")) > 0:
            linha.append("--max-fps=%d" % _numero(video["fps_max"]))
        if _numero(video.get("resolucao_max")) > 0:
            linha.append("--max-size=%d" % _numero(video["resolucao_max"]))
        linha.append("--video-buffer=%d" % _numero(video.get("buffer_ms")))

        if perfil.get("titulo"):
            linha.append("--window-title=%s" % perfil["titulo"])
        if janela.get("tela_cheia"):
            linha.append("--fullscreen")
        if janela.get("sem_borda"):
            linha.append("--window-borderless")
        if janela.get("sempre_no_topo"):
            linha.append("--always-on-top")

        if not controle.get("teclado_mouse", True):
            linha.append("--no-control")
        else:
            # ACENTO DUPLICADO (relato dele, 21/set/2026: "é" saia "eé"). No
            # teclado padrao do scrcpy a letra vai como tecla E o acento
            # pronto vai como texto, e o celular recebe os dois. Como teclado
            # simulado (UHID, o mesmo da extensao) vai so a tecla fisica e o
            # layout do celular para o aparelho "scrcpy" monta o acento.
            # O mouse continua o padrao: clique = toque, sem cursor.
            if controle.get("teclado") == "texto":
                # APPS EM JANELA PROPRIA (tela virtual): o teclado simulado
                # manda a tecla para a tela que estiver com o foco no celular,
                # que pode nao ser a desta janela. Aqui vai texto pronto,
                # entregue na tela certa -- e o acento chega inteiro, sem
                # duplicar.
                linha.append("--prefer-text")
            else:
                linha.append("--keyboard=uhid")
        if controle.get("teclado_mouse", True) and controle.get("joystick"):
            # So faz sentido com controle ligado: o joystick e uma forma de
            # controlar o celular.
            linha.append("--gamepad=uhid")
    elif controle.get("teclado_mouse"):
        # SEM IMAGEM, COM CONTROLE: o modo extensao. Mouse, teclado e controle
        # viram aparelhos fisicos simulados no celular (UHID -- funciona sem
        # fio, com cursor proprio). O scrcpy ainda precisa de uma janela para
        # receber o que se digita e move; ela nasce pequena, sem borda e fora
        # da tela, e o vigia da borda (`borda.py`) cuida dela dali em diante.
        # `--shortcut-mod=rsuper`: por padrao o scrcpy guarda Alt E a tecla
        # Windows para os atalhos dele, e nao repassa nenhuma das duas. Aqui
        # tudo tem que ir para o celular (a volta ao PC e 2x Tab, do gancho do
        # `borda.py`), entao os atalhos do scrcpy ficam presos numa tecla que
        # quase nenhum teclado tem: o Windows da DIREITA.
        linha += ["--no-video", "--keyboard=uhid", "--mouse=uhid",
                  "--shortcut-mod=rsuper"]
        if controle.get("joystick"):
            linha.append("--gamepad=uhid")
        linha += ["--window-title=%s" % (perfil.get("titulo") or "scrcpy-f"),
                  "--window-borderless", "--window-x=-10000",
                  "--window-y=-10000", "--window-width=64",
                  "--window-height=64"]
    else:
        # Sem imagem nao ha janela nem controle pra ter. Uma opcao so, que e a
        # que a versao de scripts ja usava no modo audio.
        linha.append("--no-window")

    # -- som -----------------------------------------------------------------
    if audio.get("ligado", True):
        if audio.get("codec"):
            linha.append("--audio-codec=%s" % audio["codec"])
        # FLAC e "sem compressao" nao tem taxa de bits: mandar uma seria
        # opcao ignorada na melhor das hipoteses.
        if audio.get("bitrate") and audio.get("codec") not in ("flac", "raw"):
            linha.append("--audio-bit-rate=%s" % audio["bitrate"])
        linha.append("--audio-buffer=%d" % _numero(audio.get("buffer_ms")))
        if audio.get("duplicar"):
            # Toca no PC E no celular. So existe com a fonte "playback" e so
            # no Android 13 ou mais novo; num mais velho o scrcpy recusa e o
            # motivo aparece no log da sessao.
            linha.append("--audio-source=playback")
            linha.append("--audio-dup")
        elif audio.get("fonte"):
            linha.append("--audio-source=%s" % audio["fonte"])
        if audio.get("exigir"):
            linha.append("--require-audio")
    else:
        linha.append("--no-audio")

    # -- a sessao em si ------------------------------------------------------
    if sessao.get("apagar_tela"):
        linha.append("--turn-screen-off")
    if _numero(sessao.get("tempo_tela_s")) > 0:
        # Mantem o celular acordado durante a sessao sem mexer no ajuste
        # permanente do aparelho.
        linha.append("--screen-off-timeout=%d" % _numero(sessao["tempo_tela_s"]))
    if sessao.get("sem_protetor_de_tela"):
        linha.append("--disable-screensaver")
    if sessao.get("gravar_em"):
        linha.append("--record=%s" % sessao["gravar_em"])

    return linha


def _numero(valor) -> int:
    """Um inteiro a partir do que estiver no config. Lixo vira 0."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 0


class Sessao:
    """Um scrcpy rodando (ou nao) para um perfil."""

    def __init__(self, nome: str) -> None:
        self.nome = nome
        self.processo = None
        self.linha: list = []
        self.arquivo_log = None
        self._saida = None
        self.serial = ""
        # Tempo de tela do celular ANTES de qualquer scrcpy mexer nele (ms),
        # lido na primeira partida de um perfil que estica o tempo. So a
        # troca sem desligar precisa dele (ver `Programa._troca`).
        self.tempo_original = None
        # O que fazer depois que o processo cair de vez (chamado uma vez, pelo
        # `parar`). Usado pela troca para devolver o tempo de tela.
        self.depois_de_parar = None

    # (r138) Cada pergunta le `self.processo` UMA vez: o `parar`, de outra
    # thread, zera o campo, e ler duas vezes (conferir e usar) derrubava
    # quem perguntou no meio (vigia do foco, o manter-no-app).

    @property
    def pid(self) -> int:
        p = self.processo
        return p.pid if p is not None else 0

    # -- estado --------------------------------------------------------------

    @property
    def rodando(self) -> bool:
        p = self.processo
        return p is not None and p.poll() is None

    @property
    def terminou_sozinho(self) -> bool:
        """Subiu, mas ja nao esta mais de pe."""
        p = self.processo
        return p is not None and p.poll() is not None

    @property
    def codigo_saida(self):
        p = self.processo
        return p.poll() if p is not None else None

    # -- ligar e desligar ----------------------------------------------------

    def iniciar(self, scrcpy_exe, serial: str, perfil: dict, pasta_log,
                icone=None, extras=(), sem=(), nome_log=None,
                ambiente_extra=None) -> bool:
        """
        Sobe o scrcpy com o perfil dado. Devolve se o processo chegou a nascer
        -- nao se a sessao vai dar certo, que so o proprio scrcpy sabe alguns
        segundos depois.

        `icone` e o caminho de um .png para a janela do espelhamento. O scrcpy
        so aceita isso por variavel de ambiente, lida na partida -- nao ha
        opcao de linha de comando para o icone.

        `extras` entra no fim da linha; `sem` tira as opcoes que comecam com
        um desses textos; `nome_log` troca o arquivo do log. Os tres sao da
        troca sem desligar: dois scrcpy do mesmo perfil vivem juntos por um
        instante, e cada um precisa do seu log.
        """
        if self.rodando:
            return True

        self.linha = montar(scrcpy_exe, serial, perfil)
        if sem:
            self.linha = [a for a in self.linha
                          if not any(str(a).startswith(t) for t in sem)]
        self.linha += list(extras or ())
        self.serial = serial
        self.arquivo_log = Path(pasta_log) / (nome_log or
                                              "log_%s.txt" % self.nome)

        # Log novo a cada execucao: o de ontem nao ajuda a entender o de hoje,
        # e um arquivo que so cresce vira ilegivel.
        try:
            self._saida = open(self.arquivo_log, "w", encoding="utf-8", errors="replace")
            self._saida.write("=== %s ===\n" % time.strftime("%d/%m/%Y %H:%M:%S"))
            self._saida.write(" ".join(self.linha) + "\n\n")
            self._saida.flush()
        except Exception:
            self._saida = None

        ambiente = None
        if icone or ambiente_extra:
            ambiente = dict(os.environ)
        if icone:
            # (r158) O scrcpy 4.0 le SCRCPY_ICON_DIR (pasta com scrcpy.png);
            # os mais velhos, SCRCPY_ICON_PATH (o arquivo). Vao as duas.
            icone = Path(icone)
            if icone.is_dir():
                ambiente["SCRCPY_ICON_DIR"] = str(icone)
                ambiente["SCRCPY_ICON_PATH"] = str(icone / "scrcpy.png")
            else:
                ambiente["SCRCPY_ICON_PATH"] = str(icone)
        if ambiente_extra:
            # (r158) Janela propria de app: o exe e outro, e o adb e o
            # servidor do scrcpy de verdade vao pelas variaveis dele.
            ambiente.update({k: str(v) for k, v in ambiente_extra.items()})

        try:
            self.processo = subprocess.Popen(
                self.linha,
                stdout=self._saida or subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                cwd=str(Path(scrcpy_exe).parent),
                creationflags=SEM_JANELA | ACIMA_DO_NORMAL,
                env=ambiente,
            )
            return True
        except Exception as erro:
            log.warning("nao consegui subir o scrcpy: %s", erro)
            self._fechar_log()
            self.processo = None
            return False

    def parar(self) -> None:
        """
        Pede pro scrcpy sair; se ele nao sair, derruba.

        Pode ser chamado de duas threads ao mesmo tempo (desligar no meio de
        uma troca): trabalha numa copia local do processo.
        """
        processo = self.processo
        if processo is None:
            self._fechar_log()
            self._rodar_depois()
            return

        if processo.poll() is None:
            pid = processo.pid
            # Sem /F: isso e um pedido, e e o que deixa o scrcpy fazer a
            # limpeza dele antes de sair.
            #
            # SO QUANDO HA JANELA. O pedido educado do taskkill e uma mensagem
            # de "fechar" para as janelas do processo; o modo so-som sobe sem
            # janela nenhuma, e ali o pedido falha na hora e so custaria a
            # espera inteira. Sem tela, nao ha nada na tela para restaurar.
            if "--no-window" not in self.linha:
                _taskkill(["taskkill", "/PID", str(pid)])
                fim = time.time() + ESPERA_PARA_SAIR
                while time.time() < fim and processo.poll() is None:
                    time.sleep(0.1)
            if processo.poll() is None:
                _taskkill(["taskkill", "/F", "/T", "/PID", str(pid)])

        self._fechar_log()
        self.processo = None
        self._rodar_depois()

    def _rodar_depois(self) -> None:
        tarefa, self.depois_de_parar = self.depois_de_parar, None
        if tarefa is not None:
            try:
                tarefa()
            except Exception:
                log.exception("falha no que vinha depois de parar %s", self.nome)

    def _fechar_log(self) -> None:
        try:
            if self._saida:
                self._saida.close()
        except Exception:
            pass
        self._saida = None

    def ultimas_linhas_do_log(self, quantas: int = 12) -> str:
        """O fim do log, pro relatorio nao depender de ninguem abrir arquivo."""
        try:
            if not self.arquivo_log or not Path(self.arquivo_log).exists():
                return "(sem log)"
            linhas = Path(self.arquivo_log).read_text(
                encoding="utf-8", errors="replace").splitlines()
            return "\n".join(linhas[-quantas:]) or "(log vazio)"
        except Exception as erro:
            return "(nao consegui ler o log: %s)" % erro


def _taskkill(argumentos) -> None:
    try:
        subprocess.run(argumentos, capture_output=True, timeout=10,
                       creationflags=SEM_JANELA)
    except Exception:
        pass
