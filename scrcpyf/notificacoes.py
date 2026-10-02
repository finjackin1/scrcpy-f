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
MATAR = ("pkill -f 'scrcpyf_noti[f]' ; pkill -f 'scrcpyf.Midi[a]' ; true")
JAR_NO_CELULAR = "/data/local/tmp/scrcpyf-notif.jar"
HISTORICO_HORAS = 24
HISTORICO_MAX = 500
# (02/out, revisao) Era 20 s: os eventos do logcat ja trazem cada mudanca
# na hora; a conferencia e so a rede de seguranca e acordava o celular
# (CPU e Wi-Fi) 3x por minuto, mesmo de tela apagada.
CONFERENCIA_S = 60.0
FIXA_ESPERA_S = 5.0               # (02/out) fixa que se atualiza: 1 G / 5 s
JUNTAR_RAJADA_S = 0.03            # (01/out) era 0,15: o atraso era sentido

# A conversa que obedece pedidos (uma linha por pedido, "@fim" no fim de
# cada resposta). O `M=` deixa a marca na linha de comando (pkill).
SERVIDOR = (
    "M=%s; "
    # `</dev/null`: o `cmd` do Android repassa a entrada ao servico -- dentro
    # do lote ("G") ele nao pode ler as chaves seguintes.
    "g(){ cmd notification get \"$1\" </dev/null | sed -n "
    "-e '/^NotificationRecord(/p' -e '/^  uid=/p' "
    "-e '/^  flags=/p' -e '/^    when=/p' -e '/^    contentIntent=/p' "
    "-e '/^    actions={/,/^      }/p' "
    "-e '/^    extras={/,/^    }/p'; }; "
    "while read c a; do case $c in "
    "l) cmd notification list </dev/null;; "
    "g) echo \"@k $a\"; g \"$a\";; "
    # G: varias chaves numa ida so (uma por linha, "." no fim)
    "G) while read k; do if [ \"$k\" = . ]; then break; fi; "
    "echo \"@k $k\"; g \"$k\"; done;; "
    "b) dumpsys notification | grep 'AppSettings:' | grep 'importance=NONE';; "
    # p: a tela de "configuracoes de notificacao" do proprio app, se tiver
    "p) cmd package query-activities --brief -a android.intent.action.MAIN "
    "-c android.intent.category.NOTIFICATION_PREFERENCES \"$a\" </dev/null;; "
    # t: o estado da chamada (0 nada, 1 tocando, 2 em andamento)
    "t) dumpsys telephony.registry </dev/null | grep -m1 mCallState;; "
    "esac; echo @fim; done" % MARCA)
EVENTOS = ("logcat -b events -v epoch -T 1 -s notification_enqueue:I "
           "notification_cancel:I notification_cancel_all:I %s:S" % MARCA)

# Flags do Android (como o `cmd notification get` escreve).
FIXAS = {"ONGOING_EVENT", "FOREGROUND_SERVICE", "NO_CLEAR"}

NOMES_DO_SISTEMA = {"android": "sistema android",
                    "com.android.systemui": "interface do sistema",
                    "com.samsung.android.incallui": "telefone",
                    "com.android.incallui": "telefone",
                    "com.android.server.telecom": "telefone"}


class Notif:
    """Uma notificacao ativa no celular."""

    __slots__ = ("chave", "pacote", "usuario", "quando", "titulo", "texto",
                 "subtexto", "flags", "sdk", "alvo", "canal", "acoes",
                 "categoria", "modelo")

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
        self.sdk = 0                      # o Android do celular (limpavel)
        # O que o toque no celular abre: (id do PendingIntentRecord, pacote,
        # tipo) do "contentIntent=" -- o destino de verdade se le na hora
        # do clique (`Central.destino`). None = a notificacao nao abre nada.
        self.alvo = None
        self.canal = ""                   # a categoria (canal) do Android
        # Os botoes: [(rotulo, (id, pacote, tipo))] -- so os de tipo
        # startActivity viram botao no PC (os outros so o celular aciona).
        self.acoes: list = []
        self.categoria = ""               # "msg", "call", "transport"...
        self.modelo = ""                  # MediaStyle, MessagingStyle...

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
        """
        Da para tirar, como no celular? (teste dele, 01/out: o "limpar tudo"
        do PC dizia "fixas" e o celular as tirava.) DESDE O ANDROID 14 (API
        34) o celular deixa dispensar as "fixas" (ONGOING/NO_CLEAR) -- so nao
        sai o que o sistema marca NO_DISMISS (chamada, empresa...). Testado
        no S22 (Android 16): o jar tirou a "carregando" (ONGOING_EVENT).
        Antes do 14 vale a regra antiga.
        """
        if self.sdk >= 34:
            return "NO_DISMISS" not in self.flags
        return not (self.flags & {"ONGOING_EVENT", "NO_CLEAR"})

    @property
    def resumo(self) -> bool:
        return "GROUP_SUMMARY" in self.flags

    @property
    def interna(self) -> bool:
        """(02/out, teste no S22) A "MediaOngoingActivity" da interface do
        sistema: a Samsung a cria quando toca musica (Now Bar), sem texto --
        so o nome do canal. O player ja mostra a musica; no PC ela nao entra."""
        return self.pacote == "com.android.systemui" and \
            self.canal.endswith("OngoingActivity")

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
    alvo = None
    canal = ""
    categoria = ""
    acoes: list = []
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
            continue
        # (02/out) Sem exigir o "}" logo depois do tipo: o Android 16 poe
        # " (allowlist: ...)" ali, e o clique abria so a tela inicial.
        m = re.search(r"contentIntent=PendingIntent\{\w+: PendingIntentRecord"
                      r"\{(\w+) (\S+) (\w+)", linha)
        if m:
            alvo = (m.group(1), m.group(2), m.group(3))
            continue
        m = re.match(r'^\s+\[\d+\] "(.*)" -> PendingIntent\{\w+: '
                     r'PendingIntentRecord\{(\w+) (\S+) (\w+)', linha)
        if m:
            acoes.append((m.group(1), (m.group(2), m.group(3), m.group(4))))
            continue
        if linha.startswith("NotificationRecord("):
            m = re.search(r"Notification\(channel=([^ )]+)", linha)
            if m and m.group(1) != "null":
                canal = m.group(1)
            m = re.search(r" category=(\w+)", linha)
            if m:
                categoria = m.group(1)
    if not extras and not flags and not quando:
        return None
    titulo = _valor(extras.get("android.title", "")) or \
        _valor(extras.get("android.title.big", ""))
    texto_ = _valor(extras.get("android.bigText", "")) or \
        _valor(extras.get("android.text", ""))
    n = Notif(chave, pacote, usuario, quando or int(time.time() * 1000),
              titulo, texto_, _valor(extras.get("android.subText", "")),
              flags)
    n.alvo = alvo
    n.canal = canal
    n.acoes = acoes
    n.categoria = categoria
    n.modelo = _valor(extras.get("android.template", "")).rsplit("$", 1)[-1]
    return n


# (01/out) CODIGO DE VERIFICACAO: 4 a 8 digitos (com hifen/espaco no meio)
# numa notificacao que fala em codigo. O botao "copiar codigo" copia SO os
# digitos.
_PALAVRAS_CODIGO = re.compile(
    r"c[oó]digo|code|verifica|senha|\bpin\b|\botp\b|token|autentica"
    r"|confirma[cç][aã]o", re.I)
_CODIGO = re.compile(r"(?<![\d\w])(\d{3,4}[- ]?\d{2,4}|\d{4,8})(?![\d\w])")


def codigo_de(n) -> str:
    """O codigo de verificacao da notificacao, ou ""."""
    texto = "%s %s" % (n.titulo, n.texto)
    if not _PALAVRAS_CODIGO.search(texto):
        return ""
    for m in _CODIGO.finditer(texto):
        digitos = re.sub(r"\D", "", m.group(1))
        if 4 <= len(digitos) <= 8:
            return digitos
    return ""


def botoes_de_tela(n) -> list:
    """Os botoes da notificacao que ABREM UMA TELA (startActivity) -- os
    unicos que o PC consegue repetir sem app no celular."""
    return [(rot, alvo) for rot, alvo in (n.acoes or [])
            if alvo and alvo[2] == "startActivity"]


def ler_destino(texto: str) -> dict:
    """
    A linha "requestIntent=..." do `dumpsys activity intents` -> {"act",
    "dat", "typ", "flg", "pkg", "cmp", "cat": [...]}. Os extras o Android
    nao mostra ("(has extras)"): o destino e a tela certa, mas o que vem
    dentro dela (a conversa exata, por exemplo) pode nao vir.
    """
    m = re.search(r"requestIntent=(.*)", texto)
    if not m:
        return {}
    linha = m.group(1)
    saida: dict = {"cat": []}
    cat = re.search(r"cat=\[([^\]]*)\]", linha)
    if cat:
        saida["cat"] = [c.strip() for c in cat.group(1).split(",") if c.strip()]
    for chave in ("act", "dat", "typ", "flg", "pkg", "cmp"):
        m = re.search(r"(?:^| )%s=(\S+)" % chave, linha)
        if m:
            saida[chave] = m.group(1)
    return saida


def argumentos_am(destino: dict) -> list[str]:
    """O destino -> argumentos do `am start` (sem --user/--display)."""
    args: list[str] = []
    if destino.get("act"):
        args += ["-a", destino["act"]]
    if destino.get("dat"):
        args += ["-d", destino["dat"]]
    if destino.get("typ"):
        args += ["-t", destino["typ"]]
    for c in destino.get("cat") or []:
        args += ["-c", c]
    if destino.get("cmp"):
        args += ["-n", destino["cmp"]]
    elif destino.get("pkg"):
        args += ["-p", destino["pkg"]]
    try:
        flg = int(destino.get("flg") or "0", 16)
    except ValueError:
        flg = 0
    args += ["-f", "0x%x" % (flg | 0x10000000)]       # NEW_TASK sempre
    return args


CONFIGURACOES = "com.android.settings"


def telas_da_notificacao(n, prefs: str = "") -> list:
    """
    (01/out, pedido dele) O que o Android oferece ao SEGURAR uma
    notificacao, como telas para abrir numa janela do PC: [(rotulo,
    janela, argumentos do am start)]. "desativar notificacoes" e
    "configuracoes" sao as telas das Configuracoes do Android (a do app e a
    da categoria/canal); "configuracoes do app" e a tela que o proprio app
    declara (NOTIFICATION_PREFERENCES -- os apps do sistema com configuracao
    propria); "informacoes do app" e a pagina do app.
    """
    pkg = n.pacote
    base = ["--es", "android.provider.extra.APP_PACKAGE", pkg]
    uid = n.chave.rsplit("|", 1)[-1]
    if n.usuario > 0 and uid.isdigit():
        base += ["--ei", "android.provider.extra.APP_UID", uid]
    novo = ["-f", "0x10000000"]
    do_app = ["-a", "android.settings.APP_NOTIFICATION_SETTINGS"] + base + novo
    telas = [("desativar notificações", CONFIGURACOES, do_app)]
    if n.canal:
        telas.append(("configurações", CONFIGURACOES,
                      ["-a", "android.settings.CHANNEL_NOTIFICATION_SETTINGS"]
                      + base + ["--es", "android.provider.extra.CHANNEL_ID",
                                n.canal] + novo))
    else:
        telas.append(("configurações", CONFIGURACOES, do_app))
    if prefs:
        telas.append(("configurações do app", n.app, ["-n", prefs] + novo))
    telas.append(("informações do app", CONFIGURACOES,
                  ["-a", "android.settings.APPLICATION_DETAILS_SETTINGS",
                   "-d", "package:" + pkg] + novo))
    return telas


def pacote_do_destino(destino: dict) -> str:
    cmp = destino.get("cmp") or ""
    return cmp.split("/")[0] if "/" in cmp else destino.get("pkg") or ""


def _separar_por_chave(linhas: list[str]):
    """A resposta do "G" ("@k <chave>" e as linhas dela, repetido) ->
    [(chave, texto)]."""
    saida, chave, junto = [], None, []
    for linha in linhas:
        if linha.startswith("@k "):
            if chave is not None:
                saida.append((chave, "\n".join(junto)))
            chave, junto = linha[3:].strip(), []
        elif chave is not None:
            junto.append(linha)
    if chave is not None:
        saida.append((chave, "\n".join(junto)))
    return saida


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
        self._eventos: list = []          # (tipo, chave, hora) do logcat
        self._detalhado_em: dict = {}     # chave -> ultimo "G" (fixas)
        self._adiadas: dict = {}          # chave -> quando pedir de novo
        self._medidas = 0                 # quantas chegadas ja medidas
        self.prefs: dict = {}             # pacote -> tela de config. propria
        self._servidor = None
        self._srv_trava = threading.Lock()
        self._pronto = False              # 1a leitura feita (antes nao avisa)
        self._tentou_em = 0.0
        self._jar_pronto = ""             # serial onde o jar ja foi posto
        self.sdk = 0                      # o Android do celular em uso
        self._fila = None                 # linhas da conversa (thread leitora)
        self._subindo = False             # _subir em andamento (nao reinicia)
        self._salvar_timer = None         # gravacao do historico agrupada
        self._a_remover: list = []        # chaves esperando o jar (em lote)
        self._removendo = False
        self._avisar_falha = None
        self._midia_proc = None
        self.midias: list = []            # fotos do player (ver _manter_midia)
        self.midias_versao = 0
        self.chamada = None               # Notif da chamada TOCANDO, ou None
        self._player_fechado = None       # (pacote, quando) do x do player
        # (01/out) Ganchos do Windows (central_windows, pelo programa):
        # ao_chegar(n) / ao_sair(n) / ao_limpar() / ao_player(m) -- de outra
        # thread; erro neles nao derruba nada (`_ganchos`).
        self.ao_chegar = self.ao_sair = self.ao_limpar = None
        self.ao_player = None

    # -- vida -----------------------------------------------------------------

    def garantir(self, serial: str, sdk: int = 0) -> None:
        if sdk and sdk != self.sdk:
            # A versao do Android chegou (ou mudou de celular): vale ja para
            # as que estao na lista (`Notif.limpavel` depende dela).
            self.sdk = sdk
            with self._trava:
                for n in self.ativas.values():
                    n.sdk = sdk
            self._mudou()
        if serial == self._serial and (not serial or self._vivo()
                                       or self._subindo):
            return
        if serial == self._serial and time.monotonic() - self._tentou_em < 5:
            return                       # caiu: espera um pouco e tenta de novo
        self.parar()
        if not serial:
            return
        self._serial = serial
        self._tentou_em = time.monotonic()
        self._geracao += 1
        self._subindo = True
        self._medidas = 0
        with self._trava:
            self._eventos = []
        self._carregar_historico()
        threading.Thread(target=self._subir, args=(serial, self._geracao),
                         daemon=True, name="notif").start()

    def todas(self) -> list:
        """As ativas, copiadas sob a trava (a janela le de outra thread)."""
        with self._trava:
            return list(self.ativas.values())

    def _vivo(self) -> bool:
        return bool(self._procs) and all(p.poll() is None for p in self._procs)

    def parar(self, esperar: bool = False) -> None:
        """Derruba as conversas. A faxina no celular (matar o adb do PC nao
        mata o de la) roda numa thread -- `garantir` e chamado na thread da
        janela e um celular que saiu faria o `adb shell` esperar ate 5 s;
        no encerramento (`esperar=True`) espera, antes do kill-server."""
        serial, self._serial = self._serial, ""
        self._geracao += 1
        self._subindo = False
        procs, self._procs = self._procs, []
        self._servidor = None
        self._salvar_agora()             # o que estava esperando para gravar
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
        midia, self._midia_proc = self._midia_proc, None
        if midia is not None:
            try:
                midia.terminate()
            except Exception:
                pass
        with self._trava:
            mudou = bool(self.ativas) or bool(self.midias) or \
                self.chamada is not None
            self.ativas = {}
            self.midias = []
            self.chamada = None
            self._pronto = False
        if mudou:
            self._mudou()
        self._avisar_player()                # sem celular: some do Windows
        if self.ao_limpar is not None and serial:
            self._ganchos(self.ao_limpar)

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
            self._subindo = False
            return
        if geracao != self._geracao:
            for p in (srv, ev):
                p.terminate()
            return
        fila: "queue.Queue[str | None]" = queue.Queue()
        threading.Thread(target=self._ler_servidor, args=(srv, fila),
                         daemon=True, name="notif-servidor").start()
        self._fila = fila
        self._servidor = srv
        self._procs = [srv, ev]
        self._subindo = False
        self.anotar("notificacoes: no ar (%s)" % serial)
        threading.Thread(target=self._ler_eventos, args=(ev, geracao),
                         daemon=True, name="notif-eventos").start()
        threading.Thread(target=self._manter_midia, args=(serial, geracao),
                         daemon=True, name="notif-midia").start()
        self._trabalhar(geracao)

    # -- o player (01/out) ----------------------------------------------------
    # `android\Midia.java` de pe ("vigiar"): escreve a foto das sessoes de
    # midia quando algo muda e obedece "c <pacote> <acao> [ms]". Caiu =
    # sobe de novo (o player nao derruba as notificacoes).

    def _por_jar(self, serial: str) -> bool:
        if self._jar_pronto == serial:
            return True
        from pathlib import Path
        jar = Path(caminhos.pasta_interna()) / "android" / "scrcpyf-notif.jar"
        if not jar.exists():
            return False
        self._rodar([str(self._adb()), "-s", serial, "push", str(jar),
                     JAR_NO_CELULAR], 20)
        self._jar_pronto = serial
        return True

    def _manter_midia(self, serial: str, geracao: int) -> None:
        falhas = 0
        while geracao == self._geracao and falhas < 20:
            if not self._por_jar(serial):
                return
            try:
                proc = subprocess.Popen(
                    [str(self._adb()), "-s", serial, "shell",
                     "CLASSPATH=%s app_process / scrcpyf.Midia vigiar"
                     % JAR_NO_CELULAR], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    creationflags=SEM_JANELA)
            except Exception as erro:
                self.anotar("player: nao subiu (%s)" % erro)
                return
            self._midia_proc = proc
            linhas: list = []
            subiu_em = time.monotonic()
            for bruta in proc.stdout:
                if geracao != self._geracao:
                    break
                linha = bruta.decode("utf-8", errors="replace").rstrip("\r\n")
                if linha == "vigia ok":
                    if falhas == 0:
                        self.anotar("player: no ar")
                elif linha.startswith("M\t"):
                    linhas.append(linha)
                elif linha == "fim":
                    self._chegou_foto_midia(linhas)
                    linhas = []
                elif linha.startswith("erro"):
                    self.anotar("player: %s" % linha[:200])
            if geracao != self._geracao:
                break
            # (02/out, revisao) Ficou de pe um bom tempo: a queda e nova, nao
            # a mesma de antes. Sem isto, 20 quedas somadas no dia (Wi-Fi que
            # oscila) matavam o player ate a proxima reconexao.
            if time.monotonic() - subiu_em > 120:
                falhas = 0
            falhas += 1
            self._jar_pronto = ""            # o jar pode ter saido do celular
            if falhas in (1, 5):
                self.anotar("player: caiu; subindo de novo (%dx)" % falhas)
            time.sleep(3)

    def _chegou_foto_midia(self, linhas: list) -> None:
        agora = time.monotonic()
        midias = []
        for linha in linhas:
            p = [c.replace("\\t", "\t").replace("\\n", " ").replace("\\\\", "\\")
                 for c in linha.split("\t")]
            if len(p) < 10:
                continue
            try:
                midias.append({
                    "pacote": p[1], "estado": int(p[2]), "pos": int(p[3]),
                    "dur": int(p[4]), "vel": float(p[5]), "acoes": int(p[6]),
                    "titulo": p[7], "artista": p[8], "album": p[9],
                    "recebido": agora})
            except ValueError:
                continue
        with self._trava:
            def sem_pos(lista):
                return [(m["pacote"], m["estado"], m["dur"], m["titulo"],
                         m["artista"]) for m in lista]
            mudou = sem_pos(midias) != sem_pos(self.midias)
            self.midias = midias
            self.midias_versao += 1          # a posicao (barra) se acerta
        if mudou:
            self._mudou()
        self._avisar_player()                # o Windows (e a posicao dele)

    def fechar_player(self, pacote: str) -> None:
        """
        (01/out, pedido dele) O x do player, como arrastar o player no
        celular: pausa (se toca), tira a notificacao de midia do app e some
        do PC. Volta sozinho quando o app tocar de novo (alguem deu play).
        """
        m = next((x for x in self.midias if x["pacote"] == pacote), None)
        if m is not None and m["estado"] == 3:
            self.midia_comando(pacote, "pause")
        with self._trava:
            self._player_fechado = (pacote, time.monotonic())
            chaves = [n.chave for n in self.ativas.values()
                      if n.pacote == pacote and n.modelo == "MediaStyle"]
        self.anotar("player: fechado (%s)" % pacote)
        if chaves:
            self.remover(chaves)
        self._mudou()
        self._avisar_player()

    def player(self) -> dict | None:
        """A sessao a mostrar: a que esta tocando; senao a pausada mais
        recente com musica. None = nada. A que foi fechada no x fica de fora
        ate tocar de novo."""
        with self._trava:
            lista = list(self.midias)
            fechado = self._player_fechado
        if fechado is not None:
            pkg, quando = fechado
            if any(m["pacote"] == pkg and m["estado"] == 3 for m in lista) \
                    and time.monotonic() - quando > 2.5:
                with self._trava:
                    self._player_fechado = None      # tocou de novo: volta
            else:
                lista = [m for m in lista if m["pacote"] != pkg]
        for m in lista:
            if m["estado"] == 3 and (m["titulo"] or m["dur"]):
                return m
        for m in lista:
            if m["estado"] in (2, 6, 8) and m["titulo"]:
                return m
        return None

    def posicao(self, m: dict) -> int:
        """A posicao AGORA (anda sozinha no PC enquanto toca)."""
        pos = m["pos"]
        if m["estado"] == 3:
            pos += int((time.monotonic() - m["recebido"]) * 1000 * m["vel"])
        return max(0, min(pos, m["dur"])) if m["dur"] else max(0, pos)

    def midia_comando(self, pacote: str, acao: str, ms: int = 0) -> None:
        proc = self._midia_proc
        if proc is None or proc.poll() is not None:
            self.anotar("player: %s sem o programinha no ar" % acao)
            return
        linha = "c %s %s%s\n" % (pacote, acao,
                                 (" %d" % ms) if acao == "seek" else "")
        try:
            proc.stdin.write(linha.encode())
            proc.stdin.flush()
        except Exception as erro:
            self.anotar("player: %s falhou (%s)" % (acao, erro))

    # -- conversa -------------------------------------------------------------

    @staticmethod
    def _ler_servidor(srv, fila) -> None:
        """Thread leitora: cada linha da conversa vai para a fila; None =
        a conversa acabou. Assim o `_pedir` espera COM PRAZO (antes um
        readline sem fim prendia tudo se o celular parasse de responder)."""
        try:
            for bruta in srv.stdout:
                fila.put(bruta.decode("utf-8", errors="replace").rstrip("\r\n"))
        except Exception:
            pass
        fila.put(None)

    def _pedir(self, pedido: str, espera: float = 8.0,
               entrada=()) -> list[str] | None:
        """
        Manda um pedido a conversa de pe (mais as linhas de `entrada`) e
        devolve as linhas da resposta. None = falhou: conversa caida, ou o
        celular nao respondeu no prazo -- ai a conversa e derrubada e o
        `garantir` sobe outra (melhor que ficar preso).
        """
        with self._srv_trava:
            srv, fila = self._servidor, self._fila
            if srv is None or fila is None or srv.poll() is not None:
                return None
            try:
                texto = "\n".join([pedido] + list(entrada)) + "\n"
                srv.stdin.write(texto.encode("utf-8"))
                srv.stdin.flush()
            except Exception:
                return None
            linhas = []
            fim = time.monotonic() + espera
            while True:
                resto = fim - time.monotonic()
                if resto <= 0:
                    self.anotar("notificacoes: o celular nao respondeu a '%s' "
                                "em %.0f s; refazendo a conversa"
                                % (pedido, espera))
                    try:
                        srv.terminate()
                    except Exception:
                        pass
                    return None
                try:
                    linha = fila.get(timeout=resto)
                except queue.Empty:
                    continue
                if linha is None:
                    return None
                if linha == "@fim":
                    return linhas
                linhas.append(linha)

    def _ler_eventos(self, proc, geracao: int) -> None:
        """Cada evento vai para a fila com a CHAVE da notificacao (o
        logcat ja diz qual chegou/saiu) e a hora em que chegou ao PC."""
        try:
            for bruta in proc.stdout:
                if geracao != self._geracao:
                    break
                tipo, chave = ler_evento(bruta.decode("utf-8", errors="replace"))
                if not tipo:
                    continue
                with self._trava:
                    self._eventos.append((tipo, chave, time.monotonic()))
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
            if self._vencidas():
                acordou = True
            if not acordou and time.monotonic() - ultima < CONFERENCIA_S:
                continue
            if acordou:
                time.sleep(JUNTAR_RAJADA_S)   # junta a rajada de eventos
            self._sujo.clear()
            with self._trava:
                eventos, self._eventos = self._eventos, []
            try:
                # (01/out, "demorando pra aparecer") CAMINHO CURTO: o evento
                # ja diz QUAL notificacao chegou/saiu -- detalha so ela, sem
                # pedir a lista inteira antes. A lista inteira so na 1a
                # leitura, no "saiu tudo de um app", em evento sem chave e na
                # conferencia (CONFERENCIA_S).
                if completa or not eventos or any(
                        t == "tudo" or not k for t, k, _q in eventos) or \
                        not self._aplicar_eventos(eventos):
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
            # (02/out, revisao) O leitor de eventos (logcat) caiu com a
            # conversa viva: sem isto as notificacoes so chegavam na
            # conferencia, ate a proxima reconexao.
            if not self._vivo():
                self.anotar("notificacoes: o leitor de eventos caiu")
                break

    def _vencidas(self) -> bool:
        """As fixas adiadas cujo prazo venceu voltam como evento "chegou"."""
        agora = time.monotonic()
        with self._trava:
            prontas = [k for k, quando in self._adiadas.items()
                       if quando <= agora]
            for k in prontas:
                del self._adiadas[k]
                self._eventos.append(("chegou", k, agora))
        return bool(prontas)

    def _detalhar(self, chaves: list) -> dict | None:
        """{chave: Notif} das chaves pedidas, numa ida so ("G"). None =
        a conversa falhou."""
        if not chaves:
            return {}
        linhas = self._pedir("G", espera=6 + 0.3 * len(chaves),
                             entrada=list(chaves) + ["."])
        if linhas is None:
            return None
        saida = {}
        for chave, texto in _separar_por_chave(linhas):
            n = ler_detalhe(chave, texto)
            if n is not None:
                n.sdk = self.sdk
                saida[chave] = n
        return saida

    def _aplicar_eventos(self, eventos: list) -> bool:
        """Aplica uma rajada de eventos com chave. False = nao deu (chave
        que o celular nao reconhece etc.): quem chamou rele a lista toda."""
        final: dict = {}
        for tipo, chave, _q in eventos:
            final[chave] = tipo            # o ultimo de cada chave vale
        # (02/out, revisao) FIXA QUE SE ATUALIZA (download, "carregando
        # 58%", navegacao): no maximo um "G" a cada FIXA_ESPERA_S por chave.
        # A atualizacao do meio fica guardada e e pedida quando o prazo vence
        # (`_vencidas`), entao a ultima nunca se perde.
        agora = time.monotonic()
        with self._trava:
            for k in [k for k, t in final.items() if t == "chegou"]:
                velha = self.ativas.get(k)
                feito = self._detalhado_em.get(k, 0.0)
                if velha is not None and velha.fixa and \
                        agora - feito < FIXA_ESPERA_S:
                    self._adiadas[k] = feito + FIXA_ESPERA_S
                    del final[k]
        if not final:
            return True
        chegou = [k for k, t in final.items() if t == "chegou"]
        with self._trava:
            if len(self._detalhado_em) > 500:      # nao cresce para sempre
                self._detalhado_em.clear()
            for k in chegou:
                self._detalhado_em[k] = agora
                self._adiadas.pop(k, None)
        detalhes = self._detalhar(chegou)
        if detalhes is None:
            return True                    # conversa caida: nada a fazer
        if any(k not in detalhes for k in chegou):
            return False
        with self._trava:
            antigas = dict(self.ativas)
        novas = dict(antigas)
        # No "saiu" o ultimo campo e o uid de QUEM tirou (a barra do sistema,
        # o shell...), nao o do app: compara sem ele.
        saiu = {k.rsplit("|", 1)[0] for k, t in final.items() if t == "saiu"}
        if saiu:
            for k in [k for k in novas if k.rsplit("|", 1)[0] in saiu]:
                novas.pop(k)
        novas.update(detalhes)
        self._aplicar(novas, antigas, min(q for _t, _k, q in eventos))
        return True

    def _reler(self, completa: bool) -> None:
        resposta = self._pedir("l")
        if resposta is None:
            return                       # caiu: lista vazia nao e "saiu tudo"
        chaves = [x.strip() for x in resposta if x.strip().count("|") >= 4]
        with self._trava:
            antigas = dict(self.ativas)
        detalhar = [c for c in chaves if completa or c not in antigas]
        novas = {c: antigas[c] for c in chaves if c in antigas}
        detalhes = self._detalhar(detalhar)
        if detalhes is None:
            return
        novas.update(detalhes)
        self._aplicar(novas, antigas, None)

    MEDIR_PRIMEIRAS = 5

    def _aplicar(self, novas: dict, antigas: dict, desde) -> None:
        """Poe a lista nova no lugar: historico, avisos, log e a janela."""
        novas = {c: n for c, n in novas.items() if not n.interna}
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
        if primeira and self.ao_limpar is not None:
            self._ganchos(self.ao_limpar)      # a Central do Windows recomeca
        for n in chegaram:
            if not n.fixa and not n.resumo:
                self._guardar_no_historico(n)
                # A chamada tem aviso proprio (ver `chamada`).
                if not primeira and self.ligada(n.app) and \
                        n.categoria != "call":
                    if self.pode_avisar is None or self.pode_avisar(n.app):
                        self._avisos.put(n)
                    if self.ao_chegar is not None:
                        self._ganchos(self.ao_chegar, n)
        for n in sairam:
            self._marcar_saida(n, agora)
            if self.ao_sair is not None:
                self._ganchos(self.ao_sair, n)
        # Fixa que so se atualiza ("carregando: 2 h 55 min", a cada ~40 s)
        # nao vai para o log nem para o historico.
        importa = [n for n in chegaram if not n.fixa] + sairam
        if importa or primeira:
            self._salvar_logo()
            # (01/out) Quanto levou do aviso do celular ate a lista pronta
            # no PC (as 5 primeiras de cada conexao) -- para medir.
            medida = ""
            if desde is not None and self._medidas < self.MEDIR_PRIMEIRAS:
                self._medidas += 1
                medida = " em %.0f ms" % ((time.monotonic() - desde) * 1000)
            self.anotar("notificacoes: %d no celular (+%d -%d)%s%s"
                        % (len(novas), len(chegaram), len(sairam),
                           " [1a leitura]" if primeira else "", medida))
        self._conferir_chamada(novas, chegaram, sairam)
        self._mudou()
        self._conferir_prefs({n.pacote for n in novas.values()})

    def _conferir_chamada(self, novas: dict, chegaram: list,
                          sairam: list) -> None:
        """(01/out) CHAMADA TOCANDO: notificacao de categoria "call" e o
        telefone em "tocando" (mCallState=1). Conferido so quando uma de
        chamada chega, muda ou sai (atender/recusar mudam a notificacao)."""
        mexeu = [n for n in chegaram + sairam if n.categoria == "call"]
        if not mexeu:
            return
        chamadas = [n for n in novas.values() if n.categoria == "call"]
        tocando = None
        if chamadas:
            resposta = self._pedir("t", espera=6) or []
            m = re.search(r"mCallState=(\d)", " ".join(resposta))
            if m and m.group(1) == "1":
                tocando = chamadas[0]
        with self._trava:
            antes, self.chamada = self.chamada, tocando
        if (antes is None) != (tocando is None):
            self.anotar("notificacoes: chamada %s" % (
                "TOCANDO (%s)" % tocando.titulo[:40] if tocando
                else "acabou/atendida"))

    def _conferir_prefs(self, pacotes) -> None:
        """A tela de configuracoes de notificacao propria de cada app (uma
        pergunta por pacote, guardada). Depois de mostrar: nao atrasa."""
        for pkg in sorted(p for p in pacotes if p not in self.prefs):
            resposta = self._pedir("p " + pkg, espera=8)
            if resposta is None:
                return
            achou = ""
            for linha in resposta:
                m = re.fullmatch(r"\s*(%s/[\w.$]+)\s*" % re.escape(pkg), linha)
                if m:
                    achou = m.group(1)
                    break
            self.prefs[pkg] = achou

    def _ler_bloqueados(self) -> None:
        resposta = self._pedir("b", espera=15)
        if resposta is None:
            return                       # sem resposta: fica a lista anterior
        bloq = ler_bloqueados("\n".join(resposta))
        with self._trava:
            mudou = bloq != self.bloqueados
            self.bloqueados = bloq
        if mudou:
            self._mudou()

    def reler_bloqueados(self) -> None:
        """A aba de ajustes abriu: confere de novo (numa thread)."""
        # (02/out, revisao) E um `dumpsys notification` inteiro (pesado no
        # celular): no maximo 1 a cada 10 s (trocar de aba e voltar nao
        # repete; desativar um app nas Configuracoes e voltar ainda pega).
        agora = time.monotonic()
        if self._servidor is None or \
                agora - getattr(self, "_bloq_lido_em", -99.0) < 10.0:
            return
        self._bloq_lido_em = agora
        threading.Thread(target=self._ler_bloqueados, daemon=True,
                         name="notif-bloq").start()

    def _ganchos(self, funcao, *args) -> None:
        try:
            funcao(*args)
        except Exception:
            log.exception("notificacoes: gancho do windows")

    def _avisar_player(self) -> None:
        if self.ao_player is not None:
            m = self.player()
            self._ganchos(self.ao_player, m,
                          self.posicao(m) if m is not None else 0)

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

    def para_limpar(self, app: str = "") -> list[str]:
        """As chaves do "limpar tudo" (ou do "limpar" de um app): as
        limpaveis de apps ligados -- INCLUSIVE o resumo do grupo, que fica
        escondido enquanto ha filhas (sem ele, sobrava sozinho na lista)."""
        with self._trava:
            todas = list(self.ativas.values())
        return [n.chave for n in todas if n.limpavel and self.ligada(n.app)
                and (not app or n.app == app)]

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

    def destino(self, alvo) -> dict:
        """
        (01/out, pedido dele: "toda notificacao do Android da pra clicar que
        abre algo; no PC tem que ser o mesmo") O que o toque abriria: o
        `dumpsys activity intents` mostra o pedido guardado de cada
        PendingIntent (o shell pode ler; disparar o PendingIntent ele nao
        pode). {} = nao deu. Fora da thread da janela (~0,3 s).
        """
        if not alvo or not self._serial:
            return {}
        ident = re.sub(r"[^0-9a-f]", "", str(alvo[0]))
        if not ident:
            return {}
        saida = self._rodar([str(self._adb()), "-s", self._serial, "shell",
                             "dumpsys activity intents | grep -A3 "
                             "'PendingIntentRecord{%s '" % ident], 10)
        destino = ler_destino(saida)
        if destino:
            destino["tipo"] = alvo[2]
        return destino

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
            # (01/out) EM LOTE: cliques seguidos no x juntam numa ida so do
            # jar (antes cada clique subia um app_process de ~1 s).
            self._a_remover.extend(c for c in chaves
                                   if c not in self._a_remover)
            self._avisar_falha = avisar
            iniciar = not self._removendo
            self._removendo = True
        if tiradas:
            agora = int(time.time() * 1000)
            for n in tiradas:
                self._marcar_saida(n, agora)
                if self.ao_sair is not None:
                    self._ganchos(self.ao_sair, n)
            self._salvar_logo()
            self._mudou()
        if iniciar:
            threading.Thread(target=self._remover_em_lote, args=(serial,),
                             daemon=True, name="notif-remover").start()

    def _remover_em_lote(self, serial: str) -> None:
        while True:
            time.sleep(0.15)                 # junta os cliques seguidos
            with self._trava:
                chaves, self._a_remover = self._a_remover, []
                avisar = self._avisar_falha
                if not chaves or serial != self._serial:
                    self._removendo = False
                    self._a_remover = []
                    return
            try:
                self._rodar_jar_remover(serial, chaves, avisar)
            except Exception:
                log.exception("notificacoes: remover")

    def _rodar_jar_remover(self, serial: str, chaves: list, avisar) -> None:
        adb = str(self._adb())
        if self._jar_pronto != serial:
            from pathlib import Path
            jar = Path(caminhos.pasta_interna()) / "android" / \
                "scrcpyf-notif.jar"
            self._rodar([adb, "-s", serial, "push", str(jar),
                         JAR_NO_CELULAR], 20)
            self._jar_pronto = serial
        args = " ".join("'%s'" % c.replace("'", "'\\''") for c in chaves)
        saida = self._rodar(
            [adb, "-s", serial, "shell",
             "CLASSPATH=%s app_process / scrcpyf.Notif remover %s"
             % (JAR_NO_CELULAR, args)], 15 + 3 * len(chaves)).strip()
        falhas = [x for x in saida.split("\n")
                  if not x.startswith("removido")]
        apps = sorted({c.split("|")[1] for c in chaves if c.count("|") >= 4})
        self.anotar("notificacoes: remover %d (%s) -> %s"
                    % (len(chaves), ", ".join(apps)[:200],
                       (" / ".join(falhas) or "ok")[:300]
                       if saida else "(sem resposta)"))
        if falhas or not saida:
            self._jar_pronto = ""            # pode ter sumido do celular
            self._sujo.set()                 # volta pra lista se nao saiu
            if avisar is not None:
                avisar("não consegui remover do celular")

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

    SALVAR_DEPOIS_S = 2.0

    def _salvar_logo(self) -> None:
        """Grava o historico daqui a pouco, juntando as mudancas de uma
        rajada (antes gravava a cada notificacao)."""
        with self._trava:
            if self._salvar_timer is not None:
                return
            t = threading.Timer(self.SALVAR_DEPOIS_S, self._salvar_agora)
            t.daemon = True
            self._salvar_timer = t
        t.start()

    def _salvar_agora(self) -> None:
        with self._trava:
            t, self._salvar_timer = self._salvar_timer, None
        if t is not None:
            t.cancel()
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
        self._salvar_agora()
        self._salvar_historico()
        self._mudou()

    def historico_visivel(self) -> list[dict]:
        """Mais novo primeiro (o historico guarda todos os apps)."""
        with self._trava:
            self._podar()
            return list(reversed(self.historico))


def nome_de_sistema(pacote: str) -> str:
    return NOMES_DO_SISTEMA.get(pacote, "")
