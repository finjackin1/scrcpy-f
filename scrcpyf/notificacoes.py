"""
AS NOTIFICACOES DO CELULAR NO PC (pedido dele, 01/out/2026).

Sem app instalado no celular. A sonda de 01/out (Android 16, S22) mostrou o
que o shell do adb pode:
  - `cmd notification list` (as chaves) e `cmd notification get <chave>`
    (titulo e texto inteiros, sem esconder) -- a lista pela API pede
    ACCESS_NOTIFICATIONS, que o shell NAO tem;
  - o logcat de EVENTOS diz na hora quando uma chega (notification_enqueue)
    ou sai (notification_cancel / _cancel_all);
  - apps bloqueados: `dumpsys notification` -> "AppSettings: <pacote> (<uid>)
    importance=NONE";
  - remover: o jar `scrcpyf-notif.jar` faz o mesmo que arrastar a notificacao
    na barra do celular (IStatusBarService.onNotificationClear);
  - o historico do Android e NEGADO: o historico daqui e o que o programa ve.

Como roda: duas conversas `adb shell` de pe por celular -- uma so lendo os
eventos, outra obedecendo pedidos ("l" lista, "g <chave>" detalhe, "b"
bloqueados). A cada evento (juntando os de uma rajada) a lista e relida e so
o que e novo ou mudou e detalhado. Uma conferencia completa a cada 20 s
cobre evento perdido. Nada aqui toca em Tk: a janela le o estado e esvazia a
fila de avisos (`proximos_avisos`) na thread dela.

AS CHAVES (pedido dele): a GERAL e o padrao; a de cada app, a excecao. App
desligado no PC nao avisa e nao aparece na aba; o historico guarda todos.
Nada disso muda o celular.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import subprocess
import threading
import time

from . import caminhos

log = logging.getLogger(__name__)

SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MARCA = "scrcpyf_notif"
# Mata no celular as conversas desta parte (as de agora e sobras). Os
# colchetes fazem o proprio pkill nao casar com o padrao.
MATAR = "pkill -f 'scrcpyf_noti[f]' ; true"
JAR_NO_CELULAR = "/data/local/tmp/scrcpyf-notif.jar"
HISTORICO_HORAS = 24
HISTORICO_MAX = 500
CONFERENCIA_S = 20.0
JUNTAR_RAJADA_S = 0.15

# A conversa que obedece pedidos (uma linha por pedido, "@fim" no fim de
# cada resposta). O `M=` deixa a marca na linha de comando (pkill).
SERVIDOR = (
    "M=%s; "
    "g(){ cmd notification get \"$1\" | sed -n -e '/^  uid=/p' "
    "-e '/^  flags=/p' -e '/^    when=/p' -e '/^    extras={/,/^    }/p'; }; "
    "while read c a; do case $c in "
    "l) cmd notification list;; "
    "g) echo \"@k $a\"; g \"$a\";; "
    "b) dumpsys notification | grep 'AppSettings:' | grep 'importance=NONE';; "
    "esac; echo @fim; done" % MARCA)
EVENTOS = ("logcat -b events -v epoch -T 1 -s notification_enqueue:I "
           "notification_cancel:I notification_cancel_all:I %s:S" % MARCA)

# Flags do Android (como o `cmd notification get` escreve).
FIXAS = {"ONGOING_EVENT", "FOREGROUND_SERVICE", "NO_CLEAR"}

NOMES_DO_SISTEMA = {"android": "sistema android",
                    "com.android.systemui": "interface do sistema"}


class Notif:
    """Uma notificacao ativa no celular."""

    __slots__ = ("chave", "pacote", "usuario", "quando", "titulo", "texto",
                 "subtexto", "flags")

    def __init__(self, chave: str, pacote: str, usuario: int, quando: int,
                 titulo: str, texto: str, subtexto: str, flags: set) -> None:
        self.chave = chave
        self.pacote = pacote
        self.usuario = usuario
        self.quando = quando
        self.titulo = titulo
        self.texto = texto
        self.subtexto = subtexto
        self.flags = flags

    @property
    def app(self) -> str:
        """A chave do app no programa: "pacote" ou "pacote@usuario" (copia)."""
        return self.pacote if self.usuario <= 0 else \
            "%s@%d" % (self.pacote, self.usuario)

    @property
    def fixa(self) -> bool:
        return bool(self.flags & FIXAS)

    @property
    def limpavel(self) -> bool:
        return not (self.flags & {"ONGOING_EVENT", "NO_CLEAR"})

    @property
    def resumo(self) -> bool:
        return "GROUP_SUMMARY" in self.flags

    def conteudo(self) -> tuple:
        return (self.titulo, self.texto, self.subtexto)


# ---------------------------------------------------------------------------
# Leitura do que o celular escreve
# ---------------------------------------------------------------------------

_VALOR = re.compile(r"^[\w.$\[\]]+ \((.*)\)$", re.S)


def _valor(bruto: str) -> str:
    bruto = bruto.strip()
    if bruto in ("null", ""):
        return ""
    m = _VALOR.match(bruto)
    return (m.group(1) if m else bruto).strip()


def ler_detalhe(chave: str, texto: str) -> Notif | None:
    """O que o `g` devolve (linhas do `cmd notification get`) -> Notif."""
    partes = chave.split("|")
    if len(partes) < 5:
        return None
    pacote = partes[1]
    usuario = 0
    quando = 0
    flags: set = set()
    extras: dict = {}
    atual = None
    dentro = False
    for linha in texto.replace("\r", "").split("\n"):
        if linha.startswith("    extras={"):
            dentro = True
            continue
        if dentro:
            if linha.startswith("    }"):
                dentro = False
                atual = None
                continue
            m = re.match(r"^ {8}(\S+?)=(.*)$", linha)
            if m:
                atual = m.group(1)
                extras[atual] = m.group(2)
            elif atual is not None:
                extras[atual] += "\n" + linha
            continue
        m = re.match(r"^  uid=(\d+) userId=(-?\d+)", linha)
        if m:
            usuario = int(m.group(1)) // 100000
            continue
        if linha.startswith("  flags="):
            flags = {f for f in linha.split("=", 1)[1].strip().split("|")
                     if f and f != "0"}
            continue
        m = re.match(r"^    when=(\d+)", linha)
        if m:
            quando = int(m.group(1))
    if not extras and not flags and not quando:
        return None
    titulo = _valor(extras.get("android.title", "")) or \
        _valor(extras.get("android.title.big", ""))
    texto_ = _valor(extras.get("android.bigText", "")) or \
        _valor(extras.get("android.text", ""))
    return Notif(chave, pacote, usuario, quando or int(time.time() * 1000),
                 titulo, texto_, _valor(extras.get("android.subText", "")),
                 flags)


def ler_evento(linha: str) -> tuple[str, str]:
    """
    Uma linha do logcat de eventos -> (tipo, chave). tipo = "chegou" (com a
    chave da notificacao), "saiu" (idem), "tudo" (saiu tudo de um app; chave
    vazia) ou "" (nao e evento). A chave segue o formato do
    `cmd notification list`: usuario|pacote|id|tag|uid.
    """
    m = re.search(r"notification_(enqueue|cancel_all|cancel): \[(.*)", linha)
    if not m:
        return "", ""
    tipo = {"enqueue": "chegou", "cancel": "saiu",
            "cancel_all": "tudo"}[m.group(1)]
    if tipo == "tudo":
        return tipo, ""
    c = m.group(2).split(",")
    if len(c) < 6:
        return tipo, ""
    uid, _pid, pacote, ident, tag, usuario = (x.strip() for x in c[:6])
    tag = "null" if tag in ("NULL", "") else tag
    return tipo, "%s|%s|%s|%s|%s" % (usuario, pacote, ident, tag, uid)


def ler_bloqueados(texto: str) -> set:
    """Linhas "AppSettings: <pacote> (<uid>) importance=NONE" -> {"app"}
    (com "@usuario" para copias)."""
    saida = set()
    for linha in texto.split("\n"):
        m = re.search(r"AppSettings: (\S+) \((\d+)\) importance=NONE", linha)
        if m:
            usuario = int(m.group(2)) // 100000
            saida.add(m.group(1) if usuario == 0 else
                      "%s@%d" % (m.group(1), usuario))
    return saida


# ---------------------------------------------------------------------------
# A central
# ---------------------------------------------------------------------------

class Central:
    """
    Estado das notificacoes de UM celular por vez. `garantir(serial)` e
    chamado a cada giro do programa: sobe, troca de celular ou para.
    """

    def __init__(self, adb, config, anotar, ao_mudar,
                 pasta_do_celular, pode_avisar=None) -> None:
        self._adb = adb                   # funcao -> caminho do adb
        self.config = config
        self.anotar = anotar
        self.ao_mudar = ao_mudar          # (sem argumentos; outra thread)
        self._pasta = pasta_do_celular    # funcao -> Path | None
        self.pode_avisar = pode_avisar    # funcao(app) -> bool (janela na frente?)
        self._trava = threading.RLock()
        self.ativas: dict[str, Notif] = {}
        self.historico: list[dict] = []
        self.bloqueados: set = set()
        self.versao = 0                   # muda a cada mudanca (a janela compara)
        self._avisos: "queue.Queue[Notif]" = queue.Queue()
        self._serial = ""
        self._geracao = 0
        self._procs: list = []
        self._sujo = threading.Event()
        self._pedidas: set = set()        # chaves com "chegou" (podem ter mudado)
        self._servidor = None
        self._srv_trava = threading.Lock()
        self._pronto = False              # 1a leitura feita (antes nao avisa)
        self._tentou_em = 0.0
        self._jar_pronto = ""             # serial onde o jar ja foi posto

    # -- vida -----------------------------------------------------------------

    def garantir(self, serial: str) -> None:
        if serial == self._serial and (not serial or self._vivo()):
            return
        if serial == self._serial and time.monotonic() - self._tentou_em < 5:
            return                       # caiu: espera um pouco e tenta de novo
        self.parar()
        if not serial:
            return
        self._serial = serial
        self._tentou_em = time.monotonic()
        self._geracao += 1
        self._carregar_historico()
        threading.Thread(target=self._subir, args=(serial, self._geracao),
                         daemon=True, name="notif").start()

    def _vivo(self) -> bool:
        return bool(self._procs) and all(p.poll() is None for p in self._procs)

    def parar(self, esperar: bool = False) -> None:
        """Derruba as conversas. A faxina no celular (matar o adb do PC nao
        mata o de la) roda numa thread -- `garantir` e chamado na thread da
        janela e um celular que saiu faria o `adb shell` esperar ate 5 s;
        no encerramento (`esperar=True`) espera, antes do kill-server."""
        serial, self._serial = self._serial, ""
        self._geracao += 1
        procs, self._procs = self._procs, []
        self._servidor = None
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        if serial and procs:
            faxina = threading.Thread(
                target=self._rodar,
                args=([str(self._adb()), "-s", serial, "shell", MATAR], 5),
                daemon=True, name="notif-faxina")
            faxina.start()
            if esperar:
                faxina.join(6)
        with self._trava:
            mudou = bool(self.ativas)
            self.ativas = {}
            self._pronto = False
        if mudou:
            self._mudou()

    def _rodar(self, args, espera=15) -> str:
        try:
            r = subprocess.run(args, capture_output=True, timeout=espera,
                               creationflags=SEM_JANELA)
            return (r.stdout or b"").decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _subir(self, serial: str, geracao: int) -> None:
        adb = str(self._adb())
        self._rodar([adb, "-s", serial, "shell", MATAR], 5)  # sobras
        try:
            srv = subprocess.Popen([adb, "-s", serial, "shell", SERVIDOR],
                                   stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL,
                                   creationflags=SEM_JANELA)
            ev = subprocess.Popen([adb, "-s", serial, "shell", EVENTOS],
                                  stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL,
                                  creationflags=SEM_JANELA)
        except Exception as erro:
            self.anotar("notificacoes: nao subiu (%s)" % erro)
            return
        if geracao != self._geracao:
            for p in (srv, ev):
                p.terminate()
            return
        self._servidor = srv
        self._procs = [srv, ev]
        self.anotar("notificacoes: no ar (%s)" % serial)
        threading.Thread(target=self._ler_eventos, args=(ev, geracao),
                         daemon=True, name="notif-eventos").start()
        self._trabalhar(geracao)

    # -- conversa -------------------------------------------------------------

    def _pedir(self, pedido: str, espera: float = 8.0) -> list[str]:
        """Manda um pedido a conversa de pe e devolve as linhas da resposta."""
        with self._srv_trava:
            srv = self._servidor
            if srv is None or srv.poll() is not None:
                return []
            try:
                srv.stdin.write((pedido + "\n").encode("utf-8"))
                srv.stdin.flush()
            except Exception:
                return []
            linhas = []
            fim = time.monotonic() + espera
            while time.monotonic() < fim:
                bruta = srv.stdout.readline()
                if not bruta:
                    break
                linha = bruta.decode("utf-8", errors="replace").rstrip("\r\n")
                if linha == "@fim":
                    return linhas
                linhas.append(linha)
            return linhas

    def _ler_eventos(self, proc, geracao: int) -> None:
        try:
            for bruta in proc.stdout:
                if geracao != self._geracao:
                    break
                tipo, chave = ler_evento(bruta.decode("utf-8", errors="replace"))
                if not tipo:
                    continue
                if tipo == "chegou" and chave:
                    with self._trava:
                        self._pedidas.add(chave)
                self._sujo.set()
        except Exception:
            log.exception("notificacoes: leitor de eventos")

    # -- o trabalho -----------------------------------------------------------

    def _trabalhar(self, geracao: int) -> None:
        ultima = 0.0
        self._sujo.set()                 # a primeira leitura, completa
        completa = True
        while geracao == self._geracao:
            acordou = self._sujo.wait(timeout=1.0)
            if geracao != self._geracao:
                break
            if not acordou and time.monotonic() - ultima < CONFERENCIA_S:
                continue
            if acordou:
                time.sleep(JUNTAR_RAJADA_S)   # junta a rajada de eventos
            self._sujo.clear()
            try:
                self._reler(completa)
            except Exception:
                log.exception("notificacoes: releitura")
            if completa:
                self._ler_bloqueados()
            completa = False
            ultima = time.monotonic()
            if self._servidor is None or self._servidor.poll() is not None:
                self.anotar("notificacoes: a conversa com o celular caiu")
                break

    def _reler(self, completa: bool) -> None:
        chaves = [x.strip() for x in self._pedir("l") if x.strip().count("|") >= 4]
        srv = self._servidor
        if srv is None or srv.poll() is not None:
            return                       # caiu: lista vazia nao e "saiu tudo"
        with self._trava:
            antigas = dict(self.ativas)
            pedidas, self._pedidas = self._pedidas, set()
        detalhar = [c for c in chaves
                    if completa or c not in antigas or c in pedidas]
        novas = {c: antigas[c] for c in chaves if c in antigas}
        for chave in detalhar:
            linhas = self._pedir("g " + chave)
            n = ler_detalhe(chave, "\n".join(linhas[1:] if linhas and
                                             linhas[0].startswith("@k ")
                                             else linhas))
            if n is not None:
                novas[chave] = n
        chegaram = [n for c, n in novas.items()
                    if c not in antigas or antigas[c].conteudo() != n.conteudo()]
        sairam = [n for c, n in antigas.items() if c not in novas]
        if not chegaram and not sairam and self._pronto:
            return
        with self._trava:
            self.ativas = novas
            primeira = not self._pronto
            self._pronto = True
        agora = int(time.time() * 1000)
        for n in chegaram:
            if not n.fixa and not n.resumo:
                self._guardar_no_historico(n)
                if not primeira and self.ligada(n.app) and \
                        (self.pode_avisar is None or self.pode_avisar(n.app)):
                    self._avisos.put(n)
        for n in sairam:
            self._marcar_saida(n, agora)
        # Fixa que so se atualiza ("carregando: 2 h 55 min", a cada ~40 s)
        # nao vai para o log nem para o historico.
        importa = [n for n in chegaram if not n.fixa] + sairam
        if importa or primeira:
            self._salvar_historico()
            self.anotar("notificacoes: %d no celular (+%d -%d)%s"
                        % (len(novas), len(chegaram), len(sairam),
                           " [1a leitura]" if primeira else ""))
        self._mudou()

    def _ler_bloqueados(self) -> None:
        bloq = ler_bloqueados("\n".join(self._pedir("b", espera=15)))
        with self._trava:
            mudou = bloq != self.bloqueados
            self.bloqueados = bloq
        if mudou:
            self._mudou()

    def reler_bloqueados(self) -> None:
        """A aba de ajustes abriu: confere de novo (numa thread)."""
        if self._servidor is not None:
            threading.Thread(target=self._ler_bloqueados, daemon=True,
                             name="notif-bloq").start()

    def _mudou(self) -> None:
        self.versao += 1
        try:
            self.ao_mudar()
        except Exception:
            log.exception("notificacoes: ao_mudar")

    # -- o que a janela usa ---------------------------------------------------

    def ligada(self, app: str) -> bool:
        """A chave do app no PC: a dele, senao a geral."""
        return self.config.notif_do_app(app)

    def visiveis(self) -> list[Notif]:
        """As da aba: de apps ligados, sem o resumo de grupo que tem filhas;
        mais novas primeiro."""
        with self._trava:
            todas = list(self.ativas.values())
        com_filhas = {n.app for n in todas if not n.resumo}
        lista = [n for n in todas if self.ligada(n.app)
                 and not (n.resumo and n.app in com_filhas)]
        lista.sort(key=lambda n: n.quando, reverse=True)
        return lista

    def contagem(self) -> int:
        """O numero do contador: as visiveis que nao sao fixas."""
        return sum(1 for n in self.visiveis() if not n.fixa)

    def proximos_avisos(self) -> list[Notif]:
        saida = []
        while True:
            try:
                saida.append(self._avisos.get_nowait())
            except queue.Empty:
                return saida

    def esta_ativa(self, chave: str) -> bool:
        with self._trava:
            return chave in self.ativas

    def remover(self, chaves, avisar=None) -> None:
        """
        Tira do celular (numa thread). Some do PC na hora; se o celular nao
        tirar, a proxima releitura a traz de volta e o motivo vai pro log.
        """
        chaves = [c for c in chaves if c]
        serial = self._serial
        if not chaves or not serial:
            return
        with self._trava:
            tiradas = [self.ativas.pop(c) for c in chaves if c in self.ativas]
        if tiradas:
            self._marcar_e_salvar(tiradas)
            self._mudou()

        def trabalho():
            adb = str(self._adb())
            if self._jar_pronto != serial:
                from pathlib import Path
                jar = Path(caminhos.pasta_interna()) / "android" / \
                    "scrcpyf-notif.jar"
                self._rodar([adb, "-s", serial, "push", str(jar),
                             JAR_NO_CELULAR], 20)
                self._jar_pronto = serial
            # Todas de uma vez: subir o jar custa ~1 s.
            args = " ".join("'%s'" % c.replace("'", "'\\''") for c in chaves)
            saida = self._rodar(
                [adb, "-s", serial, "shell",
                 "CLASSPATH=%s app_process / scrcpyf.Notif remover %s"
                 % (JAR_NO_CELULAR, args)], 15 + 3 * len(chaves)).strip()
            falhas = [x for x in saida.split("\n")
                      if not x.startswith("removido")]
            self.anotar("notificacoes: remover %d -> %s"
                        % (len(chaves), (" / ".join(falhas) or "ok")[:300]
                           if saida else "(sem resposta)"))
            if falhas or not saida:
                self._sujo.set()             # volta pra lista se nao saiu
                if avisar is not None:
                    avisar("não consegui remover do celular")

        threading.Thread(target=trabalho, daemon=True,
                         name="notif-remover").start()

    # -- historico ------------------------------------------------------------

    def _arquivo_historico(self):
        pasta = self._pasta()
        return None if pasta is None else pasta / "notificacoes.json"

    def _carregar_historico(self) -> None:
        arq = self._arquivo_historico()
        dados = []
        if arq is not None:
            try:
                dados = json.loads(arq.read_text(encoding="utf-8"))
            except Exception:
                dados = []
        with self._trava:
            self.historico = [d for d in dados if isinstance(d, dict)]
            self._podar()

    def _podar(self) -> None:
        limite = int(time.time() * 1000) - HISTORICO_HORAS * 3600 * 1000
        self.historico = [d for d in self.historico
                          if int(d.get("quando") or 0) >= limite][-HISTORICO_MAX:]

    def _guardar_no_historico(self, n: Notif) -> None:
        with self._trava:
            for d in reversed(self.historico[-50:]):
                if d.get("chave") == n.chave and d.get("titulo") == n.titulo \
                        and d.get("texto") == n.texto:
                    return                    # a mesma, relida
            self.historico.append({"chave": n.chave, "app": n.app,
                                   "titulo": n.titulo, "texto": n.texto,
                                   "quando": n.quando, "saiu": 0})
            self._podar()

    def _marcar_saida(self, n: Notif, agora: int) -> None:
        with self._trava:
            for d in reversed(self.historico):
                if d.get("chave") == n.chave and not d.get("saiu"):
                    d["saiu"] = agora
                    break

    def _marcar_e_salvar(self, lista) -> None:
        agora = int(time.time() * 1000)
        for n in lista:
            self._marcar_saida(n, agora)
        self._salvar_historico()

    def _salvar_historico(self) -> None:
        arq = self._arquivo_historico()
        if arq is None:
            return
        with self._trava:
            dados = json.dumps(self.historico, ensure_ascii=False)
        try:
            novo = arq.with_suffix(".novo")
            novo.write_text(dados, encoding="utf-8")
            novo.replace(arq)
        except Exception:
            log.exception("notificacoes: gravar historico")

    def limpar_historico(self) -> None:
        with self._trava:
            self.historico = []
        self._salvar_historico()
        self._mudou()

    def historico_visivel(self) -> list[dict]:
        """Mais novo primeiro (o historico guarda todos os apps)."""
        with self._trava:
            self._podar()
            return list(reversed(self.historico))


def nome_de_sistema(pacote: str) -> str:
    return NOMES_DO_SISTEMA.get(pacote, "")
