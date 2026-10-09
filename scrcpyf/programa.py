"""
O programa em si: quem liga, desliga e vigia as sessoes.

QUEM MANDA E ESTE ARQUIVO, NAO A BANDEJA
-----------------------------------------
A bandeja so empilha pedidos ("ligar o jogo"), e a janela e os atalhos de
teclado fazem o mesmo. Toda decisao acontece aqui, num laco so. Sem isso, duas partes da
interface poderiam mandar ligar ao mesmo tempo e cada uma acharia que venceu.

LIGAR DEMORA; O PROGRAMA NAO PODE CONGELAR
-------------------------------------------
Achar o celular leva de um a varios segundos -- mais ainda quando precisa
reiniciar o servidor do ADB. Se isso rodasse no laco, a bandeja ficaria sem
responder no meio, o que da a impressao de programa travado. Por isso a partida
acontece numa thread e o resultado volta pela fila, como qualquer outro pedido.

OS DOIS MODOS CONVIVEM
-----------------------
Espelhar e ouvir podem estar ligados ao mesmo tempo -- sao dois processos do
scrcpy, e o `-s` aponta o mesmo aparelho para os dois. Nada aqui desliga um
para ligar o outro.

TODA MUDANCA DE ESTADO AVISA
-----------------------------
Ligou, desligou ou caiu sozinho: vai uma notificacao do Windows. O programa
vive escondido na bandeja, entao sem aviso a unica forma de saber o que
aconteceu seria ir conferir o icone -- e no caso de uma sessao que caiu
sozinha, nem isso, porque ninguem vai conferir um icone que nao pediu atencao.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

from . import caminhos, celular, icone, sistema
from .config import Config
from .sessao import Sessao

log = logging.getLogger(__name__)

# De quanto em quanto tempo o laco olha o mundo. 1 s e suficiente: e o tempo
# que se leva para perceber que uma sessao caiu, e nao pesa em nada.
PASSO_S = 1.0

# Como cada perfil se chama nas notificacoes e o que elas dizem.
TEXTOS = {
    "jogo": {
        "nome": "Espelhamento",
        "ligou": "A tela do celular esta no PC.",
        "desligou": "A tela do celular nao esta mais no PC.",
        "caiu": "O espelhamento parou sozinho.",
        "fixou": "A tela do celular fica por cima de todas as janelas.",
        "soltou": "A tela do celular nao fica mais por cima de tudo.",
    },
    "audio": {
        "nome": "Audio do celular",
        "ligou": "O som do celular esta saindo no PC.",
        "desligou": "O som do celular parou de sair no PC.",
        "caiu": "O som do celular parou sozinho.",
    },
    "extensao": {
        "nome": "Extensao",
        "ligou": "Leve o mouse ate a borda do celular. Alt devolve.",
        "desligou": "Mouse e teclado sao so do PC de novo.",
        "caiu": "A extensao parou sozinha.",
    },
}

# TROCA SEM DESLIGAR (pedido dele, 19/set/2026). O scrcpy so le a qualidade
# ao subir; entao mudar um ajuste com o espelhamento ou o som no ar sobe um
# scrcpy NOVO por cima do velho e so derruba o velho quando o novo ja tem
# imagem (ou, no so-som, ja esta de pe ha um instante). Sem buraco na tela.
# Se o celular recusar os dois juntos, cai no plano B: derruba e sobe em
# seguida (~1 s sem imagem). A EXTENSAO tambem se aplica sozinha (pedido
# dele, 21/set/2026: "ele nao reconecta sozinho quando muda o audio/controle
# na extensao"), mas SEMPRE em sequencia: a janelinha dela e o vigia da borda
# nao convivem com uma segunda.
TROCA_AUTOMATICA = ("jogo", "audio", "extensao")
# Quanto esperar depois do ultimo clique num ajuste antes de trocar: clicar
# tres opcoes seguidas vira UMA troca, nao tres.
ESPERA_AJUSTE_S = 0.8
# Ate quando esperar o scrcpy novo mostrar imagem antes de desistir da
# sobreposicao (plano B). O normal e 1 a 2 s.
ESPERA_IMAGEM_S = 8.0
# No so-som nao ha imagem para esperar: vivo por este tempo = pegou o som
# (ele sobe com --require-audio na troca, entao sem som ele cai sozinho).
ESPERA_SOM_S = 2.5

# O aviso de quando o celular nao aparece. Ele MESMO (20/set/2026) achou o
# motivo da vez olhando o celular: a "Depuracao sem fio" estava desligada.
# Por isso o texto agora comeca pelo que conferir NO CELULAR, em ordem, e o
# Configurar abre em seguida ja no passo do celular -- em vez de mandar a
# pessoa procurar um .bat.
TEXTO_SEM_CELULAR = (
    "Nao achei o celular.\n\n"
    "No celular, nas Opcoes do desenvolvedor, confira se estao LIGADAS:\n"
    "  1. Depuracao USB\n"
    "  2. Depuracao sem fio  (e o celular na mesma rede Wi-Fi do PC)\n\n"
    "Depois de ligar, tente de novo.\n\n"
    "Vou abrir o PAREAR na janela: de la da para procurar,\n"
    "conectar pelo cabo USB ou parear com codigo."
)


def conteudo_do(perfil: dict) -> str:
    """
    O que o modo espelhar traz do celular: "ambos", "som" ou "imagem".
    Config antigo nao tem o campo: ai decide a chave "som junto" de antes.
    """
    c = perfil.get("conteudo")
    if c in ("ambos", "som", "imagem"):
        return c
    return "ambos" if (perfil.get("audio") or {}).get("ligado", True) \
        else "imagem"


def _tempo_de_tela_ms(perfil: dict) -> int:
    """O tempo de tela que o perfil pede ao celular, em ms (0 = nao mexe)."""
    try:
        return int(float((perfil.get("sessao") or {}).get("tempo_tela_s")
                         or 0) * 1000)
    except (TypeError, ValueError):
        return 0


def _texto(nome: str, chave: str) -> str:
    return TEXTOS.get(nome, {}).get(chave, nome)


# APPS EM JANELA PROPRIA (pedido dele, 23/set/2026, "parecido com o
# TabDesk"): cada app do celular abre numa janela do PC, numa TELA VIRTUAL do
# Android (`--new-display`), sem ocupar a tela de verdade do celular. Cada um
# e uma sessao comum, com o nome "app:<pacote>".
APP = "app:"
# O "Samsung DeX" da lista: uma tela virtual COM a area de trabalho do
# Samsung, em tamanho de monitor (pedido dele, 23/set/2026).
DEX = "__dex__"
# De onde vem o icone do DeX (o app do DeX no Samsung); sem ele, um desenho.
ICONE_DEX = "com.sec.android.desktopmode.uiservice"
CACHE_VERSAO = 2   # apps.json de cada celular (ver `_preparar_celular`)

# (r186) APP DUPLICADO (Dual Messenger, apps duplos, perfil de trabalho): a
# copia mora noutro USUARIO do Android. Aqui ela e "<pacote>@<usuario>"
# (ex.: "com.whatsapp@95") em TUDO que e do programa -- sessao, config,
# icone, atalho, recentes --, e so vira pacote + "--user" ao falar com o
# Android. Provado pela sonda_duplicado (25/set/2026).
COPIA = "@"
# Usuarios que NAO entram (privacidade): a Pasta Segura do Samsung.
USUARIO_FORA = ("secure", "segur", "knox")


def separar_app(chave: str) -> tuple[str, int]:
    """("com.whatsapp", 95) de "com.whatsapp@95"; (pacote, 0) do original."""
    pacote, _, usuario = (chave or "").partition(COPIA)
    return pacote, (int(usuario) if usuario.isdigit() else 0)


def _tamanho_em_bytes(texto: str) -> int:
    """ "253M", "1.7G", "22800" (K) -> bytes, como o `top` escreve."""
    texto = texto.strip().upper()
    fator = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}.get(texto[-1:], 0)
    try:
        if fator:
            return int(float(texto[:-1]) * fator)
        return int(float(texto) * 1024)
    except ValueError:
        return 0


def ler_lista_de_apps(texto: str) -> list[tuple[str, str, bool]]:
    """
    Da saida do `scrcpy --list-apps`: (nome, pacote, e_do_sistema), por nome.
    Cada linha depois de "List of apps" e "  * Nome   pacote" (sistema) ou
    "  - Nome   pacote" (instalado por ele). O pacote e a ultima palavra; o
    nome pode ter espaco.
    """
    import re
    apps = []
    vistos = set()
    comecou = False
    for linha in texto.splitlines():
        if "List of apps" in linha:
            comecou = True
            continue
        if not comecou:
            continue
        m = re.match(r"^\s*(?:\[server\]\s*\w+:\s*)?([*-])\s+(.*?)\s+(\S+)\s*$",
                     linha)
        if not m or "." not in m.group(3) or m.group(3) in vistos:
            continue
        vistos.add(m.group(3))
        apps.append((m.group(2).strip() or m.group(3), m.group(3),
                     m.group(1) == "*"))
    apps.sort(key=lambda a: a[0].lower())
    return apps


class Programa:
    """Estado do programa e as acoes que mexem nele."""

    def __init__(self, registro=None) -> None:
        self.registro = registro
        # (r191) ANTES de qualquer thread: o vigia da conexao sobe aqui
        # embaixo e le `_sair` no laco -- sem isto ele podia morrer na
        # largada (achado no teste de fumaca, 25/set/2026).
        self._sair = False
        # Um degrau acima do normal: o vigia da borda tem que responder no
        # quadro certo mesmo com o jogo rodando (pedido dele, 21/set/2026).
        sistema.prioridade_do_programa()
        self.config = Config.carregar()
        celular.PREFERENCIA = self.conexao_preferida()
        self.aplicar_area_compartilhada()           # (08/out)
        # (r192) Seriais de OUTRO celular (id diferente do que esta em uso):
        # a troca de conexao nao os le de novo a cada olhada.
        self._outro_celular: set = set()
        self._escolha_manual = ""       # (r193) serial do "usar" da lista
        # (r195) "scrcpy"/"app" -> (tipo, texto) da ultima procura; e a
        # versao do scrcpy lida uma vez (None = ler de novo).
        self.estado_atualizacao: dict = {}
        self._versao_scrcpy = None
        self._migrar_formatos()
        self._tirar_tela_ligada_da_extensao()
        self._acertar_o_som_da_extensao()
        self.sessoes: dict[str, Sessao] = {}
        self.pedidos: queue.Queue = queue.Queue()
        self.ligando: set[str] = set()
        self.bandeja = None
        self._sair = False
        # (r166) Enquanto a pasta do scrcpy e trocada, ninguem chama o adb
        # (o vigia da conexao o subiria de novo, prendendo a pasta velha).
        self.adb_pausado = False
        self._instalando = threading.Lock()
        # (r167) Procura de versao nova no prazo escolhido nas opcoes.
        threading.Thread(target=self._vigia_atualizacao, daemon=True,
                         name="vigia-atualizacao").start()

        # Quem quer saber quando o estado muda, alem da bandeja: a janela.
        # Sao chamados na thread do laco, que e a mesma da janela.
        self.ouvintes: list = []

        # Quem abre a janela quando chega o pedido "mostrar" (bandeja, atalho,
        # segunda instancia). Sem janela, fica None e o pedido e ignorado.
        self.ao_mostrar = None
        # O atalho da janela: abre ou devolve para onde estava.
        self.ao_alternar_janela = None
        # Um atalho mudou o perfil (conteudo, por cima): a janela remonta.
        self.ao_perfil_mudou = None
        # Quem abre o parear quando o celular nao aparece (a janela nova).
        self.ao_parear = None
        # O celular conectado por ultimo: serial, modelo, bateria (ver
        # `_ler_o_celular`). Vazio ate a primeira sessao subir.
        self.celular: dict = {}
        # O vigia dos apps em janela: UM laco no celular para todos.
        self._vigia_trava = threading.Lock()
        self._vigia_alvos: dict = {}
        self._vigia_proc = None
        self._tarefa_do_app: dict = {}   # pacote -> (tarefa, serial) (r134)
        # Apps em tela cheia agora, e onde a janela estava antes (r135).
        self._tela_cheia: set = set()
        self._lugar_antes_cheia: dict = {}
        # O vigia do sono: celular acordado enquanto houver app em janela.
        self._sono_trava = threading.Lock()
        self._sono_thread = None
        self._sono_parar = None
        # Animacoes do celular 4x mais rapidas com app em janela (r93).
        self._anim_trava = threading.Lock()
        self._anim_serial = ""          # "" = animacoes no valor original

        # Perfis que estao no ar com uma qualidade DIFERENTE da gravada: a
        # pessoa mexeu num ajuste com a sessao rodando. O scrcpy le as opcoes
        # so na partida, entao a mudanca so vale ao religar -- e a janela
        # precisa dizer isso, senao parece que o ajuste nao funcionou.
        self.pendentes: set[str] = set()

        # O vigia da borda, vivo so enquanto a extensao esta no ar, e onde o
        # mouse esta: "fora" (no PC) ou "dentro" (no celular).
        self.borda = None
        self.borda_estado = "fora"
        # Calibracao da extensao (ver `borda._calibrar`): "" (sem extensao),
        # "aguardando" (mao parada, por favor), "pronta" ou "falhou". A janela
        # mostra isso no cartao -- foi pedido dele em 21/set/2026.
        self.borda_calibracao = ""
        self.borda_calibrada_em = 0.0
        self._avisou_falha_da_borda = False

        # O risquinho na borda da tela (`faixa.py`), criado so no Windows.
        # Um so para o programa: o vigia e a previa da janela pedem nele.
        from . import faixa as faixa_mod
        self.faixa = faixa_mod.Faixa() if faixa_mod.NO_WINDOWS else None
        self.aplicar_estilo_da_faixa()
        # A conversa aberta com o celular para acender a tela (ver
        # `_acordar_celular`), e o que impede duas threads de usa-la juntas.
        self._shell_do_celular = None
        self._trava_do_shell = threading.Lock()
        self._serial_da_extensao = ""

        # Troca sem desligar: quem esta no meio de uma, quem tem uma marcada
        # (perfil -> quando), e a senha de cada troca -- a resposta de uma
        # troca que foi desligada no meio chega com senha velha e e jogada fora.
        self.trocando: set[str] = set()
        self._trocar_em: dict[str, float] = {}
        self._troca_senha: dict[str, object] = {}
        # (01/out) As notificacoes do celular (`notificacoes.py`): sobe com o
        # celular lido (`_conferir_o_celular`), para no desligar_tudo.
        from . import notificacoes
        self.notif = notificacoes.Central(
            lambda: self.config.adb_exe, self.config, self.anotar,
            lambda: self.pedidos.put(("notif",)), self.pasta_do_celular,
            self._pode_avisar_notif)
        # (01/out) NO WINDOWS (`central_windows`): as notificacoes tambem na
        # Central de Notificacoes e o player nos controles de midia.
        from . import central_windows
        self.windows_notif = self.windows_player = None
        if central_windows.disponivel():
            self.windows_notif = central_windows.NotificacoesWindows(
                self.anotar)
            self.windows_player = central_windows.PlayerWindows(
                self._botao_windows, self.anotar)
            self.notif.ao_chegar = self._windows_chegou
            self.notif.ao_sair = lambda n: self.windows_notif.remover(n.chave)
            self.notif.ao_limpar = self.windows_notif.limpar
            self.notif.ao_player = self._windows_player
            threading.Thread(target=self._registrar_windows, daemon=True,
                             name="windows-registro").start()
            # (08/out) o import do winrt DEPOIS da janela: junto com ela,
            # disputava o processador e a janela demorava mais (medido)
            t = threading.Timer(4.0, central_windows.aquecer)
            t.daemon = True
            t.name = "windows-aquecer"
            t.start()
        # (r191) As threads que falam com o adb sobem SO AGORA, com o
        # objeto inteiro montado (antes subiam no meio do __init__ e o
        # vigia da conexao podia ler `adb_pausado`/`_sair` antes de
        # existirem e morrer na largada -- achado no teste de fumaca).
        # O servidor do ADB acorda agora, e nao no primeiro clique (ver
        # `celular.aquecer`).
        if self.config.instalacao_ok:
            threading.Thread(target=celular.aquecer,
                             args=(self.config.adb_exe,), daemon=True,
                             name="aquecer-adb").start()
            # (r161) CONEXAO EM TEMPO REAL: o proprio adb avisa cada celular
            # que entra ou sai (`adb track-devices`).
            self._garantir_vigia_conexao()
            # (r141) As opcoes do scrcpy lidas agora, e nao no 1o app.
            threading.Thread(target=self._scrcpy_aceita, args=("",),
                             daemon=True, name="ajuda-scrcpy").start()

    # -- registro ------------------------------------------------------------

    def anotar(self, texto: str) -> None:
        log.info(texto)
        if self.registro is not None:
            self.registro.linha(texto)

    def avisar_na_tela(self, nome: str, chave: str) -> None:
        """Notificacao do Windows, pela bandeja -- se ele nao desligou."""
        if not self.config.opcao("notificacoes"):
            return
        if nome.startswith(APP):
            return          # a janela do app aparecendo ja e o aviso
        if self.bandeja is not None:
            self.bandeja.notificar(_texto(nome, "nome"), _texto(nome, chave))

    def fixar_espelhamento(self, fixar=None, avisar: bool = True) -> None:
        """
        "Por cima das outras janelas" (pedido dele, 21/set/2026): atalho e
        chave do basico mexem no MESMO ajuste, `janela.sempre_no_topo` do
        perfil "jogo". Grava (o `--always-on-top` vale nas proximas subidas,
        inclusive troca e plano B) e aplica NA HORA na janela que estiver no
        ar, sem religar. `fixar=None` = inverte (o atalho).
        """
        from . import janela_scrcpy
        janela_cfg = self.config.perfil("jogo").setdefault("janela", {})
        if fixar is None:
            fixar = not bool(janela_cfg.get("sempre_no_topo"))
        janela_cfg["sempre_no_topo"] = bool(fixar)
        gravou = self.config.gravar()
        sessao = self.sessoes.get("jogo")
        pid = getattr(sessao, "pid", 0) if sessao is not None else 0
        hwnd = janela_scrcpy.achar(pid) if pid else None
        aplicou = bool(hwnd) and janela_scrcpy.fixar_por_cima(hwnd, fixar)
        self.anotar("por cima: %s%s; janela no ar: %s" % (
            "LIGADO" if fixar else "desligado",
            "" if gravou else " (NAO GRAVOU)",
            "aplicado" if aplicou else ("recusado" if hwnd else "nenhuma")))
        if avisar:                    # veio do atalho: a chave do basico
            self.avisar_na_tela("jogo", "fixou" if fixar else "soltou")
            self._perfil_mudou("jogo")

    def alternar_conteudo(self, conteudo: str) -> None:
        """
        Atalhos "espelhar so a tela" e "espelhar so o som" (pedido dele,
        21/set/2026). No ar com o mesmo conteudo -> desliga. No ar com outro
        -> troca sem desligar. Parado -> escolhe e liga. A escolha do basico
        acompanha (e o mesmo campo `conteudo`).
        """
        perfil = self.config.perfil("jogo")
        sdk = (self.celular or {}).get("sdk")
        if conteudo != "imagem" and isinstance(sdk, int) and sdk < 30:
            self.anotar("atalho: %s RECUSADO -- som no pc pede Android 11+ "
                        "(este e o %s)" % (conteudo, sdk))
            return
        if self.ativo("jogo") and conteudo_do(perfil) == conteudo:
            self.desligar("jogo")
            return
        if conteudo_do(perfil) != conteudo:
            perfil["conteudo"] = conteudo
            gravou = self.config.gravar()
            self.anotar("atalho: conteudo = %s%s" % (
                conteudo, "" if gravou else " (NAO GRAVOU)"))
            self._perfil_mudou("jogo")
            if self.ativo("jogo") or self.ocupado("jogo"):
                self.mudou_a_qualidade("jogo")
                return
        self.ligar("jogo")

    # -- apps em janela propria ------------------------------------------------

    def listar_apps(self):
        """
        UMA LISTAGEM POR VEZ (23/set/2026: o relatorio mostrou duas seguidas
        ao conectar -- a da janela e a do cache). Quem chega com outra em
        andamento espera ela e usa o resultado.
        """
        trava = self.__dict__.setdefault("_trava_listar", threading.Lock())
        if trava.locked():
            with trava:
                apps = list(getattr(self, "apps_do_celular", None) or [])
                if _tem_app(apps):
                    return apps, ""
        with trava:
            return self._listar_apps()

    def _listar_apps(self):
        """
        FORA DA THREAD DA JANELA (leva uns segundos: o scrcpy sobe o servidor
        no celular so para perguntar). Devolve (lista, erro): a lista de
        `ler_lista_de_apps`, ou [] e o motivo em portugues.
        """
        if not self.config.instalacao_ok:
            return [], "a pasta do scrcpy não foi encontrada (opções > geral)."
        alvo = self._achar_celular()
        if not alvo:
            return [], "celular não encontrado. conecte em parear e tente de novo."
        # UTF-8 aqui, e nao o `celular._rodar`: nome de app tem acento, e
        # lido na codificacao do Windows um "Á" derruba a leitura inteira.
        import subprocess
        self._vez_de_lancar()
        try:
            r = subprocess.run(
                [str(self.config.scrcpy_exe), "-s", alvo, "--list-apps"],
                capture_output=True, timeout=40,
                cwd=str(self.config.scrcpy_exe.parent),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            saida = ((r.stdout or b"") + b"\n" + (r.stderr or b"")).decode(
                "utf-8", errors="replace")
        except Exception as erro:
            self.anotar("apps: o scrcpy nao respondeu (%s)" % erro)
            return [], "o scrcpy não respondeu. tente atualizar de novo."
        apps = ler_lista_de_apps(saida)
        if not apps and not getattr(self, "_listando_de_novo", False):
            # 23/set/2026: com uma janela de app subindo o scrcpy devolveu a
            # lista vazia e o cache guardou so o DeX. Espera e tenta de novo.
            self.anotar("apps: lista vazia; tento de novo em 2 s")
            time.sleep(2)
            self._listando_de_novo = True
            try:
                return self._listar_apps()
            finally:
                self._listando_de_novo = False
        if not apps:
            linhas = [l for l in saida.splitlines() if l.strip()][-3:]
            self.anotar("apps: lista vazia; fim da saida: %s"
                        % " / ".join(linhas))
            return [], "o celular não respondeu com a lista de apps."
        # SO O QUE TEM ICONE NO CELULAR (pedido dele, 23/set/2026: "tem
        # apps que nao aparecem na tela do meu celular e aparecem na lista").
        # O --list-apps traz tudo o que esta instalado, inclusive servico
        # sem icone; aqui ficam so os que a gaveta do celular mostra. Se a
        # pergunta falhar, a lista segue inteira (melhor sobrar que sumir).
        # (r139) UMA pergunta ao celular: os apps com icone E o fabricante
        # (antes eram dois adb seguidos).
        fabricante = ""
        try:
            r = subprocess.run(
                [str(self.config.adb_exe), "-s", alvo, "shell",
                 "cmd package query-activities --brief "
                 "-a android.intent.action.MAIN "
                 "-c android.intent.category.LAUNCHER; "
                 "echo \"@fab $(getprop ro.product.manufacturer)\"; "
                 # (r186) os apps com icone de cada OUTRO usuario (copias)
                 "pm list users 2>/dev/null | grep 'UserInfo{' | "
                 "while read -r l; do u=${l#*UserInfo\\{}; u=${u%%:*}; "
                 "[ \"$u\" = 0 ] && continue; echo \"@user $u $l\"; "
                 "cmd package query-activities --brief --user $u "
                 "-a android.intent.action.MAIN "
                 "-c android.intent.category.LAUNCHER </dev/null 2>/dev/null; done"],
                capture_output=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            linhas_r = (r.stdout or b"").decode("utf-8", "replace") \
                .splitlines()
            fabricante = next((l[5:].strip().lower() for l in linhas_r
                               if l.startswith("@fab ")), "")
            com_icone = set()
            copias: dict = {}               # usuario -> {pacotes}
            usuario = 0
            for l in linhas_r:
                l = l.strip()
                if l.startswith("@user "):
                    partes = l.split(None, 2)
                    usuario = int(partes[1]) if partes[1].isdigit() else -1
                    nome_u = (partes[2] if len(partes) > 2 else "").lower()
                    if usuario > 0 and not any(x in nome_u
                                               for x in USUARIO_FORA):
                        copias[usuario] = set()
                    else:
                        usuario = -1        # fora (Pasta Segura etc.)
                    continue
                if "/" not in l or " " in l or l.startswith("@"):
                    continue
                if usuario == 0:
                    com_icone.add(l.split("/")[0])
                elif usuario > 0:
                    copias[usuario].add(l.split("/")[0])
            if len(com_icone) >= 5:
                antes = len(apps)
                apps = [a for a in apps if a[1] in com_icone]
                self.anotar("apps: %d com icone no celular (de %d)"
                            % (len(apps), antes))
            # (r186) CADA COPIA vira "Nome (2)", "Nome (3)"... logo abaixo
            # do original, com a chave "<pacote>@<usuario>".
            n_copias = 0
            for u in sorted(copias):
                for nome_a, pac, sist in list(apps):
                    if COPIA in pac or pac not in copias[u]:
                        continue
                    ja = sum(1 for a in apps if a[1].startswith(pac + COPIA))
                    apps.append(("%s (%d)" % (nome_a, ja + 2),
                                 "%s%s%d" % (pac, COPIA, u), sist))
                    n_copias += 1
            if copias:
                apps.sort(key=lambda a: a[0].lower())
                self.anotar("apps: %d copias (usuarios %s)" % (
                    n_copias, ", ".join(str(u) for u in sorted(copias))))
        except Exception as erro:
            self.anotar("apps: nao filtrei pelos icones (%s)" % erro)
        # (r185) Sem a deteccao de jogos (`cmd game`): com o "automatico"
        # fora, o formato e so o que ele escolhe (celular de padrao).
        # Samsung: o DeX entra na lista como se fosse um app.
        if "samsung" in fabricante:
            apps.insert(0, ("Samsung DeX", DEX, False))
        self.anotar("apps: %d na lista" % len(apps))
        self._guardar_lista(apps)
        if not apps:
            linhas = [l for l in saida.splitlines() if l.strip()][-3:]
            self.anotar("apps: lista vazia; fim da saida: %s" % " / ".join(linhas))
            return [], "o celular não respondeu com a lista de apps."
        return apps, ""

    def apps_abertos(self) -> set:
        """Pacotes com janela no ar ou subindo."""
        nomes = set(self.sessoes) | set(self.ligando)
        return {n[len(APP):] for n in nomes if n.startswith(APP)
                and (n in self.ligando or self.ativo(n))}

    def na_conexao(self, nome: str, conexao: str) -> bool:
        """(r196) A sessao `nome` esta nessa conexao? Sem sessao (ou
        subindo, sem serial ainda) conta como sim: quem pergunta e a troca
        de qualidade, e na duvida ela aplica."""
        s = self.sessoes.get(nome)
        serial = getattr(s, "serial", "") if s is not None else ""
        return not serial or self.conexao_de(serial) == conexao

    def app_subindo(self, pacote: str) -> bool:
        return (APP + pacote) in self.ligando

    def em_tela_cheia(self, pacote: str) -> bool:
        return pacote in self._tela_cheia

    def alternar_app(self, pacote: str, rotulo: str,
                     tela_cheia: bool = False) -> None:
        """Abre o app numa janela propria; se ja estiver aberto, fecha.
        `tela_cheia` (r135): abre ocupando o monitor, so desta vez."""
        nome = APP + pacote
        if self.ativo(nome):
            self.desligar(nome)
            return
        if self.ocupado(nome):
            return
        if not self.config.instalacao_ok:
            sistema.avisar("Nao achei o adb.exe e o scrcpy.exe.\n\n"
                           "Escolha a pasta do scrcpy em opcoes > geral.")
            return
        self.anotar("pedido: abrir o app %s (%s)" % (rotulo, pacote))
        self.retomar_conexao()      # (07/out) abrir um app = quer o celular
        try:
            self.config.lembrar_recente(pacote)   # grupo "recentes" da lista
        except Exception as erro:
            log.warning("nao gravei o recente: %s", erro)
        self.ligando.add(nome)
        # (08/out, pedido dele) o app marcado para SEMPRE abrir em tela cheia
        # (sair dela pelo menu continua valendo ate fechar a janela)
        if not tela_cheia and pacote != DEX and \
                self.config.app(pacote).get("tela_cheia"):
            tela_cheia = True
        if tela_cheia:
            self._tela_cheia.add(pacote)
        else:
            self._tela_cheia.discard(pacote)
        self._avisar_mudanca()
        threading.Thread(target=self._partida_app, args=(nome, pacote, rotulo),
                         kwargs={"tela_cheia": tela_cheia},
                         daemon=True, name="partida-%s" % nome).start()

    def reabrir_app(self, pacote: str, tela_cheia=None,
                    virou: bool = False) -> None:
        """
        AJUSTE DO APP SEM FECHAR A JANELA (pedido dele, 24/set/2026): a
        janela e trocada por uma nova, no mesmo lugar e na mesma altura, ja
        com o ajuste novo -- sem reiniciar o app (`_trocar_sem_reiniciar`);
        se nao der, plano B: fecha e abre de novo.

        `tela_cheia` (r135): True/False entra/sai da tela cheia pela mesma
        troca; None mantem como esta. Saindo, a janela volta ao lugar e ao
        tamanho de antes da tela cheia.
        """
        nome = APP + pacote
        sessao = self.sessoes.get(nome)
        if sessao is None or self.ocupado(nome) or not self.ativo(nome):
            return
        from . import janela_scrcpy
        hwnd = self._janela_da_sessao(nome)
        lugar = janela_scrcpy.area(hwnd) if hwnd else None
        if lugar and not virou and pacote != DEX:
            # (07/out) A orientacao escolhida mudou: a janela vira junto.
            try:
                nova = self._tela_do_app(pacote, self.config_efetiva(
                    pacote, getattr(sessao, "serial", "")))
            except Exception:
                nova = None
            if nova and "deitado" in nova and \
                    nova["deitado"] != (lugar[2] > lugar[3]):
                virou = True
        if virou and lugar:
            # (07/out) Em pe <-> deitado: a altura nova e a largura velha
            # (o lado curto continua do mesmo tamanho na tela).
            lugar = (lugar[0], lugar[1], lugar[3], lugar[2])
        estava = pacote in self._tela_cheia
        cheia = estava if tela_cheia is None else bool(tela_cheia)
        if cheia and not estava and lugar:
            self._lugar_antes_cheia[pacote] = lugar
        if estava and not cheia:
            lugar = self._lugar_antes_cheia.pop(pacote, None)
        if cheia:
            self._tela_cheia.add(pacote)
        else:
            self._tela_cheia.discard(pacote)
        rotulo = next((a[0] for a in (getattr(self, "apps_do_celular", None)
                                      or []) if a[1] == pacote), None) or \
            (self.config.apps.get("nomes") or {}).get(pacote) or pacote
        frente = bool(hwnd) and janela_scrcpy.frente() == hwnd
        self.sessoes.pop(nome, None)
        self.ligando.add(nome)
        self.anotar("app %s: trocando a janela para o ajuste novo" % pacote)
        self._avisar_mudanca()

        def fazer():
            # (r125) SEM REINICIAR: sobe a nova, passa o app, fecha a velha.
            if pacote != DEX:
                # (r136/r137) DISFARCE: foto da janela velha por cima so no
                # ULTIMO instante da troca (ver `_trocar_sem_reiniciar`); ate
                # la a velha segue ao vivo. Sai sozinha em qualquer caminho:
                # `soltar` no finally.
                capas: list = []
                try:
                    if self._trocar_sem_reiniciar(nome, pacote, rotulo,
                                                  sessao, lugar, frente,
                                                  cheia, capas=capas,
                                                  hwnd_velha=hwnd):
                        return
                except Exception:
                    log.exception("falha trocando %s sem reiniciar", nome)
                finally:
                    for capa in capas:
                        capa.soltar()
            # Plano B (r123): fecha e abre de novo -- o app reinicia.
            self.anotar("app %s: troca sem reiniciar nao deu; reabrindo"
                        % pacote)
            try:
                sessao.parar()
            except Exception:
                log.exception("falha fechando %s para reabrir", nome)
            self._partida_app(nome, pacote, rotulo, lugar=lugar,
                              tela_cheia=cheia)

        threading.Thread(target=fazer, daemon=True,
                         name="reabrir-%s" % nome).start()

    # FECHAR O APP AO FECHAR A JANELA (pedido dele, 24/set/2026; provado pela
    # sonda_fechar: fechar a janela deixa a tarefa nos recentes). Fechar =
    # como arrastar para fora dos recentes (removeTask): NUNCA o "forcar
    # parada", que corta as notificacoes. Os jeitos vao do mais comum ao
    # alternativo e cada um e conferido -- versoes diferentes do Android.
    JEITOS_DE_FECHAR = ("am stack remove %s", "cmd activity stack remove %s")

    def _app_fechou(self, nome: str, sessao, esperar: bool = False) -> None:
        pacote = nome[len(APP):]
        info = self._tarefa_do_app.pop(pacote, None)
        self._tela_cheia.discard(pacote)          # tela cheia era so desta vez
        self._lugar_antes_cheia.pop(pacote, None)
        if pacote == DEX:
            return
        modo = self.config.app(pacote).get("ao_fechar") or \
            self.config.apps.get("ao_fechar") or "fechar"
        if modo != "fechar":
            return
        if not info:
            self.anotar("fechar o app %s: tarefa desconhecida, ficou nos "
                        "recentes" % pacote)
            return
        # (02/out) TODAS as tarefas do app nesta janela: a da abertura e as
        # das reaberturas da vigia (cada reabertura pode criar uma nova;
        # antes so a primeira era lembrada e a nova ficava nos recentes).
        tarefas, serial = info
        serial = getattr(sessao, "serial", "") or serial

        def nos_recentes(tarefa, recentes) -> bool:
            # (02/out, teste no S22) So a secao "Recent tasks:": antes dela
            # vem "mHiddenTasks=[...]", que lista tarefas JA tiradas -- e o
            # fechamento dava "NAO consegui" por engano.
            return ("#%s " % tarefa) in recentes.split("Recent tasks:", 1)[-1]

        def fechar_uma(tarefa, recentes) -> None:
            if not nos_recentes(tarefa, recentes):
                return                   # ja saiu sozinha
            for jeito in self.JEITOS_DE_FECHAR:
                self._shell(serial, jeito % tarefa, espera=6)
                recentes = self._shell(serial, "dumpsys activity recents",
                                       espera=8)
                if not nos_recentes(tarefa, recentes):
                    self.anotar("app %s: fechado no celular (%s, tarefa %s)"
                                % (pacote, jeito.split(" %")[0], tarefa))
                    return
            self.anotar("app %s: NAO consegui fechar no celular (tarefa %s) "
                        "-- nenhum jeito serviu nesta versao"
                        % (pacote, tarefa))

        def fazer():
            time.sleep(0.8)          # a tela virtual vai embora primeiro
            if pacote in self.apps_abertos():
                return               # ele abriu de novo nesse meio tempo
            recentes = self._shell(serial, "dumpsys activity recents",
                                   espera=8)
            for tarefa in tarefas:
                fechar_uma(tarefa, recentes)

        if esperar:
            fazer()
        else:
            threading.Thread(target=fazer, daemon=True,
                             name="fechar-%s" % nome).start()

    def _conferir_troca(self, serial, tela, pacote, tarefa, resp) -> None:
        if self._tarefa_na_tela(serial, tela, pacote) != tarefa:
            self.anotar("app %s: a tarefa NAO passou para a tela %s (%r); o "
                        "vigia abre o app nela" % (pacote, tela, resp[:150]))

    def _tarefa_na_tela(self, serial: str, tela: str, pacote: str) -> str:
        """O numero da tarefa do app na tela virtual `tela`, pelo dumpsys."""
        import re
        pacote = separar_app(pacote)[0]                     # (r186)
        # (02/out, revisao) PERGUNTA LEVE PRIMEIRO (~9 KB contra ~115 KB do
        # dumpsys; e chamada a cada 0,3 s ao abrir/trocar app). Formato
        # conferido no S22: "RootTask id=.. displayId=188" e, embaixo,
        # "  taskId=3241: <pacote>/<tela> ...".
        leve = self._shell(serial, "cmd activity stack list", espera=8)
        if "taskId=" in leve and "RootTask id=" in leve:
            na_tela = raiz = None
            visto = False
            for linha in leve.splitlines():
                m = re.search(r"RootTask id=(\d+).*?displayId=(\d+)", linha)
                if m:
                    raiz, na_tela = m.group(1), m.group(2)
                    continue
                if na_tela != tela or "taskId=" not in linha:
                    continue
                m = re.match(r"\s*taskId=(\d+): %s/" % re.escape(pacote), linha)
                if m:
                    return raiz or m.group(1)   # a raiz, como o dumpsys dava
                visto = visto or pacote in linha
            # O app ainda nao esta nesta tela (subindo, ou na troca): "" sem
            # o dumpsys. Esta mas nao casou (tarefa com tela de outro pacote
            # na base): o dumpsys, que casa pela linha inteira.
            if not visto:
                return ""
        texto = self._shell(serial, "dumpsys activity activities", espera=8)
        dentro = False
        for linha in texto.splitlines():
            m = re.match(r"\s*Display #(\d+)", linha)
            if m:
                if dentro:
                    break
                dentro = m.group(1) == tela
                continue
            # (02/out) O bloco acaba na primeira linha sem recuo: a ultima
            # tela nao tem "Display #" depois (ver LACO_DA_VIGIA).
            if dentro and linha[:1] not in ("", " "):
                break
            if dentro:
                m = re.search(r"Task\{\w+ #(\d+) .*?%s" % re.escape(pacote),
                              linha)
                if m:
                    return m.group(1)
        return ""

    def _trocar_sem_reiniciar(self, nome, pacote, rotulo, velha, lugar,
                              frente, cheia=False, capas=None,
                              hwnd_velha=None) -> bool:
        """
        AJUSTE SEM REINICIAR O APP (pedido dele, 24/set/2026; provado pela
        sonda_troca: tarefa passou em 0,24 s, MESMO processo, troca inteira
        ~1,3 s). Sobe a janela nova (tela virtual vazia, fora da vista) com
        a velha no ar, passa a TAREFA do app para a tela nova
        (`am display move-stack`), poe a janela nova no lugar da velha e so
        entao fecha a velha -- que ja esta vazia, entao nada e destruido.
        False = nada foi mexido de irreversivel: o plano B reabre.
        """
        from . import janela_scrcpy
        t0 = time.monotonic()
        serial = getattr(velha, "serial", "")
        with self._vigia_trava:
            alvo = self._vigia_alvos.get(pacote)
        tela_v = alvo[0] if alvo else \
            (self._tela_da_sessao(velha) or ("",))[0]
        if not serial or not tela_v:
            return False
        # (r128, mais rapido) A tarefa e procurada ENQUANTO a janela nova
        # sobe, em vez de antes.
        achada: list = []
        busca = threading.Thread(
            target=lambda: achada.append(
                self._tarefa_na_tela(serial, tela_v, pacote)),
            daemon=True, name="tarefa-%s" % nome)
        busca.start()
        # O vigia reabriria o app na tela velha assim que ela esvaziasse:
        # sai do vigia agora; a janela nova entra nele ao "subir".
        with self._vigia_trava:
            self._vigia_alvos.pop(pacote, None)
        threading.Thread(target=self._religar_vigia, args=(serial,),
                         daemon=True, name="vigia-troca").start()
        nova = self._partida_app(nome, pacote, rotulo, lugar=lugar,
                                 serial=serial, troca=True,
                                 log_velho=str(velha.arquivo_log or ""),
                                 tela_cheia=cheia)
        if nova is None:
            return False
        tela_n = None
        fim = time.monotonic() + 8
        while not tela_n and time.monotonic() < fim and nova.rodando:
            tela_n = (self._tela_da_sessao(nova) or (None,))[0]
            if not tela_n:
                time.sleep(0.02)
        busca.join(5)
        tarefa = achada[0] if achada else ""
        if not tela_n or not tarefa:
            self.anotar("app %s: troca sem reiniciar parou (tela nova %s, "
                        "tarefa %r na tela %s)" % (pacote, tela_n, tarefa,
                                                   tela_v))
            nova.parar()
            return False
        t_pronta = time.monotonic() - t0
        # (r137) A FOTO SO AGORA: ate aqui a janela velha seguia ao vivo (a
        # nova sobe invisivel -- so aparece no 1o quadro, que so vem depois
        # do move-stack). Congelado = so o move-stack + a nova aparecer.
        from . import disfarce
        capa = disfarce.cobrir(hwnd_velha, espera=0.1)
        if capas is not None:
            capas.append(capa)
        t_foto = time.monotonic()
        # (r139) Pela conversa ja aberta: sem esperar um adb novo subir. A
        # prova de que passou e a janela nova aparecer (so aparece com
        # imagem), e a conferencia abaixo segue igual.
        mover = "am display move-stack %s %s" % (tarefa, tela_n)
        resp = "" if self._pela_conversa(serial, mover) else \
            self._shell(serial, mover, espera=6).strip()
        t_move = time.monotonic() - t_foto
        # (r128) A conferencia no dumpsys (o erro do `am` sai pelo canal de
        # erro, que o `_shell` nao le) agora e DEPOIS, sem segurar a troca:
        # se a tarefa nao passou, a tela nova fica vazia e o vigia do app
        # abre o app nela sozinho -- so fica anotado.
        threading.Thread(target=self._conferir_troca,
                         args=(serial, tela_n, pacote, tarefa, resp),
                         daemon=True, name="confere-%s" % nome).start()
        # (r127) A janela nova ja nasceu NO LUGAR da velha (--window-x/y e
        # altura): o scrcpy so mostra a janela no 1o quadro, que so vem
        # agora, com o app nela. Nascer fora da vista e trazer depois NAO
        # funcionou (2 testes dele: a janela ficou escondida, nem a procura
        # pelo processo achava).
        self.pedidos.put(("subiu", nome, nova))
        threading.Thread(target=velha.parar, daemon=True,
                         name="parar-velha-%s" % nome).start()
        self.anotar("app %s: janela trocada SEM reiniciar em %.2f s "
                    "(tarefa %s, tela %s -> %s)"
                    % (pacote, time.monotonic() - t0, tarefa, tela_v, tela_n))
        hwnd = None
        if frente or capa.ativo:
            fim = time.monotonic() + 2
            while time.monotonic() < fim:
                hwnd = janela_scrcpy.achar(nova.pid)
                if hwnd:
                    if frente:
                        janela_scrcpy.trazer(hwnd)
                    break
                time.sleep(0.01)
        # (r136) A nova ja apareceu (debaixo do disfarce): um instante para
        # ela assentar e o disfarce some esmaecendo.
        if capa.ativo:
            time.sleep(disfarce.ASSENTAR_S)
            capa.soltar()
        # (r137) Tempos por fase, para achar onde ainda da pra cortar.
        self.anotar("app %s: disfarce %s -- nova pronta %.2f s, move-stack "
                    "%.2f s, congelado %.2f s"
                    % (pacote, "no ar" if capa.ativo
                       else "nao cobriu (%s)" % capa.motivo, t_pronta,
                       t_move, time.monotonic() - t_foto))
        return True

    def abrir_pelo_atalho(self, pacote: str, rotulo: str = "",
                          sair_se_falhar: bool = False) -> None:
        """
        (r159) O atalho da area de trabalho. Confere o celular ANTES (so o
        caminho curto): sem ele, uma caixa "nao conectado" e mais nada -- sem
        abrir o parear nem esperar conexao; se o scrcpy-f subiu so por causa
        do atalho (`sair_se_falhar`), ele fecha no OK.
        """
        self.anotar("atalho da area de trabalho: %s (%s)" % (rotulo or pacote,
                                                            pacote))

        def fazer():
            alvo = ""
            if self.config.instalacao_ok:
                alvo = self._em_uso_pronto() or celular.achar_rapido(
                    self.config.adb_exe, self.config.ip_reserva)
            if not alvo:
                self.anotar("atalho: celular nao conectado%s"
                            % (" -- fechando" if sair_se_falhar else ""))
                sistema.avisar("O celular não está conectado.\n\n"
                               "Conecte o celular e abra o atalho de novo.",
                               esperar=True)
                if sair_se_falhar and not self.sessoes and not self.ligando:
                    self.pedidos.put("sair")
                return
            self.pedidos.put(("app", pacote, rotulo))

        threading.Thread(target=fazer, daemon=True, name="atalho").start()

    def criar_atalho(self, pacote: str, rotulo: str) -> tuple:
        """(r159) Atalho do app na area de trabalho. FORA da thread da
        janela (o Windows leva ~1 s). Devolve (ok, caminho ou motivo)."""
        from . import atalho_desktop
        png = self.pasta_de_icones() / (pacote + ".png")
        padrao = icone.gravar_para_janela(caminhos.pasta_dados())
        ok, texto = atalho_desktop.criar(
            pacote, rotulo, png, padrao / "scrcpy.png" if padrao else None)
        self.anotar("atalho de %s na area de trabalho: %s" % (
            pacote, texto if ok else "FALHOU -- %s" % texto))
        return ok, texto

    def abrir_ou_trazer(self, pacote: str, rotulo: str = "") -> None:
        """Atalho do app: aberto -> vem para a frente; fechado -> abre."""
        if self.ativo(APP + pacote):
            self.trazer_app(pacote)
            return
        nome = rotulo or (self.config.apps.get("nomes") or {}).get(pacote) \
            or pacote
        self.alternar_app(pacote, nome)

    def _janela_da_sessao(self, nome: str):
        from . import janela_scrcpy
        sessao = self.sessoes.get(nome)
        pid = getattr(sessao, "pid", 0) if sessao is not None else 0
        return janela_scrcpy.achar(pid) if pid else None

    # -- no Windows (01/out) -----------------------------------------------

    def _registrar_windows(self) -> None:
        """O scrcpy-f com nome e icone na Central do Windows, e o protocolo
        "scrcpyf:" do clique nas notificacoes (HKCU, sem admin)."""
        from . import atalho_desktop, central_windows
        try:
            pasta = icone.gravar_para_janela(caminhos.pasta_dados(),
                                             self.config.scrcpy_exe)
            png = (pasta / "scrcpy.png") if pasta is not None else \
                caminhos.pasta_dados() / "icone-janela.png"
            exe, args = atalho_desktop.alvo_do_programa()
            if central_windows.registrar(png, [exe] + list(args)):
                self.anotar("windows: scrcpy-f registrado (central e scrcpyf:)")
        except Exception:
            log.exception("windows: registro")

    def _nome_windows(self, app: str) -> str:
        from . import notificacoes
        nome = self._nome_do_app(app)
        if nome == app:
            pacote = app.split(COPIA)[0]
            nome = notificacoes.nome_de_sistema(pacote) or \
                pacote.split(".")[-1]
        return nome

    def _icone_windows(self, app: str):
        try:
            arq = self.pasta_de_icones() / (app + ".png")
            return arq if arq.exists() else None
        except Exception:
            return None

    def _windows_chegou(self, n, de_novo: bool = False) -> None:
        if self.windows_notif is None or \
                not self.config.opcao("notif_windows"):
            return
        # (03/out) Os botoes e o responder vem do ouvinte; ele costuma chegar
        # antes, mas se ainda nao chegou, tenta uma vez daqui a pouco.
        o = self.notif.ouvida(n.chave)
        if o is None and self.notif.ouvinte_ok and not de_novo:
            t = threading.Timer(1.5, lambda: self._windows_chegou(n, True))
            t.daemon = True
            t.start()
            return
        o = o or {}
        acoes = [(i, titulo, texto) for i, (titulo, texto, _tela)
                 in enumerate((o.get("acoes") or [])[:3])]
        self.windows_notif.mostrar(n.chave, n.app, self._nome_windows(n.app),
                                   n.titulo, n.texto or n.subtexto,
                                   self._icone_windows(n.app), acoes,
                                   self._rosto_windows(o.get("icone")))

    def _rosto_windows(self, png):
        """(03/out) A foto de quem mandou num arquivo para o Windows (um por
        foto, na pasta temporaria; o mesmo nome = a mesma foto)."""
        if not png:
            return None
        import hashlib
        import tempfile
        from pathlib import Path
        arq = Path(tempfile.gettempdir()) / ("scrcpy-f-rosto-%s.png" %
                                             hashlib.md5(png).hexdigest()[:12])
        try:
            if not arq.exists():
                arq.write_bytes(png)
            return arq
        except Exception:
            return None

    def _windows_player(self, m, posicao: int) -> None:
        if self.windows_player is None:
            return
        if not self.config.opcao("player_windows"):
            m = None
        app = m["pacote"] if m else ""
        imagem = (self._capa_windows(app) or self._icone_windows(app)) \
            if m else None
        self.windows_player.atualizar(m, posicao, self._nome_windows(app)
                                      if m else "", imagem)

    def _capa_windows(self, app: str):
        """(02/out) A capa do album (do celular) num arquivo para o Windows
        mostrar nos controles de midia. Um arquivo por capa (o Windows
        guarda a imagem pelo endereco); a anterior e apagada."""
        capa = self.notif.capa(app) if self.notif is not None else None
        if not capa:
            return None
        import hashlib
        import tempfile
        from pathlib import Path
        arq = Path(tempfile.gettempdir()) / ("scrcpy-f-capa-%s.jpg" %
                                             hashlib.md5(capa).hexdigest()[:12])
        try:
            if not arq.exists():
                arq.write_bytes(capa)
                velha = getattr(self, "_capa_arquivo", None)
                if velha is not None and velha != arq:
                    velha.unlink(missing_ok=True)
            self._capa_arquivo = arq
            return arq
        except OSError:
            return None

    def _botao_windows(self, acao: str, ms: int) -> None:
        """Botao (ou tecla de midia) dos controles do Windows -> o celular."""
        m = self.notif.player()
        if not m:
            return
        self.anotar("player (windows): %s" % acao)
        self.notif.midia_comando(m["pacote"], acao, ms)

    def _icones_das_notificacoes(self) -> None:
        """(01/out) O icone de quem manda notificacao e nao esta na lista de
        apps (o "sistema android", a interface do sistema...): pedido ao
        celular uma vez por pacote; a janela ve pelo `icones_versao`."""
        pedidos = self.__dict__.setdefault("_icones_notif_pedidos", set())
        try:
            pasta = self.pasta_de_icones()
        except Exception:
            return
        faltam = sorted({n.app for n in self.notif.todas()
                         if n.app not in pedidos
                         and not (pasta / (n.app + ".png")).exists()})
        if not faltam:
            return
        pedidos.update(faltam)

        def buscar():
            try:
                if self.buscar_icones(faltam):
                    self.icones_versao = getattr(self, "icones_versao", 0) + 1
                    self.anotar("icones das notificacoes: %s" % ", ".join(
                        faltam)[:200])
            except Exception:
                log.exception("icones das notificacoes")

        threading.Thread(target=buscar, daemon=True,
                         name="icones-notif").start()

    def _pode_avisar_notif(self, app: str) -> bool:
        """(01/out) Sem aviso se o app ja esta aberto numa janela do PC e na
        frente (ele ja esta vendo). Chamado da thread das notificacoes."""
        from . import janela_scrcpy
        if not self.ativo(APP + app):
            return True
        hwnd = self._janela_da_sessao(APP + app)
        return not hwnd or janela_scrcpy.frente() != hwnd

    def _nome_do_app(self, app: str) -> str:
        return (self.config.apps.get("nomes") or {}).get(app) or \
            next((a[0] for a in (getattr(self, "apps_do_celular", None) or [])
                  if a[1] == app), app)

    def abrir_pela_notificacao(self, app: str, alvo=None,
                               chave: str = "") -> None:
        """
        (01/out) Clique numa notificacao: abre O QUE O TOQUE NO CELULAR
        ABRIRIA (pedido dele), numa janela do PC. O destino vem do
        `dumpsys activity intents` (numa thread); a janela e a do app de
        destino (a do sistema android abre as Configuracoes). Sem destino
        que de para abrir: o app, como antes.
        (02/out, pedido dele) `chave` = clique no CORPO da notificacao: ela
        sai, como no celular -- la so as que tem AUTO_CANCEL saem ao toque
        (as fixas, de musica, de download em andamento ficam). Os botoes da
        notificacao nao passam chave: no celular eles tambem nao tiram.
        """
        self.anotar("notificacao: abrir %s" % app)
        threading.Thread(target=self._abrir_destino, args=(app, alvo, chave),
                         daemon=True, name="notif-abrir").start()

    def _abrir_destino(self, app: str, alvo, chave: str = "") -> None:
        pelo_ouvinte = False
        try:
            # (03/out) Com o ouvinte, o toque e o MESMO do celular (o item
            # exato: a conversa, o e-mail), na janela do app.
            pelo_ouvinte = self._pelo_ouvinte(app, chave, -1)
            if not pelo_ouvinte:
                self._abrir_destino_ja(app, alvo)
        finally:
            # Depois de ler o destino: tirar antes podia levar junto o
            # registro do PendingIntent que o `dumpsys` mostra. Pelo ouvinte
            # quem tira e o `_abrir_intencao`, depois do toque.
            if not pelo_ouvinte:
                self._tirar_se_auto(chave)

    def _tirar_se_auto(self, chave: str) -> None:
        n = next((x for x in self.notif.todas() if x.chave == chave),
                 None) if chave else None
        if n is not None and "AUTO_CANCEL" in n.flags:
            self.anotar("notificacao: aberta -> sai (AUTO_CANCEL)")
            self.notif.remover([chave])

    PELO_OUVINTE = "--scrcpyf-ouvinte"

    def _pelo_ouvinte(self, app: str, chave: str, indice: int) -> bool:
        """
        (03/out) O toque (`indice` -1) ou o botao `indice` da notificacao
        abre uma TELA do app: pelo ouvinte ela abre na janela do app no PC,
        exatamente onde o toque no celular abriria. False = sem ouvinte,
        nao abre tela, ou o app nao abre em janela (fica o jeito antigo).
        """
        o = self.notif.ouvida(chave) if chave else None
        if not o:
            return False
        if indice < 0:
            abre_tela = o.get("toque") == "a"
        else:
            acoes = o.get("acoes") or []
            abre_tela = 0 <= indice < len(acoes) and acoes[indice][2]
        if not abre_tela or not any(a[1] == app for a in (
                getattr(self, "apps_do_celular", None) or [])):
            return False
        self.anotar("notificacao: %s pelo ouvinte -> janela %s" % (
            "toque" if indice < 0 else "botao %d" % indice, app))
        self.pedidos.put(("abrir_destino", app, self._nome_do_app(app),
                          [self.PELO_OUVINTE, chave, str(indice)]))
        return True

    def acao_notificacao(self, app: str, chave: str, indice: int,
                         texto: str = "", ao_fim=None) -> None:
        """
        (03/out) Um botao do proprio app na notificacao (Responder, Marcar
        como lida, Curtir...). Com `texto`: a resposta. O que abre tela vai
        para a janela do app; o resto o celular faz sozinho. `ao_fim(ok,
        detalhe)` e chamado DE OUTRA THREAD.
        """
        def trabalho():
            ok, detalhe = False, ""
            try:
                if not texto and self._pelo_ouvinte(app, chave, indice):
                    ok, detalhe = True, "abrindo"
                else:
                    ok, detalhe = self.notif.apertar_acao(chave, indice, texto)
            except Exception as erro:
                log.exception("acao da notificacao")
                ok, detalhe = False, str(erro)
            if ao_fim is not None:
                ao_fim(ok, detalhe)

        threading.Thread(target=trabalho, daemon=True,
                         name="notif-acao").start()

    def _abrir_destino_ja(self, app: str, alvo) -> None:
        from . import notificacoes
        destino = self.notif.destino(alvo) if alvo else {}
        pacote, usuario = separar_app(app)
        if destino.get("tipo") == "startActivity":
            alvo_pkg = notificacoes.pacote_do_destino(destino)
            serial = self._em_uso_pronto()
            if not alvo_pkg and destino.get("act") and serial:
                comp = self._shell(serial, "cmd package resolve-activity "
                                   "--brief -a '%s' | tail -1"
                                   % destino["act"], espera=8).strip()
                alvo_pkg = comp.split("/")[0] if "/" in comp else ""
            if alvo_pkg:
                janela = alvo_pkg if usuario <= 0 else \
                    "%s%s%d" % (alvo_pkg, COPIA, usuario)
                args = notificacoes.argumentos_am(destino)
                self.anotar("notificacao: destino %s -> janela %s (%s)"
                            % (app, janela, " ".join(args)[:160]))
                self.pedidos.put(("abrir_destino", janela,
                                  self._nome_do_app(janela), args))
                return
        abre = any(a[1] == app for a in (getattr(self, "apps_do_celular",
                                                 None) or []))
        self.anotar("notificacao: sem destino de tela (%s); %s"
                    % (destino.get("tipo") or "nao lido",
                       "abre o app" if abre else "o app nao abre em janela"))
        if abre:
            self.pedidos.put(("app", app, self._nome_do_app(app)))

    # (01/out) CHAMADA: o `cmd telecom` nao tem "atender"; o que o Android
    # aceita do shell e a tecla de telefone (KEYCODE_CALL / ENDCALL, que o
    # sistema trata com o telefone tocando) e, de reserva, o botao do fone
    # (`cmd media_session dispatch headsethook` -- a sessao do telecom e a
    # de prioridade global). Atender pelo PC atende NO CELULAR.

    def _estado_chamada(self, serial: str) -> str:
        import re
        r = self._shell(serial, "dumpsys telephony.registry | grep -m1 "
                        "mCallState", espera=6)
        m = re.search(r"mCallState=(\d)", r)
        return m.group(1) if m else "?"

    def atender_chamada(self) -> None:
        self._acao_chamada("atender", ["input keyevent KEYCODE_CALL",
                                       "cmd media_session dispatch headsethook"])

    def recusar_chamada(self) -> None:
        self._acao_chamada("recusar", ["input keyevent KEYCODE_ENDCALL"])

    def _acao_chamada(self, nome: str, jeitos: list) -> None:
        def trabalho():
            serial = self._em_uso_pronto()
            if not serial:
                self.anotar("chamada: %s sem celular" % nome)
                return
            for jeito in jeitos:
                self._shell(serial, jeito, espera=6)
                time.sleep(1.0)
                estado = self._estado_chamada(serial)
                self.anotar("chamada: %s por '%s' -> estado %s" % (
                    nome, jeito, estado))
                if estado != "1":            # saiu de "tocando": serviu
                    return
            self.anotar("chamada: %s NAO funcionou (segue tocando)" % nome)

        threading.Thread(target=trabalho, daemon=True,
                         name="chamada-%s" % nome).start()

    def abrir_tela(self, janela: str, args: list) -> None:
        """(01/out) Uma tela do celular (do menu da notificacao: as
        configuracoes do app, da categoria...) na janela do app `janela`."""
        self.anotar("notificacao: tela %s (%s)" % (janela, " ".join(args)[:160]))
        self.pedidos.put(("abrir_destino", janela, self._nome_do_app(janela),
                          list(args)))

    def _abrir_com_destino(self, janela: str, nome: str, args: list) -> None:
        """No laco: a janela do app ja aberta recebe o destino (e vem para a
        frente); fechada, abre ja com ele (sem o --start-app)."""
        if self.ativo(APP + janela):
            sessao = self.sessoes.get(APP + janela)
            threading.Thread(target=self._abrir_intencao,
                             args=(getattr(sessao, "serial", ""), janela,
                                   sessao, args, True),
                             daemon=True, name="notif-destino").start()
            return
        if self.ocupado(APP + janela) or not self.config.instalacao_ok:
            return
        self.anotar("pedido: abrir o app %s (%s) no destino da notificacao"
                    % (nome, janela))
        self.ligando.add(APP + janela)
        # (08/out) o app marcado "sempre em tela cheia" tambem abre assim
        # pela notificacao
        cheia = bool(self.config.app(janela).get("tela_cheia"))
        if cheia:
            self._tela_cheia.add(janela)
        else:
            self._tela_cheia.discard(janela)
        self._avisar_mudanca()
        threading.Thread(target=self._partida_app,
                         args=(APP + janela, janela, nome),
                         kwargs={"intencao": args, "tela_cheia": cheia},
                         daemon=True,
                         name="partida-%s" % janela).start()

    def _abrir_intencao(self, serial: str, chave: str, sessao, args: list,
                        trazer: bool = False) -> None:
        """Poe o destino da notificacao na tela virtual da janela. Recusado
        (tela nao exportada, por exemplo): a tela de entrada do app."""
        import shlex
        _pacote, usuario = separar_app(chave)
        tela = None
        fim = time.monotonic() + 20
        while not tela and time.monotonic() < fim and sessao is not None \
                and sessao.rodando:
            tela = (self._tela_da_sessao(sessao) or (None,))[0]
            if not tela:
                time.sleep(0.1)
        if not tela:
            self.anotar("notificacao %s: sem a tela da janela" % chave)
            return
        if args and args[0] == self.PELO_OUVINTE:
            # (03/out) O toque/botao de verdade, na tela da janela.
            k, indice = args[1], int(args[2])
            if indice < 0:
                ok, _d = self.notif.tocar_corpo(k, int(tela))
            else:
                ok, _d = self.notif.apertar_acao(k, indice, "", int(tela))
            if ok and indice < 0:
                self._tirar_se_auto(k)
            if not ok:
                comp = self._componente(serial, chave)
                if comp:
                    self._shell(serial, "am start --user %d --display %s -n %s"
                                % (max(usuario, 0), tela, comp), espera=8)
            if trazer:
                self.trazer_app(chave)
            return
        resp = self._shell(serial, "am start --user %d --display %s %s"
                           % (max(usuario, 0), tela,
                              " ".join(shlex.quote(a) for a in args)),
                           espera=8).strip()
        falhou = any(p in resp for p in ("Error", "Exception", "Security"))
        self.anotar("notificacao %s: destino na tela %s -> %s"
                    % (chave, tela, ("FALHOU: " if falhou else "") +
                       resp.replace("\n", " ")[:160]))
        if falhou:
            comp = self._componente(serial, chave)
            if comp:
                self._shell(serial, "am start --user %d --display %s -n %s"
                            % (max(usuario, 0), tela, comp), espera=8)
        if trazer:
            self.trazer_app(chave)

    def trazer_app(self, pacote: str) -> bool:
        """A janela do app vem para a frente (o icone dele na lista)."""
        from . import janela_scrcpy
        hwnd = self._janela_da_sessao(APP + pacote)
        return bool(hwnd) and janela_scrcpy.trazer(hwnd)

    def trocar_janelas(self) -> None:
        """
        Atalho "trocar entre as janelas do celular" (pedido dele,
        23/set/2026): passa para a PROXIMA janela do celular -- o espelhar e
        cada app, nesta ordem --, como um Alt+Tab so delas.
        """
        from . import janela_scrcpy
        nomes = ["jogo"] + sorted(n for n in self.sessoes if n.startswith(APP))
        janelas = [h for h in (self._janela_da_sessao(n) for n in nomes) if h]
        if not janelas:
            self.anotar("trocar janelas: nenhuma janela do celular aberta")
            return
        frente = janela_scrcpy.frente()
        vez = janelas.index(frente) + 1 if frente in janelas else 0
        alvo = janelas[vez % len(janelas)]
        janela_scrcpy.trazer(alvo)

    def _shell(self, serial: str, comando: str, espera: float = 15) -> str:
        """Um comando no celular (fora da thread da janela). Nunca levanta."""
        import subprocess
        try:
            r = subprocess.run([str(self.config.adb_exe), "-s", serial,
                                "shell", comando], capture_output=True,
                               timeout=espera,
                               creationflags=getattr(subprocess,
                                                     "CREATE_NO_WINDOW", 0))
            return (r.stdout or b"").decode("utf-8", errors="replace")
        except Exception:
            return ""

    # O laco que roda NO CELULAR, um so para todas as janelas de app. Cada
    # volta: UM `dumpsys activity activities` (antes era um por janela, 10x
    # por segundo -- com 2 apps o Android travou: "o processo system nao
    # esta respondendo", teste dele de 23/set/2026). Para cada tela virtual
    # vigiada: o app sumiu -> olha a energia (acorda se a tela apagou) e abre
    # o app de novo, sem animacao. A cada ~6 s confere a energia mesmo com
    # tudo em ordem. `%s` = pares 'tela=componente', entre aspas simples.
    # (02/out, revisao; ele deixou a decisao comigo) Era 0,4: roda o tempo
    # todo com qualquer app em janela. A 0,6 pesa 1/3 menos no celular e o
    # app que saiu volta ~0,2 s mais tarde (o voltar da tela inicial
    # continua < 1 s).
    VIGIA_A_CADA_S = 0.6
    # Mata no celular os lacos da vigia (o de agora e sobras). Os colchetes
    # fazem o proprio pkill nao casar com o padrao.
    VIGIA_MATAR = "pkill -f 'scrcpyf-vigi[a]' ; true"
    # (r150) PERGUNTA LEVE PRIMEIRO. A sonda_peso (25/set/2026): o dumpsys
    # inteiro traz ~115 KB por volta; `cmd activity stack list` traz ~9 KB
    # com o que importa -- cada tarefa com o app, `visible=` e a tela
    # (`displayId=` na linha do grupo de cima). O sed poe o numero da tela no
    # fim de cada linha de tarefa (" @D45"). App achado na tela certa:
    # visivel -> nada; nao visivel -> "escondido" (como antes). NAO achado
    # (saiu, ou a tela sumiu) -> SO ENTAO o dumpsys de sempre decide, com a
    # mesma regra de antes -- que tambem sabe se a tela ainda existe (sem
    # isso, reabrir numa tela que acabou de fechar podia jogar o app na tela
    # do celular). Android sem a pergunta leve (resposta vazia): `s=0` e o
    # laco vira o de antes, inteiro.
    # (02/out, teste no S22) O BLOCO DA TELA ACABA NA PRIMEIRA LINHA SEM
    # RECUO. Antes ia ate o proximo "Display #" -- a ULTIMA tela virtual
    # nao tem um depois dela, e o bloco engolia o resto do dumpsys (tarefas
    # recentes...). La o app aparecia sem "visible=true" e virava
    # "escondido" para sempre: tela preta e o app nunca reaberto (o relato
    # dele de 02/out, voltar na tela inicial do Google).
    LACO_DA_VIGIA = (
        "f=/data/local/tmp/scrcpyf-vigia.txt; "
        "sleep 1; n=0; s=1; while :; do n=$((n+1)); d=0; M=; "
        "if [ $s = 1 ]; then M=$(cmd activity stack list 2>/dev/null | "
        "sed -n '/taskId=/{G;s/\\n/ @D/;p;d;};"
        "/displayId=/{s/.*displayId=\\([0-9]*\\).*/\\1/;h;}'); "
        "case \"$M\" in *taskId=*) ;; *) s=0;; esac; fi; "
        "if [ $n = 3 ]; then dumpsys activity activities > $f 2>/dev/null; "
        "d=1; echo \"vivo $([ $s = 1 ] && echo leve || echo pesado) "
        "$(grep '^Display #' $f | tr '\\n' ' ' | cut -c1-150)\"; fi; "
        "for p in %s; do t=${p%%%%=*}; c=${p#*=}; u=${c%%=*}; c=${c#*=}; "
        "k=${c%%/*}; "
        "if [ $s = 1 ]; then l=$(printf '%%s\\n' \"$M\" | "
        "grep \"@D$t\\$\" | grep -m1 \": $k/\"); "
        "case \"$l\" in *visible=true*) continue;; "
        "?*) v=$(printf '%%s\\n' \"$M\" | grep \"@D$t\\$\" | "
        "grep -c visible=true); echo \"escondido $t $v\"; continue;; "
        "esac; fi; "
        "if [ $d = 0 ]; then dumpsys activity activities > $f 2>/dev/null; "
        "d=1; fi; "
        "b=$(sed -n \"/^Display #$t /,/^[^ ]/p\" $f); "
        "case \"$b\" in '') continue;; esac; "
        "l=$(printf '%%s\\n' \"$b\" | grep -m1 \"Task{.*$k\"); "
        "case \"$l\" in *visible=true*) continue;; "
        "?*) echo \"escondido $t\"; continue;; esac; "
        "am start --user $u -f 0x10000 --display $t -n $c >/dev/null 2>&1; "
        "echo \"reaberto $t $l\" | cut -c1-160; done; "
        "sleep %s; done")
    # (r110) Acordar o celular SAIU daqui: agora e o vigia do sono, que
    # tambem apaga a tela fisica. Os dois acordando juntos brigariam.

    def _manter_no_app(self, pacote: str, sessao) -> None:
        """
        O APP NAO SAI DA JANELA (pedido dele, 23/set/2026). Acha o numero da
        tela virtual no log do scrcpy ("New display: ... (id=97)") e a tela
        de entrada do app, e poe os dois no vigia unico (`LACO_DA_VIGIA`).
        Enquanto a janela existir o app volta sozinho; fechou, sai do vigia.
        """
        import re
        serial = getattr(sessao, "serial", "")
        tela = ""
        fim = time.monotonic() + 20
        while not tela and time.monotonic() < fim and sessao.rodando:
            try:
                with open(sessao.arquivo_log, encoding="utf-8",
                          errors="replace") as arq:        # (r138) fecha
                    texto = arq.read()
                m = re.search(r"New display: .*?\(id=(\d+)\)", texto)
                tela = m.group(1) if m else ""
            except Exception:
                pass
            if not tela:
                time.sleep(0.3)
        if not tela:
            self.anotar("manter no app %s: nao achei o numero da tela" % pacote)
            return
        componente = self._componente(serial, pacote)       # (r186)
        if not componente:
            self.anotar("manter no app %s: sem a tela de entrada (%r)"
                        % (pacote, componente))
            return
        with self._vigia_trava:
            self._vigia_alvos[pacote] = (tela, componente)
        self._religar_vigia(serial)
        self.anotar("manter no app %s: vigiando a tela %s" % (pacote, tela))
        # (r134) A TAREFA do app, para fechar o app ao fechar a janela (ver
        # `_app_fechou`). O app ainda pode estar subindo: tenta por ~5 s.
        fim = time.monotonic() + 5
        while sessao.rodando and not self._sair and time.monotonic() < fim:
            tarefa = self._tarefa_na_tela(serial, tela, pacote)
            if tarefa:
                self._tarefa_do_app[pacote] = ([tarefa], serial)
                break
            time.sleep(0.3)
        while sessao.rodando and not self._sair:
            time.sleep(0.5)
        with self._vigia_trava:
            # (r125) Na troca de janela a NOVA ja pode estar vigiando o mesmo
            # app em outra tela: so tira o alvo se ainda for o desta.
            if (self._vigia_alvos.get(pacote) or ("",))[0] == tela:
                self._vigia_alvos.pop(pacote, None)
            else:
                return
        self._religar_vigia(serial)

    def _religar_vigia(self, serial: str) -> None:
        """Troca o laco do celular pelo da lista de agora (ou so desliga)."""
        # (02/out, revisao) UM religar por vez, inteiro (pkill + subida): a
        # troca de janela e o manter-no-app religam de threads diferentes, e
        # entre o pkill de uma e a subida da outra sobrava um laco orfao NO
        # CELULAR (matar o adb do PC nao o mata), a 0,4 s, com alvos velhos.
        trava = self.__dict__.setdefault("_vigia_religar_trava",
                                         threading.Lock())
        with trava:
            self._religar_vigia_ja(serial)

    def _religar_vigia_ja(self, serial: str) -> None:
        import subprocess
        with self._vigia_trava:
            velho, self._vigia_proc = self._vigia_proc, None
            if velho is not None:
                try:
                    velho.terminate()
                except Exception:
                    pass
            alvos = dict(self._vigia_alvos)
        # (r120) Matar o adb do PC NAO mata o laco no celular (o mesmo que o
        # STATUS_MATAR resolve no status): sem isto, cada troca de janela
        # deixava um laco velho lendo o dumpsys a cada 0,4 s no celular.
        self._shell(serial, self.VIGIA_MATAR, 5)
        self._animacoes_rapidas(serial, bool(alvos))
        with self._vigia_trava:
            if self._vigia_proc is not None:     # outra thread subiu um
                try:                             # enquanto as animacoes
                    self._vigia_proc.terminate() # eram trocadas
                except Exception:
                    pass
                self._vigia_proc = None
            alvos = dict(self._vigia_alvos)
            if not alvos or self._sair:
                return
            # (r186) "tela=usuario=entrada": a copia reabre no usuario dela.
            pares = " ".join("'%s=%d=%s'" % (tela, separar_app(pac)[1], comp)
                             for pac, (tela, comp) in alvos.items())
            laco = self.LACO_DA_VIGIA % (pares, self.VIGIA_A_CADA_S)
            try:
                proc = subprocess.Popen(
                    [str(self.config.adb_exe), "-s", serial, "shell", laco],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception as erro:
                self.anotar("vigia dos apps: nao subiu (%s)" % erro)
                return
            self._vigia_proc = proc
        de_quem = {tela: pacote for pacote, (tela, _c) in alvos.items()}
        entrada = {tela: comp for _p, (tela, comp) in alvos.items()}

        def ler():
            vezes: dict = {}
            episodio: dict = {}       # tela -> [ultimo "escondido", trazido]
            for bruta in proc.stdout:
                linha = bruta.decode("utf-8", "replace").strip()
                if linha.startswith("vivo"):
                    self.anotar("vigia dos apps: no ar -- telas: %s"
                                % linha[5:])
                    continue
                # "escondido <tela> 0" = nada visivel na tela dele (foi
                # para tras); com numero > 0, outro app esta por cima.
                if linha.startswith("escondido ") and \
                        linha.split()[2:3] == ["0"]:
                    self._voltar_escondido(serial, linha.split()[1],
                                           de_quem, entrada, episodio)
                # (02/out) Reaberto pela vigia: a tarefa pode ser outra.
                if linha.startswith("reaberto ") and \
                        linha.split()[1] in de_quem:
                    t = linha.split()[1]
                    self._seguir_tarefa(serial, t, de_quem[t])
                # (r114) "escondido" = o app segue na tela virtual, so o
                # Android o marcou como nao visivel (ex.: jogo aberto no
                # celular). NAO reabre -- reabrir em loop fazia o video do
                # Insta repetir um pedaco "tipo gif". Anota pouco (~1/min).
                palavra = linha.split(" ", 1)[0]
                if linha == "acordado" or palavra in ("reaberto",
                                                      "escondido"):
                    tela = (linha.split() + [""])[1] if \
                        palavra != "acordado" else ""
                    chave = "celular acordado" if linha == "acordado" else \
                        palavra + " " + de_quem.get(tela, tela)
                    vezes[chave] = vezes.get(chave, 0) + 1
                    n = vezes[chave]
                    teto = 150 if palavra == "escondido" else 20
                    if n <= 3 or n % teto == 0:
                        self.anotar("vigia dos apps: %s (%dx)%s" % (
                            chave, n, (" -- " + linha[:150]) if n <= 3 and
                            linha != "acordado" else ""))

        threading.Thread(target=ler, daemon=True, name="vigia-le").start()

    # VOLTAR NA TELA INICIAL DO APP DEIXAVA A JANELA PRETA (teste dele,
    # 02/out/2026, app Google). O app se manda para tras (moveTaskToBack):
    # a tarefa segue na tela virtual, invisivel, e a tela virtual nao tem
    # inicio por baixo. Para o vigia isso e "escondido", que nao reabre
    # (r114). Aqui: escondido, NADA visivel na tela virtual (sem outro app
    # por cima, ex.: link aberto no navegador) e a janela na frente do PC (esta
    # usando a janela) -> traz o app de volta UMA vez por episodio, como o
    # inicio faria (MAIN/LAUNCHER + NEW_TASK|RESET_TASK_IF_NEEDED), sem
    # recriar a tela. Episodio = "escondido" seguidos (o laco repete a cada
    # 0,4 s); 1,5 s sem ele = acabou.
    def _voltar_escondido(self, serial: str, tela: str, de_quem: dict,
                          entrada: dict, episodio: dict) -> None:
        from . import janela_scrcpy
        agora = time.monotonic()
        ep = episodio.get(tela)
        if ep is None or agora - ep[0] > 1.5:
            ep = episodio[tela] = [agora, False]
        ep[0] = agora
        chave, comp = de_quem.get(tela), entrada.get(tela)
        if ep[1] or not chave or not comp:
            return
        sessao = self.sessoes.get(APP + chave)
        pid = getattr(sessao, "pid", 0)
        if not pid or janela_scrcpy.pid_da_frente() != pid:
            return
        ep[1] = True
        comando = ("am start --user %d -a android.intent.action.MAIN "
                   "-c android.intent.category.LAUNCHER -f 0x10210000 "
                   "--display %s -n %s" % (separar_app(chave)[1], tela, comp))
        if not self._pela_conversa(serial, comando):
            threading.Thread(target=self._shell, args=(serial, comando, 5),
                             daemon=True, name="vigia-volta").start()
        self.anotar("vigia dos apps: %s foi para tras com a janela na "
                    "frente; trazido de volta" % chave)
        self._seguir_tarefa(serial, tela, chave)

    def _seguir_tarefa(self, serial: str, tela: str, chave: str) -> None:
        """(02/out) Depois de uma reabertura: guarda a tarefa nova do app,
        para fechar tambem ela quando a janela fechar (`_app_fechou`)."""
        def trabalho():
            time.sleep(1.5)
            nova = self._tarefa_na_tela(serial, tela, chave)
            if not nova:
                return
            tarefas, s = self._tarefa_do_app.get(chave, ([], serial))
            if nova not in tarefas:
                self._tarefa_do_app[chave] = (tarefas + [nova], s)

        threading.Thread(target=trabalho, daemon=True,
                         name="seguir-tarefa").start()

    # -- vigia do sono -------------------------------------------------------
    # APP NO PC NAO MORRE COM A TELA DO CELULAR APAGADA (pedido dele,
    # 23/set/2026; provado pela sonda_sono). Dormindo, o Android pausa os
    # apps em todas as telas; acordado -- mesmo bloqueado -- eles seguem.
    # Enquanto houver app (ou o DeX) em janela:
    # - o celular ia dormir (botao ou tempo) com a tela ACESA -> acorda na
    #   hora e apaga SO a tela fisica (scrcpy so de controle, -S), com
    #   --keep-active para nao dormir por tempo;
    # - o botao com a tela apagada POR NOS -> ele quer usar o celular: solta
    #   o controle e acende a tela normal;
    # - fechou o ultimo app com a tela apagada por nos -> o celular dorme de
    #   verdade (a menos que o espelhar esteja no ar).
    # O estado vem de UM laco no celular que so escreve quando muda.
    LACO_DO_SONO = (
        "o=; while :; do s=$(dumpsys power | grep -m1 mWakefulness=); "
        "if [ \"$s\" != \"$o\" ]; then echo \"$s\"; o=$s; fi; "
        "sleep 0.4; done")
    # Depois de agir, os "dormindo" que ja estavam na fila sao velhos.
    SONO_SURDO_S = 1.5
    # (r133) Mata NO CELULAR as sobras do vigia do sono: o laco (dumpsys
    # power) e o servidor do scrcpy de controle com keep_active -- a sonda da
    # tela achou um vivo havia 4 h, segurando a tela acesa com o programa
    # fechado. Matar o processo do PC nao mata o do celular. Os colchetes
    # fazem o proprio pkill nao casar com o padrao.
    SONO_PADRAO_CONTROLE = "video=false audio=false.*keep_active=tru[e]"
    SONO_MATAR_CONTROLE = "pkill -f '%s' ; true" % SONO_PADRAO_CONTROLE
    # (r150) O VIGIA DO SONO POR EVENTO. A sonda_peso (25/set/2026) mediu o
    # `dumpsys power` como a pergunta MAIS pesada ao celular (~68 ms cada,
    # 2,5x por segundo). Aqui o celular AVISA: o `logcat` do buffer de
    # eventos escreve uma linha quando alguem pede para dormir
    # (power_sleep_requested) e quando a tela apaga/acende
    # (power_screen_state). So entao o estado e lido -- na hora e de novo
    # 0,3 s depois (o pedido chega antes da troca de estado). Uma conferencia
    # a cada 3 s fica de seguranca (evento perdido, logcat que caiu). A saida
    # e a MESMA do laco antigo ("mWakefulness=..." so quando muda). O
    # "scrcpyf_sono:S" nao filtra nada: e a marca para o pkill achar o
    # logcat e os lacos no celular.
    LACO_DO_SONO_EVENTO = (
        "o=; c(){ s=$(dumpsys power | grep -m1 mWakefulness=); "
        "if [ \"$s\" != \"$o\" ] || [ \"$1\" = e ]; then echo \"$s\"; "
        "o=$s; fi; }; c; "
        "( ( logcat -b events -T \"$(date '+%m-%d %H:%M:%S.000')\" "
        "-s power_sleep_requested power_screen_state scrcpyf_sono:S "
        "2>/dev/null; echo semlog ) & while :; do sleep 3; echo t; done ) | "
        "while read l; do case \"$l\" in t) c;; semlog) echo semlog;; "
        "*power_sleep_requested*) cmd input keyevent KEYCODE_WAKEUP; "
        "echo botao; sleep 0.3; c e;; *) c e;; esac; done")
    # (r154) Pedido de dormir (o botao ou o tempo) = o PROPRIO celular manda
    # acordar na hora e avisa "botao"; o PC so decide se o painel liga ou
    # desliga. So eventos de AGORA em diante (-T com a hora do celular): um
    # pedido velho no buffer viraria um toque fantasma.
    # (r153) Evento = escreve o estado MESMO SEM MUDAR ("c e"). Teste dele:
    # o nosso WAKEUP nao gera evento; o laco ficava achando que o celular
    # seguia "Dozing" e o toque seguinte (Dozing de novo) nao era avisado.
    # O lado do PC ja ignora repeticao (surdo de 1,5 s depois de agir).
    # (r156) Com o programinha do painel VIGIANDO o botao, o laco do celular
    # vira so uma conferencia de seguranca a cada 3 s (mudou -> escreve).
    LACO_DO_SONO_ESTADO = (
        "o=; c(){ s=$(dumpsys power | grep -m1 mWakefulness=); "
        "if [ \"$s\" != \"$o\" ]; then echo \"$s\"; o=$s; fi; }; "
        "c; while :; do sleep 3; c; done")
    # O celular conhece os eventos? (arquivo de nomes de evento do Android.)
    SONO_TEM_EVENTOS = ("grep -c -w -e power_sleep_requested -e "
                        "power_screen_state /system/etc/event-log-tags "
                        "2>/dev/null")
    SONO_MATAR = ("pkill -f 'mWakefulnes[s]=' ; pkill -f 'scrcpyf_son[o]' ; "
                  + SONO_MATAR_CONTROLE)

    def _acender_de_verdade(self, serial: str) -> str:
        """
        (r151) Acorda o celular e confere pelo proprio `dumpsys power` (o
        estado e o da tela), repetindo o WAKEUP ate 4x. Devolve o que
        aconteceu, para o registro.
        """
        import re
        estado = ""
        # (r153) CICLO DORMIR -> ACORDAR, sem scrcpy nenhum no meio. Testes
        # dele (25/set/2026): so o WAKEUP deixava o celular "Awake" com o
        # painel ainda desligado pelo scrcpy de controle; o que acendia de
        # verdade era ele apertar o botao mais duas vezes (dormir e acordar
        # de novo). Aqui: meio segundo para a limpeza do scrcpy terminar,
        # dorme de verdade e acorda -- o Android religa o painel ao acordar.
        time.sleep(0.5)
        self._shell(serial, "cmd input keyevent KEYCODE_SLEEP", espera=5)
        time.sleep(0.7)
        for vez in range(1, 5):
            self._shell(serial, "cmd input keyevent KEYCODE_WAKEUP", espera=5)
            time.sleep(0.35)
            texto = self._shell(serial, "dumpsys power | grep -E -m3 "
                                "'mWakefulness=|Display Power: state='",
                                espera=5)
            acordado = re.search(r"mWakefulness=(\w+)", texto)
            tela = re.search(r"Display Power: state=(\w+)", texto)
            estado = "%s/%s" % (acordado.group(1) if acordado else "?",
                                tela.group(1) if tela else "?")
            if acordado and acordado.group(1) == "Awake" and \
                    (tela is None or tela.group(1) != "OFF"):
                return "tela acesa (%s, tentativa %d)" % (estado, vez)
        return "NAO acendeu depois de 4 tentativas (%s)" % estado

    # (08/out, teste dele: "o do celular foi pro pc mas nao o inverso") O
    # scrcpy so passa o texto do PC para o celular no Ctrl+V dentro da janela
    # dele. Aqui o programa vigia a area de transferencia do Windows (o numero
    # de sequencia, sem abrir nada: leve) e, quando muda, poe o texto no
    # celular (android\Area.java, no scrcpyf-notif.jar). O que veio DO
    # celular (dono = um scrcpy) nao volta; texto igual ao ultimo nao vai de
    # novo (sem ida e volta infinita). Tudo isso so com a opcao ligada.
    AREA_MAX = 16000                     # letras (a linha do adb tem limite)

    def _garantir_vigia_area(self) -> None:
        t = getattr(self, "_area_thread", None)
        if t is not None and t.is_alive():
            return
        self._area_thread = threading.Thread(target=self._vigia_area,
                                             daemon=True, name="area-pc")
        self._area_thread.start()

    @staticmethod
    def _area_do_windows():
        """(numero de sequencia, texto ou None, exe do dono) -- so Windows."""
        import ctypes
        import ctypes.wintypes as wt
        import os
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        u.GetClipboardData.restype = ctypes.c_void_p
        k.GlobalLock.restype = ctypes.c_void_p
        k.GlobalLock.argtypes = [ctypes.c_void_p]
        k.GlobalUnlock.argtypes = [ctypes.c_void_p]
        seq = u.GetClipboardSequenceNumber()
        dono_exe = ""
        hwnd = u.GetClipboardOwner()
        if hwnd:
            pid = wt.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            h = k.OpenProcess(0x1000, False, pid.value)
            if h:
                buf = ctypes.create_unicode_buffer(600)
                n = wt.DWORD(600)
                if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    dono_exe = os.path.basename(buf.value).lower()
                k.CloseHandle(h)
        texto = None
        for _vez in range(5):
            if u.OpenClipboard(None):
                try:
                    dados = u.GetClipboardData(13)          # CF_UNICODETEXT
                    if dados:
                        p = k.GlobalLock(dados)
                        if p:
                            try:
                                texto = ctypes.wstring_at(p)
                            finally:
                                k.GlobalUnlock(dados)
                finally:
                    u.CloseClipboard()
                break
            time.sleep(0.05)
        return seq, texto, dono_exe

    @staticmethod
    def _area_por_no_windows(texto: str) -> bool:
        """Poe `texto` na area de transferencia do Windows (CF_UNICODETEXT)."""
        import ctypes
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        k.GlobalAlloc.restype = ctypes.c_void_p
        k.GlobalLock.restype = ctypes.c_void_p
        k.GlobalLock.argtypes = [ctypes.c_void_p]
        k.GlobalUnlock.argtypes = [ctypes.c_void_p]
        u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        dados = (texto + "\0").encode("utf-16-le")
        for _vez in range(10):
            if u.OpenClipboard(None):
                break
            time.sleep(0.05)
        else:
            return False
        try:
            u.EmptyClipboard()
            h = k.GlobalAlloc(0x0002, len(dados))         # GMEM_MOVEABLE
            p = k.GlobalLock(h)
            ctypes.memmove(p, dados, len(dados))
            k.GlobalUnlock(h)
            return bool(u.SetClipboardData(13, h))
        finally:
            u.CloseClipboard()

    def _area_no_celular(self, serial: str):
        """(08/out, relato dele: "a copia do celular ainda nao foi pro pc")
        O programinha `Area vigiar` de pe no celular: avisa quando o texto de
        la muda ("C") e recebe o do PC ("S") sem abrir processo novo. O
        scrcpy so sincroniza com uma janela dele aberta; isto vale sempre."""
        import base64
        import subprocess
        proc = getattr(self, "_area_proc", None)
        if proc is not None and proc.poll() is None and \
                getattr(self, "_area_proc_serial", "") == serial:
            return proc
        self._parar_area_no_celular()
        if time.monotonic() < getattr(self, "_area_proximo", 0.0):
            return None
        self._area_proximo = time.monotonic() + 5.0      # nao insiste
        if not self.notif._por_jar(serial):
            return None
        from .notificacoes import JAR_NO_CELULAR
        try:
            proc = subprocess.Popen(
                [str(self.config.adb_exe), "-s", serial, "shell",
                 "CLASSPATH=%s app_process / scrcpyf.Area vigiar"
                 % JAR_NO_CELULAR], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as erro:
            self.anotar("area: o vigia do celular nao subiu (%s)" % erro)
            return None
        self._area_proc, self._area_proc_serial = proc, serial

        def ler():
            for bruta in proc.stdout:
                linha = bruta.decode("utf-8", "replace").strip()
                if linha == "vigiando":
                    self.anotar("area: vigiando a area de transferencia do "
                                "celular")
                elif linha.startswith("C "):
                    try:
                        texto = base64.b64decode(linha[2:]).decode("utf-8")
                    except Exception:
                        continue
                    if not self.config.opcao("area_compartilhada"):
                        continue
                    self._area_do_celular = texto
                    if self._area_por_no_windows(texto) and \
                            not getattr(self, "_area_avisou_cel", False):
                        self._area_avisou_cel = True
                        self.anotar("area: celular -> pc funcionando")
                elif linha.startswith("erro"):
                    self.anotar("area: o celular disse: %s" % linha[:150])

        threading.Thread(target=ler, daemon=True, name="area-celular").start()
        return proc

    def _parar_area_no_celular(self) -> None:
        proc, self._area_proc = getattr(self, "_area_proc", None), None
        if proc is not None and proc.poll() is None:
            try:
                proc.stdin.close()             # ele sai sozinho
                proc.terminate()
            except Exception:
                pass

    def _vigia_area(self) -> None:
        import base64
        try:
            ultimo_seq = self._area_do_windows()[0]
        except Exception as erro:
            self.anotar("area: o Windows nao respondeu (%s)" % erro)
            return
        self.anotar("area: vigiando a area de transferencia do pc")
        enviado = None
        try:
            while not self._sair:
                time.sleep(0.4)
                if not self.config.opcao("area_compartilhada"):
                    self._parar_area_no_celular()
                    continue
                try:
                    serial = self._em_uso_pronto()
                    proc = self._area_no_celular(serial) if serial else None
                    import ctypes
                    seq = ctypes.windll.user32.GetClipboardSequenceNumber()
                    if seq == ultimo_seq:
                        continue
                    ultimo_seq, texto, dono = self._area_do_windows()
                    # o que veio do celular (pelo scrcpy ou por nos) nao volta
                    veio_do_celular = dono == "scrcpy.exe" or (
                        dono.startswith("scrcpy-f_") and
                        dono.endswith(".exe")) or \
                        texto == getattr(self, "_area_do_celular", None)
                    if veio_do_celular:
                        enviado = texto
                        continue
                    if not texto or texto == enviado:
                        continue
                    if not serial or len(texto) > self.AREA_MAX:
                        self.anotar("area: pc -> celular nao foi (%s)" % (
                            "sem celular pronto" if not serial else
                            "texto grande: %d letras" % len(texto)))
                        continue
                    b64 = base64.b64encode(texto.encode("utf-8")).decode(
                        "ascii")
                    enviado = texto
                    if proc is not None and proc.poll() is None:
                        proc.stdin.write(("S %s\n" % b64).encode("ascii"))
                        proc.stdin.flush()
                        r = "ok"
                    else:
                        if not self.notif._por_jar(serial):
                            self.anotar("area: pc -> celular nao foi "
                                        "(sem o jar)")
                            continue
                        from .notificacoes import JAR_NO_CELULAR
                        r = self._shell(serial, "CLASSPATH=%s app_process / "
                                        "scrcpyf.Area %s"
                                        % (JAR_NO_CELULAR, b64),
                                        espera=10).strip()
                    if r != "ok":
                        self.anotar("area: o celular nao aceitou (%s)"
                                    % r[:120])
                    elif not getattr(self, "_area_avisou", False):
                        self._area_avisou = True        # 1x por execucao
                        self.anotar("area: pc -> celular funcionando (dono %s)"
                                    % (dono or "?"))
                except Exception as erro:
                    self.anotar("area: falhou (%s)" % erro)
        finally:
            self._parar_area_no_celular()

    def aplicar_area_compartilhada(self, reabrir: bool = False) -> None:
        """(08/out, pedido dele) Copiar/colar entre PC e celular (OPCOES >
        geral). `reabrir`: o que esta no ar sobe de novo, ja com a escolha."""
        from . import sessao as _sessao
        _sessao.AREA_COMPARTILHADA = self.config.opcao("area_compartilhada")
        if _sessao.AREA_COMPARTILHADA:
            self._garantir_vigia_area()
        if reabrir:
            for nome in ("jogo", "extensao"):
                self.mudou_a_qualidade(nome)
            for pacote in self.apps_abertos():
                self.reabrir_app(pacote)

    # (08/out, pedido dele) CORRECOES POR APP ("fixes"): cada uma desligada
    # de fabrica, menos nos apps que ja se sabe que precisam. No config do
    # app: True = ligada, "nao" = desligada, nada = a de fabrica.
    FIXES = ("rodinha_arrasto", "teclado_celular")
    FIXES_DE_FABRICA = {
        # rodinha: o Instagram rola o feed junto com os comentarios;
        # teclado: a caixa de republicar so aparece com o teclado na janela
        "com.instagram.android": {"rodinha_arrasto": True,
                                  "teclado_celular": True},
    }

    def fix_do_app(self, pacote: str, chave: str) -> bool:
        base = pacote.split(COPIA)[0]
        v = self.config.app(pacote).get(chave)
        if v is True or v == "sim":
            return True
        if v is False or v == "nao":
            return False
        return bool(self.FIXES_DE_FABRICA.get(base, {}).get(chave))

    def fix_de_fabrica(self, pacote: str, chave: str) -> bool:
        return bool(self.FIXES_DE_FABRICA.get(pacote.split(COPIA)[0], {})
                    .get(chave))

    _apagar_ao_subir = False             # (08/out) ver `_partida_app`
    _acordado_apagado = threading.Event()

    def _celular_dormindo(self, serial: str) -> bool:
        """A tela do celular esta APAGADA? Dormindo (botao ou tempo) ou --
        (08/out, relato dele) -- acordado com o painel desligado (por nos:
        um controle que caiu deixava assim, e o app seguinte acendia)."""
        import re
        # (08/out, pedido dele: abrir o mais rapido possivel) o painel apagado
        # POR NOS e uma marca daqui (o vigia sabe); perguntar ao SurfaceFlinger
        # custava uma consulta pesada a cada abertura
        if getattr(self, "_painel_por_nos", False):
            return True
        texto = self._shell(serial, "dumpsys power | grep -m1 mWakefulness=",
                            espera=5)
        m = re.search(r"mWakefulness=(\w+)", texto)
        return bool(m and m.group(1) in ("Asleep", "Dozing"))

    def _garantir_vigia_sono(self, serial: str) -> None:
        """Sobe o vigia do sono, se ainda nao estiver no ar."""
        # (08/out, relato dele: o Instagram pedido no segundo em que o vigia
        # do WhatsApp saia esperou 8 s e piscou) o vigia SAINDO (pondo o
        # celular para dormir) nao atende mais pedidos: espera ele acabar e
        # sobe um novo
        t = self._sono_thread
        if t is not None and t.is_alive() and \
                getattr(self, "_sono_saindo", False):
            t.join(10)
        with self._sono_trava:
            t = self._sono_thread
            if t is not None and t.is_alive():
                return
            self._sono_saindo = False
            parar = threading.Event()
            self._sono_parar = parar
            t = threading.Thread(target=self._vigia_sono, args=(serial, parar),
                                 daemon=True, name="vigia-sono")
            self._sono_thread = t
            t.start()

    def _parar_vigia_sono(self) -> None:
        """No encerramento: o vigia solta o celular e sai."""
        with self._sono_trava:
            t, parar = self._sono_thread, self._sono_parar
        if parar is not None:
            parar.set()
        if t is not None:
            t.join(8)

    # (r154) O PAINEL RELIGADO DIRETO (pedido dele, 25/set/2026: acender pelo
    # botao "sem mexer no app do pc e com o menor delay possivel"). Um
    # programinha nosso fica DE PE no celular (android\scrcpyf-tela.jar,
    # provado pela sonda_painel: "ok 2 1" e a tela acendeu) e liga/desliga o
    # painel na hora -- o Android fica acordado o tempo todo. O ciclo dormir
    # /acordar (r153) ficou so de reserva, se o programinha nao responder.
    TELA_JAR = "/data/local/tmp/scrcpyf-tela.jar"
    TELA_MATAR = "pkill -f 'scrcpyf.Tel[a]' ; true"

    def _vigia_sono(self, serial: str, parar) -> None:
        import os
        import re
        import subprocess
        sem_janela = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        adb = str(self.config.adb_exe)
        linhas: "queue.Queue[str]" = queue.Queue()
        respostas: "queue.Queue[str]" = queue.Queue()
        vigia_ok = threading.Event()
        caminho_log = caminhos.pasta_relatorios() / "log_sono.txt"
        estado = {"laco": None, "controle": None, "log": None,
                  "modo": self.LACO_DO_SONO, "tela": None,
                  "laco_desde": 0.0, "jar_vigia": True,
                  # (08/out) o painel esta apagado POR NOS (o controle pode
                  # ter caido) e o controle que falta subir (depois do app)
                  "apagado": False, "controle_pendente": False}

        def subir_laco():
            try:
                proc = subprocess.Popen(
                    [adb, "-s", serial, "shell", estado["modo"]],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    creationflags=sem_janela)
            except Exception as erro:
                self.anotar("vigia do sono: laco nao subiu (%s)" % erro)
                return None
            estado["laco_desde"] = time.monotonic()

            def ler():
                for bruta in proc.stdout:
                    linhas.put(bruta.decode("utf-8", "replace").strip())

            threading.Thread(target=ler, daemon=True,
                             name="vigia-sono-le").start()
            return proc

        def subir_tela():
            """(r154) O programinha do painel, de pe e lendo on/off."""
            jar = caminhos.pasta_interna() / "android" / "scrcpyf-tela.jar"
            if not jar.exists():
                self.anotar("vigia do sono: falta o %s" % jar)
                return None
            try:
                subprocess.run([adb, "-s", serial, "push", str(jar),
                                self.TELA_JAR], capture_output=True,
                               timeout=20, creationflags=sem_janela)
                # (r156) "vigia": o proprio programinha le o botao, acorda o
                # celular e alterna o painel; aqui chegam so os avisos.
                proc = subprocess.Popen(
                    [adb, "-s", serial, "shell",
                     "CLASSPATH=%s app_process / scrcpyf.Tela%s"
                     % (self.TELA_JAR, " vigia" if estado["jar_vigia"]
                        else "")],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, creationflags=sem_janela)
            except Exception as erro:
                self.anotar("vigia do sono: painel nao subiu (%s)" % erro)
                return None

            def ler():
                for bruta in proc.stdout:
                    t = bruta.decode("utf-8", "replace").strip()
                    if t == "vigia ok":
                        vigia_ok.set()
                    elif t.startswith("botao "):
                        linhas.put("jar" + t)
                    elif t == "semlog" or t.startswith("erro vigia"):
                        linhas.put("jarsemlog " + t)
                        self.anotar("vigia do sono: programinha: %s"
                                    % t[:200])
                    elif t.startswith(("ok", "erro")):
                        respostas.put(t)
                    elif t:
                        # (r157) Qualquer outra coisa (erro do Android ao
                        # subir, etc.) vai para o registro.
                        self.anotar("vigia do sono: programinha disse: %s"
                                    % t[:200])

            threading.Thread(target=ler, daemon=True,
                             name="vigia-sono-painel").start()
            return proc

        def painel(ordem: str, espera: float = 2.5) -> bool:
            """Manda on/off e espera o "ok" (a 1a vez carrega o Android:
            ~1,5 s; depois, instantaneo). False = nao deu."""
            p = estado["tela"]
            if p is None or p.poll() is not None:
                p = estado["tela"] = subir_tela()
                if p is None:
                    return False
                espera = max(espera, 5.0)     # sobe e carrega o Android
            while not respostas.empty():
                try:
                    respostas.get_nowait()
                except queue.Empty:
                    break
            try:
                p.stdin.write((ordem + "\n").encode("ascii"))
                p.stdin.flush()
                r = respostas.get(timeout=espera)
            except Exception as erro:
                self.anotar("vigia do sono: painel %s sem resposta (%s)"
                            % (ordem, erro or "tempo"))
                return False
            if not r.startswith("ok"):
                self.anotar("vigia do sono: painel %s: %s" % (ordem, r[:200]))
                return False
            return True

        def controle_vivo() -> bool:
            c = estado["controle"]
            return c is not None and c.poll() is None

        def subir_controle() -> None:
            if controle_vivo():
                return                  # (r156) ja esta de pe
            try:
                if estado["log"] is None:
                    estado["log"] = open(caminho_log, "w", encoding="utf-8",
                                         errors="replace")
                estado["log"].write("=== %s -- tela fisica apagada ===\n"
                                    % time.strftime("%d/%m/%Y %H:%M:%S"))
                estado["log"].flush()
                scr = str(self.config.scrcpy_exe)
                self._vez_de_lancar()
                estado["controle"] = subprocess.Popen(
                    [scr, "-s", serial, "--no-video", "--no-audio",
                     "--no-window", "--turn-screen-off", "--keep-active"],
                    stdout=estado["log"], stderr=subprocess.STDOUT,
                    cwd=os.path.dirname(scr), creationflags=sem_janela)
            except Exception as erro:
                estado["controle"] = None
                self.anotar("vigia do sono: controle nao subiu (%s)" % erro)

        def soltar_controle(esperar: bool = True) -> None:
            c, estado["controle"] = estado["controle"], None
            if c is None or c.poll() is not None:
                return

            def fim():
                try:
                    c.terminate()
                    c.wait(5)
                except Exception:
                    try:
                        c.kill()
                    except Exception:
                        pass
                # (r152) Deixa o servidor sair sozinho (ate 2 s); so mata
                # se sobrar.
                for _vez in range(8):
                    if estado["controle"] is not None:
                        # (r154) Ja subiu OUTRO controle (toque rapido): o
                        # padrao do pgrep/pkill acharia o novo. Nao mexe.
                        return
                    vivo = self._shell(serial, "pgrep -f '%s' >/dev/null && "
                                       "echo vivo" % self.SONO_PADRAO_CONTROLE,
                                       espera=5).strip()
                    if vivo != "vivo":
                        return
                    time.sleep(0.25)
                if estado["controle"] is not None:
                    return
                self.anotar("vigia do sono: controle nao saiu sozinho; "
                            "derrubado")
                self._shell(serial, self.SONO_MATAR_CONTROLE, espera=5)

            if esperar:
                fim()
            else:
                threading.Thread(target=fim, daemon=True,
                                 name="vigia-sono-solta").start()

        def acordar() -> None:
            comando = "cmd input keyevent KEYCODE_WAKEUP"
            if not self._pela_conversa(serial, comando):
                self._shell(serial, comando, espera=5)

        def acender(t0: float, avisado: bool) -> None:
            """QUER A TELA: painel ligado direto; o controle sai depois."""
            if not avisado:
                acordar()
            ok = painel("on")
            estado["apagado"] = False
            self._painel_por_nos = False
            estado["controle_pendente"] = False
            soltar_controle(esperar=False)
            if ok:
                self.anotar("vigia do sono: botao com a tela apagada -> "
                            "painel religado em %.2f s"
                            % (time.monotonic() - t0))
            else:
                self.anotar("vigia do sono: botao com a tela apagada -> "
                            "reserva: %s" % self._acender_de_verdade(serial))

        def apagar(t0: float, avisado: bool, motivo: str,
                   adiar: bool = False) -> None:
            """QUER A TELA APAGADA com os apps rodando. `adiar`: o controle
            (--keep-active) so sobe depois do app (ver `apagar_pedido`)."""
            if not avisado:
                acordar()
            ok = painel("off")
            estado["apagado"] = True
            self._painel_por_nos = True
            if adiar:
                estado["controle_pendente"] = True
            else:
                subir_controle()  # --keep-active: nao dorme por tempo
            self.anotar("vigia do sono: %s -> acordado, so a tela apagada "
                        "(%s, %.2f s)" % (motivo, "painel" if ok else
                                          "pelo controle",
                                          time.monotonic() - t0))

        self._shell(serial, self.SONO_MATAR + " ; " + self.TELA_MATAR,
                    espera=5)                               # sobras de antes
        # (r150) Por evento se o celular conhece os eventos; senao, o laco
        # de sempre (0,4 s). Na duvida (resposta estranha), o de sempre.
        tem = self._shell(serial, self.SONO_TEM_EVENTOS, espera=5).strip()
        tem_eventos = tem.isdigit() and int(tem) >= 1
        # (r154) O programinha do painel ja sobe aquecido ("on" com a tela
        # acesa nao muda nada): o 1o toque de verdade ja e instantaneo.
        # (08/out, pedido dele: abrir app nao acende a tela do celular) Com
        # um app pedindo a tela APAGADA, aquece com "off" (o celular ainda
        # dorme: nao muda nada) e so entao acorda e apaga o painel na hora.
        # (08/out, relato dele: "quando abri o instagram a tela acendeu") o
        # "on" de aquecer acendia um painel que NOS tinhamos apagado: aquece
        # com "ping" (carrega e nao mexe no painel)
        aquecido = painel("ping", espera=6)
        # (r156) Vigiando pelo programinha: o laco so confere a cada 3 s.
        pelo_jar = aquecido and vigia_ok.wait(1.0)
        if not pelo_jar:
            self.anotar("vigia do sono: o programinha NAO ficou vigiando "
                        "(aquecido=%s, vigia=%s)" % (aquecido,
                                                     vigia_ok.is_set()))
        if not pelo_jar and estado["tela"] is not None:
            # Subiu, mas nao esta vigiando: reinicia sem vigiar (senao ele
            # e o laco acordariam e alternariam juntos).
            estado["jar_vigia"] = False
            try:
                estado["tela"].terminate()
            except Exception:
                pass
            estado["tela"] = None
            self._shell(serial, self.TELA_MATAR, espera=5)
            aquecido = painel("ping", espera=6)
        if pelo_jar:
            estado["modo"] = self.LACO_DO_SONO_ESTADO
        elif tem_eventos:
            estado["modo"] = self.LACO_DO_SONO_EVENTO
        por_evento = estado["modo"] is not self.LACO_DO_SONO
        estado["laco"] = subir_laco()
        self.anotar("vigia do sono: no ar (%s; painel %s)" % (
            "o programinha vigia o botao" if pelo_jar else
            "por evento" if por_evento else "conferindo a cada 0,4 s",
            "pronto" if aquecido else "SEM o programinha -- reserva"))
        botoes = 0
        surdo_ate = 0.0
        vazio_desde = None
        religar_em = 0.0

        def apagar_pedido() -> None:
            """(08/out) Um app abriu com o celular dormindo: acorda com o
            painel ja desligado (a tela nao acende) e avisa quem espera."""
            self._apagar_ao_subir = False
            t0 = time.monotonic()
            if estado["apagado"] and self._painel_por_nos:
                # (08/out, relato dele: abrir o Instagram logo depois de
                # fechar o WhatsApp acendeu a tela) o celular JA esta
                # acordado com o painel apagado por nos: o "acordar-off" de
                # novo era visto pelo programinha como o botao e acendia
                self._acordado_apagado.set()
                return
            # (08/out, relato dele: "a tela liga e desliga") o programinha
            # acorda e segura o painel desligado no mesmo instante
            if painel("acordar-off", espera=5):
                # (08/out, relato dele: o app caiu com "Server connection
                # failed") o scrcpy de controle subindo JUNTO com o do app
                # brigavam ao mandar o servidor ao celular: o controle sobe
                # depois que o app subiu (`controle_pendente`)
                estado["apagado"] = True
                self._painel_por_nos = True
                estado["controle_pendente"] = True
                self.anotar("vigia do sono: app aberto com o celular apagado"
                            " -> acordado com a tela apagada (%.2f s)"
                            % (time.monotonic() - t0))
            else:
                apagar(t0, False, "app aberto com o celular apagado",
                       adiar=True)
            self._acordado_apagado.set()
        try:
            while not parar.is_set() and not self._sair:
                if self._apagar_ao_subir:
                    apagar_pedido()
                    surdo_ate = time.monotonic() + self.SONO_SURDO_S
                # o controle que esperava o app subir (2 s de folga)
                if estado["controle_pendente"] and not any(
                        n.startswith(APP) for n in list(self.ligando)):
                    estado["pendente_desde"] = estado.get(
                        "pendente_desde") or time.monotonic()
                    if time.monotonic() - estado["pendente_desde"] > 2.0:
                        estado["controle_pendente"] = False
                        estado["pendente_desde"] = None
                        if estado["apagado"]:
                            subir_controle()
                try:
                    linha = linhas.get(timeout=0.5)
                except queue.Empty:
                    linha = ""
                agora = time.monotonic()
                if linha == "semlog" and por_evento:
                    # (r154) O logcat do celular caiu/nao existe: sem o aviso
                    # do botao, o estado volta a ser o aviso (laco antigo).
                    por_evento = False
                    self.anotar("vigia do sono: sem os avisos do celular; "
                                "seguindo pelo estado")
                if linha.startswith("jarbotao "):
                    # (r156) O programinha ja acordou e alternou o painel;
                    # aqui so o controle (nao dormir por tempo) acompanha.
                    partes = linha.split()
                    if partes[1] == "apagada":
                        estado["apagado"] = True
                        self._painel_por_nos = True
                        subir_controle()
                    elif partes[1] == "acesa":
                        estado["apagado"] = False
                        self._painel_por_nos = False
                        estado["controle_pendente"] = False
                        soltar_controle(esperar=False)
                    botoes += 1
                    if botoes <= 5 or botoes % 10 == 0:
                        self.anotar("vigia do sono: botao -> %s (%dx)"
                                    % (" ".join(partes[1:]), botoes))
                    continue
                cair = pelo_jar and (linha.startswith("jarsemlog") or (
                    estado["tela"] is not None and
                    estado["tela"].poll() is not None))
                if cair:
                    # (r156) O programinha parou de vigiar: volta ao laco
                    # que avisa o botao (ou ao de 0,4 s).
                    pelo_jar = False
                    # Se o programinha subir de novo (pelo painel), sobe SEM
                    # vigiar: o laco agora e quem avisa o botao.
                    estado["jar_vigia"] = False
                    estado["modo"] = self.LACO_DO_SONO_EVENTO if \
                        tem_eventos else self.LACO_DO_SONO
                    por_evento = tem_eventos
                    velho = estado["laco"]
                    if velho is not None and velho.poll() is None:
                        try:
                            velho.terminate()
                        except Exception:
                            pass
                    self._shell(serial, "pkill -f 'mWakefulnes[s]=' ; true",
                                espera=5)
                    estado["laco"] = subir_laco()
                    self.anotar("vigia do sono: o programinha parou de "
                                "vigiar (%s) -> %s" % (linha[10:120] or "caiu",
                                "por evento" if tem_eventos
                                else "conferindo a cada 0,4 s"))
                    continue
                m = re.search(r"mWakefulness=(\w+)", linha)
                dormindo = bool(m and m.group(1) in ("Asleep", "Dozing"))
                # (r154) "botao" = o celular avisou o pedido de dormir e JA
                # mandou acordar la mesmo (sem ida e volta ao PC). Nos 1,5 s
                # depois de o laco subir, e evento velho: ignora.
                botao = linha == "botao" and \
                    agora - estado["laco_desde"] > 1.5
                if botao and agora >= surdo_ate:
                    if controle_vivo():
                        acender(agora, avisado=True)
                    else:
                        apagar(agora, True, "botao")
                    # (r155) Era 1 s: o toque logo depois de acender era
                    # ignorado (teste dele). Um toque = UM pedido de dormir;
                    # o que vem dentro deste respiro e eco das nossas acoes.
                    # (r157) Cada "botao" e UM toque de verdade: nao ha eco a
                    # engolir (o teste dele mostrou toques rapidos perdidos).
                    surdo_ate = 0.0
                elif dormindo and agora >= surdo_ate and pelo_jar:
                    # (r156) Conferencia de 3 s viu o celular dormindo: o
                    # programinha nao acordou a tempo. So acorda -- quem
                    # decide o painel e ele.
                    acordar()
                    self.anotar("vigia do sono: dormindo na conferencia -> "
                                "acordado")
                    surdo_ate = time.monotonic() + self.SONO_SURDO_S
                elif dormindo and agora >= surdo_ate:
                    if not por_evento:
                        # Laco antigo: o estado e o unico aviso -- alterna.
                        if controle_vivo():
                            acender(agora, avisado=False)
                        else:
                            apagar(agora, False, "celular ia dormir (%s)"
                                   % m.group(1))
                    elif controle_vivo():
                        # Por evento, dormir SEM o botao (ex.: evento
                        # perdido): so acorda e mantem apagado.
                        acordar()
                        painel("off")
                        self.anotar("vigia do sono: dormiu sem aviso com a "
                                    "tela apagada -> acordado")
                    else:
                        # Tempo de tela esgotado (sem botao): apaga.
                        apagar(agora, False, "celular ia dormir (%s)"
                               % m.group(1))
                    surdo_ate = time.monotonic() + self.SONO_SURDO_S
                # Acabaram os apps (2 s de folga para quem esta subindo).
                if self.apps_abertos():
                    vazio_desde = None
                else:
                    vazio_desde = vazio_desde or agora
                    if agora - vazio_desde > 2.0:
                        break
                # O laco caiu (Wi-Fi, adb): sobe de novo, no maximo a cada 3 s.
                laco = estado["laco"]
                if (laco is None or laco.poll() is not None) and \
                        agora >= religar_em:
                    religar_em = agora + 3.0
                    estado["laco"] = subir_laco()
        except Exception:
            log.exception("vigia do sono quebrou")
        finally:
            self._sono_saindo = True        # (08/out) ver `_garantir_vigia_sono`
            self._painel_por_nos = False    # dorme (ou acende) na saida
            laco = estado["laco"]
            if laco is not None and laco.poll() is None:
                try:
                    laco.terminate()
                except Exception:
                    pass
            # (08/out) apagado por nos, mesmo com o controle caido
            apagada = controle_vivo() or estado["apagado"]
            # (08/out, relato dele: "quando paro de usar ... acende e volta a
            # desligar") Sem o espelhar no ar o celular DORME DIRETO, com o
            # painel ainda desligado (testado no S22: dormir assim e acordar
            # pelo botao traz a tela normal). Acender antes era a piscada.
            dormir_direto = apagada and not self.ativo("jogo")
            if dormir_direto:
                # (08/out, relato dele: "depois que eu fecho +/- 2 s a tela
                # acende") O programinha do painel e o laco vigiam o BOTAO pelo
                # pedido de dormir -- o nosso SLEEP parecia um toque e eles
                # acordavam o celular. Saem ANTES do SLEEP.
                tela = estado["tela"]
                if tela is not None and tela.poll() is None:
                    try:
                        tela.terminate()
                    except Exception:
                        pass
                self._shell(serial, self.SONO_MATAR.replace(
                    " ; " + self.SONO_MATAR_CONTROLE, "") + " ; " +
                    self.TELA_MATAR, espera=5)
                self._shell(serial, "cmd input keyevent KEYCODE_SLEEP",
                            espera=5)
                time.sleep(0.4)
            elif apagada:
                painel("on", espera=1.5)
            soltar_controle()
            tela = estado["tela"]
            if tela is not None and tela.poll() is None:
                try:
                    tela.terminate()
                except Exception:
                    pass
            self._shell(serial, self.SONO_MATAR + " ; " + self.TELA_MATAR,
                        espera=5)                           # laco (r133)
            if dormir_direto:
                # dormiu la em cima; o scrcpy de controle saiu com a tela
                # apagada e nao a acende (ele so restaura com a tela ligada)
                pass
            if estado["log"] is not None:
                try:
                    estado["log"].close()
                except Exception:
                    pass
            self.anotar("vigia do sono: saiu%s" % (
                " (celular posto para dormir)" if apagada else ""))

    # -- vigia do foco ---------------------------------------------------------
    # A ATENCAO SEGUE O MOUSE (pedido dele, 23/set/2026; provado pela
    # sonda_foco). O Android da foco a UMA tela por vez (a do ultimo toque) e
    # app sem foco pausa video (Instagram reiniciava so rolando). Mouse PARADO
    # sobre a janela de um app por FOCO_PARADO_S = o app ganha o foco, com um
    # toque cancelado no canto da tela dele (DOWN + CANCEL: o foco segue o
    # toque e o app nao recebe clique). Uma vez por entrada: sair das janelas
    # de app e voltar manda de novo. Tocar no celular devolve o foco ao que
    # esta nele (o proprio Android faz isso).
    FOCO_PARADO_S = 0.25

    def _garantir_vigia_foco(self, serial: str) -> None:
        with self._sono_trava:
            t = getattr(self, "_foco_thread", None)
            if t is not None and t.is_alive():
                return
            t = threading.Thread(target=self._vigia_foco, args=(serial,),
                                 daemon=True, name="vigia-foco")
            self._foco_thread = t
            t.start()

    @staticmethod
    def _tela_da_sessao(sessao):
        """(numero da tela virtual, largura) pelo log do scrcpy, ou None."""
        import re
        try:
            with open(sessao.arquivo_log, encoding="utf-8",
                      errors="replace") as arq:            # (r138) fecha
                texto = arq.read()
        except Exception:
            return None
        achados = re.findall(r"New display: (\d+)x(\d+)\S*\s*\(id=(\d+)\)",
                             texto)
        if not achados:
            return None
        larg, _alt, tela = achados[-1]
        return tela, int(larg)

    def _rodinha_alvos(self, apps, cache: dict) -> dict:
        """(08/out) pid -> (serial, tela, largura, altura) das janelas de app
        com a correcao "rodinha como arrasto" ligada."""
        import re
        alvos = {}
        for nome, s in apps:
            pacote = nome[len(APP):]
            pid = getattr(s, "pid", 0)
            if not pid or not self.fix_do_app(pacote, "rodinha_arrasto"):
                continue
            chave = (nome, pid)
            info = cache.get(chave)
            if info is None:
                try:
                    with open(s.arquivo_log, encoding="utf-8",
                              errors="replace") as arq:
                        achados = re.findall(
                            r"New display: (\d+)x(\d+)\S*\s*\(id=(\d+)\)",
                            arq.read())
                except Exception:
                    achados = []
                if not achados:
                    continue
                larg, alt, tela = achados[-1]
                info = cache[chave] = (getattr(s, "serial", "") or "", tela,
                                       int(larg), int(alt))
            alvos[pid] = info
        return alvos

    def _rodinha(self):
        r = getattr(self, "_rodinha_obj", None)
        if r is None:
            from .rodinha import Rodinha

            def mandar(serial, comando):
                if not self._pela_conversa(serial, comando):
                    threading.Thread(target=self._shell,
                                     args=(serial, comando, 5),
                                     daemon=True).start()
            r = self._rodinha_obj = Rodinha(mandar)
        return r

    def _vigia_foco(self, serial: str) -> None:
        from . import janela_scrcpy
        telas: dict = {}
        ultimo = None
        candidato, desde = None, 0.0
        vazio_desde = None
        vezes = 0
        rodinha_em, rodinha_cache = 0.0, {}
        self.anotar("vigia do foco: no ar")
        try:
            while not self._sair:
                time.sleep(0.1)
                agora = time.monotonic()
                apps = [(n, s) for n, s in list(self.sessoes.items())
                        if n.startswith(APP)]
                # (08/out) a rodinha como arrasto: quem tem a correcao
                if agora >= rodinha_em:
                    rodinha_em = agora + 1.0
                    try:
                        self._rodinha().atualizar(
                            self._rodinha_alvos(apps, rodinha_cache))
                    except Exception:
                        log.exception("rodinha: nao atualizei")
                if not apps and not any(n.startswith(APP)
                                        for n in list(self.ligando)):
                    vazio_desde = vazio_desde or agora
                    if agora - vazio_desde > 3.0:
                        break
                    continue
                vazio_desde = None
                pid = janela_scrcpy.pid_sob_o_mouse()
                nome, sessao = None, None
                if pid:
                    for n, s in apps:
                        if getattr(s, "pid", 0) == pid:
                            nome, sessao = n, s
                            break
                if nome != candidato:
                    candidato, desde = nome, agora
                if nome is None:
                    ultimo = None          # saiu: a proxima entrada manda
                    continue
                if nome == ultimo or agora - desde < self.FOCO_PARADO_S:
                    continue
                # (r129) Guardada POR SESSAO, nao por nome: depois de uma
                # troca de janela o nome e o mesmo mas a tela e outra, e o
                # toque ia para a tela velha, que nao existe mais.
                chave = (nome, getattr(sessao, "pid", 0))
                info = telas.get(chave) or self._tela_da_sessao(sessao)
                if not info:
                    continue
                telas[chave] = info
                ultimo = nome
                tela, larg = info
                x = max(0, larg - 2)
                # (08/out, checagem no S22: o foco do Android e um so, e o
                # toque o levava para a janela do PC) Se o teclado esta aberto
                # NA TELA DO CELULAR (ele esta digitando nele), nao toca: o
                # celular nao perde o campo. Decidido la mesmo, numa ida so.
                comando = ("d=$(dumpsys input_method); "
                           "if echo \"$d\" | grep -q 'mInputShown=true' && "
                           "echo \"$d\" | grep -qE "
                           "'mDisplayIdToShowIme=0( |$)'; then :; else "
                           "input -d %s motionevent DOWN %d 2; "
                           "input -d %s motionevent CANCEL %d 2; fi"
                           % (tela, x, tela, x))
                if not self._pela_conversa(serial, comando):     # (r139)
                    threading.Thread(target=self._shell,
                                     args=(serial, comando, 5),
                                     daemon=True, name="foco-toque").start()
                vezes += 1
                if vezes <= 5 or vezes % 20 == 0:
                    self.anotar("vigia do foco: atencao para %s (tela %s, "
                                "%dx)" % (nome[len(APP):], tela, vezes))
        except Exception:
            log.exception("vigia do foco quebrou")
        try:
            self._rodinha().atualizar({})        # sem app: sem gancho
        except Exception:
            pass
        self.anotar("vigia do foco: saiu")

    # ANIMACOES 4x MAIS RAPIDAS COM APP EM JANELA (pedido dele, 23/set/2026).
    # Cada escala de animacao do celular vai a 1/4 do valor que ele tinha
    # enquanto houver ao menos um app aberto em janela; fechou o ultimo, volta
    # ao original. O original fica guardado NO CELULAR (ANIM_ARQUIVO): se o
    # programa cair no meio, a proxima vez parte do original, nao do 1/4.
    ANIM_CHAVES = ("window_animation_scale", "transition_animation_scale",
                   "animator_duration_scale")
    ANIM_ARQUIVO = "/data/local/tmp/scrcpyf-anim.txt"
    ANIM_FATOR = 0.25

    # DESLIGADO (teste dele, 23/set/2026: "ficou estranha, volte ao normal").
    # Com False nunca acelera (o celular dele ja voltou ao original no teste).
    ANIM_ACELERAR = False

    def _animacoes_rapidas(self, serial: str, rapidas: bool) -> None:
        import re
        rapidas = rapidas and self.ANIM_ACELERAR
        with self._anim_trava:
            if rapidas == bool(self._anim_serial):
                return
            alvo = serial if rapidas else self._anim_serial
            if not alvo:
                return
            self._anim_serial = serial if rapidas else ""
            valido = re.compile(r"[0-9.]+|null")
            guardado = self._shell(
                alvo, "cat %s 2>/dev/null" % self.ANIM_ARQUIVO).split()
            if len(guardado) != 3 or not all(valido.fullmatch(v)
                                             for v in guardado):
                if not rapidas:
                    return
                guardado = self._shell(alvo, "; ".join(
                    "settings get global %s" % c
                    for c in self.ANIM_CHAVES)).split()
                if len(guardado) != 3 or not all(valido.fullmatch(v)
                                                 for v in guardado):
                    self._anim_serial = ""
                    self.anotar("animacoes: nao li as do celular (%r)"
                                % guardado)
                    return
                self._shell(alvo, "echo '%s' > %s"
                            % (" ".join(guardado), self.ANIM_ARQUIVO))
            if rapidas:
                cmds = []
                for chave, v in zip(self.ANIM_CHAVES, guardado):
                    base = 1.0 if v == "null" else float(v)  # null = padrao
                    cmds.append("settings put global %s %g"
                                % (chave, base * self.ANIM_FATOR))
            else:
                cmds = [("settings delete global %s" % c) if v == "null" else
                        ("settings put global %s %s" % (c, v))
                        for c, v in zip(self.ANIM_CHAVES, guardado)]
                cmds.append("rm -f %s" % self.ANIM_ARQUIVO)
            self._shell(alvo, "; ".join(cmds))
            self.anotar("animacoes: %s (original %s)" % (
                "1/4 com app em janela" if rapidas else "de volta ao original",
                " ".join(guardado)))

    # -- status do celular (ao vivo) -------------------------------------------
    #
    # Pedido dele (23/set/2026): atualizar a cada 750 ms, sem piscar. Dois
    # processos ficam rodando NO CELULAR enquanto a tela "status" esta a
    # vista, cada um escrevendo sem parar: um laco que le bateria, disco,
    # memoria, CPU e GPU, e o proprio `top` (os que mais pesam). Aqui so se
    # le o que eles escrevem; a janela olha `status_atual` e troca os numeros
    # no lugar. Saiu da tela, os dois param.

    # era 0,75 (pedido dele, 23/set/2026: so roda na aba). Mudou aqui? Mude
    # tambem o texto "ao vivo · a cada ..." em janela.py.
    STATUS_A_CADA_S = 0.25
    STATUS_LENTO_VOLTAS = 24  # bateria e disco: a cada ~6 s, como antes
    # Lista de apps (sonda_top, 23/set/2026): numa leitura de 0,25 s quase
    # todo app da 0%% e sai das 12 primeiras linhas, atras do proprio Android.
    # Agora: 40 linhas por leitura e a MEDIA DOS ULTIMOS ~2 s de cada um
    # (quem nao apareceu numa leitura conta 0 nela).
    STATUS_TOP_LINHAS = 40
    STATUS_MEDIA_S = 2.0
    # Mata no celular os medidores deste programa (os de agora e sobras). Os
    # colchetes fazem o proprio comando nao casar com o padrao.
    STATUS_MATAR = ("pkill -f 'echo @[f]; i=' ; "
                    "pkill -f '%CPU,RES,NAM[E]' ; true")
    # Nomes que nao sao apps: o proprio medidor e os comandos do laco.
    NAO_SAO_APPS = {"top", "sh", "dumpsys", "grep", "head", "tail", "cat",
                    "sleep", "df", "toybox", "logcat"}

    def ligar_status(self) -> None:
        # (02/out, revisao) UMA subida por vez: a janela tenta a cada 3 s em
        # thread nova, e duas juntas subiam medidores em dobro.
        trava = self.__dict__.setdefault("_status_trava", threading.Lock())
        if not trava.acquire(blocking=False):
            return
        try:
            self._ligar_status()
        finally:
            trava.release()

    def _ligar_status(self) -> None:
        if getattr(self, "_status_procs", None):
            return
        # (02/out, revisao) SO O CELULAR EM USO. Antes, sem ele, caia no
        # `celular.achar` (reconnect, kill-server, start-server, ate ~25 s) a
        # cada 3 s com a aba aberta -- derrubava o adb das notificacoes e da
        # vigia. Achar o celular e trabalho da vigia da conexao.
        alvo = self._em_uso_pronto()
        if not alvo:
            erro = "celular não encontrado"
            if (getattr(self, "status_atual", None) or {}).get("erro") != erro:
                self.status_atual = {"erro": erro}   # (dict novo = repinta)
            return
        import subprocess
        # Sobra de vez anterior (ou do programa que caiu) ainda rodando no
        # celular: mata antes de subir os novos.
        self._shell(alvo, self.STATUS_MATAR, espera=5)
        self._status_serial = alvo
        passo = self.STATUS_A_CADA_S
        laco = ("i=0; while :; do echo @s; "
                "if [ $((i%%%d)) -eq 0 ]; then dumpsys battery | grep -E "
                "'^ *(level|status|temperature):'; df /data | tail -1; fi; "
                "head -3 /proc/meminfo; head -1 /proc/stat; "
                "cat /sys/kernel/gpu/gpu_busy 2>/dev/null; echo @f; "
                "i=$((i+1)); sleep %s; done"
                % (self.STATUS_LENTO_VOLTAS, passo))
        # (r188) + USER: o WhatsApp e a copia dele tem o mesmo nome de
        # processo; o usuario (u0_a524 x u95_a524) separa os dois.
        topo = "top -b -d %s -m %d -s 1 -o %%CPU,RES,USER,NAME" % (
            passo, self.STATUS_TOP_LINHAS)
        sem_janela = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        procs = []
        for comando in (laco, topo):
            try:
                procs.append(subprocess.Popen(
                    [str(self.config.adb_exe), "-s", alvo, "shell", comando],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    creationflags=sem_janela))
            except Exception as erro:
                self.anotar("status: nao subiu (%s)" % erro)
        if len(procs) < 2:
            for p in procs:
                p.terminate()
            self.status_atual = {"erro": "não consegui ler o celular"}
            return
        self._status_procs = procs
        self._status_quadros = 0
        self._status_desde = time.monotonic()
        self._status_base = {}
        self.status_atual = getattr(self, "status_atual", None) or {}
        self.status_atual.pop("erro", None)
        threading.Thread(target=self._ler_laco_status, args=(procs[0],),
                         daemon=True, name="status-laco").start()
        threading.Thread(target=self._ler_top, args=(procs[1],),
                         daemon=True, name="status-top").start()

    def status_morreu(self) -> bool:
        """Algum dos dois medidores do celular parou de escrever?"""
        procs = getattr(self, "_status_procs", None) or []
        try:
            return any(p.poll() is not None for p in procs
                       if hasattr(p, "poll"))
        except Exception:
            return False

    def desligar_status(self) -> None:
        """Chamado da thread da janela: o que fala com o celular vai a parte."""
        procs = getattr(self, "_status_procs", None) or []
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        self._status_procs = None
        if not procs:
            return
        segundos = time.monotonic() - getattr(self, "_status_desde",
                                              time.monotonic())
        self.anotar("status: %d leituras do top em %.0f s"
                    % (getattr(self, "_status_quadros", 0), segundos))
        # Matar o PROCESSO DO PC nao mata o do celular (teste de 23/set/2026:
        # medidores velhos seguiam rodando la, 20%% de um nucleo cada).
        serial = getattr(self, "_status_serial", "")

        def matar():
            # Religou no meio (voltou na aba)? O ligar ja limpou; nao matar
            # os novos.
            if serial and not getattr(self, "_status_procs", None):
                self._shell(serial, self.STATUS_MATAR, 5)

        threading.Thread(target=matar, daemon=True, name="status-mata").start()

    def _publicar_status(self, **campos) -> None:
        """Troca o dicionario inteiro (a janela le sem trava)."""
        novo = dict(getattr(self, "status_atual", None) or {})
        novo.update(campos)
        self.status_atual = novo

    def _ler_laco_status(self, proc) -> None:
        import re
        linhas: list[str] = []
        cpu_antes = None
        for bruta in proc.stdout:
            linha = bruta.decode("utf-8", errors="replace").strip()
            if linha == "@s":
                linhas = []
                continue
            if linha != "@f":
                linhas.append(linha)
                continue
            campos = {}
            for l in linhas:
                chave, _, valor = l.partition(":")
                valor = valor.strip()
                if chave == "level" and valor.isdigit():
                    campos["bateria"] = int(valor)
                elif chave == "status" and valor.isdigit():
                    campos["carregando"] = valor == "2"
                elif chave == "temperature" and valor.isdigit():
                    campos["temperatura"] = int(valor) / 10.0
                elif chave in ("MemTotal", "MemAvailable"):
                    m = re.match(r"(\d+)", valor)
                    if m:
                        campos[chave] = int(m.group(1)) * 1024
                elif l.startswith("cpu "):
                    numeros = [int(n) for n in l.split()[1:] if n.isdigit()]
                    if len(numeros) >= 5:
                        agora = (sum(numeros), numeros[3] + numeros[4])
                        if cpu_antes and agora[0] > cpu_antes[0]:
                            campos["cpu"] = round(100.0 * (
                                1 - (agora[1] - cpu_antes[1])
                                / (agora[0] - cpu_antes[0])))
                        cpu_antes = agora
                elif l.endswith("%") and l[:-1].strip().isdigit():
                    campos["gpu"] = int(l[:-1].strip())
                else:
                    df = l.split()
                    if len(df) >= 4 and df[1].isdigit() and df[3].isdigit():
                        campos["disco_total"] = int(df[1]) * 1024
                        campos["disco_livre"] = int(df[3]) * 1024
            if "MemTotal" in campos and "MemAvailable" in campos:
                campos["ram_total"] = campos["MemTotal"]
                campos["ram_usada"] = campos.pop("MemTotal") - \
                    campos.pop("MemAvailable")
            self._publicar_status(**campos)

    def _ler_top(self, proc) -> None:
        import re
        from collections import deque
        _re_cpu = re.compile(r"(\d+)%cpu\b")
        _re_usuario = re.compile(r"u(\d+)_")
        linhas: list = []
        nas_linhas = False
        # Ultimas leituras dentro de STATUS_MEDIA_S: (instante, {nome: cpu}).
        janela: deque = deque()
        ram_de: dict = {}
        primeira = True     # a 1a leitura do top vem toda zerada: descartar
        for bruta in proc.stdout:
            linha = bruta.decode("utf-8", errors="replace").rstrip()
            if linha.lstrip().startswith("Tasks:"):
                if nas_linhas and not primeira:
                    agora = time.monotonic()
                    janela.append((agora, {n: c for n, c, _r in linhas}))
                    for n, _c, r in linhas:
                        ram_de[n] = r
                    while janela and agora - janela[0][0] > self.STATUS_MEDIA_S:
                        janela.popleft()
                    soma: dict = {}
                    for _t, leitura in janela:
                        for n, c in leitura.items():
                            soma[n] = soma.get(n, 0.0) + c
                    media = sorted(((n, s / len(janela), ram_de.get(n, ""))
                                    for n, s in soma.items()),
                                   key=lambda x: -x[1])
                    self._status_quadros = getattr(
                        self, "_status_quadros", 0) + 1
                    self._publicar_status(pesados=media[:5])
                elif nas_linhas:
                    primeira = False
                linhas, nas_linhas = [], False
                continue
            if "%CPU" in linha and "NAME" in linha:
                nas_linhas = True
                continue
            m = _re_cpu.match(linha.strip())
            if m and int(m.group(1)) >= 100:
                self._nucleos = max(1, int(m.group(1)) // 100)
                continue
            if not nas_linhas:
                continue
            campos = linha.split(None, 3)
            if len(campos) < 4:
                continue
            try:
                cpu = float(campos[0])
            except ValueError:
                continue
            cpu = cpu / getattr(self, "_nucleos", 1)
            nome, ram = campos[3].strip(), campos[1]
            # (r188) Processo da COPIA (usuario > 0): "pacote@u[:resto]",
            # a mesma chave da lista de apps (nome e icone de la).
            m = _re_usuario.match(campos[2])
            if m and int(m.group(1)) > 0:
                base, dois, resto = nome.partition(":")
                nome = "%s%s%s%s%s" % (base, COPIA, m.group(1), dois, resto)
            # Fora: tarefas do nucleo do Android ("[u16:4-memlat_wq]", sem
            # memoria propria) e os comandos do proprio medidor.
            if nome.startswith("[") or nome.endswith("]") or \
                    nome in self.NAO_SAO_APPS or ram in ("0", "0K"):
                continue
            linhas.append((nome, cpu, ram))

    def uso_do_app(self, pacote: str) -> dict:
        """
        FORA DA THREAD DA JANELA. RAM, CPU e memoria de video de um app
        (pedido dele: parar o mouse no app mostra quanto ele usa). O uso de
        GPU POR APP o Android nao entrega a ninguem de fora; o que existe e
        quanto de memoria de video ele ocupa (`dumpsys gpu`).
        """
        import re
        alvo = self._serial_conhecido()                       # (r149)
        chave = pacote
        pacote, usuario = separar_app(chave)
        if not alvo or not re.fullmatch(r"[A-Za-z0-9._]+", pacote):
            return {}
        # (r186) SO os processos do USUARIO do app (o original e a copia
        # tem o mesmo nome; o UID diz de quem e: usuario x 100000 + app).
        # Sem o `ps`, o original cai no `pidof` de antes; a copia, nao.
        if usuario:
            uid = "%d[0-9]{5}" % usuario
        else:
            uid = "[0-9]{1,5}"
        escolher = (
            "p=$(ps -A -o PID=,UID=,NAME= 2>/dev/null | grep -E "
            "'^ *[0-9]+ +%s +%s$' | sed 's/^ *\\([0-9]*\\).*/\\1/'); "
            "p=$(echo $p); " % (uid, pacote.replace(".", "\\.")))
        if not usuario:
            escolher += "[ -z \"$p\" ] && p=$(pidof %s); " % pacote
        texto = self._shell(alvo, escolher + (
            "[ -z \"$p\" ] && echo @parado && exit; "
            "echo @n $(nproc 2>/dev/null); "
            "echo @pid $p; top -b -n 2 -d 0.6 -p $(echo $p | tr ' ' ',') "
            "-o PID,%CPU,RES 2>/dev/null | tail -n $(echo $p | wc -w); "
            "echo @gpu; dumpsys gpu 2>/dev/null | grep -E \"Proc ($(echo $p | "
            "tr ' ' '|')) total\""), espera=15)
        if "@parado" in texto:
            return {"parado": True}
        uso = {"cpu": 0.0, "ram": 0, "video": 0}
        secao = ""
        nucleos = getattr(self, "_nucleos", 1)
        for linha in texto.splitlines():
            linha = linha.strip()
            if linha.startswith("@n "):
                partes = linha.split()
                if len(partes) > 1 and partes[1].isdigit():
                    nucleos = max(1, int(partes[1]))
                continue
            if linha.startswith("@"):
                secao = linha.split()[0]
                continue
            if secao == "@pid":
                campos = linha.split()
                if len(campos) >= 3 and campos[0].isdigit():
                    try:
                        uso["cpu"] += float(campos[1])
                    except ValueError:
                        pass
                    uso["ram"] += _tamanho_em_bytes(campos[2])
            elif secao == "@gpu":
                m = re.search(r"total:\s*(\d+)", linha)
                if m:
                    uso["video"] += int(m.group(1))
        uso["cpu"] = uso["cpu"] / nucleos
        return uso

    # -- icones dos apps ------------------------------------------------------

    # -- cache por celular (pedido dele, 23/set/2026) -------------------------
    #
    # `_internal\celulares\<id>\`: `apps.json` (a lista com nomes e a
    # assinatura dos pacotes instalados) e `icones\`. Ao conectar, a lista
    # guardada aparece NA HORA; em segundo plano o celular diz quais pacotes
    # tem (e a versao de cada um, uma pergunta leve) e so o que mudou e
    # refeito: lista nova se entrou/saiu/atualizou algo, icone so dos novos
    # ou atualizados, icone de quem saiu apagado.

    def pasta_do_celular(self):
        ident = (self.celular or {}).get("id") or \
            getattr(self, "_ultimo_id", None)
        if not ident:
            return None
        pasta = caminhos.pasta_dados() / "celulares" / ident
        if not caminhos.garantir_pasta(pasta / "icones", pais=True):
            return None
        return pasta

    def pasta_de_icones(self):
        cel = self.pasta_do_celular()
        if cel is not None:
            return cel / "icones"
        pasta = caminhos.pasta_dados() / "icones"
        caminhos.garantir_pasta(pasta)
        return pasta

    @staticmethod
    def _guardar_modelo(ident: str, modelo: str) -> None:
        """(01/out) O nome do celular, para a lista do parear mostrar quem
        ainda nao conectou (`conexao.nome_guardado`)."""
        if not ident or not modelo:
            return
        try:
            pasta = caminhos.pasta_dados() / "celulares" / ident
            pasta.mkdir(parents=True, exist_ok=True)
            arquivo = pasta / "modelo.txt"
            if not arquivo.exists() or \
                    arquivo.read_text(encoding="utf-8").strip() != modelo:
                arquivo.write_text(modelo, encoding="utf-8")
        except Exception:
            pass

    def _guardar_lista(self, apps) -> None:
        """Poe a lista no cache do celular, mantendo a assinatura."""
        import json
        pasta = self.pasta_do_celular()
        if pasta is None or not _tem_app(apps):
            return
        arquivo = pasta / "apps.json"
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except Exception:
            dados = {}
        dados["apps"] = [list(a) for a in apps]
        try:
            arquivo.write_text(json.dumps(dados, ensure_ascii=False),
                               encoding="utf-8")
        except Exception:
            pass
        self.apps_do_celular = list(apps)
        self.apps_versao = getattr(self, "apps_versao", 0) + 1

    def _assinatura(self, serial: str) -> dict:
        """{pacote: versao} de tudo que esta instalado (leve: ~0,3 s)."""
        # (r186) + os pacotes de cada outro usuario, como "<pacote>@<u>":
        # copia nova/removida muda a assinatura e a lista se refaz sozinha.
        saida = self._shell(serial, "pm list packages --show-versioncode "
                            "2>/dev/null || pm list packages; "
                            "for u in $(pm list users 2>/dev/null | sed -n "
                            "'s/.*UserInfo{\\([0-9]*\\):.*/\\1/p'); do "
                            "[ \"$u\" = 0 ] || pm list packages --user $u "
                            "2>/dev/null | sed \"s/^package:\\([^ ]*\\).*"
                            "/package:\\1@$u/\"; done", espera=15)
        pacotes = {}
        for linha in saida.splitlines():
            linha = linha.strip()
            if not linha.startswith("package:"):
                continue
            partes = linha[8:].split()
            versao = ""
            for p in partes[1:]:
                if p.startswith("versionCode:"):
                    versao = p[12:]
            if partes:
                pacotes[partes[0]] = versao
        return pacotes

    def _preparar_celular(self, serial: str, ident: str) -> None:
        import json
        pasta = self.pasta_do_celular()
        if pasta is None or not serial:
            return
        # (r133) SOBRAS DE UMA EXECUCAO ANTERIOR no celular (programa que
        # caiu ou foi fechado a forca): lacos dos vigias e o scrcpy de
        # controle que segura a tela acesa. Sem app aberto, nada disso e
        # nosso de agora.
        if not self.apps_abertos():
            self._shell(serial, self.VIGIA_MATAR + " ; " + self.SONO_MATAR,
                        espera=5)
        arquivo = pasta / "apps.json"
        guardado = {}
        try:
            guardado = json.loads(arquivo.read_text(encoding="utf-8"))
        except Exception:
            pass
        if not _tem_app(guardado.get("apps")):
            guardado.pop("apps", None)
        if guardado.get("apps"):
            self.apps_do_celular = [tuple(a) for a in guardado["apps"]]
            self.apps_versao = getattr(self, "apps_versao", 0) + 1
            self.anotar("cache %s: %d apps na hora" % (ident,
                                                       len(guardado["apps"])))
        # Previa do status: a tela "status" abre com os numeros ja la.
        self._status_previa_ate = time.monotonic() + 3.0
        try:
            self.ligar_status()
        except Exception:
            pass
        agora = self._assinatura(serial)
        antes = guardado.get("pacotes") or {}
        if not agora:
            self.anotar("cache %s: o celular nao listou os pacotes" % ident)
            return
        mudaram = {p for p, v in agora.items() if antes.get(p) != v}
        sairam = set(antes) - set(agora)
        apps = self.apps_do_celular if guardado.get("apps") else []
        # CACHE_VERSAO 2 (23/set/2026): a lista passou a trazer so app com
        # icone e a detectar os jogos -- cache mais velho e refeito sozinho,
        # sem ele precisar clicar em "atualizar".
        velho = guardado.get("versao") != CACHE_VERSAO
        if mudaram or sairam or not apps or velho:
            novos, erro = self.listar_apps()
            if novos:
                apps = novos
                self.apps_do_celular = list(novos)
                self.apps_versao = getattr(self, "apps_versao", 0) + 1
            elif erro:
                self.anotar("cache %s: lista nao veio (%s)" % (ident, erro))
                return
        # (r177) Lista do cache sem nada mudado: os jogos tambem nao mudaram
        # -- vale o que esta guardado (antes perguntava tudo de novo, ~12 s,
        # antes dos icones).
        icones = pasta / "icones"
        for p in sairam:
            try:
                (icones / (p + ".png")).unlink()
            except Exception:
                pass
        faltam = [p for _n, p, _s in apps
                  if p in mudaram or not (icones / (p + ".png")).exists()]
        if faltam:
            self.buscar_icones(faltam)
            self.icones_versao = getattr(self, "icones_versao", 0) + 1
        try:
            arquivo.write_text(json.dumps({"apps": [list(a) for a in apps],
                                           "pacotes": agora,
                                           "versao": CACHE_VERSAO},
                                          ensure_ascii=False),
                               encoding="utf-8")
        except Exception as erro:
            self.anotar("cache %s: nao gravei (%s)" % (ident, erro))
        self.anotar("cache %s: %d mudaram, %d sairam, %d icones pedidos"
                    % (ident, len(mudaram) if antes else -1, len(sairam),
                       len(faltam)))
        self._ler_sinais(serial, apps, agora)
        # (08/out, pedido dele) a VERIFICACAO e AUTOMATICA: ao conectar, o que
        # falta (1a vez: todos; depois so os novos/atualizados). O resultado
        # fica em interface.json (por versao): da proxima vez ja carrega.
        dados = self.interface_dos_apps()
        from . import analise_app
        if sairam or any((dados.get(p) or {}).get("v") != agora.get(p, "") or
                         ((dados.get(p) or {}).get("resultado") ==
                          analise_app.TABLET and
                          (dados.get(p) or {}).get("real_v") !=
                          agora.get(p, ""))
                         for _n, p, _s in apps if p != DEX and COPIA not in p):
            self.analisar_apps(so_faltam=True, serial=serial, versoes=agora)
        self._conferir_depois(serial)

    # -- (08/out, pedido dele) MELHOR MODO DE CADA APP (melhor_modo.py) -------

    def _arquivo_sinais(self):
        pasta = self.pasta_do_celular()
        return pasta / "sinais.json" if pasta is not None else None

    def sinais_dos_apps(self) -> dict:
        """{pacote: sinal} do celular em uso (lido do disco uma vez)."""
        arq = self._arquivo_sinais()
        guardado = getattr(self, "_sinais", None)
        if guardado is not None and guardado[0] == arq:
            return guardado[1]
        import json
        dados = {}
        try:
            if arq is not None and arq.exists():
                dados = json.loads(arq.read_text(encoding="utf-8")) or {}
        except Exception:
            dados = {}
        self._sinais = (arq, dados)
        return dados

    def _ler_sinais(self, serial: str, apps, versoes: dict) -> None:
        """Os sinais (jogo, categoria, motor) dos apps sem sinal ou que
        mudaram de versao. Numa conversa so; roda na thread do cache."""
        import json
        from . import melhor_modo
        sinais = dict(self.sinais_dos_apps())
        pacotes = sorted({a[1].split(COPIA)[0] for a in apps
                          if a[1] != DEX})
        faltam = [p for p in pacotes
                  if (sinais.get(p) or {}).get("v") != versoes.get(p, "")]
        sairam = [p for p in sinais if p not in pacotes]
        if not faltam and not sairam:
            return
        t0 = time.monotonic()
        if faltam:
            saida = self._shell(serial, melhor_modo.roteiro_de_leitura(faltam),
                                espera=120)
            novos = melhor_modo.ler_saida(saida, versoes)
            if not novos:
                self.anotar("melhor modo: o celular nao respondeu os sinais")
                return
            sinais.update(novos)
        for p in sairam:
            sinais.pop(p, None)
        arq = self._arquivo_sinais()
        try:
            if arq is not None:
                arq.write_text(json.dumps(sinais, ensure_ascii=False),
                               encoding="utf-8")
        except Exception as erro:
            self.anotar("melhor modo: nao gravei os sinais (%s)" % erro)
        self._sinais = (arq, sinais)
        jogos = sorted(p for p in sinais if melhor_modo.tipo_do_app(
            p, sinais[p])[0] == melhor_modo.JOGO)
        self.anotar("melhor modo: %d apps lidos em %.1f s; jogos: %s" % (
            len(faltam), time.monotonic() - t0, ", ".join(jogos) or "nenhum"))
        self.apps_versao = getattr(self, "apps_versao", 0) + 1

    # -- (08/out, pedido dele) ANALISE DA INTERFACE (analise_app.py): o botao
    # "verificar apps" le a tabela de telas de cada APK no celular. Guardado
    # por versao em <celular>\interface.json; depois da 1a vez, app novo ou
    # atualizado e analisado sozinho ao conectar.

    def _arquivo_interface(self):
        pasta = self.pasta_do_celular()
        return pasta / "interface.json" if pasta is not None else None

    def interface_dos_apps(self) -> dict:
        arq = self._arquivo_interface()
        guardado = getattr(self, "_interface", None)
        if guardado is not None and guardado[0] == arq:
            return guardado[1]
        import json
        dados = {}
        try:
            if arq is not None and arq.exists():
                dados = json.loads(arq.read_text(encoding="utf-8")) or {}
        except Exception:
            dados = {}
        self._interface = (arq, dados)
        return dados

    def _gravar_interface(self, dados: dict) -> None:
        import json
        arq = self._arquivo_interface()
        # (08/out) a conferencia gravada no disco por OUTRO lado (outra
        # execucao) nao se perde: o que falta aqui vem de la
        try:
            if arq is not None and arq.exists():
                disco = json.loads(arq.read_text(encoding="utf-8")) or {}
                for p, a in disco.items():
                    m = dados.get(p)
                    if isinstance(a, dict) and isinstance(m, dict) and \
                            a.get("real") and not m.get("real") and \
                            a.get("v") == m.get("v"):
                        m["real"], m["real_v"] = a["real"], a.get("real_v")
        except Exception:
            pass
        try:
            if arq is not None:
                arq.write_text(json.dumps(dados, ensure_ascii=False),
                               encoding="utf-8")
        except Exception as erro:
            self.anotar("analise: nao gravei (%s)" % erro)
        self._interface = (arq, dados)

    analise_estado = None       # None | {"feitos", "total", "app", "fim"...}

    def analisar_apps(self, so_faltam: bool = False, serial: str = "",
                      versoes: dict | None = None) -> bool:
        """Comeca a analise (thread). False = ja rodando ou sem celular."""
        if self.analise_estado is not None and \
                not self.analise_estado.get("fim"):
            return False
        serial = serial or self._em_uso_pronto()
        apps = [a for a in (getattr(self, "apps_do_celular", None) or [])
                if a[1] != DEX and COPIA not in a[1]]
        if not serial or not apps:
            return False
        self.analise_estado = {"feitos": 0, "total": 0, "app": "",
                               "fim": False, "cancelar": False}
        threading.Thread(target=self._analisar, args=(serial, apps,
                                                      so_faltam, versoes),
                         daemon=True, name="analise-apps").start()
        return True

    def cancelar_analise(self) -> None:
        if self.analise_estado is not None:
            self.analise_estado["cancelar"] = True

    def _analisar(self, serial: str, apps, so_faltam: bool,
                  versoes: dict | None = None) -> None:
        import subprocess
        from . import analise_app
        estado = self.analise_estado
        versoes = versoes or self._assinatura(serial) or {}
        dados = dict(self.interface_dos_apps())
        # desinstalados saem do guardado
        for p in [k for k in dados if not k.startswith("_") and versoes and
                  k not in versoes]:
            dados.pop(p)
        fila = [(n, p) for n, p, _s in apps
                if not so_faltam or (dados.get(p) or {}).get("v") !=
                versoes.get(p, "")]
        estado["total"] = len(fila)
        t0 = time.monotonic()
        contagem = {}
        adb = str(self.config.adb_exe)
        sem_janela = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        for nome, pacote in fila:
            if estado.get("cancelar") or self._sair:
                break
            estado["app"] = nome
            try:
                caminho = self._shell(serial, "pm path %s | head -1"
                                      % pacote, espera=10).strip()
                caminho = caminho.split(":", 1)[-1].strip()
                r = subprocess.run(
                    [adb, "-s", serial, "exec-out",
                     "unzip -p '%s' resources.arsc" % caminho],
                    capture_output=True, timeout=90,
                    creationflags=sem_janela)
                c = analise_app.conclusao(analise_app.ler_tabela(r.stdout))
                c["v"] = versoes.get(pacote, "")
                dados[pacote] = c
                contagem[c["resultado"]] = contagem.get(c["resultado"], 0) + 1
            except Exception as erro:
                self.anotar("analise %s: falhou (%s)" % (pacote, erro))
            estado["feitos"] += 1
            if estado["feitos"] % 10 == 0:
                self._gravar_interface(dados)      # o que ja tem nao se perde
        # (08/out, relato dele: apps "de tablet" abrindo com a tela de celular
        # esticada) a CONFERENCIA DE VERDADE de quem a tabela diz tablet: o
        # app aberto escondido nos dois formatos (`_conferir_tablet`)
        conferir = [(n, p) for n, p, _s in apps
                    if (dados.get(p) or {}).get("resultado") ==
                    analise_app.TABLET and
                    (dados.get(p) or {}).get("real_v") != versoes.get(p, "")]
        if conferir and self._scrcpy_aceita("--new-display") and \
                self._scrcpy_aceita("--no-window"):
            estado["total"] += len(conferir)
            for nome, pacote in conferir:
                if estado.get("cancelar") or self._sair:
                    break
                if self._ocupado_com_o_celular():
                    self.anotar("conferencia: o programa esta usando o "
                                "celular; o resto fica para depois")
                    break
                # (teste no S22) com o celular DORMINDO o Android congela os
                # apps: a tela sai sem montar, com tarja falsa ou nem abre.
                # So confere acordado (ele usando, ou com janela de app
                # aberta: o vigia do sono o mantem acordado de tela apagada);
                # o resto fica para a proxima vez (`_conferir_depois`).
                if "Awake" not in (self._shell(
                        serial, "dumpsys power | grep mWakefulness=",
                        espera=10) or ""):
                    self.anotar("conferencia: celular dormindo, %d ficam "
                                "para depois" % (estado["total"] -
                                                 estado["feitos"]))
                    break
                estado["app"] = nome
                try:
                    real = self._conferir_tablet(serial, pacote,
                                                 dados[pacote])
                    if real:
                        dados[pacote]["real"] = real
                        dados[pacote]["real_v"] = versoes.get(pacote, "")
                        contagem["tablet " + real] = \
                            contagem.get("tablet " + real, 0) + 1
                except Exception as erro:
                    self.anotar("conferencia %s: falhou (%s)"
                                % (pacote, erro))
                estado["feitos"] += 1
                self._gravar_interface(dados)
        # cancelada no meio: o resto fica para a proxima conexao
        if not estado.get("cancelar"):
            dados["_feito"] = True
        self._gravar_interface(dados)
        estado["fim"] = True
        estado["contagem"] = contagem
        self.anotar("analise: %d de %d apps em %.0f s%s -- %s" % (
            estado["feitos"], estado["total"], time.monotonic() - t0,
            " (cancelada)" if estado.get("cancelar") else "",
            ", ".join("%s %d" % kv for kv in sorted(contagem.items()))))
        self.apps_versao = getattr(self, "apps_versao", 0) + 1

    # (08/out, relato dele: o Instagram caiu ao abrir -- "Server connection
    # failed", o servidor "Aborted") dois scrcpy subindo no MESMO instante
    # gravam o mesmo scrcpy-server no celular e um le o arquivo pela metade.
    # Entre duas subidas, uma folga que cobre o envio e o carregar do servidor.
    _LANCAR_TRAVA = threading.Lock()
    _ultimo_lancamento = 0.0
    FOLGA_ENTRE_SCRCPY_S = 1.2

    def _vez_de_lancar(self) -> None:
        with Programa._LANCAR_TRAVA:
            espera = (Programa._ultimo_lancamento + self.FOLGA_ENTRE_SCRCPY_S
                      - time.monotonic())
            if espera > 0:
                time.sleep(espera)
            Programa._ultimo_lancamento = time.monotonic()

    def _conferencia_pendente(self) -> bool:
        from . import analise_app
        return any(isinstance(a, dict) and
                   a.get("resultado") == analise_app.TABLET and
                   a.get("real_v") != a.get("v")
                   for a in self.interface_dos_apps().values())

    def _ocupado_com_o_celular(self) -> bool:
        """Alguma sessao do programa no ar ou subindo."""
        return bool(self.sessoes or self.ligando)

    def _conferir_depois(self, serial: str) -> None:
        """(08/out) A conferencia so roda com o celular ACORDADO e o programa
        SEM nada no ar (relato dele: com ela rodando junto, a abertura do
        Instagram caiu). A cada 60 s olha se da; acaba quando nao falta
        nenhum app."""
        t = getattr(self, "_conferir_thread", None)
        if t is not None and t.is_alive():
            return

        def laco():
            while not self._sair and self._conferencia_pendente():
                time.sleep(60)
                if self._em_uso_pronto() != serial or \
                        self._ocupado_com_o_celular() or \
                        (self.analise_estado is not None and
                         not self.analise_estado.get("fim")):
                    continue
                if "Awake" not in (self._shell(
                        serial, "dumpsys power | grep mWakefulness=",
                        espera=10) or ""):
                    continue
                if self.analisar_apps(so_faltam=True, serial=serial):
                    while not self._sair and self.analise_estado and \
                            not self.analise_estado.get("fim"):
                        time.sleep(2)

        self._conferir_thread = threading.Thread(
            target=laco, daemon=True, name="conferir-depois")
        self._conferir_thread.start()

    def _conferir_tablet(self, serial: str, pacote: str, analise: dict) -> str:
        """(08/out) Abre o app ESCONDIDO (tela virtual sem janela, sem som,
        sem acender o celular) no formato de celular e no de tablet que o
        modo pc usaria, e compara as telas montadas
        (`analise_app.conferencia`). Sem som do app enquanto isso (appops
        PLAY_AUDIO, devolvido no fim). "" = nao deu para conferir."""
        import re
        import subprocess
        from . import analise_app, formatos, melhor_modo
        # App ja aberto (no celular, numa janela ou nos recentes): abrir de
        # novo levaria a tarefa DELE para a tela escondida e o fim a fecharia.
        # Fica para a proxima conexao.
        if re.search(r"taskId=\d+: %s/" % re.escape(pacote),
                     self._shell(serial, "am stack list", espera=10) or ""):
            self.anotar("conferencia %s: aberto no celular, fica para depois"
                        % pacote)
            return ""
        cel = self.celular or {}
        dp = melhor_modo.largura_do_tablet(analise)
        l, a, d, _p = formatos.tela_app("pc", 720, True, cel, dp)
        formatos_ = (("cel", 720, 1560, 320), ("tab", l, a, d))
        sem_janela = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        som = self._shell(serial, "appops get %s PLAY_AUDIO" % pacote,
                          espera=10) or ""
        self._shell(serial, "appops set %s PLAY_AUDIO ignore" % pacote,
                    espera=10)
        telas = {}
        t0 = time.monotonic()
        try:
            for nome, w, h, dpi in formatos_:
                if self._sair:
                    return ""
                self._vez_de_lancar()
                proc = subprocess.Popen(
                    [str(self.config.scrcpy_exe), "-s", serial, "--no-audio",
                     "--no-window", "--no-power-on", "--record=NUL",
                     "--record-format=mkv", "--max-fps=5",
                     "--new-display=%dx%d/%d" % (w, h, dpi),
                     "--no-vd-system-decorations", "--start-app=" + pacote],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    cwd=str(self.config.scrcpy_exe.parent),
                    creationflags=sem_janela)
                try:
                    fim = time.monotonic() + 15
                    while time.monotonic() < fim:
                        linha = proc.stdout.readline().decode(
                            "utf-8", "replace")
                        if not linha or "New display" in linha:
                            break
                    # espera a tela do app ficar parada (ate ~9 s)
                    antes, pecas = None, {}
                    for vez in range(10):
                        time.sleep(1.0)
                        pecas = analise_app.pecas_da_tela(
                            self._shell(serial, "dumpsys activity top",
                                        espera=15) or "", pacote, w, h)
                        marca = (pecas["achou"], len(pecas["ids"]),
                                 pecas["views"])
                        if pecas["achou"] and marca == antes and vez >= 3:
                            break
                        antes = marca
                    telas[nome] = pecas
                finally:
                    tarefas = self._shell(serial, "am stack list",
                                          espera=10) or ""
                    for tid in set(re.findall(r"taskId=(\d+): %s/"
                                              % re.escape(pacote), tarefas)):
                        self._shell(serial, "am stack remove %s" % tid,
                                    espera=10)
                    proc.kill()
                    # (08/out, achado: uma tela escondida com o 99 ficou 38 min
                    # de pe) o servidor no celular nem sempre percebe o PC
                    # saindo: derrubado la tambem (a tela some junto)
                    self._shell(serial, "pkill -f 'max_fps=5 power_on=false "
                                "new_display=%dx%d/%d' ; true" % (w, h, dpi),
                                espera=10)
                    time.sleep(0.8)
        finally:
            m = re.search(r"PLAY_AUDIO: (\w+)", som)
            volta = m.group(1) if m else "default"
            self._shell(serial, "appops set %s PLAY_AUDIO %s"
                        % (pacote, volta), espera=10)
        real = analise_app.conferencia(telas.get("cel") or {},
                                       telas.get("tab") or {})
        self.anotar("conferencia %s: %s em %.0f s (celular %d ids, tablet "
                    "%dx%d/%d %d ids%s%s)" % (
                        pacote, real, time.monotonic() - t0,
                        len((telas.get("cel") or {}).get("ids") or ()), l, a,
                        d, len((telas.get("tab") or {}).get("ids") or ()),
                        "" if (telas.get("tab") or {}).get("cheia", True)
                        else ", com tarja",
                        ", em colunas" if (telas.get("tab") or {}).get(
                            "colunas") else ""))
        return real

    def melhor_auto(self) -> bool:
        # (08/out, rework) sempre ligado: o modo sai da verificacao
        return True

    def verificacao_feita(self) -> bool:
        return bool(self.interface_dos_apps().get("_feito"))

    def melhor_do_app(self, pacote: str, serial: str = ""):
        """A recomendacao do app ({tipo, porque, janela, pc, analise}) ou
        None (DeX)."""
        from . import melhor_modo
        if pacote == DEX:
            return None
        base = pacote.split(COPIA)[0]
        return melhor_modo.recomendacao(base, self.sinais_dos_apps().get(base),
                                        self.celular or {},
                                        self.conexao_de(serial),
                                        self.interface_dos_apps().get(base))

    def config_efetiva(self, pacote: str, serial: str = "") -> dict:
        """O que vale para o app: o automatico por baixo, o personalizado
        dele por cima (`melhor_modo.mesclar`)."""
        from . import melhor_modo
        return melhor_modo.mesclar(self.config.app(pacote),
                                   self.melhor_do_app(pacote, serial),
                                   self.config.apps.get("modo") or "pc")

    def _desenhar_icone_dex(self) -> None:
        """Reserva do icone do DeX: um monitor branco num quadrado azul.
        Serve em qualquer celular/versao; nunca quebra (falhou, fica a letra)."""
        try:
            from PIL import Image, ImageDraw
            n = 96
            img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((0, 0, n - 1, n - 1), radius=22,
                                fill=(20, 40, 160, 255))
            d.rounded_rectangle((18, 24, 78, 62), radius=4,
                                outline=(255, 255, 255, 255), width=6)
            d.rectangle((44, 62, 52, 72), fill=(255, 255, 255, 255))
            d.rounded_rectangle((32, 70, 64, 76), radius=3,
                                fill=(255, 255, 255, 255))
            img.save(self.pasta_de_icones() / (DEX + ".png"))
        except Exception as erro:
            self.anotar("icones: nao desenhei o do DeX (%s)" % erro)

    def buscar_icones(self, pacotes) -> int:
        """
        FORA DA THREAD DA JANELA. Pede ao celular o icone de cada pacote (o
        programinha de `android\\`, rodando la como o servidor do scrcpy) e
        guarda cada um como PNG em `icones\\`. Devolve quantos chegaram.
        """
        import re
        # DeX sem icone (r164, 25/set/2026): "__dex__" nao e pacote, entao
        # ficava so a letra. Agora: desenha um reserva na hora e pede ao
        # celular o icone do app do DeX, que por cima substitui o desenho.
        quer_dex = DEX in pacotes
        if quer_dex:
            self._desenhar_icone_dex()
        # (r186) A copia usa o icone do original com um numero no canto:
        # pede o do original (se faltar) e desenha no fim.
        copias = [p for p in pacotes if COPIA in p]
        pasta_i = self.pasta_de_icones()
        pacotes = list(pacotes) + [
            separar_app(c)[0] for c in copias
            if not (pasta_i / (separar_app(c)[0] + ".png")).exists()]
        pacotes = list(dict.fromkeys(
            p for p in pacotes if p != DEX
            and re.fullmatch(r"[A-Za-z0-9._]+", p)))
        if copias:
            try:
                return self._buscar_icones_de_pacotes(
                    pacotes, quer_dex) + self._icones_das_copias(copias)
            except Exception as erro:
                self.anotar("icones: copias falharam (%s)" % erro)
                return 0
        return self._buscar_icones_de_pacotes(pacotes, quer_dex)

    def _icones_das_copias(self, copias) -> int:
        """(r186) icone do original + o numero da copia num circulo."""
        from PIL import Image, ImageDraw, ImageFont
        pasta = self.pasta_de_icones()
        feitos = 0
        nomes = {a[1]: a[0] for a in (getattr(self, "apps_do_celular", None)
                                      or [])}
        for chave in copias:
            base = pasta / (separar_app(chave)[0] + ".png")
            if not base.exists():
                continue
            import re as _re
            m = _re.search(r"\((\d+)\)\s*$", nomes.get(chave, ""))
            numero = m.group(1) if m else "2"
            img = Image.open(base).convert("RGBA").resize((96, 96))
            d = ImageDraw.Draw(img)
            r = 20
            d.ellipse((96 - 2 * r - 1, 96 - 2 * r - 1, 95, 95),
                      fill=(225, 93, 255, 255), outline=(20, 20, 24, 255),
                      width=3)
            try:
                fonte = ImageFont.truetype("arialbd.ttf", 26)
            except Exception:
                fonte = ImageFont.load_default()
            try:
                d.text((96 - r - 1, 96 - r - 1), numero,
                       fill=(255, 255, 255, 255), font=fonte, anchor="mm")
            except Exception:       # fonte sem ancora (Pillow velho)
                d.text((96 - r - 6, 96 - r - 8), numero,
                       fill=(255, 255, 255, 255), font=fonte)
            img.save(pasta / (chave + ".png"))
            feitos += 1
        return feitos

    def _buscar_icones_de_pacotes(self, pacotes, quer_dex) -> int:
        import base64
        import subprocess
        if quer_dex and ICONE_DEX not in pacotes:
            pacotes.append(ICONE_DEX)
        if not pacotes or not self.config.instalacao_ok:
            return 0
        jar = caminhos.pasta_interna() / "android" / "scrcpyf-icones.jar"
        if not jar.exists():
            self.anotar("icones: falta o %s" % jar)
            return 0
        alvo = self._achar_celular()
        if not alvo:
            return 0
        adb = str(self.config.adb_exe)
        sem_janela = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        destino_no_celular = "/data/local/tmp/scrcpyf-icones.jar"
        try:
            subprocess.run([adb, "-s", alvo, "push", str(jar),
                            destino_no_celular], capture_output=True,
                           timeout=30, creationflags=sem_janela)
        except Exception as erro:
            self.anotar("icones: nao consegui mandar o programinha (%s)" % erro)
            return 0
        pasta = self.pasta_de_icones()
        chegaram = 0
        motivos: list = []
        for i in range(0, len(pacotes), 40):
            lote = pacotes[i:i + 40]
            comando = ("CLASSPATH=%s app_process / scrcpyf.Icones 96 %s"
                       % (destino_no_celular, " ".join(lote)))
            try:
                r = subprocess.run([adb, "-s", alvo, "shell", comando],
                                   capture_output=True, timeout=90,
                                   creationflags=sem_janela)
            except Exception as erro:
                self.anotar("icones: o celular nao respondeu (%s)" % erro)
                break
            saida = (r.stdout or b"").decode("utf-8", errors="replace")
            neste = 0
            for linha in saida.splitlines():
                pacote, _, dado = linha.strip().partition("\t")
                if pacote in lote and dado.startswith("-"):
                    # "pacote<TAB>-<TAB>motivo": guarda os primeiros motivos
                    if len(motivos) < 6:
                        motivos.append("%s: %s" % (pacote,
                                                   dado[1:].strip()[:160]))
                    continue
                if pacote in lote and dado:
                    try:
                        bruto = base64.b64decode(dado)
                        (pasta / (pacote + ".png")).write_bytes(bruto)
                        if pacote == ICONE_DEX and quer_dex:
                            (pasta / (DEX + ".png")).write_bytes(bruto)
                        neste += 1
                    except Exception:
                        pass
            chegaram += neste
            if not neste:
                erro = (r.stderr or b"").decode("utf-8", errors="replace")
                fim = [l for l in (saida + "\n" + erro).splitlines()
                       if l.strip()][-4:]
                self.anotar("icones: nenhum veio neste lote; fim da saida: %s"
                            % " / ".join(fim))
                break
        self.anotar("icones: %d de %d" % (chegaram, len(pacotes)))
        for motivo in motivos:
            self.anotar("icones: falhou %s" % motivo)
        return chegaram

    def _partida_app(self, nome: str, pacote: str, rotulo: str,
                     lugar=None, serial: str = "", troca: bool = False,
                     log_velho: str = "", tela_cheia: bool = False,
                     intencao=None):
        """
        `lugar` = (x, y, largura, altura) da imagem da janela velha, quando
        e um "reabrir" (ver `reabrir_app`).

        `troca=True` (r125, `_trocar_sem_reiniciar`): sobe SO a janela, com
        a tela virtual vazia (sem --start-app) e fora da vista, no celular
        `serial` (sem procurar de novo), e DEVOLVE a sessao em vez de avisar
        o laco -- quem troca poe o app nela e a janela no lugar. None = nao
        subiu.
        """
        t0 = time.monotonic()      # (08/out) o tempo do pedido ao scrcpy
        try:
            alvo = serial or self._achar_celular()
            if not alvo:
                if troca:
                    return None
                self.pedidos.put(("falhou", nome, TEXTO_SEM_CELULAR))
                return
            sdk = (self.celular or {}).get("sdk")
            if isinstance(sdk, int) and sdk < 29:
                self.pedidos.put(("falhou", nome, "app em janela precisa do "
                                  "Android 10 ou mais novo."))
                return
            # A imagem sai com a qualidade do ESPELHAR (nivel, codec, taxa).
            # Sem som (varias janelas nao dividem o som do celular), sem
            # apagar a tela de verdade nem mexer no tempo dela, e o teclado
            # manda texto pronto (ver `sessao.montar`).
            perfil = self.perfil_para_subir("jogo", alvo)
            perfil.setdefault("video", {})["ligado"] = True
            # QUALIDADE DOS APPS (23/set/2026): a unica, de OPCOES >
            # qualidade (ja veio no perfil_para_subir). O app personalizado
            # (APPS > personalizados) pode trocar a predefinicao e cada
            # fileira; vazio = "padrao" (segue opcoes).
            # (08/out) com o MELHOR MODO por baixo do que ele escolheu
            deste = self.config_efetiva(pacote, alvo)
            from . import qualidade
            import copy
            # (08/out, rework) o NIVEL e o SOM do app (senao os gerais)
            q = self.config.qualidade
            audio_q = qualidade.audio_do_som(qualidade.som_de(deste, q))
            qualidade.aplicar_no_perfil(perfil, qualidade.video_do_nivel(
                qualidade.nivel_de(deste, q)), None)
            self._resolucao_no_perfil(perfil)               # (r189)
            # ONDE O SOM TOCA: o do app, senao o de APPS > ajustes; de
            # fabrica o som fica no celular (varias janelas nao dividem o
            # som, que e do celular inteiro).
            onde = deste.get("onde") or self.config.apps.get("onde") \
                or "celular"
            if onde != "celular":
                # Nao exigido: se outra sessao ja estiver com o som, a
                # janela sobe muda em vez de falhar.
                audio = copy.deepcopy(perfil.get("audio") or {})
                audio["exigir"] = False
                perfil["audio"] = audio
                qualidade.aplicar_no_perfil(perfil, None, audio_q)
            qualidade.aplicar_onde(perfil, onde)
            perfil["sessao"] = {}
            # TELA CHEIA (r135): o --fullscreen do scrcpy; a posicao que vai
            # junto (lugar) escolhe em qual monitor.
            perfil["janela"] = {"tela_cheia": True} if tela_cheia else {}
            perfil["titulo"] = rotulo
            perfil["controle"] = {"teclado_mouse": True, "joystick": False,
                                  "teclado": "texto"}
            desenho = icone.gravar_para_janela(caminhos.pasta_dados(),
                                               self.config.scrcpy_exe)
            seguro = "".join(ch if ch.isalnum() else "_" for ch in pacote)
            sessao = Sessao(nome)
            # (r158) JANELA PROPRIA: cada app roda de um .exe so dele (botao
            # separado na barra de tarefas) e com o icone dele. Falhou =
            # o scrcpy de sempre (agrupado), com o icone do scrcpy-f.
            from . import janelas_proprias
            exe_app, icone_app, variaveis, como = janelas_proprias.para_o_app(
                self.config.scrcpy_exe, self.config.adb_exe, pacote,
                self.pasta_de_icones() / (pacote + ".png"), desenho)
            if como != "pronta":
                self.anotar("app %s: janela propria -> %s (%s)"
                            % (pacote, exe_app.name, como))
            if pacote == DEX:
                # A area de trabalho do Samsung, de proposito, em tamanho
                # de monitor.
                # (r142) Densidade de MONITOR (160): com a do celular (369)
                # tudo ficava em escala de celular. Escolhida por ele na
                # sonda_dex (25/set/2026: "ficou perfeita").
                extras = ["--new-display=1920x1080/160"]
            else:
                # O APP PRESO NA JANELA (pedido dele, 23/set/2026: o botao
                # do mouse levava a uma "tela tipo DeX"):
                # - sem as decoracoes da tela virtual = sem area de trabalho,
                #   barra ou botoes do Samsung dentro da janela;
                # - mouse: direito e o 4o botao = VOLTAR, o do meio e o 5o
                #   nao fazem nada (o do meio era o INICIO);
                # - os atalhos do scrcpy (Alt+H = inicio, Alt+S = recentes)
                #   vao para a tecla Windows da direita, que quase ninguem tem;
                # - e se o app sair mesmo assim (voltar demais), o
                #   `_manter_no_app` abre ele de novo na mesma tela.
                extras = ["--new-display", "--no-vd-system-decorations",
                          "--mouse-bind=b-b-:b-b-", "--shortcut-mod=rsuper",
                          # (08/out) quem acende/apaga e o vigia do sono
                          "--no-power-on"]
                # (r141) O TECLADO DO CELULAR DENTRO DA JANELA (pedido dele,
                # 25/set/2026: no Instagram a caixa de texto so aparece
                # junto do teclado, que nao ia para a tela virtual). So
                # aparece ao clicar num campo; digitar pelo PC segue igual.
                # scrcpy sem a opcao (antes do 3.2): segue sem ela.
                # (r143) "local" mostrava o teclado mas deixava uma faixa
                # preta no topo do Instagram, com ou sem digitar. Ele quer o
                # teclado ESCONDIDO e o do PC funcionando: "hide".
                # (r144) A faixa preta e do Instagram (teste dele). (r145)
                # "fallback" nao trouxe a caixa do repost. (r146, ok dele)
                # TECLADO FISICO SIMULADO + teclado do celular "na janela":
                # com teclado fisico o Android nao desenha o da tela, mas o
                # app ve um teclado aberto e mostra a caixa. O uhid tinha
                # sido descartado aqui (a tecla vai para a tela com foco);
                # o vigia do foco (r113) agora da o foco a janela sob o
                # mouse, e o acento via uhid ja funciona na extensao.
                # (r147) NAO trouxe a caixa: volta o texto pronto. (r148,
                # pedido dele) OPCAO POR APP, desligada de fabrica: o
                # teclado do celular desenhado na janela ("local") -- o unico
                # jeito em que a caixa do repost do Instagram aparece.
                # (08/out, checagem no S22: sem politica o teclado abria NA
                # TELA DO CELULAR ao tocar num campo da janela) "hide" = o
                # teclado da tela nao aparece em lugar nenhum; o do PC digita.
                POLITICA_TECLADO = "local" if self.fix_do_app(
                    pacote, "teclado_celular") else "hide"
                if POLITICA_TECLADO and \
                        self._scrcpy_aceita("--display-ime-policy"):
                    extras.append("--display-ime-policy=" + POLITICA_TECLADO)
                # (01/out) `intencao` = o destino de uma notificacao: a tela
                # sobe vazia e o destino entra pelo `am start`.
                if not troca and COPIA not in pacote and not intencao:
                    extras.append("--start-app=%s" % pacote)
                # (r184) FORMATO E RESOLUCAO DO APP (formatos.py; antes: o
                # "modo jogo" seguia o monitor a risca).
                tamanho = self._tela_do_app(pacote, deste)
                if tamanho:
                    extras[0] = tamanho["opcao"]
                    if tamanho.get("lado"):
                        # A imagem vai inteira, no tamanho da tela virtual
                        # (a "resolucao" geral da qualidade nao corta).
                        perfil.setdefault("video", {})["resolucao_max"] = \
                            tamanho["lado"]
                    self.anotar("app %s: %s" % (pacote, tamanho["nota"]))
            # REABRIR NO MESMO LUGAR (r123): posicao e ALTURA da janela velha;
            # a largura o scrcpy tira do formato da imagem -- o ajuste novo
            # pode ter trocado o formato (tela do celular x do monitor).
            if lugar and pacote != DEX:
                extras += ["--window-x=%d" % lugar[0],
                           "--window-y=%d" % lugar[1]]
                if not tela_cheia:
                    extras.append("--window-height=%d" % lugar[3])
            elif pacote != DEX and not tela_cheia and tamanho and \
                    tamanho.get("janela"):
                # (08/out) a janela do tamanho de 720p em qualquer nivel
                extras += ["--window-width=%d" % tamanho["janela"][0],
                           "--window-height=%d" % tamanho["janela"][1]]
            # TELA APAGADA = APP SEM IMAGEM (pedido dele, 23/set/2026): com o
            # celular dormindo o Android pausa os apps em todas as telas,
            # inclusive a virtual. Acende antes de abrir; o vigia do sono
            # mantem acordado enquanto houver janela de app.
            if not troca:       # na troca o app ja esta aberto: acordado
                # (08/out, pedido dele: mexer no PC nao acende a tela do
                # celular) Dormindo: o vigia do sono acorda com o PAINEL
                # APAGADO (o app roda, a tela fica preta). Acordado: o de
                # sempre (o WAKEUP nao muda nada).
                if self._celular_dormindo(alvo):
                    # (08/out, pedido dele: abrir o mais rapido possivel) a
                    # janela sobe JUNTO com o acordar apagado (antes esperava
                    # o vigia, ~2 s); o scrcpy do app vai com --no-power-on
                    self._acordado_apagado.clear()
                    self._apagar_ao_subir = True
                    threading.Thread(target=self._garantir_vigia_sono,
                                     args=(alvo,), daemon=True,
                                     name="vigia-sono-sobe").start()
                else:
                    acordar = "cmd input keyevent KEYCODE_WAKEUP"
                    if not self._pela_conversa(alvo, acordar):   # (r139)
                        self._shell(alvo, acordar, espera=5)
            # Na troca a velha ainda escreve no log dela: a nova usa o outro
            # nome (os dois se revezam, como no espelhar).
            nome_log = "log_app_%s.txt" % seguro
            if troca and str(log_velho).endswith(nome_log):
                nome_log = "log_app_%s_2.txt" % seguro
            self._vez_de_lancar()
            self.anotar("app %s: scrcpy chamado %d ms depois do pedido" % (
                pacote, (time.monotonic() - t0) * 1000))
            ok = sessao.iniciar(exe_app, alvo, perfil,
                                caminhos.pasta_relatorios(), icone=icone_app,
                                extras=extras, nome_log=nome_log,
                                ambiente_extra=variaveis)
            if not ok:
                if troca:
                    return None
                self.pedidos.put(("falhou", nome,
                                  "Nao consegui abrir %s.\n\nDetalhes em "
                                  "relatorios\\log_app_%s.txt." % (rotulo,
                                                                   seguro)))
                return
            if self._sair:
                sessao.parar()
                return None
            # (07/out) MODO PC: o app ainda nao visto -> confere se ele
            # encheu a tela ou ficou com tarja (jogo que so roda deitado).
            if pacote != DEX and tamanho and tamanho.get("conferir"):
                threading.Thread(target=self._conferir_orientacao,
                                 args=(alvo, pacote, sessao,
                                       tamanho["deitado"],
                                       tamanho.get("largura_dp", 0)),
                                 daemon=True,
                                 name="orientacao-%s" % pacote).start()
            if troca:
                return sessao
            self.pedidos.put(("subiu", nome, sessao))
            if intencao:
                threading.Thread(target=self._abrir_intencao,
                                 args=(alvo, pacote, sessao, intencao),
                                 daemon=True,
                                 name="destino-%s" % pacote).start()
            elif COPIA in pacote:
                # (r186) A copia: o --start-app nao escolhe usuario; a tela
                # virtual sobe vazia e o app entra nela pelo `am start`.
                threading.Thread(target=self._abrir_copia,
                                 args=(alvo, pacote, sessao), daemon=True,
                                 name="copia-%s" % pacote).start()
            self._garantir_vigia_sono(alvo)
            self._garantir_vigia_foco(alvo)
        except Exception as erro:
            log.exception("falha ao abrir o app %s", pacote)
            if troca:
                return None
            self.pedidos.put(("falhou", nome, "Falha inesperada: %s" % erro))

    def _tela_do_app(self, pacote: str, deste: dict):
        """
        (r184) A tela virtual do app: {"opcao": "--new-display=...",
        "lado": lado maior ou 0, "nota": para o registro}. None = a de
        sempre (tamanho do celular).
        """
        from . import formatos, qualidade
        cel = self.celular or {}
        apps = self.config.apps
        # (08/out, rework) A TELA VIRTUAL sai do MODO (pc so com a
        # verificacao), da RESOLUCAO DO NIVEL e da orientacao; a densidade,
        # da resolucao (pc: a largura do tablet do app; celular: a do
        # aparelho).
        modo = deste.get("modo") or "celular"
        try:
            largura_dp = int(deste.get("sw_dp") or 0) if modo == "pc" else 0
        except (TypeError, ValueError):
            largura_dp = 0
        # (08/out, rework) A ORIENTACAO e sempre automatica (a que o programa
        # reconheceu; nao sabida = o palpite e confere). (08/out, teste do
        # WhatsApp) ela so vale para a LARGURA em que foi vista: com a tela
        # estreita demais o app abre o layout de celular e trava em pe; com a
        # largura nova ele e conferido de novo.
        sabido = (apps.get("orientacao") or {}).get(pacote)
        if sabido and (apps.get("orient_dp") or {}).get(pacote) != largura_dp:
            sabido = None
        deitado, conferir = sabido == "deitado", not sabido
        # (08/out) no modo pc o palpite e DEITADO (o formato do monitor; o
        # app que so roda em pe e conferido e reaberto em pe uma vez)
        if not sabido and (deste.get("forma_auto") == "deitado" or
                           modo == "pc"):
            deitado = True
        if modo != "pc" and not formatos.tela_do_celular(cel):
            return None                       # sem o celular lido
        p = qualidade.P_DO_NIVEL[qualidade.nivel_de(deste,
                                                    self.config.qualidade)]
        # (09/out, pedido dele) o tamanho do app: o dele, senao o de todos
        escala = formatos.TAMANHOS.get(
            self.config.app(pacote).get("escala") or apps.get("escala")
            or "normal", 1.0)
        l, a, dpi, usado = formatos.tela_app(modo, p, deitado, cel,
                                             largura_dp, escala)
        if usado != p:
            self.anotar("app %s: %dp nao cabe no celular; vai %dp"
                        % (pacote, p, usado))
        # (08/out, pedido dele: "a dpi tem que acompanhar a resolucao pra
        # manter tudo no tamanho correto") a JANELA nasce do tamanho que teria
        # em 720p, em qualquer nivel: o layout (dp) e o mesmo, entao a
        # resolucao so muda a NITIDEZ (antes 1080p abria a janela enorme e
        # 540p pequena). Cabe em 90% da area do monitor.
        l7, a7, _d7, _u7 = formatos.tela_app(modo, 720, l > a, cel,
                                             largura_dp)
        janela = self._caber_no_monitor(l7, a7)
        return {"opcao": "--new-display=%dx%d/%d" % (l, a, dpi),
                "lado": max(l, a), "modo": modo, "deitado": l > a,
                "conferir": conferir, "largura_dp": largura_dp,
                "janela": janela,
                "nota": "tela virtual %dx%d/%d (modo %s, %dp, %s%s%s)" % (
                    l, a, dpi, modo, usado, "deitado" if l > a else "em pe",
                    (", layout %d dp" % largura_dp) if modo == "pc" and
                    largura_dp else "",
                    (", tamanho x%.2f" % escala) if escala != 1.0 else "")}

    def _caber_no_monitor(self, l: int, a: int):
        """(largura, altura) de `l x a` reduzida para caber em 90% da area
        util do monitor principal (mesma proporcao)."""
        try:
            from . import monitores
            lista = monitores.listar()
            m = next((x for x in lista if x.get("principal")),
                     lista[0] if lista else None)
            ml, ma = (m["l"], m["a"]) if m else (1920, 1080)
        except Exception:
            ml, ma = 1920, 1080
        esc = min(1.0, ml * 0.9 / float(l), ma * 0.85 / float(a))
        return int(l * esc), int(a * esc)

    # (07/out) EM PE OU DEITADO, SOZINHO. Os apps novos enchem a tela de
    # tablet em qualquer forma; o que trava a orientacao (jogo) fica com a
    # janela dele em outra forma, com tarja. Duas leituras iguais seguidas
    # decidem: igual a tela = guarda e pronto; diferente = guarda e reabre
    # na outra forma (uma vez so: da proxima o app ja abre certo).
    def _conferir_orientacao(self, serial: str, pacote: str, sessao,
                             deitado: bool, largura_dp: int = 0) -> None:
        tela = None
        fim = time.monotonic() + 20
        while tela is None and sessao.rodando and not self._sair and \
                time.monotonic() < fim:
            achada = self._tela_da_sessao(sessao)
            tela = achada[0] if achada else None
            if tela is None:
                time.sleep(0.3)
        if tela is None:
            self.anotar("orientacao %s: sem o numero da tela" % pacote)
            return
        da_tela = "deitado" if deitado else "em_pe"
        vistas = []
        fim = time.monotonic() + 15
        while sessao.rodando and not self._sair and time.monotonic() < fim:
            time.sleep(1.2)
            try:
                forma = self._forma_do_app(serial, tela, pacote)
            except Exception:
                log.exception("orientacao %s: leitura falhou", pacote)
                return
            if forma is None:
                continue
            vistas.append(forma)
            if len(vistas) >= 2 and vistas[-1] == vistas[-2]:
                break
        else:
            self.anotar("orientacao %s: sem leitura firme (%s)"
                        % (pacote, vistas))
            return
        forma = vistas[-1]
        orient = self.config.apps.setdefault("orientacao", {})
        orient[pacote] = forma
        # a largura em que foi vista (outra largura = conferir de novo)
        self.config.apps.setdefault("orient_dp", {})[pacote] = largura_dp
        self.config.gravar()
        self.anotar("orientacao %s: o app fica %s (tela %s)"
                    % (pacote, forma, da_tela))
        if forma != da_tela and sessao.rodando and not self._sair:
            self.reabrir_app(pacote, virou=True)

    def _forma_do_app(self, serial: str, tela: str, pacote: str):
        """"deitado", "em_pe" ou None: a forma da janela do app na tela
        virtual, pelo `dumpsys window windows` (so as linhas que importam).
        Quase quadrada = None (nao decide)."""
        import re
        pac = separar_app(pacote)[0]
        texto = self._shell(
            serial, "dumpsys window windows | grep -E "
            "'Window #|mDisplayId|frame=|mFrame='", espera=8)
        bloco_ok = False
        tela_ok = False
        for linha in texto.splitlines():
            if "Window #" in linha:
                bloco_ok = (" %s/" % pac) in linha
                tela_ok = False
                continue
            if not bloco_ok:
                continue
            m = re.search(r"mDisplayId=(\d+)", linha)
            if m:
                tela_ok = m.group(1) == str(tela)
                continue
            m = re.search(r"\b(?:frame|mFrame)=\[(-?\d+),(-?\d+)\]"
                          r"\[(-?\d+),(-?\d+)\]", linha)
            if m and tela_ok:
                x0, y0, x1, y1 = (int(v) for v in m.groups())
                larg, alt = x1 - x0, y1 - y0
                if larg <= 0 or alt <= 0 or \
                        abs(larg - alt) < 0.1 * max(larg, alt):
                    return None
                return "deitado" if larg > alt else "em_pe"
        return None

    def _resolucao_no_perfil(self, perfil: dict) -> None:
        """(r189) A resolucao em "p" da qualidade vira o --max-size (lado
        maior) com a proporcao do celular. Sempre por cima do que o perfil
        guardar (perfis antigos ainda tem "resolucao_max" solto)."""
        from . import qualidade
        video = perfil.setdefault("video", {})
        if "resolucao" in video:
            video["resolucao_max"] = qualidade.lado_maior(
                video.get("resolucao"), self.celular)

    def _migrar_formatos(self) -> None:
        """(r184) Marcas de jogo / tela do monitor viram formato, 1 vez."""
        try:
            from . import formatos, monitores
            lista = monitores.listar(estrito=True)
            m = next((x for x in lista if x.get("principal")),
                     lista[0] if lista else None)
            fmt = formatos.do_monitor(m["l"], m["a"]) if m and m["a"] > 0 \
                else "16:9"
            mudou = formatos.migrar(self.config.apps, fmt)
            # (r189) qualidade em "p"; a fixa "nitido" virou "celular".
            from . import qualidade
            if qualidade.migrar(self.config.qualidade, self.config.apps):
                mudou = True
                for perfil in self.config.perfis.values():
                    if isinstance(perfil, dict) and \
                            perfil.get("predef") == "nitido":
                        perfil["predef"] = "celular"
            # (08/out, rework) predefinicoes -> nivel e som
            if qualidade.migrar_niveis(self.config.qualidade,
                                       self.config.perfis, self.config.apps):
                mudou = True
            if mudou:
                self.config.gravar()
                log.info("formatos/qualidade: marcas antigas convertidas "
                         "(%s)", fmt)
        except Exception:
            log.exception("formatos: conversao falhou")

    def _componente(self, serial: str, chave: str) -> str:
        """A tela de entrada do app (do usuario dele), ou ""."""
        import re
        # (02/out, revisao) Guardada por 10 min: abrir, trocar e a copia
        # perguntavam de novo a cada vez (a copia, duas).
        guardados = self.__dict__.setdefault("_componentes", {})
        agora = time.monotonic()
        achado = guardados.get((serial, chave))
        if achado and agora - achado[1] < 600:
            return achado[0]
        pacote, usuario = separar_app(chave)
        comp = self._shell(serial, "cmd package resolve-activity --brief "
                           "--user %d %s | tail -1" % (usuario, pacote))
        comp = (comp.strip().splitlines()[-1:] or [""])[0].strip()
        if not re.fullmatch(r"[A-Za-z0-9._$/]+", comp) or "/" not in comp:
            return ""
        guardados[(serial, chave)] = (comp, agora)
        return comp

    def _abrir_copia(self, serial: str, chave: str, sessao) -> None:
        """(r186) Poe a copia na tela virtual da janela dela."""
        pacote, usuario = separar_app(chave)
        tela = None
        fim = time.monotonic() + 20
        while not tela and time.monotonic() < fim and sessao.rodando:
            tela = (self._tela_da_sessao(sessao) or (None,))[0]
            if not tela:
                time.sleep(0.1)
        comp = self._componente(serial, chave) if tela else ""
        if not tela or not comp:
            self.anotar("copia %s: nao abri (tela %s, entrada %r)"
                        % (chave, tela, comp))
            return
        resp = self._shell(serial, "am start --user %d --display %s -n %s"
                           % (usuario, tela, comp), espera=8).strip()
        self.anotar("copia %s: aberta na tela %s (%s)"
                    % (chave, tela, resp[:120]))

    def _serial_conhecido(self) -> str:
        """(r149) O celular ja lido (sem gastar um `adb devices`); sem ele,
        procura. Se o conhecido tiver saido da rede, o comando falha e quem
        chamou ja trata vazio -- e o proximo `achar` de uma partida corrige."""
        serial = (self.celular or {}).get("serial", "")
        return serial or celular.achar(self.config.adb_exe,
                                       self.config.ip_reserva)

    def _em_uso_pronto(self) -> str:
        """(limpeza 01/out) O serial do celular em uso, se o adb o lista como
        pronto agora (a vigia atualiza `_prontos` a cada 1,5 s); senao vazio."""
        serial = (self.celular or {}).get("serial", "")
        prontos = getattr(self, "_prontos", None) or set()
        return serial if serial in prontos else ""

    def _achar_celular(self) -> str:
        """
        O celular de toda partida: o EM USO, se esta pronto; senao a procura
        completa. Antes cada partida chamava `celular.achar`, que escolhe pela
        preferencia de conexao e nao pelo celular em uso -- com DOIS celulares
        ligados um modo podia subir no outro (limite anotado no r193).
        """
        return self._em_uso_pronto() or celular.achar(
            self.config.adb_exe, self.config.ip_reserva)

    def _scrcpy_aceita(self, opcao: str) -> bool:
        """
        (r141) O scrcpy instalado conhece `opcao`? Olha o `--help` UMA vez
        por execucao (e por pasta do scrcpy). Opcao desconhecida faz o
        scrcpy recusar subir -- entao na duvida, nao usa.
        """
        exe = str(self.config.scrcpy_exe)
        guardado = getattr(self, "_ajuda_scrcpy", None)
        if not guardado or guardado[0] != exe:
            import subprocess
            try:
                r = subprocess.run(
                    [exe, "--help"], capture_output=True, timeout=10,
                    cwd=str(self.config.scrcpy_exe.parent),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                ajuda = ((r.stdout or b"") + (r.stderr or b"")).decode(
                    "utf-8", errors="replace")
            except Exception as erro:
                log.debug("scrcpy --help: %s", erro)
                ajuda = ""
            if not ajuda:
                return False            # tenta de novo na proxima
            guardado = (exe, ajuda)
            self._ajuda_scrcpy = guardado
        return bool(opcao) and opcao in guardado[1]

    def _perfil_mudou(self, nome: str) -> None:
        """Um atalho mudou o perfil: a janela remonta a tela, se estiver nela."""
        if self.ao_perfil_mudou is not None:
            try:
                self.ao_perfil_mudou(nome)
            except Exception as erro:
                log.debug("janela nao remontou: %s", erro)

    # -- consulta ------------------------------------------------------------

    def ativo(self, nome: str) -> bool:
        # No meio de uma troca o perfil continua "no ar" para todo o resto,
        # mesmo no instante em que o scrcpy velho ja caiu e o novo ainda nao
        # entrou na lista.
        if nome in self.trocando:
            return True
        sessao = self.sessoes.get(nome)
        return bool(sessao and sessao.rodando)

    def aplicando(self, nome: str) -> bool:
        """Um ajuste esta a caminho (marcado ou trocando) -- a janela diz."""
        return nome in self.trocando or nome in self._trocar_em

    def ocupado(self, nome: str) -> bool:
        """Esta no meio da partida (procurando o celular)."""
        return nome in self.ligando

    def situacao(self, nome: str) -> str:
        """'ligando', 'rodando' ou 'parado' -- o que a janela mostra."""
        if self.ocupado(nome):
            return "ligando"
        return "rodando" if self.ativo(nome) else "parado"

    def estado_do_icone(self) -> str:
        """
        O que o icone da bandeja deve mostrar. Com os dois ligados, o
        espelhamento ganha: e o que tem presenca na tela, entao e o que a
        pessoa espera ver representado.
        """
        if self.ativo("jogo"):
            return "jogo" + self._marca_pareado()
        if self.ativo("extensao"):
            return "extensao" + self._marca_pareado()
        if self.ativo("audio"):
            return "audio" + self._marca_pareado()
        return "parado" + self._marca_pareado()

    def _marca_pareado(self) -> str:
        """ "+par" com um celular lido (o icone ganha a borda verde); (01/out)
        "+notif" com notificacao do celular a ver (bolinha laranja)."""
        marca = "+par" if (self.celular or {}).get("id") else ""
        notif = getattr(self, "notif", None)
        if notif is not None and notif.contagem():
            marca += "+notif"
        return marca

    # -- acoes ---------------------------------------------------------------

    def alternar(self, nome: str) -> None:
        """Liga se estiver parado, desliga se estiver rodando."""
        if self.ativo(nome):
            self.desligar(nome)
        else:
            self.ligar(nome)

    def ligar(self, nome: str) -> None:
        """Sobe um perfil. Volta na hora: o trabalho acontece numa thread."""
        if self.ativo(nome) or self.ocupado(nome):
            return
        self.retomar_conexao()      # (07/out) ligar algo = quer o celular
        if not self.config.instalacao_ok:
            self.anotar("pedido: ligar '%s' -- RECUSADO, instalacao do scrcpy "
                        "nao encontrada" % nome)
            sistema.avisar(
                "Nao achei o adb.exe e o scrcpy.exe na pasta:\n\n%s\n\n"
                "Corrija o caminho no config.json."
                % (self.config.pasta_scrcpy or "(nao definida)"))
            return

        self.anotar("pedido: ligar '%s'" % nome)
        self.ligando.add(nome)
        self._avisar_mudanca()
        threading.Thread(target=self._partida, args=(nome,),
                         daemon=True, name="partida-%s" % nome).start()

    def _guardar_endereco(self, serial: str) -> None:
        """(r139) Pergunta ao celular o endereco dele na rede (numa thread) e
        guarda como reserva da proxima vez. (02/out) Tambem ao CONECTAR:
        antes so o espelhar/extensao guardavam, e quem so usava apps em
        janela ficava com um endereco velho (6 s de espera a cada abertura)."""
        def trabalho():
            try:
                endereco = celular.endereco_na_rede(self.config.adb_exe,
                                                    serial)
                if endereco:
                    self.config.lembrar_ip(endereco)
            except Exception as erro:
                log.debug("endereco do celular: %s", erro)

        threading.Thread(target=trabalho, daemon=True,
                         name="endereco").start()

    def _partida(self, nome: str) -> None:
        """Roda fora do laco: acha o celular e sobe o scrcpy."""
        t0 = time.monotonic()      # (08/out) o tempo do pedido ao scrcpy
        try:
            alvo = self._achar_celular()
            if not alvo:
                self.pedidos.put(("falhou", nome, TEXTO_SEM_CELULAR))
                return

            # (r139) O endereco de reserva e so para a PROXIMA vez: pergunta
            # ao celular em paralelo, sem segurar esta partida.
            self._guardar_endereco(alvo)

            # O icone da janela do espelhamento. Falhar aqui nao impede
            # nada: a sessao sobe com o icone padrao do scrcpy.
            desenho = icone.gravar_para_janela(caminhos.pasta_dados(),
                                               self.config.scrcpy_exe)

            perfil = self.perfil_para_subir(nome, alvo)
            sessao = Sessao(nome)
            if _tempo_de_tela_ms(perfil):
                # O tempo de tela de ANTES, guardado para a troca sem
                # desligar poder devolve-lo no fim (ver `_troca`).
                sessao.tempo_original = self._ler_tempo_de_tela(alvo)
            self._vez_de_lancar()
            self.anotar("'%s': scrcpy chamado %d ms depois do pedido" % (
                nome, (time.monotonic() - t0) * 1000))
            ok = sessao.iniciar(self.config.scrcpy_exe, alvo, perfil,
                                caminhos.pasta_relatorios(),
                                icone=desenho)
            if not ok:
                self.pedidos.put(("falhou", nome,
                                  "Nao consegui iniciar o scrcpy.\n\n"
                                  "Detalhes em relatorios\\log_%s.txt." % nome))
                return

            if self._sair:
                # O programa foi fechado enquanto esta partida corria: o
                # encerramento ja passou por aqui e nao sabe desta sessao.
                # Sem derrubar agora, ela sobraria orfa depois da saida.
                sessao.parar()
                return
            self.pedidos.put(("subiu", nome, sessao))
        except Exception as erro:  # nunca deixar a thread morrer calada
            log.exception("falha ao subir o perfil %s", nome)
            self.pedidos.put(("falhou", nome, "Falha inesperada: %s" % erro))

    def desligar(self, nome: str, esperar: bool = False) -> None:
        """
        Derruba um perfil.

        O FECHAMENTO RODA NUMA THREAD. Pedir ao scrcpy que saia com jeito pode
        levar ate 1,5 s, e este metodo roda na thread da janela: esperar aqui
        seria a janela congelada a cada "Desligar". O perfil sai da lista NA
        HORA, entao para todo o resto ele ja esta desligado.

        `esperar=True` so no encerramento do programa, que precisa ver as
        sessoes caidas antes de sair -- senao sobraria um scrcpy orfao.
        """
        if nome == "extensao":
            # O vigia sai ANTES do scrcpy: se o mouse estiver do lado do
            # celular, ele e devolvido ao PC enquanto a janelinha ainda existe.
            self._parar_borda()
        sessao = self.sessoes.pop(nome, None)
        self.pendentes.discard(nome)
        # Uma troca em andamento morre aqui: a resposta dela chega com senha
        # velha e o scrcpy novo e derrubado ao chegar.
        self._troca_senha.pop(nome, None)
        self.trocando.discard(nome)
        self._trocar_em.pop(nome, None)
        if sessao is not None:
            self.anotar("desligando '%s'" % nome)
            if esperar:
                sessao.parar()
            else:
                threading.Thread(target=sessao.parar, daemon=True,
                                 name="parar-%s" % nome).start()
            if nome.startswith(APP):
                self._app_fechou(nome, sessao, esperar=esperar)
            self.avisar_na_tela(nome, "desligou")
        self._avisar_mudanca()

    def religar(self, nome: str) -> None:
        """
        Derruba e sobe de novo, para a qualidade nova valer. Sem a
        notificacao de "desligou" no meio: para quem pediu, e uma acao so.

        Derrubar e subir acontecem NA MESMA THREAD, em sequencia: subir o novo
        antes de o velho soltar o celular faria os dois disputarem a captura.
        """
        sessao = self.sessoes.pop(nome, None)
        if sessao is None or self.ocupado(nome):
            return
        self.anotar("pedido: religar '%s'" % nome)
        if nome == "extensao":
            self._parar_borda()
        self.pendentes.discard(nome)
        # Para a janela, religar tambem e "aplicando o ajuste".
        self.trocando.add(nome)
        self.ligando.add(nome)
        self._avisar_mudanca()

        def trabalho():
            try:
                sessao.parar()
            except Exception:
                log.exception("falha ao derrubar %s para religar", nome)
            self._partida(nome)

        threading.Thread(target=trabalho, daemon=True,
                         name="religar-%s" % nome).start()

    # -- a borda (modo extensao) --------------------------------------------

    def _iniciar_borda(self, sessao) -> None:
        from . import borda as borda_mod
        pid = sessao.pid          # (r138) le uma vez so (ver Sessao.pid)
        if not borda_mod.disponivel() or not pid:
            return
        perfil = self.config.perfil("extensao")
        self.borda_estado = "fora"
        # A senha deste vigia: evento que chegar com outra senha e de um vigia
        # antigo (religar), atrasado na fila, e e ignorado.
        senha = object()
        self._senha_da_borda = senha
        self.borda = borda_mod.Borda(
            pid, perfil.get("titulo") or "scrcpy-f",
            perfil.get("borda") or {},
            # Da thread do vigia: so empilha. Quem age e o laco.
            lambda evento, detalhe="", s=senha: self.pedidos.put(
                ("borda", s, evento, detalhe)),
            faixa=self.faixa, ler_celular=self._dumpsys_input,
            acordar=self._acordar_celular, volume=self._volume_do_celular)
        self._serial_da_extensao = (sessao.linha[2] if len(sessao.linha) > 2
                                    and sessao.linha[1] == "-s" else "")
        self.borda.iniciar()
        self._conferir_radio()        # sem esperar o proximo giro do laco

    # -- radio do celular acordado --------------------------------------------
    #
    # RODAR BEM EM QUALQUER REDE (pedido dele, 21/set/2026). A sonda da rede
    # mostrou o padrao: a maior parte das idas e voltas em 2-10 ms e, de vez
    # em quando, uma de 141 ms. Um dos motivos classicos disso e o Wi-Fi do
    # celular COCHILAR entre pacotes para poupar bateria: o primeiro movimento
    # depois de uma pausa pega o radio dormindo e chega atrasado -- o engasgo.
    # Na extensao nao ha imagem correndo (e as vezes nem som), entao o trafego
    # para toda vez que a mao para. Um "ainda estou aqui" de poucos bytes a
    # cada 80 ms mantem o radio acordado; e o mesmo truque dos programas de
    # jogo por streaming. Custo: desprezivel.
    #
    # EM TODO MODO NO AR (pedido dele, 21/set/2026): a sonda do Wi-Fi mostrou
    # o celular parado com mediana de 86 ms e picos de 237 ms, e os modos de
    # Wi-Fi "baixa latencia"/"alto desempenho" o Android recusa pelo adb (so
    # root ou app). Entao o radio acordado deixou de ser so da extensao: liga
    # com QUALQUER sessao no ar (espelhar, so tela, so som) e desliga quando a
    # ultima cai. Quem decide e `_conferir_radio`, a cada giro do laco.
    RADIO_A_CADA_S = 0.08

    def _conferir_radio(self) -> None:
        serial = ""
        for sessao in list(self.sessoes.values()):
            linha = getattr(sessao, "linha", None) or []
            if sessao.rodando and len(linha) > 2 and linha[1] == "-s":
                serial = linha[2]
                break
        # (r140) No meio de uma partida ou troca a sessao sai da lista por
        # um instante: nao desliga o radio (nem fecha a conversa, que a
        # troca usa para passar o app de janela) por causa disso.
        if not serial and (self.ligando or self.trocando):
            return
        if serial == getattr(self, "_serial_do_radio", ""):
            return
        self._serial_do_radio = serial
        if serial:
            if getattr(self, "_radio_parar", None) is None:
                self._ligar_radio_acordado()
            self.anotar("radio acordado: ligado (%s)" % serial)
        else:
            self._desligar_radio_acordado()
            if self.borda is None:
                with self._trava_do_shell:
                    self._fechar_shell()
            self.anotar("radio acordado: desligado")

    def _ligar_radio_acordado(self) -> None:
        self._radio_parar = threading.Event()
        parar = self._radio_parar

        def laco():
            while not parar.wait(self.RADIO_A_CADA_S):
                # `:` e o comando que nao faz nada; a linha em si ja e o
                # pacote. Vai pela conversa aberta com o celular (a mesma do
                # acender a tela e do volume), sem abrir processo nenhum.
                self._mandar_ao_celular(":")

        threading.Thread(target=laco, daemon=True,
                         name="radio-acordado").start()

    def _desligar_radio_acordado(self) -> None:
        parar = getattr(self, "_radio_parar", None)
        if parar is not None:
            parar.set()
            self._radio_parar = None

    # (08/out, checagem no S22) A EXTENSAO poe no celular um teclado fisico
    # simulado, e com teclado fisico o Android NAO mostra o teclado da tela:
    # pegar o celular e tocar num campo ficava sem teclado. Enquanto o mouse
    # esta no PC, "mostrar o teclado da tela com teclado fisico" fica ligado;
    # no celular (digitando pelo PC), desligado. O valor dele volta ao parar.
    def _teclado_da_tela(self, mostrar) -> None:
        """mostrar: True/False, ou None = volta ao valor que o celular tinha.
        Numa linha so (o ultimo pedido vale), fora da thread de quem chama."""
        self._ime_quer = mostrar
        if getattr(self, "_ime_rodando", False):
            return
        self._ime_rodando = True
        serial = self._em_uso_pronto()
        feito = [object()]                 # o ultimo pedido aplicado

        def trabalho():
            try:
                while True:
                    quer = self._ime_quer
                    feito[0] = quer        # (sem celular conta como feito)
                    if not serial:
                        break
                    if getattr(self, "_ime_original", None) is None:
                        v = self._shell(serial, "settings get secure "
                                        "show_ime_with_hard_keyboard",
                                        espera=5).strip()
                        self._ime_original = v if v in ("0", "1") else "0"
                    valor = self._ime_original if quer is None else \
                        ("1" if quer else "0")
                    comando = ("settings put secure "
                               "show_ime_with_hard_keyboard %s" % valor)
                    # (08/out, relato dele: "demorou bastante") na VOLTA, com
                    # o campo ja guardado: a opcao e o toque num comando so,
                    # pela conversa aberta (sem esperar resposta) -- o
                    # celular confere se e o mesmo campo e se o teclado esta
                    # fechado, e toca
                    guardado = getattr(self, "_campo_guardado", None)
                    rapido = bool(quer and guardado and
                                  self.borda_estado == "fora")
                    resposta = ""
                    if rapido:
                        servido, (x, y) = guardado
                        comando += ("; d=$(dumpsys input_method 2>/dev/null);"
                                    " case \"$d\" in *\"mServedView=%s\"*) "
                                    "case \"$d\" in *\"mInputShown=true\"*) "
                                    "echo aberto;; *) input tap %d %d; "
                                    "echo tocou;; esac;; *) echo outro;; esac"
                                    % (servido.replace('"', ""), x, y))
                        resposta = self._shell(serial, comando,
                                               espera=5).strip()
                        self._ime_aplicado = valor
                    elif valor != getattr(self, "_ime_aplicado", None):
                        if not self._pela_conversa(serial, comando):
                            self._shell(serial, comando, espera=5)
                        self._ime_aplicado = valor
                    if quer is None:
                        self._ime_original = None
                        self._ime_aplicado = None
                    elif resposta == "tocou":
                        self.anotar("teclado: campo selecionado no celular -> "
                                    "teclado reaberto (na hora)")
                    elif quer and resposta != "aberto" and \
                            self._ime_quer is True:
                        self._reabrir_teclado(serial)  # outro campo: le agora
                    if self._ime_quer is quer or self._ime_quer == quer:
                        break
            except Exception:
                log.exception("teclado da tela: nao mudei")
            finally:
                self._ime_rodando = False
                # (08/out) um pedido que chegou bem na saida nao se perde
                if self._ime_quer != feito[0] and not self._sair:
                    self._teclado_da_tela(self._ime_quer)
        threading.Thread(target=trabalho, daemon=True,
                         name="teclado-da-tela").start()

    # (08/out, pedido dele: "tem como acelerar mais essa volta do teclado?")
    # O leitor da tela (uiautomator) leva ~2 s. Entao o lugar do campo e lido
    # ENQUANTO o mouse esta no celular (ao entrar, e de novo quando o campo
    # ativo muda -- pergunta leve a cada 1,5 s) e guardado; na volta, sendo o
    # mesmo campo, o toque e na hora.
    def _campo_servido(self, serial: str):
        """(campo ativo na tela do celular ou None, teclado aberto?)."""
        import re
        d = self._shell(serial, "dumpsys input_method 2>/dev/null | grep -E "
                        "'^ *mServedView=|mCurTokenDisplayId=|mInputShown='",
                        espera=6)
        servido = re.search(r"^\s*mServedView=(\S+)", d, re.M)
        if not servido or servido.group(1) == "null" or \
                "mCurTokenDisplayId=0" not in d:
            return None, False
        return servido.group(1), "mInputShown=true" in d

    def _lugar_do_campo(self, serial: str):
        """Onde tocar no campo com foco (o FIM dele), pelo uiautomator."""
        import re
        xml = self._shell(serial, "uiautomator dump --compressed "
                          "/data/local/tmp/scrcpyf-ui.xml >/dev/null 2>&1; "
                          "grep -o '<node[^>]*focused=\"true\"[^>]*>' "
                          "/data/local/tmp/scrcpyf-ui.xml | head -3",
                          espera=10)
        # (08/out, relato dele: "clicando no lugar errado no centro da tela")
        # a CAIXA DE TEXTO primeiro; outro elemento com foco so se nao houver
        nos = xml.splitlines()
        nos = [n for n in nos if "EditText" in n] + \
            [n for n in nos if "EditText" not in n]
        for no in nos:
            b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', no)
            editavel = "EditText" in no or 'focusable="true"' in no
            if not b or not editavel:
                continue
            x1, y1, x2, y2 = (int(v) for v in b.groups())
            if x2 - x1 < 4 or y2 - y1 < 4:
                continue
            x = max(x1 + 2, x2 - 16) if x2 - x1 > 40 else (x1 + x2) // 2
            return x, (y1 + y2) // 2
        return None

    def _vigia_campo(self, serial: str) -> None:
        """Com o mouse no celular: guarda o lugar do campo ativo."""
        visto = None
        # (08/out, relato dele: o toque caia no meio da tela) com o mouse no
        # celular o teclado da tela SOME e a caixa DESCE; o lugar lido antes
        # disso era o de cima. So le com o teclado fechado e a tela parada
        # (o mesmo campo, fechado, por 0,8 s)
        estavel_desde, ultimo = None, None
        while not self._sair and self.borda_estado == "dentro":
            try:
                servido, aberto = self._campo_servido(serial)
                agora = time.monotonic()
                if not servido or aberto:
                    estavel_desde, ultimo = None, None
                    if not servido:
                        visto = None
                elif servido != ultimo:
                    ultimo, estavel_desde = servido, agora
                elif servido != visto and agora - estavel_desde >= 0.8:
                    lugar = self._lugar_do_campo(serial)
                    if lugar:
                        self._campo_guardado = (servido, lugar)
                        visto = servido
            except Exception as erro:
                self.anotar("teclado: vigia do campo falhou (%s)" % erro)
                return
            for _i in range(7):          # (08/out) a cada 0,7 s
                if self._sair or self.borda_estado != "dentro":
                    return
                time.sleep(0.1)

    def _garantir_vigia_campo(self) -> None:
        # cada entrada le de novo (o lugar da vez anterior pode ter mudado)
        self._campo_guardado = None
        serial = self._em_uso_pronto()
        t = getattr(self, "_campo_thread", None)
        if not serial or (t is not None and t.is_alive()):
            return
        self._campo_thread = threading.Thread(
            target=self._vigia_campo, args=(serial,), daemon=True,
            name="teclado-campo")
        self._campo_thread.start()

    def _reabrir_teclado(self, serial: str) -> None:
        """(08/out, pedido dele: "quando eu voltar o mouse pro pc e uma caixa
        de texto ainda tiver selecionada o teclado deve voltar a aparecer")
        Ligar a opcao nao reabre o teclado de um campo ja selecionado, e o
        Android nao tem comando para "mostrar o teclado". Entao: so se ha um
        campo ATIVO na tela do celular (mServedView, tela 0; pergunta leve),
        o programa toca no FIM dele -- o teclado abre e o cursor vai ao fim.
        O lugar vem do guardado (mesmo campo) ou, senao, do leitor da tela."""
        servido, aberto = self._campo_servido(serial)
        if not servido or aberto:
            return
        guardado = getattr(self, "_campo_guardado", None)
        if guardado and guardado[0] == servido:
            lugar, como = guardado[1], "na hora"
        else:
            lugar, como = self._lugar_do_campo(serial), "lido agora"
        if not lugar or self.borda_estado != "fora":
            return                       # sem lugar, ou o mouse ja voltou
        self._shell(serial, "input tap %d %d" % lugar, espera=5)
        self.anotar("teclado: campo selecionado no celular -> teclado "
                    "reaberto (%s)" % como)

    def _parar_borda(self) -> None:
        # O radio NAO desliga aqui: outro modo pode estar no ar. Quem cuida e
        # o `_conferir_radio` (a conversa fechada abaixo reabre sozinha).
        self.borda_calibracao = ""
        if self.borda is not None:
            self.borda.parar()
            self.borda = None
            self._teclado_da_tela(None)      # (08/out) o valor dele de volta
        with self._trava_do_shell:
            self._fechar_shell()
        self.borda_estado = "fora"

    def previa_da_borda(self, mostrar: bool, borda: dict | None = None) -> None:
        """
        A janela esta mostrando a aba Extensao: o risquinho aparece no lugar
        escolhido, para a pessoa ver na tela de verdade onde ele fica. Com a
        extensao ligada quem manda no risquinho e o vigia; a previa so vale
        com ela desligada.
        """
        if self.faixa is None:
            return
        ret = None
        if mostrar:
            from . import faixa as faixa_mod, monitores as mon
            # ARRASTAR O CELULAR NO MAPA passa por aqui a cada pixel, e
            # perguntar os monitores ao Windows custa caro (21/set/2026):
            # a lista vale por um segundo -- monitor nao aparece e some
            # nesse intervalo.
            agora = time.monotonic()
            lista, quando = getattr(self, "_monitores_guardados", (None, 0.0))
            if not lista or agora - quando > 1.0:
                lista = mon.listar(estrito=True)
                self._monitores_guardados = (lista, agora)
            if lista:
                if borda is None:
                    borda = self.config.perfil("extensao").get("borda") or {}
                ret = faixa_mod.retangulo(mon.trecho(lista, borda))
        self.faixa.pedir("previa", ret)

    def _acertar_o_som_da_extensao(self) -> None:
        """
        Uma vez: o som da extensao fica em Opus, 128 kb/s e 50 ms de atraso
        (pedido dele, 21/set/2026 -- em 20/set tinha ficado em 20 ms e ele
        pediu para voltar a 50). So mexe em quem esta no valor de fabrica
        anterior: escolha feita a mao nao se perde.
        """
        try:
            audio = self.config.perfil("extensao").get("audio") or {}
            de_fabrica = (str(audio.get("codec")) == "opus"
                          and str(audio.get("bitrate")).upper() == "128K"
                          and int(audio.get("buffer_ms") or 0) in (20, 50))
            if de_fabrica and int(audio.get("buffer_ms") or 0) != 50:
                audio["buffer_ms"] = 50
                self.config.gravar()
        except Exception:
            log.exception("nao consegui acertar o som da extensao")

    def _tirar_tela_ligada_da_extensao(self) -> None:
        """
        A chave "Manter a tela do celular ligada" existiu por uma rodada e
        saiu (pedido dele, 19/set/2026: fica so o acender quando o mouse
        chega, sempre). Quem ligou a chave ficou com o tempo de tela esticado
        gravado no config; aqui ele volta a zero, uma vez, para a extensao
        nao continuar mexendo no tempo de tela do celular.
        """
        try:
            sessao = self.config.perfil("extensao").get("sessao") or {}
            if float(sessao.get("tempo_tela_s") or 0) > 0:
                sessao["tempo_tela_s"] = 0
                self.config.gravar()
        except Exception:
            log.exception("nao consegui limpar o tempo de tela da extensao")

    # -- o que sobe de verdade ------------------------------------------------

    def conexao_de(self, serial: str = "") -> str:
        """(r196) "cabo" ou "sem_fio" -- do serial que a sessao vai usar; sem
        serial, a do celular em uso (senao a preferida)."""
        if serial:
            return "cabo" if celular.e_cabo(serial) else "sem_fio"
        return self.conexao_em_uso() or self.conexao_preferida()

    def perfil_para_subir(self, nome: str, serial: str = "") -> dict:
        """
        O perfil como o scrcpy vai recebe-lo. ESPELHAR E SOM VIRARAM UM MODO
        (visual novo, 21/set/2026): o perfil "jogo" ganhou `conteudo` --
        "ambos", "som" ou "imagem" -- e aqui ele vira as opcoes de verdade.
        No "so som" a pessoa esta jogando NO celular: nada de apagar a tela
        nem mexer no tempo dela, e sem janela nem controle.
        """
        import copy
        from . import qualidade
        perfil = copy.deepcopy(self.config.perfil(nome))
        # QUALIDADE UNICA (23/set/2026): a de OPCOES > qualidade vale para
        # todos os modos, por cima do que o perfil tiver.
        # (r196) ...do CONJUNTO DA CONEXAO que a sessao vai usar.
        # (08/out, rework) O NIVEL (imagem) e o SOM: os do modo, senao os
        # gerais -- iguais no cabo e no sem fio.
        q = self.config.qualidade
        qualidade.aplicar_no_perfil(
            perfil, qualidade.video_do_nivel(qualidade.nivel_de(perfil, q)),
            qualidade.audio_do_som(qualidade.som_de(perfil, q)))
        self._resolucao_no_perfil(perfil)                   # (r189)
        # (02/out, relato do amigo: Redmi Note 8 Pro) Android 10 ou mais
        # velho nao manda som; na extensao (sem imagem) o scrcpy ficava sem
        # nada para receber e caia na hora ("Demuxer error").
        sdk = (self.celular or {}).get("sdk")
        if nome == "extensao" and isinstance(sdk, int) and sdk < 30:
            perfil.setdefault("audio", {})["ligado"] = False
        if nome != "jogo":
            return perfil
        conteudo = conteudo_do(perfil)
        video = perfil.setdefault("video", {})
        audio = perfil.setdefault("audio", {})
        if conteudo == "som":
            video["ligado"] = False
            audio["ligado"] = True
            audio["exigir"] = True
            perfil.setdefault("controle", {})["teclado_mouse"] = False
            perfil["sessao"] = dict(perfil.get("sessao") or {},
                                    apagar_tela=False, tempo_tela_s=0,
                                    sem_protetor_de_tela=False)
            perfil["titulo"] = "Celular - som"
        elif conteudo == "imagem":
            video["ligado"] = True
            audio["ligado"] = False
        else:
            video["ligado"] = True
            audio["ligado"] = True
        return perfil

    # -- a marca na tela (faixa) ---------------------------------------------

    def aplicar_estilo_da_faixa(self) -> None:
        """Cor, transparencia, espessura e brilho da marca, do config."""
        if self.faixa is None:
            return
        borda = self.config.perfil("extensao").get("borda") or {}
        try:
            self.faixa.definir_estilo(
                cor=str(borda.get("cor") or "#FF5A1F"),
                transparencia=float(borda.get("transparencia", 0.45)),
                espessura=int(borda.get("espessura", 3)),
                brilhar=bool(borda.get("brilhar", True)))
        except Exception:
            log.exception("nao consegui aplicar o estilo da faixa")

    def _abrir_configurar(self, no_celular: bool = False) -> None:
        """
        Pedido de parear o celular (menu da bandeja, ou o celular que nao
        apareceu). Desde o visual novo (v0.6.0) o parear mora na propria
        janela; o Configurar separado saiu do programa.
        """
        if self.ao_parear is not None:
            self.anotar("pedido: parear (na janela)")
            self.ao_parear()
        else:
            self.anotar("pedido: parear -- SEM janela, nada a abrir")

    # -- o celular conectado: modelo e bateria -----------------------------

    VIGIA_CONEXAO_S = 1.5
    VIGIA_CONEXAO_PARADO_S = 3.0
    PING_S = 8.0            # (r163) de quanto em quanto o celular e cutucado
    PING_ESPERA_S = 4.0     # sem resposta nisso = falhou

    def _vigia_conexao(self) -> None:
        """
        (r161/r162) CONEXAO EM TEMPO REAL (pedido dele, 25/set/2026: desligou
        a depuracao sem fio e o programa seguiu dizendo "conectado").
        Pergunta ao SERVIDOR do adb (no PC, sem falar com o celular) quem
        esta conectado, a cada VIGIA_CONEXAO_S; mudou -> pedido
        "dispositivos". O r161 usava o `adb track-devices`, mas a saida dele
        pela linha de comando nao veio no formato esperado e nada chegava
        (teste dele): a pergunta simples e a que funciona em todo adb.
        """
        import subprocess
        sem_janela = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        anterior = None
        falhas = 0
        ultimo_ping = 0.0
        sem_resposta = 0
        self.anotar("vigia da conexao: no ar")
        while not self._sair:
            if self.adb_pausado:
                time.sleep(self.VIGIA_CONEXAO_S)
                continue
            try:
                r = subprocess.run([str(self.config.adb_exe), "devices"],
                                   capture_output=True, timeout=10,
                                   creationflags=sem_janela)
                texto = (r.stdout or b"").decode("utf-8", "replace")
                vistos = {}
                for linha in texto.replace("\r", "").splitlines():
                    partes = linha.split("\t")
                    if len(partes) >= 2 and partes[0].strip():
                        vistos[partes[0].strip()] = partes[1].strip()
                falhas = 0
                if vistos != anterior:
                    anterior = vistos
                    self.pedidos.put(("dispositivos", vistos))
                # (r163) O CELULAR RESPONDE? (pedido dele: "se o celular nao
                # responder, considera desconectado"). O adb pode seguir
                # listando um celular sem fio que ja sumiu da rede. A cada
                # PING_S, um "echo" nele; 2 sem resposta -> desconectado, e
                # o adb solta a conexao morta (volta sozinho se ele voltar).
                serial = (self.celular or {}).get("serial", "")
                agora = time.monotonic()
                if serial and vistos.get(serial) == "device" and \
                        agora - ultimo_ping >= self.PING_S:
                    ultimo_ping = agora
                    try:
                        p = subprocess.run(
                            [str(self.config.adb_exe), "-s", serial, "shell",
                             "echo ok"], capture_output=True,
                            timeout=self.PING_ESPERA_S,
                            creationflags=sem_janela)
                        vivo = b"ok" in (p.stdout or b"")
                    except Exception:
                        vivo = False
                    sem_resposta = 0 if vivo else sem_resposta + 1
                    if sem_resposta >= 2:
                        sem_resposta = 0
                        self.pedidos.put(("sem_resposta", serial))
                        if ":" in serial or "_adb-tls-connect" in serial:
                            try:
                                subprocess.run(
                                    [str(self.config.adb_exe), "disconnect",
                                     serial], capture_output=True, timeout=5,
                                    creationflags=sem_janela)
                            except Exception:
                                pass
            except Exception as erro:
                falhas += 1
                if falhas in (1, 10):
                    self.anotar("vigia da conexao: adb nao respondeu (%s)"
                                % erro)
            # (02/out, revisao) So na bandeja, sem nada no ar: 3 s (eram
            # ~2.400 adb.exe por hora a 1,5 s). Janela aberta ou algo
            # rodando/subindo: o tempo real de sempre.
            rapido = (self.sessoes or self.ligando or
                      getattr(self, "janela_na_tela", True))
            time.sleep(self.VIGIA_CONEXAO_S if rapido else
                       self.VIGIA_CONEXAO_PARADO_S)

    def _dispositivos(self, vistos: dict) -> None:
        """Do laco: a lista de celulares do adb mudou."""
        prontos = {s for s, e in vistos.items() if e == "device"}
        antes = getattr(self, "_prontos", None)
        self._prontos = prontos
        self._ultimos_vistos = dict(vistos)
        if self.conexao_pausada:
            # (07/out) "desconectar tudo": ninguem entra sozinho (nem o
            # cabo ligado) ate ele pedir de novo
            if prontos != antes:
                self._avisar_mudanca()
            return
        self._outro_celular &= prontos     # saiu e voltou: vale olhar de novo
        atual = (self.celular or {}).get("serial", "")
        if atual and atual not in prontos:
            self.anotar("celular DESCONECTADO (%s)" % atual)
            self.celular = {}
            self._cel_preparado = None
            self._lendo_celular = False
            self._avisar_mudanca()
            atual = ""
        if celular.PREFERENCIA == "sem_fio" and prontos != antes:
            # Cabo que apareceu, OU sem fio que caiu com o cabo ja ligado
            # (03/out, teste no S22: a porta fechou -- `adb usb`, religar a
            # depuracao -- e o cabo nem saiu da lista; ninguem reabria).
            ja = antes or set()
            caiu_sem_fio = any(not celular.e_cabo(s) for s in ja - prontos)
            for s in sorted(prontos):
                if celular.e_cabo(s) and (s not in ja or caiu_sem_fio):
                    self._abrir_sem_fio(s)
                    break
        # (07/out, relato dele) Abrindo o sem fio pelo cabo, o cabo NAO entra
        # em uso antes: tudo o que subisse por ele (leitura, notificacoes,
        # icones) morria no `tcpip` e o celular parecia sumir. Quando o sem
        # fio fica pronto ele entra direto; se nao ficar, o cabo entra
        # (`_sem_fio_terminou`).
        if not any(celular.e_cabo(s) for s in prontos) and \
                self.estado_sem_fio()[0] in ("pronto", "falhou"):
            self._sem_fio_estado = None      # tirou o cabo: o recado sai
        so_cabo = prontos and all(celular.e_cabo(s) for s in prontos)
        esperar = so_cabo and getattr(self, "_abrindo_sem_fio", False)
        if not atual and prontos and prontos != antes and not esperar:
            escolhido = celular.escolher_serial(
                "\n".join("%s\tdevice" % s for s in sorted(prontos)))
            if escolhido:
                self.anotar("celular CONECTADO (%s)" % escolhido)
                self._ler_o_celular(escolhido)
                self._guardar_endereco(escolhido)
        elif atual and prontos != antes:
            self._reavaliar_conexao()
        if prontos != antes:
            # A janela mostra se o cabo esta la (seletor do parear).
            self._avisar_mudanca()

    # -- (r192) seletor de conexao ------------------------------------------
    # Pedido dele (30/set/2026): escolher cabo ou sem fio SEM PARAR O ADB.
    # A troca so muda qual conexao (ja de pe) o programa usa: nunca
    # kill-server, nunca `tcpip`. O que esta aberto segue na conexao em que
    # nasceu (o scrcpy nao migra); o que abrir depois usa a nova.

    CONEXOES = ("sem_fio", "cabo")

    def conexao_preferida(self) -> str:
        v = self.config.opcoes.get("conexao")
        return v if v in self.CONEXOES else "sem_fio"

    def definir_conexao(self, valor: str) -> None:
        if valor not in self.CONEXOES:
            return
        self.config.opcoes["conexao"] = valor
        self.config.gravar()
        celular.PREFERENCIA = valor
        self.anotar("conexao preferida: %s" % valor)
        self._reavaliar_conexao()
        self._avisar_mudanca()

    def conexao_em_uso(self) -> str:
        """"cabo", "sem_fio" ou "" (nenhum celular)."""
        serial = (self.celular or {}).get("serial", "")
        if not serial:
            return ""
        return "cabo" if celular.e_cabo(serial) else "sem_fio"

    def conexoes_de_pe(self) -> set:
        """Quais conexoes o adb tem prontas agora (de qualquer celular)."""
        prontos = getattr(self, "_prontos", None) or set()
        return {"cabo" if celular.e_cabo(s) else "sem_fio" for s in prontos}

    def _reavaliar_conexao(self) -> None:
        """Com um celular em uso: se a conexao preferida apareceu (ou a
        preferencia mudou), passa a usar ela. Le o celular por ela antes;
        a troca so vale se for o MESMO celular (ver o pedido "celular")."""
        atual = (self.celular or {}).get("serial", "")
        prontos = (getattr(self, "_prontos", None) or set()) - \
            self._outro_celular
        if not atual or atual not in prontos:
            return
        escolhido = celular.escolher_serial(
            "\n".join("%s\tdevice" % s for s in sorted(prontos)))
        if escolhido and escolhido != atual:
            self.anotar("conexao: trocando %s -> %s" % (atual, escolhido))
            self._lendo_celular = False
            self._ler_o_celular(escolhido)

    # -- (07/out, pedido dele) DESCONECTAR TUDO: segurar 2 s o botao da
    # conexao na barra. Para tudo, solta as conexoes sem fio e o programa
    # fica desconectado (nem o cabo ligado entra sozinho) ate ele clicar no
    # botao de novo ou usar o PAREAR.

    conexao_pausada = False

    def desconectar_tudo(self, desparear: bool = False) -> None:
        """(08/out, pedido dele: o "desparear" do PAREAR com duas opcoes)
        `desparear` = alem de desconectar, o celular SAI do sem fio (`adb usb`:
        a porta 5555 fecha nele) e o programa esquece o endereco: so volta
        pareando de novo (cabo ou codigo). Sem ele, fica pareado: o clique na
        conexao ou o PAREAR liga de novo."""
        self.anotar("pedido: %s" % ("desparear (desconecta e esquece)"
                                    if desparear else
                                    "desconectar tudo (fica desconectado)"))
        serial = (self.celular or {}).get("serial", "")
        self.conexao_pausada = True
        for nome in list(self.sessoes) + list(self.ligando):
            try:
                self.desligar(nome)
            except Exception:
                log.exception("desconectar tudo: %s", nome)
        self._abrindo_sem_fio = False
        self._sem_fio_estado = None
        if self.celular:
            self.anotar("celular DESCONECTADO (%s, a pedido)"
                        % self.celular.get("serial", ""))
        self.celular = {}
        self._cel_preparado = None
        self._lendo_celular = False
        adb = self.config.adb_exe
        if desparear and self.config.ip_reserva:
            self.anotar("desparear: esquecido o endereco %s"
                        % self.config.ip_reserva)
            self.config.ip_reserva = ""
            self.config.gravar()

        def soltar():
            if desparear and serial:
                saida = celular._rodar([adb, "-s", serial, "usb"], espera=8)
                self.anotar("desparear: sem fio desligado no celular (%s)"
                            % (saida or "").strip()[:80])
            celular._rodar([adb, "disconnect"], espera=8)
        threading.Thread(target=soltar, daemon=True,
                         name="desconectar").start()
        self._conferir_o_celular()       # notificacoes e bateria param ja
        self._avisar_mudanca()

    def retomar_conexao(self) -> None:
        """Volta a conectar sozinho (o clique no botao, ou o PAREAR)."""
        if not self.conexao_pausada:
            return
        self.anotar("pedido: voltar a conectar")
        self.conexao_pausada = False
        vistos = getattr(self, "_ultimos_vistos", None) or {}
        self._prontos = set()            # tudo "aparece" de novo
        self._sem_fio_tentado = {}
        self._dispositivos(vistos)
        if not self.celular and self.config.ip_reserva:
            # o sem fio foi solto no desconectar: liga de novo no ultimo
            adb, ip = self.config.adb_exe, self.config.ip_reserva
            threading.Thread(target=lambda: celular._rodar(
                [adb, "connect", "%s:5555" % ip], espera=8),
                daemon=True, name="reconectar").start()
        self._avisar_mudanca()

    SEM_FIO_TENTATIVAS = 3       # (07/out) sozinho: ate 3 vezes, 6 s entre

    def _abrir_sem_fio(self, serial: str, a_pedido: bool = False) -> None:
        """
        (03/out, pedido dele depois do teste do amigo: so plugar o cabo nao
        abria o sem fio, e o botao do PAREAR nao e obvio) Preferindo o sem
        fio, o cabo que aparece abre a conexao sem fio sozinho, numa thread.
        O `tcpip` derruba o cabo por um instante e ele "aparece" de novo:
        o mesmo cabo so comeca de novo depois de um minuto.

        (07/out, relato dele: "plugo, tiro, plugo de novo e clico") Uma
        tentativa so, curta e calada, falhava e ficava assim: agora sao ate
        SEM_FIO_TENTATIVAS, cada uma esperando o celular responder, e o fim
        aparece na tela ("pode tirar o cabo" ou o motivo). `a_pedido` = o
        botao do PAREAR: comeca na hora, mesmo com algo aberto pelo cabo.
        """
        agora = time.monotonic()
        tentados = getattr(self, "_sem_fio_tentado", None)
        if tentados is None:
            tentados = self._sem_fio_tentado = {}
        if getattr(self, "_abrindo_sem_fio", False):
            return
        if not a_pedido and agora - tentados.get(serial, -999.0) < 60:
            return
        tentados[serial] = agora
        self._abrindo_sem_fio = True
        adb = self.config.adb_exe
        sem_fio = [s for s in (getattr(self, "_prontos", None) or set())
                   if not celular.e_cabo(s)]
        if not sem_fio or a_pedido:      # (cabo de carregar: sem recado)
            self._sem_fio_estado = ("abrindo", "abrindo a conexão sem fio "
                                    "pelo cabo…")
            self._avisar_mudanca()
        pode_reiniciar = a_pedido or not (self.sessoes or self.ligando)

        def trabalho():
            from . import conexao
            ip, como, alvo = "", "", ""
            try:
                # Este celular ja tem sem fio de pe? (mesmo ro.serialno)
                _m, id_cabo = conexao._identidade(adb, serial)
                for s in sem_fio:
                    if id_cabo and conexao._identidade(adb, s)[1] == id_cabo \
                            and conexao._responde(adb, s):
                        ip, como, alvo = s, "ja estava de pe", s
                        break
                vez = 0
                while not ip and vez < self.SEM_FIO_TENTATIVAS and \
                        not self._sair:
                    vez += 1
                    ip, como = conexao.abrir_sem_fio(adb, serial,
                                                     pode_reiniciar)
                    self.anotar("cabo abre o sem fio (%d/%d): %s (%s)" % (
                        vez, self.SEM_FIO_TENTATIVAS,
                        "OK " + ip if ip else "nao", como))
                    if ip or como in ("celular sem Wi-Fi",) or \
                            "tcpip ficou para depois" in como:
                        break
                    time.sleep(6)
                if ip and not alvo:
                    alvo = "%s:%d" % (ip, conexao.PORTA_SEM_FIO)
                    self.config.lembrar_ip(ip)
            except Exception as erro:
                como = str(erro)
                self.anotar("cabo abre o sem fio: falhou (%s)" % erro)
            finally:
                self.pedidos.put(("sem_fio_fim", serial, alvo, como))

        threading.Thread(target=trabalho, daemon=True,
                         name="abrir-sem-fio").start()

    def abrir_sem_fio_agora(self) -> bool:
        """(07/out) O botao "abrir sem fio" do PAREAR: o cabo ligado agora
        abre o sem fio na hora (sem esperar o minuto). False = sem cabo."""
        cabos = sorted(s for s in (getattr(self, "_prontos", None) or set())
                       if celular.e_cabo(s))
        if not cabos:
            return False
        self.anotar("pedido: abrir o sem fio pelo cabo (%s)" % cabos[0])
        self._abrir_sem_fio(cabos[0], a_pedido=True)
        return True

    def estado_sem_fio(self) -> tuple[str, str]:
        """("abrindo"|"pronto"|"falhou"|"", texto) -- para a tela."""
        return getattr(self, "_sem_fio_estado", None) or ("", "")

    def _sem_fio_terminou(self, serial: str, alvo: str, como: str) -> None:
        """Na thread do programa: o fim da abertura do sem fio. `alvo` = o
        serial sem fio que respondeu (vazio = nao abriu)."""
        self._abrindo_sem_fio = False
        if alvo and como == "ja estava de pe":
            # cabo so para carregar, com o sem fio ja em uso: nada a dizer
            self._sem_fio_estado = None
            self._avisar_mudanca()
            return
        if alvo:
            self._sem_fio_estado = ("pronto", "sem fio pronto: pode tirar o "
                                    "cabo.")
            # entra direto pelo sem fio: o vigia pode ainda nao te-lo visto
            # (e a leitura de quem nao esta na lista e descartada)
            self._prontos = set(getattr(self, "_prontos", None) or ()) | {alvo}
            atual = (self.celular or {}).get("serial", "")
            if not atual or celular.e_cabo(atual):
                self._lendo_celular = False
                self.anotar("conexao: sem fio pronto, entrando por %s" % alvo)
                self._ler_o_celular(alvo)
            if self.bandeja is not None and self.config.opcao("notificacoes"):
                self.bandeja.notificar("Sem fio pronto",
                                       "Pode tirar o cabo: o celular segue "
                                       "conectado pelo Wi-Fi.")
        else:
            motivo = {"celular sem Wi-Fi": "o celular não está no wi-fi"}.get(
                como, "não respondeu (o celular está na mesma rede do pc?)"
                if "nao respondeu" in como else como or "falhou")
            if "tcpip ficou para depois" in como:
                motivo = "algo está aberto pelo cabo; feche e tente de novo"
            self._sem_fio_estado = ("falhou", "o sem fio não abriu: %s."
                                    % motivo)
            # o cabo entra em uso (estava esperando o sem fio)
            atual = (self.celular or {}).get("serial", "")
            prontos = getattr(self, "_prontos", None) or set()
            if not atual and serial in prontos:
                self.anotar("celular CONECTADO (%s, pelo cabo)" % serial)
                self._ler_o_celular(serial)
        self._avisar_mudanca()

    def _ler_o_celular(self, serial: str) -> None:
        """
        Modelo, versao, id e bateria do celular, numa thread e numa pergunta
        SO ao adb (antes eram cinco, uma atras da outra). A resposta volta
        pela fila: nome embaixo do PAREAR, icone verde, cache (ver
        `_preparar_celular`).
        """
        if not serial or getattr(self, "_lendo_celular", False):
            return
        self._lendo_celular = True
        self._celular_lido_em = time.monotonic()

        def trabalho():
            info = {"serial": serial}
            try:
                saida = self._adb_shell(
                    serial, "echo m=$(getprop ro.product.model); "
                    "echo s=$(getprop ro.build.version.sdk); "
                    "echo r=$(getprop ro.build.version.release); "
                    "echo i=$(getprop ro.serialno); "
                    "dumpsys battery | grep -E "
                    "'^ *(level|AC powered|USB powered):'; "
                    # (r184) tela e densidade de verdade, e o maior tamanho
                    # que o codificador de video transmite (formatos.py).
                    "wm size; wm density; echo @codecs; "
                    "grep -h -E '<MediaCodec |<Type |<Limit name=\"size\"|"
                    "</MediaCodec' /vendor/etc/media_codecs*.xml "
                    "/odm/etc/media_codecs*.xml /system/etc/media_codecs*.xml "
                    "2>/dev/null", tempo=8)
                import re as _re
                from . import formatos
                texto = saida.stdout.decode("utf-8", "replace")
                texto, _, codecs = texto.partition("@codecs")
                tam = {}
                for linha in texto.splitlines():
                    m = _re.match(r"\s*(Physical|Override) (size|density):"
                                  r"\s*(\d+)(?:x(\d+))?", linha)
                    if m:
                        tam[(m.group(1), m.group(2))] = m.groups()[2:]
                tela = tam.get(("Override", "size")) or \
                    tam.get(("Physical", "size"))
                if tela and tela[1]:
                    info["tela_cel"] = (int(tela[0]), int(tela[1]))
                dens = tam.get(("Override", "density")) or \
                    tam.get(("Physical", "density"))
                if dens:
                    info["dpi"] = int(dens[0])
                lim = formatos.ler_limite_do_codificador(codecs)
                if lim:
                    info["limite_video"] = lim
                for linha in texto.splitlines():
                    linha = linha.strip()
                    chave, _, valor = linha.partition("=")
                    valor = valor.strip()
                    if chave == "m" and valor:
                        info["modelo"] = valor
                    elif chave == "s" and valor.isdigit():
                        info["sdk"] = int(valor)
                    elif chave == "r" and valor:
                        info["android"] = valor
                    elif chave == "i":
                        ident = _re.sub(r"[^A-Za-z0-9_-]", "", valor)[:40]
                        if ident:
                            info["id"] = ident
                    elif linha.startswith("level:"):
                        info["bateria"] = int(linha.split(":", 1)[1])
                    elif linha.startswith(("AC powered:", "USB powered:")):
                        if linha.split(":", 1)[1].strip() == "true":
                            info["carregando"] = True
                if "id" not in info and info.get("modelo"):
                    info["id"] = _re.sub(r"[^A-Za-z0-9_-]", "",
                                         info["modelo"])
            except Exception as erro:
                log.info("nao li o celular: %s", erro)
            self.pedidos.put(("celular", info))

        threading.Thread(target=trabalho, daemon=True,
                         name="ler-celular").start()

    def ler_celular_agora(self, serial: str = "") -> None:
        """Logo depois de parear: acha o celular (o endereco que o parear
        guarda nem sempre e o que o adb usa) e le tudo dele. (r193) Com
        `serial` (o "usar" da lista), e ESSE celular, mesmo com outro em
        uso."""
        self.retomar_conexao()           # (07/out) pediu: volta a conectar
        if serial:
            self._escolha_manual = serial
            self._outro_celular.discard(serial)
            # (07/out) o sem fio que o cabo acabou de abrir (e que respondeu)
            # pode ainda nao ter sido visto pelo vigia: sem isto a leitura
            # dele era descartada
            if not celular.e_cabo(serial):
                self._prontos = set(getattr(self, "_prontos", None) or ()) \
                    | {serial}

        def achar():
            alvo = serial or celular.achar(self.config.adb_exe,
                                           self.config.ip_reserva)
            if alvo:
                self._lendo_celular = False
                self._ler_o_celular(alvo)

        threading.Thread(target=achar, daemon=True, name="achar-lendo").start()

    def carregar_ultimo_cache(self) -> None:
        """Ao abrir, antes de o celular responder: a lista e os icones do
        ultimo celular usado aparecem na hora (pedido dele, 23/set/2026)."""
        import json
        try:
            base = caminhos.pasta_dados() / "celulares"
            arquivos = sorted(base.glob("*/apps.json"),
                              key=lambda a: a.stat().st_mtime, reverse=True)
        except Exception:
            return
        for arquivo in arquivos[:1]:
            try:
                dados = json.loads(arquivo.read_text(encoding="utf-8"))
            except Exception:
                continue
            if _tem_app(dados.get("apps")):
                self._ultimo_id = arquivo.parent.name
                self.apps_do_celular = [tuple(a) for a in dados["apps"]]
                self.apps_versao = getattr(self, "apps_versao", 0) + 1
                self.anotar("cache %s: %d apps ao abrir" % (
                    self._ultimo_id, len(self.apps_do_celular)))

    # BATERIA NA HORA (pedido dele, 23/set/2026: "atualizar so quando mudar
    # no celular"). Um laco leve NO CELULAR le a bateria a cada 2 s e so
    # escreve quando o numero ou o carregando muda; o PC so recebe (e so
    # repinta) nessas horas. Vale embaixo do PAREAR e na tela status.
    # (07/out, pedido dele) + a TEMPERATURA da bateria, relida a cada 45
    # voltas (90 s): muda devagar e cada leitura nova repintaria o rodape.
    BATERIA_LACO = (
        "m=scrcpyf_bateria; B=/sys/class/power_supply/battery; u=; i=0; "
        "t=; while :; do if [ -r $B/capacity ]; then c=$(cat $B/capacity); "
        "s=$(cat $B/status); else d=$(dumpsys battery); "
        "c=$(echo \"$d\" | grep -m1 ' level:' | tr -dc 0-9); "
        "s=$(echo \"$d\" | grep -m1 ' status:' | tr -dc 0-9); fi; "
        "if [ $((i%45)) -eq 0 ]; then if [ -r $B/temp ]; then "
        "t=$(cat $B/temp); else t=$(dumpsys battery | grep -m1 "
        "' temperature:' | tr -dc 0-9); fi; fi; i=$((i+1)); "
        "if [ \"$c $t $s\" != \"$u\" ]; then echo \"@b $c $t $s\"; "
        "u=\"$c $t $s\"; fi; sleep 2; done")
    BATERIA_MATAR = "pkill -f 'scrcpyf_bateri[a]' ; true"

    def _vigiar_bateria(self, serial: str) -> None:
        """Do laco: mantem o vigia da bateria no celular conectado."""
        import subprocess
        proc = getattr(self, "_bat_proc", None)
        vivo = proc is not None and proc.poll() is None
        if vivo and getattr(self, "_bat_serial", "") == serial:
            return
        if vivo:
            try:
                proc.terminate()
            except Exception:
                pass
            self._bat_proc = None
            # (02/out, revisao) Trocou de celular: o laco segue rodando NO
            # celular antigo (matar o adb do PC nao o mata).
            velho = getattr(self, "_bat_serial", "")
            if velho and velho != serial:
                threading.Thread(target=self._shell,
                                 args=(velho, self.BATERIA_MATAR, 5),
                                 daemon=True, name="bateria-sai").start()
        if not serial or self._sair:
            return
        agora = time.monotonic()
        if agora - getattr(self, "_bat_tentou", 0.0) < 10.0:
            return
        self._bat_tentou = agora
        self._bat_serial = serial

        def trabalho():
            self._shell(serial, self.BATERIA_MATAR, 5)   # sobra de antes
            try:
                p = subprocess.Popen(
                    [str(self.config.adb_exe), "-s", serial, "shell",
                     self.BATERIA_LACO],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception as erro:
                self.anotar("bateria: vigia nao subiu (%s)" % erro)
                return
            self._bat_proc = p
            for bruta in p.stdout:
                partes = bruta.decode("utf-8", "replace").split()
                if len(partes) < 2 or partes[0] != "@b" or \
                        not partes[1].isdigit():
                    continue
                # "@b nivel [temperatura] estado" (o estado do sysfs pode ter
                # espaco: "Not charging"; a temperatura falta se nao leu)
                resto = partes[2:]
                temp = None
                if resto and resto[0].lstrip("-").isdigit() and \
                        len(resto[0]) >= 3:
                    temp = int(resto.pop(0)) / 10.0              # (07/out)
                estado = " ".join(resto)
                info = {"serial": serial, "bateria": int(partes[1]),
                        "carregando": estado in ("Charging", "Full", "2",
                                                 "5")}
                if temp is not None:
                    info["temperatura"] = temp
                if (self.celular or {}).get("serial") == serial:
                    self.pedidos.put(("celular", info))
                if getattr(self, "_status_procs", None):
                    self._publicar_status(bateria=info["bateria"],
                                          carregando=info["carregando"])

        threading.Thread(target=trabalho, daemon=True,
                         name="bateria").start()

    def _parar_bateria(self) -> None:
        proc, self._bat_proc = getattr(self, "_bat_proc", None), None
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        serial = getattr(self, "_bat_serial", "")
        if serial:
            self._shell(serial, self.BATERIA_MATAR, 3)

    def _conferir_o_celular(self) -> None:
        """Com alguma sessao no ar, a bateria e relida de minuto em minuto."""
        self._vigiar_bateria((self.celular or {}).get("serial", ""))
        # (01/out) As notificacoes seguem o celular em uso (lido: com id, a
        # pasta do historico ja existe).
        cel = self.celular or {}
        self.notif.garantir(cel.get("serial", "") if cel.get("id") and
                            self.config.instalacao_ok else "",
                            int(cel.get("sdk") or 0))
        if not self.sessoes:
            return
        # (02/out, revisao) A bateria ja chega pelo vigia dela; a releitura
        # inteira (getprop, codecs, tamanho da tela) de minuto em minuto so
        # vale sem ele.
        bat = getattr(self, "_bat_proc", None)
        if bat is not None and bat.poll() is None:
            return
        if time.monotonic() - getattr(self, "_celular_lido_em", 0.0) < 60.0:
            return
        serial = next((s.serial for s in self.sessoes.values()
                       if getattr(s, "serial", "")), "")
        self._ler_o_celular(serial)

    def _acordar_celular(self) -> None:
        """
        Acende a tela do celular (se estiver apagada) quando o mouse vai para
        ele. Pedidos dele (18/set/2026): "as vezes ela apaga e nao volta com o
        mouse" e depois "que ela acendesse assim que o mouse fosse jogado pra
        ela". O mouse e o teclado do scrcpy NAO acordam o Android sozinhos: o
        celular os ve como aparelhos internos (IsExternal: false no dumpsys),
        e so aparelho externo acorda a tela.

        RAPIDO: uma sessao `adb shell` fica aberta enquanto a extensao dura, e
        o pedido e so uma linha escrita nela -- sem abrir processo nenhum na
        hora. `cmd input` fala direto com o sistema (o `input` antigo subia
        uma maquina Java inteira a cada chamada). A tecla WAKEUP so acende:
        com a tela ja acesa nao faz nada. No maximo uma vez por segundo.
        Chamado da thread do vigia; nunca espera.
        """
        agora = time.monotonic()
        if agora - getattr(self, "_acordou_em", 0.0) < 1.0:
            return
        self._acordou_em = agora
        self._mandar_ao_celular("cmd input keyevent KEYCODE_WAKEUP")

    # Teclas de volume do celular (ver `borda.GanchoDeTeclas`).
    TECLAS_DE_VOLUME = {"subir": "KEYCODE_VOLUME_UP",
                        "descer": "KEYCODE_VOLUME_DOWN",
                        "mudo": "KEYCODE_VOLUME_MUTE"}

    def _volume_do_celular(self, acao: str) -> None:
        """
        Volume do celular pelo teclado do PC, com o mouse nele (pergunta
        dele, 19/set/2026, teclado 60%). E a tecla de volume de verdade do
        Android: aparece a barra de volume do proprio celular.
        """
        tecla = self.TECLAS_DE_VOLUME.get(acao)
        if tecla:
            self._mandar_ao_celular("cmd input keyevent " + tecla)

    def _serial_da_conversa(self) -> str:
        return (self._serial_da_extensao if self.borda is not None else "") \
            or getattr(self, "_serial_do_radio", "")

    def _pela_conversa(self, serial: str, comando: str) -> bool:
        """
        (r139) Comando SEM resposta pela conversa ja aberta com o celular:
        sem abrir um adb novo (~0,1 s cada no Windows). So vale se a conversa
        e deste celular; False = quem chamou usa o `_shell` de sempre.
        """
        # (r140) Sem conversa no ar (ex.: a troca tirou a unica sessao da
        # lista), abre uma PARA ESTE celular -- escrever nela nao espera.
        conversa = self._serial_da_conversa()
        if not serial or (conversa and conversa != serial):
            return False
        try:
            return self._mandar_ao_celular(comando, serial)
        except Exception:
            return False

    def _mandar_ao_celular(self, comando: str, serial: str = "") -> bool:
        """Uma linha na conversa aberta com o celular. Nunca espera.
        Devolve se a linha foi entregue (r139)."""
        serial = self._serial_da_conversa() or serial
        if not serial:
            return False
        linha = (comando + "\n").encode("ascii")
        with self._trava_do_shell:
            for _tentativa in range(2):
                shell = self._shell_do_celular
                # (r140) Conversa aberta com OUTRO celular: fecha e abre
                # a deste.
                if shell is not None and \
                        getattr(self, "_shell_serial", serial) != serial:
                    self._fechar_shell()
                    shell = None
                if shell is None or shell.poll() is not None:
                    shell = self._abrir_shell(serial)
                    self._shell_do_celular = shell
                    self._shell_serial = serial
                    if shell is None:
                        return False
                try:
                    shell.stdin.write(linha)
                    shell.stdin.flush()
                    return True
                except Exception:
                    self._fechar_shell()
        return False

    def _abrir_shell(self, serial: str):
        import subprocess
        try:
            return subprocess.Popen(
                [str(self.config.adb_exe), "-s", serial, "shell"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as erro:
            log.warning("nao consegui abrir a conversa com o celular: %s", erro)
            return None

    def _fechar_shell(self) -> None:
        shell, self._shell_do_celular = self._shell_do_celular, None
        if shell is None:
            return
        try:
            shell.stdin.close()
        except Exception:
            pass
        try:
            shell.terminate()
        except Exception:
            pass

    def _dumpsys_input(self) -> str:
        """
        O `dumpsys input` do celular da extensao, em texto. O vigia tira dele
        a curva de aceleracao do mouse e o tamanho da tela (girada ou nao),
        que a volta pela borda precisa. Chamado da thread do vigia.

        Em BYTES e decodificado como UTF-8 aqui: com `text=True` o Windows
        tenta ler na codificacao dele, um caractere do Android derruba a
        leitura e a saida vem vazia (aconteceu na sonda de 18/set/2026).
        """
        serial = self._serial_da_extensao
        if not serial:
            return ""
        import subprocess
        try:
            bruto = subprocess.run(
                [str(self.config.adb_exe), "-s", serial, "shell", "dumpsys",
                 "input"],
                capture_output=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return (bruto.stdout or b"").decode("utf-8", "replace")
        except Exception as erro:
            log.warning("nao consegui ler o celular: %s", erro)
            return ""

    def mudou_a_borda(self) -> None:
        """A pessoa mudou o celular de lugar: vale na hora, sem religar."""
        if self.borda is not None:
            self.borda.definir(self.config.perfil("extensao").get("borda") or {})

    def mudou_a_qualidade(self, nome: str) -> None:
        """
        Um ajuste do perfil mudou. Espelhamento e som: troca sozinho, sem
        desligar, um instante depois do ultimo clique. Extensao: fica
        pendente ate o "Religar".
        """
        if not (self.ativo(nome) or self.ocupado(nome)):
            return
        if nome in TROCA_AUTOMATICA:
            self._trocar_em[nome] = time.monotonic() + ESPERA_AJUSTE_S
        else:
            self.pendentes.add(nome)
        self._avisar_mudanca()

    # -- troca sem desligar --------------------------------------------------

    def _conferir_trocas(self) -> None:
        """Do laco: dispara as trocas marcadas cujo tempo de espera passou."""
        agora = time.monotonic()
        for nome, quando in list(self._trocar_em.items()):
            if nome in self.trocando or self.ocupado(nome):
                continue            # espera a troca/partida atual terminar
            if not self.ativo(nome):
                self._trocar_em.pop(nome, None)
                continue
            if agora >= quando:
                self._trocar_em.pop(nome, None)
                if nome == "extensao":
                    self.religar(nome)      # sempre em sequencia
                else:
                    self.trocar(nome)

    def trocar(self, nome: str) -> None:
        velha = self.sessoes.get(nome)
        if velha is None or not velha.rodando:
            return
        perfil = self.perfil_para_subir(nome, velha.serial)
        senha = object()
        self._troca_senha[nome] = senha
        self.trocando.add(nome)
        self.anotar("aplicando o ajuste em '%s' sem desligar" % nome)
        self._avisar_mudanca()
        threading.Thread(target=self._troca, args=(nome, velha, perfil, senha),
                         daemon=True, name="troca-%s" % nome).start()

    def _troca(self, nome: str, velha, perfil: dict, senha) -> None:
        """
        Fora do laco. Sobe o scrcpy novo por cima do velho, espera ele ter
        imagem, derruba o velho. Se o novo nao vingar: plano B, em sequencia.

        DUAS LIMPEZAS DO SCRCPY ATRAPALHAM A SOBREPOSICAO, e sao consertadas
        aqui:
        - TELA DO CELULAR APAGADA: o velho, ao sair, acende a tela de novo;
          o novo nao sabe. Depois que o velho sai, o Alt+O (atalho do proprio
          scrcpy) apaga de novo.
        - TEMPO DE TELA ESTICADO: cada scrcpy guarda o tempo que achou ao
          subir e devolve ao sair. O novo acharia o tempo JA esticado pelo
          velho, e no fim deixaria o celular com 24 h de tela para sempre.
          Entao o novo sobe SEM `--screen-off-timeout`: quem estica (depois
          que o velho devolve) e quem devolve o original no fim somos nos,
          pelo adb.
        """
        nova = None
        como = "erro"
        try:
            serial = velha.serial
            video = (perfil.get("video") or {}).get("ligado", True)
            audio = perfil.get("audio") or {}
            sessao_cfg = perfil.get("sessao") or {}
            titulo = perfil.get("titulo") or None
            tempo_ms = _tempo_de_tela_ms(perfil)
            desenho = icone.gravar_para_janela(caminhos.pasta_dados(),
                                               self.config.scrcpy_exe)

            extras = []
            alvo = None
            if video and not (perfil.get("janela") or {}).get("tela_cheia"):
                from . import janela_scrcpy
                antiga = janela_scrcpy.achar(velha.pid, titulo)
                alvo = janela_scrcpy.area(antiga) if antiga else None
                if alvo:
                    extras += ["--window-x=%d" % alvo[0],
                               "--window-y=%d" % alvo[1],
                               "--window-width=%d" % alvo[2],
                               "--window-height=%d" % alvo[3]]
            exigir_som = (audio.get("ligado", True) and not audio.get("exigir"))
            sem = ("--screen-off-timeout",) if tempo_ms else ()
            nome_log = ("log_%s.txt" % nome
                        if str(velha.arquivo_log or "").endswith("_2.txt")
                        else "log_%s_2.txt" % nome)

            nova = Sessao(nome)
            nova.tempo_original = velha.tempo_original
            # Sem saber o tempo de tela ORIGINAL nao ha como devolve-lo no
            # fim: nesse caso nada de sobrepor, vai direto ao plano B (onde o
            # proprio scrcpy cuida do tempo, como sempre).
            sobrepor = not (tempo_ms and velha.tempo_original is None)
            # --require-audio SO na sobreposicao: se o celular nao der o som
            # para dois ao mesmo tempo, o novo cai na hora (em vez de subir
            # mudo e o velho ser derrubado) e o plano B entra.
            if sobrepor:
                self._vez_de_lancar()
            ok = sobrepor and nova.iniciar(
                self.config.scrcpy_exe, serial, perfil,
                caminhos.pasta_relatorios(), icone=desenho,
                extras=extras + (["--require-audio"] if exigir_som else []),
                sem=sem, nome_log=nome_log)

            pronto, janela_nova = False, None
            if ok:
                from . import janela_scrcpy
                fim = time.monotonic() + (ESPERA_IMAGEM_S if video
                                          else ESPERA_SOM_S)
                while (time.monotonic() < fim and not self._sair
                       and self._troca_senha.get(nome) is senha
                       and nova.rodando):
                    if video:
                        janela_nova = janela_scrcpy.achar(nova.pid, titulo)
                        if janela_nova:
                            pronto = True
                            break
                    time.sleep(0.03)
                if not video:
                    pronto = nova.rodando and time.monotonic() >= fim

            if self._sair or self._troca_senha.get(nome) is not senha:
                nova.parar()
                return

            if pronto:
                from . import janela_scrcpy
                if alvo and janela_nova:
                    janela_scrcpy.por_no_lugar(janela_nova, alvo)
                velha_esticava = any(str(a).startswith("--screen-off-timeout")
                                     for a in velha.linha)
                velha.depois_de_parar = None    # o tempo, cuidamos aqui
                velha.parar()
                if tempo_ms or (video and sessao_cfg.get("apagar_tela")):
                    time.sleep(0.6)             # a limpeza do velho acontecer
                if tempo_ms:
                    if velha_esticava:
                        self._por_tempo_de_tela(serial, tempo_ms)
                    original = nova.tempo_original
                    if original:
                        nova.depois_de_parar = (
                            lambda s=serial, v=original:
                            self._por_tempo_de_tela(s, v))
                if video and sessao_cfg.get("apagar_tela") and janela_nova:
                    if not janela_scrcpy.apagar_tela_do_celular(janela_nova):
                        log.info("troca: nao consegui reapagar a tela")
                como = "sobreposta"
            else:
                # PLANO B: derruba os dois e sobe um normal, com tudo (o
                # tempo de tela volta a ser do proprio scrcpy).
                self.anotar("troca '%s': sobreposicao nao vingou (%s); "
                            "religando em sequencia" % (
                                nome, " / ".join(
                                    nova.ultimas_linhas_do_log(2).splitlines())))
                nova.parar()
                velha.parar()
                if tempo_ms:
                    time.sleep(0.3)     # a limpeza do velho devolver o tempo
                nova = Sessao(nome)
                nova.tempo_original = velha.tempo_original
                self._vez_de_lancar()
                if not nova.iniciar(self.config.scrcpy_exe, serial, perfil,
                                    caminhos.pasta_relatorios(), icone=desenho,
                                    extras=extras, nome_log=nome_log):
                    nova = None
                como = "sequencial"
        except Exception:
            log.exception("falha na troca de %s", nome)
            try:
                if nova is not None and velha.rodando:
                    nova.parar()
                    nova = None
            except Exception:
                pass
        finally:
            self.pedidos.put(("trocou", nome, nova, senha, como))

    def _adb_shell(self, serial: str, *comando, tempo: float = 5):
        import subprocess
        return subprocess.run(
            [str(self.config.adb_exe), "-s", serial, "shell"] + list(comando),
            capture_output=True, timeout=tempo,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _ler_tempo_de_tela(self, serial: str):
        try:
            saida = self._adb_shell(serial, "settings", "get", "system",
                                    "screen_off_timeout").stdout
            return int((saida or b"").decode("ascii", "replace").strip())
        except Exception:
            return None

    def _por_tempo_de_tela(self, serial: str, valor_ms: int) -> None:
        try:
            self._adb_shell(serial, "settings", "put", "system",
                            "screen_off_timeout", str(int(valor_ms)))
        except Exception as erro:
            log.warning("nao consegui ajustar o tempo de tela: %s", erro)

    def _garantir_vigia_conexao(self) -> None:
        """(r167) Uma vez so. Antes so subia se o scrcpy ja existisse ao
        abrir: quem instalava pelo botao ficava sem conexao em tempo real
        ate reabrir o programa."""
        if getattr(self, "_vigia_conexao_no_ar", False):
            return
        self._vigia_conexao_no_ar = True
        threading.Thread(target=self._vigia_conexao, daemon=True,
                         name="vigia-conexao").start()

    # -- atualizacao (r167) ---------------------------------------------------
    # PEDIDO DELE (25/set/2026): procurar versao nova do scrcpy no prazo das
    # opcoes (todo dia, semana, mes ou nunca), avisar e perguntar; sim =
    # instala por cima (`instalar_scrcpy`). "Nao" pula AQUELA versao: a
    # pergunta volta so quando sair outra (o botao instalar segue valendo).

    PRAZOS = {"diario": 86400, "semanal": 7 * 86400, "mensal": 30 * 86400}
    PRAZO_DE_FABRICA = "semanal"

    def prazo_atualizacao(self) -> str:
        v = self.config.opcoes.get("procurar_atualizacao")
        return v if v in self.PRAZOS or v == "nunca" else self.PRAZO_DE_FABRICA

    def _vigia_atualizacao(self) -> None:
        time.sleep(60)            # a abertura primeiro; internet sem pressa
        while not self._sair:
            try:
                prazo = self.PRAZOS.get(self.prazo_atualizacao())
                ultima = float(self.config.opcoes.get("ultima_procura") or 0)
                if prazo and time.time() - ultima >= prazo:
                    self.procurar_atualizacao(manual=False)
            except Exception:
                log.exception("vigia da atualizacao")
            for _i in range(3600):          # confere o prazo de hora em hora
                if self._sair:
                    return
                time.sleep(1)

    def versao_do_scrcpy(self) -> str:
        """A versao do scrcpy em uso ("4.1"), ou "" se nao deu para ler."""
        import re
        import subprocess
        exe = self.config.scrcpy_exe
        if not exe or not exe.exists():
            return ""
        try:
            r = subprocess.run([str(exe), "--version"], capture_output=True,
                               timeout=10, cwd=str(exe.parent),
                               creationflags=getattr(subprocess,
                                                     "CREATE_NO_WINDOW", 0))
            texto = ((r.stdout or b"") + (r.stderr or b"")).decode(
                "utf-8", "replace")
        except Exception:
            return ""
        m = re.search(r"scrcpy\s+v?(\d+(?:\.\d+)*)", texto)
        return m.group(1) if m else ""

    @staticmethod
    def _numeros(v: str) -> tuple:
        import re
        n = [int(x) for x in re.findall(r"\d+", v or "")[:4]]
        return tuple(n + [0] * (4 - len(n)))        # 4.1 == 4.1.0

    def procurar_atualizacao(self, manual: bool = False) -> str:
        """
        FORA DA THREAD DA JANELA (pode abrir a caixa de pergunta). Procura
        o scrcpy e o proprio scrcpy-f (r168). Devolve um texto curto.
        """
        # (r180) Uma procura por vez: o vigia do prazo e o botao ao mesmo
        # tempo abririam duas perguntas iguais.
        trava = self.__dict__.setdefault("_trava_procura", threading.Lock())
        if not trava.acquire(blocking=False):
            return "já estou procurando"
        try:
            self.config.opcoes["ultima_procura"] = time.time()
            self.config.gravar()
            textos = [self._procurar_scrcpy(manual)]
            self.estado_atualizacao["scrcpy"] = self._classificar(textos[0])
            try:
                textos.append(self._procurar_app(manual))
                self.estado_atualizacao["app"] = self._classificar(
                    textos[1])
            except Exception:
                log.exception("procurar o scrcpy-f")
                self.estado_atualizacao["app"] = ("erro", "não deu")
            self._versao_scrcpy = None      # pode ter trocado agora
            return " · ".join(t for t in textos if t)
        finally:
            trava.release()

    # (r195) O RESULTADO POR PROGRAMA (tela de atualizacoes, em
    # `self.estado_atualizacao`): cada linha da tabela mostra o seu.
    # Classifica o texto curto que as procuras ja devolviam (um lugar so;
    # os textos estao logo abaixo).

    @staticmethod
    def _classificar(texto: str) -> tuple[str, str]:
        t = (texto or "").lower()
        if "em dia" in t:
            return "ok", "em dia"
        if "disponível" in t:
            import re
            m = re.search(r"(\d+(?:\.\d+)+)", t)
            return "nova", ("%s disponível" % m.group(1)) if m else \
                "versão nova"
        if "atualizando" in t or "pronto" in t or "instalad" in t:
            return "ok", "atualizado"
        if "cancelad" in t:
            return "info", "cancelada"
        if not t:
            return "info", ""
        return "erro", "não deu para procurar"

    def versao_do_scrcpy_guardada(self) -> str:
        """(r195) A versao do scrcpy lida uma vez (a tela pede a cada
        montagem; ler de novo e subir o scrcpy.exe toda vez)."""
        v = getattr(self, "_versao_scrcpy", None)
        if v is None:
            v = self.versao_do_scrcpy()
            self._versao_scrcpy = v
        return v

    def _procurar_app(self, manual: bool) -> str:
        """(r168) Versao nova do scrcpy-f no GitHub dele?"""
        from . import VERSAO, atualizar
        info, erro = atualizar.ultima_do_app()
        if info is None:
            self.anotar("atualizacao do scrcpy-f: %s" % erro)
            return ""
        nova = info["versao"]
        self.anotar("atualizacao: scrcpy-f %s, publicado %s" % (VERSAO,
                                                                 nova))
        if self._numeros(nova) <= self._numeros(VERSAO):
            return "scrcpy-f em dia"
        if not manual and self.config.opcoes.get("pular_app") == nova:
            return "scrcpy-f %s disponível" % nova
        if not caminhos.empacotado():
            return "scrcpy-f %s disponível (só atualiza o .exe)" % nova
        sim = sistema.perguntar(
            "Saiu o scrcpy-f %s (você tem o %s).\n\nAtualizar agora? O "
            "programa fecha, o Windows pede permissão de administrador e ele "
            "abre sozinho na versão nova. Seus ajustes, apps e atalhos ficam "
            "como estão." % (nova, VERSAO), "scrcpy-f -- atualização")
        if not sim:
            self.config.opcoes["pular_app"] = nova
            self.config.gravar()
            self.anotar("atualizacao: ele disse nao ao scrcpy-f %s" % nova)
            return "scrcpy-f %s disponível" % nova
        return self._atualizar_app(info)

    def _atualizar_app(self, info: dict) -> str:
        import os
        import sys
        from pathlib import Path
        from . import atualizar, inicio_windows
        arquivo, erro = atualizar.baixar(info)
        if arquivo is None:
            self.anotar("atualizar scrcpy-f: %s" % erro)
            sistema.avisar("A atualização não deu certo: %s." % erro)
            return "falhou: %s" % erro
        exe = Path(sys.executable).resolve()
        bat, _res = atualizar.escrever_bat_app(arquivo, os.getpid(), exe)
        if bat is None:
            return "falhou: não consegui preparar"
        self.anotar("atualizar scrcpy-f: %s baixado; pedindo administrador"
                    % info["nome"])
        if not inicio_windows._executar_elevado(str(bat), esperar=False):
            self.anotar("atualizar scrcpy-f: administrador negado")
            return "atualização cancelada"
        self.config.opcoes.pop("pular_app", None)
        self.config.gravar()
        if not atualizar.esperar_e_reabrir(exe):
            self.anotar("atualizar scrcpy-f: nao subi quem reabre")
        self.anotar("atualizar scrcpy-f: fechando para trocar")
        self.pedidos.put("sair")
        return "atualizando…"

    def avisar_atualizacao_feita(self) -> None:
        """(r168) Ao abrir: a atualizacao do scrcpy-f da vez passada deu
        certo? Avisa uma vez so."""
        from . import VERSAO, atualizar
        r = atualizar.resultado_da_ultima_do_app()
        if r is None:
            return
        self.anotar("atualizacao do scrcpy-f: %s" % (r or "ok"))
        sistema.avisar("scrcpy-f atualizado para a versão %s." % VERSAO
                       if r == "" else
                       "A atualização do scrcpy-f não terminou: %s.\n\n"
                       "O programa segue na versão %s." % (r, VERSAO))

    def _procurar_scrcpy(self, manual: bool) -> str:
        from . import atualizar
        info, erro = atualizar.ultima_do_scrcpy()
        if info is None:
            self.anotar("atualizacao: %s" % erro)
            return "não deu para procurar agora"
        instalada = self.versao_do_scrcpy()
        nova = info["versao"]
        self.anotar("atualizacao: scrcpy instalado %s, publicado %s%s"
                    % (instalada or "?", nova, " (manual)" if manual else ""))
        if instalada and self._numeros(nova) <= self._numeros(instalada):
            return "scrcpy em dia (%s)" % instalada
        if not manual and self.config.opcoes.get("pular_scrcpy") == nova:
            return "scrcpy %s disponível" % nova
        sim = sistema.perguntar(
            "Saiu o scrcpy %s (você tem o %s).\n\nAtualizar agora? O que "
            "estiver aberto pelo scrcpy-f fecha durante a troca, e o Windows "
            "vai pedir permissão de administrador." % (nova,
                                                     instalada or "?"),
            "scrcpy-f -- atualização")
        if not sim:
            self.config.opcoes["pular_scrcpy"] = nova
            self.config.gravar()
            self.anotar("atualizacao: ele disse nao ao %s" % nova)
            return "scrcpy %s disponível" % nova
        ok, texto = self.instalar_scrcpy(lambda _t: None)
        sistema.avisar(("Pronto: " + texto) if ok else
                       ("A atualização não deu certo: %s.\n\nO scrcpy que "
                        "você tinha continua funcionando." % texto))
        return texto if ok else "falhou: %s" % texto

    def instalar_scrcpy(self, avisar) -> tuple[bool, str]:
        """
        (r166) FORA DA THREAD DA JANELA. Baixa o scrcpy mais novo e instala
        em `scrcpy\\` ao lado do programa (ver `atualizar.py`). `avisar(t)`
        recebe o andamento em texto curto. Devolve (ok, texto final).
        """
        if not self._instalando.acquire(blocking=False):
            return False, "já tem uma instalação em andamento"
        try:
            ok, texto = self._instalar_scrcpy(avisar)
            if ok:
                self.estado_atualizacao["scrcpy"] = ("ok", "em dia")
            return ok, texto
        finally:
            self._versao_scrcpy = None      # (r195) a tela le de novo
            self._instalando.release()

    def _instalar_scrcpy(self, avisar) -> tuple[bool, str]:
        from pathlib import Path
        from . import atualizar
        avisar("procurando a versão mais nova…")
        info, erro = atualizar.ultima_do_scrcpy()
        if info is None:
            self.anotar("instalar scrcpy: %s" % erro)
            return False, erro
        self.anotar("instalar scrcpy: %s (%d bytes, sha %s)" % (
            info["nome"], info["tamanho"], "sim" if info["sha256"] else "nao"))

        def andamento(feito, total):
            avisar("baixando %s: %d de %d MB" % (
                info["versao"], feito // 1048576, max(1, total // 1048576)))

        arquivo, erro = atualizar.baixar(info, andamento)
        if arquivo is None:
            self.anotar("instalar scrcpy: %s" % erro)
            return False, erro
        destino = atualizar.pasta_do_scrcpy()
        em_uso = self.config.pasta_scrcpy is not None and \
            Path(self.config.pasta_scrcpy).resolve() == destino.resolve()
        if em_uso:
            # Reinstalar por cima da que esta em uso: solta tudo antes.
            avisar("fechando o que usa o scrcpy…")
            self.adb_pausado = True
            self.desligar_tudo()
        avisar("instalando -- confirme a permissão de administrador")
        try:
            ok, erro = atualizar.instalar(arquivo)
        finally:
            self.adb_pausado = False
        self.anotar("instalar scrcpy: %s" % ("ok" if ok else erro))
        if not ok:
            return False, erro
        self.config.scrcpy = str(destino)
        self.config.opcoes.pop("pular_scrcpy", None)
        self.config.gravar()
        self._ajuda_scrcpy = None        # o --help e do scrcpy novo
        if self.config.instalacao_ok:
            self._garantir_vigia_conexao()
        return True, "scrcpy %s instalado" % info["versao"]

    def desligar_tudo(self) -> None:
        """No encerramento: espera cada sessao cair de verdade.

        (r165) CADA PASSO POR SI: antes, um erro no primeiro pulava todos os
        outros -- scrcpy orfao espelhando e a tela do celular apagada."""
        def passo(nome, fazer):
            try:
                fazer()
            except Exception:
                log.exception("desligar tudo: %s", nome)

        passo("status", self.desligar_status)
        passo("notificacoes", lambda: self.notif.parar(esperar=True))
        if self.windows_player is not None:
            passo("windows: player", self.windows_player.encerrar)
        if self.windows_notif is not None:
            # O que ficou na Central nao teria mais como sair dela: limpa.
            passo("windows: central", self.windows_notif.limpar)
        for nome in list(self.sessoes):
            passo(nome, lambda n=nome: self.desligar(n, esperar=True))
        passo("sono", self._parar_vigia_sono)        # solta a tela do celular
        passo("animacoes", lambda: self._animacoes_rapidas("", False))
        passo("bateria", self._parar_bateria)
        # Sobra do vigia dos apps: o do PC e o laco no celular (r120: matar
        # o adb do PC nao mata o laco de la).
        with self._vigia_trava:
            velho, self._vigia_proc = self._vigia_proc, None
        if velho is not None:
            passo("vigia dos apps", velho.terminate)
            serial = (self.celular or {}).get("serial", "")
            if serial:
                passo("vigia no celular",
                      lambda: self._shell(serial, self.VIGIA_MATAR, 5))

    def encerrar(self) -> None:
        self._sair = True

    def parar_adb(self) -> None:
        """
        (r173, pedido dele) Ao fechar o programa, o servidor do adb para de
        vez (antes ficava rodando em segundo plano). Na proxima abertura o
        `celular.aquecer` sobe de novo. Nunca levanta.
        """
        import subprocess
        adb = self.config.adb_exe
        if not adb or not adb.exists():
            return
        try:
            self._desligar_wifi_rapido()     # (09/out) antes do adb sair
        except Exception:
            pass
        try:
            subprocess.run([str(adb), "kill-server"], capture_output=True,
                           timeout=5, cwd=str(adb.parent),
                           creationflags=getattr(subprocess,
                                                 "CREATE_NO_WINDOW", 0))
            self.anotar("adb parado")
        except Exception as erro:
            self.anotar("adb: nao consegui parar (%s)" % erro)

    # -- laco ----------------------------------------------------------------

    def _protegido(self, nome: str, fazer, *args) -> None:
        try:
            fazer(*args)
        except Exception:
            log.exception("passo: %s", nome)

    def passo(self) -> None:
        """Um giro do laco: consome pedidos e confere quem ainda esta de pe."""
        while True:
            try:
                pedido = self.pedidos.get_nowait()
            except queue.Empty:
                break
            # (r165) Um pedido com erro nao leva junto os outros nem as
            # conferencias -- e, sem janela, nao derruba o laco.
            self._protegido("pedido %r" % (pedido,), self._atender, pedido)

        self._protegido("trocas", self._conferir_trocas)
        self._protegido("celular", self._conferir_o_celular)
        self._protegido("radio", self._conferir_radio)
        self._protegido("wifi rapido", self._conferir_wifi_rapido)

        # Uma sessao pode ter morrido sozinha -- o celular negou a captura de
        # audio, o Wi-Fi caiu, ou a janela do espelhamento foi fechada no X.
        # Em qualquer caso o icone nao pode continuar dizendo que esta no ar.
        # (No meio de uma troca o velho cai DE PROPOSITO: nao conta.)
        caiu = [nome for nome, s in self.sessoes.items()
                if not s.rodando and nome not in self.trocando]
        for nome in caiu:
            if nome == "extensao":
                self._parar_borda()
            sessao = self.sessoes.pop(nome, None)
            if sessao is not None:
                # Fecha o log e roda o que vinha depois (devolver o tempo
                # de tela, se a sessao nasceu de uma troca).
                threading.Thread(target=sessao.parar, daemon=True,
                                 name="caiu-%s" % nome).start()
            self.anotar("a sessao '%s' terminou sozinha (codigo %s); fim do log: %s"
                        % (nome, sessao.codigo_saida if sessao else "?",
                           " / ".join(sessao.ultimas_linhas_do_log(3).splitlines())
                           if sessao else ""))
            self._codec_recusado(sessao)
            if nome.startswith(APP) and sessao is not None:
                self._app_fechou(nome, sessao)     # fechou a janela no X
            self.avisar_na_tela(nome, "caiu")
        if caiu:
            self._avisar_mudanca()

    def _codec_recusado(self, sessao) -> None:
        """(09/out) O celular nao aceitou as opcoes de tempo real do
        codificador (`sessao.OPCOES_CODEC`): elas saem para as proximas
        partidas desta execucao e fica anotado."""
        from . import sessao as _sessao
        if not _sessao.OPCOES_CODEC or sessao is None:
            return
        try:
            fim = sessao.ultimas_linhas_do_log(12)
        except Exception:
            return
        baixo = fim.lower()
        if "error" in baixo and ("codec" in baixo or "encoder" in baixo or
                                 "configure" in baixo):
            _sessao.OPCOES_CODEC = ""
            self.anotar("codificador recusou as opcoes de tempo real: "
                        "desligadas (fim do log: %s)" % " / ".join(
                            fim.splitlines()[-3:]))

    # (09/out, pedido dele: menos atraso no sem fio sem mexer nas
    # predefinicoes) WI-FI DO CELULAR EM BAIXA LATENCIA (o modo dos jogos:
    # sem economia de energia no radio) enquanto houver sessao SEM FIO; volta
    # ao normal quando a ultima sai, ao trocar para o cabo e ao fechar.
    # Celular que nao deixar (`cmd wifi` pede permissao que o shell nao tem
    # em alguns): fica anotado e nao tenta de novo nesta execucao.

    def _conferir_wifi_rapido(self) -> None:
        sem_fio = [s.serial for n, s in self.sessoes.items()
                   if s.rodando and s.serial and not celular.e_cabo(s.serial)]
        quer = sem_fio[0] if sem_fio else ""
        tem = getattr(self, "_wifi_rapido_em", "")
        # desligar so depois de 5 s sem sessao sem fio: numa troca (uma cai,
        # a outra sobe) nao fica liga-desliga
        agora = time.monotonic()
        if quer:
            self._wifi_rapido_visto = agora
        elif tem and agora - getattr(self, "_wifi_rapido_visto", 0) < 5:
            return
        if quer == tem or getattr(self, "_wifi_rapido_ocupado", False) or \
                getattr(self, "_wifi_rapido_recusado", False):
            return
        self._wifi_rapido_ocupado = True

        def trabalho():
            try:
                if tem:
                    self._wifi_rapido(tem, False)
                ok = self._wifi_rapido(quer, True) if quer else True
                self._wifi_rapido_em = quer if ok else ""
                if quer and not ok:
                    self._wifi_rapido_recusado = True
            finally:
                self._wifi_rapido_ocupado = False
        threading.Thread(target=trabalho, daemon=True,
                         name="wifi-rapido").start()

    def _wifi_rapido(self, serial: str, ligar: bool) -> bool:
        """`cmd wifi force-low-latency-mode enabled|disabled`. True = o
        celular aceitou."""
        saida = self._shell(serial, "cmd wifi force-low-latency-mode %s" % (
            "enabled" if ligar else "disabled"), espera=5)
        baixo = saida.lower()
        ok = not any(p in baixo for p in ("exception", "permission",
                                          "unknown", "error", "not ",
                                          "usage"))
        self.anotar("wifi do celular em baixa latencia: %s -> %s%s" % (
            "ligar" if ligar else "desligar", "ok" if ok else "RECUSOU",
            "" if ok else " (%s)" % saida.strip()[:120]))
        return ok

    def _desligar_wifi_rapido(self) -> None:
        """Ao fechar: devolve o Wi-Fi do celular ao normal (na hora)."""
        tem = getattr(self, "_wifi_rapido_em", "")
        if tem:
            self._wifi_rapido_em = ""
            self._wifi_rapido(tem, False)

    def _atender(self, pedido) -> None:
        acao = pedido[0] if isinstance(pedido, tuple) else pedido

        if acao in ("jogo", "audio", "extensao"):
            self.alternar(acao)
        elif acao == "mostrar":
            if self.ao_mostrar is not None:
                self.ao_mostrar()
        elif acao == "alternar_janela":
            if self.ao_alternar_janela is not None:
                self.ao_alternar_janela()
        elif acao == "fixar_espelhamento":
            self.fixar_espelhamento()
        elif acao == "so_tela":
            self.alternar_conteudo("imagem")
        elif acao == "so_som":
            self.alternar_conteudo("som")
        elif acao == "trocar_janelas":
            self.trocar_janelas()
        elif acao == "mini_player":
            if getattr(self, "ao_mini_player", None) is not None:
                self.ao_mini_player()
        elif acao == "sem_fio_fim":
            self._sem_fio_terminou(pedido[1], pedido[2], pedido[3])
        elif acao == "menu_bandeja":
            # (07/out) botao direito no icone: o menu da casa, desenhado
            # pela janela (sem ela, o da bandeja nao chega aqui)
            if getattr(self, "ao_menu_bandeja", None) is not None:
                self.ao_menu_bandeja(pedido[1], pedido[2])
        elif acao == "app":
            self.abrir_ou_trazer(pedido[1],
                                 pedido[2] if len(pedido) > 2 else "")
        elif acao == "configurar":
            self._abrir_configurar()
        elif acao == "sair":
            self.anotar("pedido: sair")
            self.encerrar()
        elif acao == "subiu":
            _, nome, sessao = pedido
            self.ligando.discard(nome)
            self.trocando.discard(nome)
            self.sessoes[nome] = sessao
            # Subiu com o que estava gravado na hora da partida. Um ajuste
            # feito DURANTE a partida chegou tarde para ela -- mas isso e raro
            # o bastante para nao valer uma segunda marca; o normal e mexer
            # com a sessao parada ou ja no ar.
            self.pendentes.discard(nome)
            if nome == "extensao":
                self._iniciar_borda(sessao)
            if nome.startswith(APP) and nome != APP + DEX:
                threading.Thread(target=self._manter_no_app,
                                 args=(nome[len(APP):], sessao), daemon=True,
                                 name="manter-%s" % nome).start()
            self._ler_o_celular(getattr(sessao, "serial", ""))
            self.anotar("'%s' no ar" % nome)
            self._avisar_mudanca()
            self.avisar_na_tela(nome, "ligou")
        elif acao == "trocou":
            _, nome, nova, senha, como = pedido
            if self._troca_senha.get(nome) is not senha:
                # Desligaram no meio: o novo nao tem mais dono.
                if nova is not None:
                    threading.Thread(target=nova.parar, daemon=True,
                                     name="parar-%s" % nome).start()
                return
            self._troca_senha.pop(nome, None)
            self.trocando.discard(nome)
            if nova is not None and nova.rodando:
                self.sessoes[nome] = nova
                self.anotar("ajuste aplicado em '%s' (%s)" % (nome, como))
            else:
                self.sessoes.pop(nome, None)
                self.anotar("troca de '%s' FALHOU (%s)" % (nome, como))
                self.avisar_na_tela(nome, "caiu")
            self._avisar_mudanca()
        elif acao == "dispositivos":
            self._dispositivos(pedido[1])
        elif acao == "notif":
            self._avisar_mudanca()          # (01/out) contador, bolinha, aba
            self._icones_das_notificacoes()
        elif acao == "abrir_destino":
            self._abrir_com_destino(pedido[1], pedido[2], pedido[3])
        elif acao == "sem_resposta":
            # (r163) Listado pelo adb mas mudo: para o programa, saiu.
            if (self.celular or {}).get("serial") == pedido[1]:
                self.anotar("celular NAO RESPONDE (%s) -> desconectado"
                            % pedido[1])
                self.celular = {}
                self._cel_preparado = None
                self._lendo_celular = False
                self._prontos = set(getattr(self, "_prontos", None) or ()) - {
                    pedido[1]}
                self._avisar_mudanca()
        elif acao == "celular":
            self._lendo_celular = False
            info = pedido[1]
            prontos = getattr(self, "_prontos", None)
            if prontos is not None and info.get("serial") not in prontos:
                # (r161) Resposta de um celular que ja saiu: nao reacende.
                return
            antigo = self.celular
            if antigo.get("serial") and \
                    antigo.get("serial") != info.get("serial") and \
                    (prontos is None or antigo.get("serial") in prontos):
                # (r192) Troca de conexao com um celular em uso: so se for
                # o MESMO aparelho. Outro celular fica marcado e nao e lido
                # de novo (senao o seletor pularia de aparelho).
                manual = info.get("serial") == getattr(
                    self, "_escolha_manual", "")
                if manual:
                    # O "usar" da lista: o antigo vira o "outro" (senao a
                    # reavaliacao o traria de volta).
                    self._escolha_manual = ""
                    if antigo.get("id") != info.get("id"):
                        self._outro_celular.add(antigo.get("serial"))
                elif antigo.get("id") and info.get("id") and \
                        antigo.get("id") != info.get("id"):
                    self._outro_celular.add(info.get("serial"))
                    self.anotar("conexao: %s e outro celular; fica o atual"
                                % info.get("serial"))
                    return
                self.anotar("conexao: agora por %s (%s)" % (
                    "cabo" if celular.e_cabo(info.get("serial", ""))
                    else "sem fio", info.get("serial")))
            self.celular = dict(antigo, **info) if (
                antigo.get("serial") == info.get("serial")) else info
            if self.celular != antigo:
                self._avisar_mudanca()
            # Primeira leitura deste celular: prepara tudo em segundo plano
            # (apps, icones, status), para a janela abrir ja pronta.
            ident = self.celular.get("id")
            if ident and ident != getattr(self, "_cel_preparado", None):
                self._cel_preparado = ident
                self._guardar_modelo(ident, self.celular.get("modelo", ""))
                threading.Thread(target=self._preparar_celular,
                                 args=(self.celular.get("serial", ""), ident),
                                 daemon=True, name="preparar").start()
        elif acao == "borda":
            _, senha, evento, detalhe = pedido
            if senha is getattr(self, "_senha_da_borda", None):
                self._evento_da_borda(evento, detalhe)
        elif acao == "falhou":
            _, nome, mensagem = pedido
            self.ligando.discard(nome)
            self.trocando.discard(nome)
            self.anotar("'%s' NAO subiu: %s" % (nome, mensagem.splitlines()[0]))
            if mensagem == TEXTO_SEM_CELULAR and self.celular:
                # Sumiu: o icone volta a cinza ate conectar de novo.
                self.celular = {}
                self._cel_preparado = None
            self._avisar_mudanca()
            sistema.avisar(mensagem)
            if mensagem is TEXTO_SEM_CELULAR:
                # Sem celular nao ha o que tentar aqui: o PAREAR e o lugar
                # de conectar. Abre logo.
                self._abrir_configurar(no_celular=True)

    def _evento_da_borda(self, evento: str, detalhe: str) -> None:
        if self.borda is None:
            return                      # evento atrasado de um vigia ja parado
        if evento == "pronta":
            self._teclado_da_tela(True)  # (08/out) comeca com o mouse no PC
        if evento in ("entrou", "voltou"):
            self.borda_estado = "dentro" if evento == "entrou" else "fora"
            # (08/out) mouse no PC = o celular mostra o teclado da tela
            self._teclado_da_tela(evento == "voltou")
            if evento == "entrou":
                self._garantir_vigia_campo()   # o lugar do campo, ja lido
            self.anotar("borda: %s%s" % (evento, (" (%s)" % detalhe)
                                          if detalhe else ""))
            self._avisar_mudanca()
        elif evento == "morreu":
            # O vigia caiu: sem ele a extensao nao faz nada (e a janelinha
            # poderia ficar solta). Derruba o modo inteiro e diz.
            self.anotar("borda: o vigia MORREU -- %s" % detalhe)
            self.desligar("extensao")
            if self.bandeja is not None:
                self.bandeja.notificar(
                    "Extensao", "A extensao parou por um erro. Ligue de novo.")
        elif evento in ("calibrar", "calibrou", "nao calibrou"):
            self.borda_calibracao = {"calibrar": "aguardando",
                                     "calibrou": "pronta",
                                     "nao calibrou": "falhou"}[evento]
            if evento == "calibrou":
                self.borda_calibrada_em = time.monotonic()
            self.anotar("borda: %s%s" % (evento, (" (%s)" % detalhe)
                                          if detalhe else ""))
            self._avisar_mudanca()
        elif evento == "falhou":
            self.anotar("borda: FALHOU -- %s" % detalhe)
            if not self._avisou_falha_da_borda:
                # Uma vez por execucao: falhar de novo a cada encostada na
                # borda viraria uma chuva de avisos.
                self._avisou_falha_da_borda = True
                if self.bandeja is not None:
                    self.bandeja.notificar(
                        "Extensao", "Nao consegui passar o mouse para o "
                        "celular. Tente de novo encostando na borda.")
        else:
            self.anotar("borda: %s%s" % (evento, (" (%s)" % detalhe)
                                          if detalhe else ""))

    def _avisar_mudanca(self) -> None:
        """O estado mudou: repinta o icone, reescreve o menu, avisa a janela."""
        if self.bandeja is not None:
            self.bandeja.atualizar(self.estado_do_icone())
        for ouvinte in list(self.ouvintes):
            try:
                ouvinte()
            except Exception:
                log.exception("um ouvinte do estado falhou")

    def rodar(self) -> None:
        """
        O laco SEM JANELA. Desde a v0.3.0 quem normalmente manda na thread
        principal e a janela (`janela.py`), que chama `passo` de tempos em
        tempos. Este laco sobra como plano B: se o Tk nao abrir por algum
        motivo, o programa continua de pe so com a bandeja, em vez de morrer.
        """
        try:
            while not self._sair:
                self.passo()
                time.sleep(PASSO_S)
        except KeyboardInterrupt:
            self.anotar("interrompido pelo teclado")
        finally:
            self.desligar_tudo()


def _tem_app(apps) -> bool:
    """A lista tem ao menos um app de verdade (e nao so o DeX)?"""
    return any(a and a[1] != DEX for a in (apps or []))
