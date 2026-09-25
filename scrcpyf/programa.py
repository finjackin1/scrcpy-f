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
        # Um degrau acima do normal: o vigia da borda tem que responder no
        # quadro certo mesmo com o jogo rodando (pedido dele, 21/set/2026).
        sistema.prioridade_do_programa()
        self.config = Config.carregar()
        self._tirar_tela_ligada_da_extensao()
        self._acertar_o_som_da_extensao()
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
        # JOGOS que o proprio celular diz que sao jogo (`cmd game`), lidos
        # junto com a lista de apps e guardados no config (23/set/2026).
        self.jogos_detectados: set = set(self.config.apps.get("jogos") or [])
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
        alvo = celular.achar(self.config.adb_exe, self.config.ip_reserva)
        if not alvo:
            return [], "celular não encontrado. conecte em parear e tente de novo."
        # UTF-8 aqui, e nao o `celular._rodar`: nome de app tem acento, e
        # lido na codificacao do Windows um "Á" derruba a leitura inteira.
        import subprocess
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
                 "echo \"@fab $(getprop ro.product.manufacturer)\""],
                capture_output=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            linhas_r = (r.stdout or b"").decode("utf-8", "replace") \
                .splitlines()
            fabricante = next((l[5:].strip().lower() for l in linhas_r
                               if l.startswith("@fab ")), "")
            com_icone = {l.strip().split("/")[0] for l in linhas_r
                         if "/" in l and not l.startswith("@fab")}
            if len(com_icone) >= 5:
                antes = len(apps)
                apps = [a for a in apps if a[1] in com_icone]
                self.anotar("apps: %d com icone no celular (de %d)"
                            % (len(apps), antes))
        except Exception as erro:
            self.anotar("apps: nao filtrei pelos icones (%s)" % erro)
        # (r177) EM SEGUNDO PLANO: perguntar app por app se e jogo levava
        # ~12 s e segurava a lista e os icones. A lista aparece ja; a marca
        # de jogo chega quando terminar.
        threading.Thread(target=self._detectar_jogos,
                         args=(alvo, [a[1] for a in apps]), daemon=True,
                         name="jogos").start()
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

    def _detectar_jogos(self, alvo: str, pacotes: list) -> None:
        """
        JOGO DETECTADO (sonda_jogos, 23/set/2026): no Android 12+ o
        `cmd game list-modes <app>` responde "current mode" so para app
        declarado como jogo; para o resto diz "is not of game type". Um adb
        shell so para todos. Jogo abre no formato do monitor (ver
        `_partida_app`); ele pode desmarcar um que nao e.
        """
        import re
        import subprocess
        pacotes = [p for p in pacotes if re.fullmatch(r"[A-Za-z0-9._]+", p)]
        if not pacotes:
            return
        # (r177) 4 filas ao mesmo tempo no celular (antes uma so, app por
        # app): ~4x mais rapido. `&` e `wait` existem em qualquer shell de
        # Android.
        filas = [pacotes[i::4] for i in range(4) if pacotes[i::4]]
        laco = " ".join(
            "(for p in %s; do cmd game list-modes $p 2>/dev/null | "
            "grep -q 'current mode' && echo $p; done) &" % " ".join(f)
            for f in filas) + " wait"
        try:
            r = subprocess.run([str(self.config.adb_exe), "-s", alvo, "shell",
                                laco], capture_output=True, timeout=90,
                               creationflags=getattr(subprocess,
                                                     "CREATE_NO_WINDOW", 0))
        except Exception as erro:
            self.anotar("jogos: nao consegui perguntar (%s)" % erro)
            return
        validos = set(pacotes)
        jogos = sorted({l.strip() for l in (r.stdout or b"").decode(
            "utf-8", "replace").splitlines() if l.strip() in validos})
        self.jogos_detectados = set(jogos)
        self.anotar("jogos: %d detectados (%s)" % (len(jogos),
                                                  ", ".join(jogos)[:300]))
        if jogos != (self.config.apps.get("jogos") or []):
            if jogos:
                self.config.apps["jogos"] = jogos
            else:
                self.config.apps.pop("jogos", None)
            self.config.gravar()

    def e_jogo(self, pacote: str) -> bool:
        """Marcado por ele (sim ou nao) ganha; senao, o que o celular diz."""
        marcado = self.config.app(pacote).get("jogo")
        if marcado is not None:
            return bool(marcado)
        return pacote in self.jogos_detectados

    def apps_abertos(self) -> set:
        """Pacotes com janela no ar ou subindo."""
        nomes = set(self.sessoes) | set(self.ligando)
        return {n[len(APP):] for n in nomes if n.startswith(APP)
                and (n in self.ligando or self.ativo(n))}

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
        try:
            self.config.lembrar_recente(pacote)   # grupo "recentes" da lista
        except Exception as erro:
            log.warning("nao gravei o recente: %s", erro)
        self.ligando.add(nome)
        if tela_cheia:
            self._tela_cheia.add(pacote)
        else:
            self._tela_cheia.discard(pacote)
        self._avisar_mudanca()
        threading.Thread(target=self._partida_app, args=(nome, pacote, rotulo),
                         kwargs={"tela_cheia": tela_cheia},
                         daemon=True, name="partida-%s" % nome).start()

    def reabrir_app(self, pacote: str, tela_cheia=None) -> None:
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
        tarefa, serial = info
        serial = getattr(sessao, "serial", "") or serial

        def fazer():
            time.sleep(0.8)          # a tela virtual vai embora primeiro
            if pacote in self.apps_abertos():
                return               # ele abriu de novo nesse meio tempo
            for jeito in self.JEITOS_DE_FECHAR:
                self._shell(serial, jeito % tarefa, espera=6)
                recentes = self._shell(serial, "dumpsys activity recents",
                                       espera=8)
                if ("#%s " % tarefa) not in recentes:
                    self.anotar("app %s: fechado no celular (%s)"
                                % (pacote, jeito.split(" %")[0]))
                    return
            self.anotar("app %s: NAO consegui fechar no celular (tarefa %s) "
                        "-- nenhum jeito serviu nesta versao"
                        % (pacote, tarefa))

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
        texto = self._shell(serial, "dumpsys activity activities", espera=8)
        dentro = False
        for linha in texto.splitlines():
            m = re.match(r"\s*Display #(\d+)", linha)
            if m:
                if dentro:
                    break
                dentro = m.group(1) == tela
                continue
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
                alvo = celular.achar_rapido(self.config.adb_exe,
                                            self.config.ip_reserva)
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
    VIGIA_A_CADA_S = 0.4
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
        "for p in %s; do t=${p%%=*}; c=${p#*=}; k=${c%%/*}; "
        "if [ $s = 1 ]; then l=$(printf '%%s\\n' \"$M\" | "
        "grep \"@D$t\\$\" | grep -m1 \": $k/\"); "
        "case \"$l\" in *visible=true*) continue;; "
        "?*) echo \"escondido $t\"; continue;; esac; fi; "
        "if [ $d = 0 ]; then dumpsys activity activities > $f 2>/dev/null; "
        "d=1; fi; "
        "b=$(sed -n \"/^Display #$t /,/^Display #/p\" $f); "
        "case \"$b\" in '') continue;; esac; "
        "l=$(printf '%%s\\n' \"$b\" | grep -m1 \"Task{.*$k\"); "
        "case \"$l\" in *visible=true*) continue;; "
        "?*) echo \"escondido $t\"; continue;; esac; "
        "am start -f 0x10000 --display $t -n $c >/dev/null 2>&1; "
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
        componente = self._shell(serial, "cmd package resolve-activity "
                                         "--brief %s | tail -1" % pacote)
        componente = (componente.strip().splitlines()[-1:] or [""])[0].strip()
        if not re.fullmatch(r"[A-Za-z0-9._$/]+", componente) or \
                "/" not in componente:
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
                self._tarefa_do_app[pacote] = (tarefa, serial)
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
            pares = " ".join("'%s=%s'" % (tela, comp)
                             for tela, comp in alvos.values())
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

        def ler():
            vezes: dict = {}
            for bruta in proc.stdout:
                linha = bruta.decode("utf-8", "replace").strip()
                if linha.startswith("vivo"):
                    self.anotar("vigia dos apps: no ar -- telas: %s"
                                % linha[5:])
                    continue
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

    def _garantir_vigia_sono(self, serial: str) -> None:
        """Sobe o vigia do sono, se ainda nao estiver no ar."""
        with self._sono_trava:
            t = self._sono_thread
            if t is not None and t.is_alive():
                return
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
                  "laco_desde": 0.0, "jar_vigia": True}

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
            soltar_controle(esperar=False)
            if ok:
                self.anotar("vigia do sono: botao com a tela apagada -> "
                            "painel religado em %.2f s"
                            % (time.monotonic() - t0))
            else:
                self.anotar("vigia do sono: botao com a tela apagada -> "
                            "reserva: %s" % self._acender_de_verdade(serial))

        def apagar(t0: float, avisado: bool, motivo: str) -> None:
            """QUER A TELA APAGADA com os apps rodando."""
            if not avisado:
                acordar()
            ok = painel("off")
            subir_controle()      # --keep-active: nao dorme por tempo
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
        aquecido = painel("on", espera=6)
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
            aquecido = painel("on", espera=6)
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
        try:
            while not parar.is_set() and not self._sair:
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
                        subir_controle()
                    elif partes[1] == "acesa":
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
            laco = estado["laco"]
            if laco is not None and laco.poll() is None:
                try:
                    laco.terminate()
                except Exception:
                    pass
            apagada = controle_vivo()
            if apagada:
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
            if apagada and not self.ativo("jogo"):
                # O celular dorme como se ele tivesse apertado o botao.
                self._shell(serial, "cmd input keyevent KEYCODE_SLEEP",
                            espera=5)
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

    def _vigia_foco(self, serial: str) -> None:
        from . import janela_scrcpy
        telas: dict = {}
        ultimo = None
        candidato, desde = None, 0.0
        vazio_desde = None
        vezes = 0
        self.anotar("vigia do foco: no ar")
        try:
            while not self._sair:
                time.sleep(0.1)
                agora = time.monotonic()
                apps = [(n, s) for n, s in list(self.sessoes.items())
                        if n.startswith(APP)]
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
                comando = ("input -d %s motionevent DOWN %d 2; "
                           "input -d %s motionevent CANCEL %d 2"
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
        if getattr(self, "_status_procs", None):
            return
        # (r149) Aqui fica o `achar` de verdade: roda 1x ao entrar na aba, e
        # com um serial velho o medidor cairia e religaria sem parar.
        alvo = celular.achar(self.config.adb_exe, self.config.ip_reserva)
        if not alvo:
            self.status_atual = {"erro": "celular não encontrado"}
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
        topo = "top -b -d %s -m %d -s 1 -o %%CPU,RES,NAME" % (
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
            campos = linha.split(None, 2)
            if len(campos) < 3:
                continue
            try:
                cpu = float(campos[0])
            except ValueError:
                continue
            cpu = cpu / getattr(self, "_nucleos", 1)
            nome, ram = campos[2].strip(), campos[1]
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
        if not alvo or not re.fullmatch(r"[A-Za-z0-9._]+", pacote):
            return {}
        texto = self._shell(alvo, (
            "p=$(pidof %s); [ -z \"$p\" ] && echo @parado && exit; "
            "echo @n $(nproc 2>/dev/null); "
            "echo @pid $p; top -b -n 2 -d 0.6 -p $(echo $p | tr ' ' ',') "
            "-o PID,%%CPU,RES 2>/dev/null | tail -n $(echo $p | wc -w); "
            "echo @gpu; dumpsys gpu 2>/dev/null | grep -E \"Proc ($(echo $p | "
            "tr ' ' '|')) total\"") % pacote, espera=15)
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
        try:
            (pasta / "icones").mkdir(parents=True, exist_ok=True)
        except Exception:
            return None
        return pasta

    def pasta_de_icones(self):
        cel = self.pasta_do_celular()
        if cel is not None:
            return cel / "icones"
        pasta = caminhos.pasta_dados() / "icones"
        try:
            pasta.mkdir(exist_ok=True)
        except Exception:
            pass
        return pasta

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
        saida = self._shell(serial, "pm list packages --show-versioncode "
                            "2>/dev/null || pm list packages", espera=15)
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
        import base64
        import re
        import subprocess
        # DeX sem icone (r164, 25/set/2026): "__dex__" nao e pacote, entao
        # ficava so a letra. Agora: desenha um reserva na hora e pede ao
        # celular o icone do app do DeX, que por cima substitui o desenho.
        quer_dex = DEX in pacotes
        if quer_dex:
            self._desenhar_icone_dex()
        pacotes = [p for p in pacotes if p != DEX
                   and re.fullmatch(r"[A-Za-z0-9._]+", p)]
        if quer_dex and ICONE_DEX not in pacotes:
            pacotes.append(ICONE_DEX)
        if not pacotes or not self.config.instalacao_ok:
            return 0
        jar = caminhos.pasta_interna() / "android" / "scrcpyf-icones.jar"
        if not jar.exists():
            self.anotar("icones: falta o %s" % jar)
            return 0
        alvo = celular.achar(self.config.adb_exe, self.config.ip_reserva)
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
                     log_velho: str = "", tela_cheia: bool = False):
        """
        `lugar` = (x, y, largura, altura) da imagem da janela velha, quando
        e um "reabrir" (ver `reabrir_app`).

        `troca=True` (r125, `_trocar_sem_reiniciar`): sobe SO a janela, com
        a tela virtual vazia (sem --start-app) e fora da vista, no celular
        `serial` (sem procurar de novo), e DEVOLVE a sessao em vez de avisar
        o laco -- quem troca poe o app nela e a janela no lugar. None = nao
        subiu.
        """
        try:
            alvo = serial or celular.achar(self.config.adb_exe,
                                           self.config.ip_reserva)
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
            perfil = self.perfil_para_subir("jogo")
            perfil.setdefault("video", {})["ligado"] = True
            # QUALIDADE DOS APPS (23/set/2026): a unica, de OPCOES >
            # qualidade (ja veio no perfil_para_subir). O app personalizado
            # (APPS > personalizados) pode trocar a predefinicao e cada
            # fileira; vazio = "padrao" (segue opcoes).
            deste = self.config.app(pacote)
            from . import qualidade
            import copy
            audio_q = None
            if deste.get("predef"):
                video_p, audio_q = qualidade.valores_da_predef(
                    self.config.qualidade, deste["predef"])
                qualidade.aplicar_no_perfil(perfil, video_p, None)
            for campo, valor in (deste.get("video_fino") or {}).items():
                qualidade.escrever(perfil, "video", campo, valor)
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
                for campo, valor in (deste.get("audio_fino") or {}).items():
                    qualidade.escrever(perfil, "audio", campo, valor)
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
                          "--mouse-bind=b-b-:b-b-", "--shortcut-mod=rsuper"]
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
                POLITICA_TECLADO = "local" if deste.get("teclado_celular") \
                    else ""
                if POLITICA_TECLADO and \
                        self._scrcpy_aceita("--display-ime-policy"):
                    extras.append("--display-ime-policy=" + POLITICA_TECLADO)
                if not troca:
                    extras.append("--start-app=%s" % pacote)
                # TELA DO APP NO TAMANHO DO MONITOR (pedido dele, 23/set/2026:
                # "o jogo inicia na resolucao e formato da tela do pc"): a
                # tela virtual nasce com a resolucao do monitor principal
                # (16:9 1080/1440/2160...), e nao com a do celular. Vale o do
                # app (APPS > personalizados), senao o de APPS > ajustes.
                # JOGO (23/set/2026): marcado por ele (APPS > menu do app ou
                # personalizados) abre no formato do monitor, a menos que o
                # app tenha a tela escolhida a mao.
                jogo = self.e_jogo(pacote)
                tela = deste.get("tela") or ("pc" if jogo else None) or \
                    self.config.apps.get("tela") or "celular"
                if tela == "pc":
                    from . import monitores
                    lista = monitores.listar(estrito=True)
                    m = next((x for x in lista if x.get("principal")),
                             lista[0] if lista else None)
                    if m and m["l"] > 0 and m["a"] > 0:
                        extras[0] = "--new-display=%dx%d" % (m["l"], m["a"])
                        # E A IMAGEM NA RESOLUCAO DO MONITOR (pedido dele,
                        # 23/set/2026): a "resolucao" da qualidade nao corta
                        # o jogo -- vai inteiro (se o celular nao der conta,
                        # o proprio scrcpy desce o tamanho sozinho).
                        perfil.setdefault("video", {})["resolucao_max"] = \
                            max(m["l"], m["a"])
                        self.anotar("app %s: tela virtual %dx%d (monitor)"
                                    % (pacote, m["l"], m["a"]))
            # REABRIR NO MESMO LUGAR (r123): posicao e ALTURA da janela velha;
            # a largura o scrcpy tira do formato da imagem -- o ajuste novo
            # pode ter trocado o formato (tela do celular x do monitor).
            if lugar and pacote != DEX:
                extras += ["--window-x=%d" % lugar[0],
                           "--window-y=%d" % lugar[1]]
                if not tela_cheia:
                    extras.append("--window-height=%d" % lugar[3])
            # TELA APAGADA = APP SEM IMAGEM (pedido dele, 23/set/2026): com o
            # celular dormindo o Android pausa os apps em todas as telas,
            # inclusive a virtual. Acende antes de abrir; o vigia do sono
            # mantem acordado enquanto houver janela de app.
            if not troca:       # na troca o app ja esta aberto: acordado
                acordar = "cmd input keyevent KEYCODE_WAKEUP"
                if not self._pela_conversa(alvo, acordar):       # (r139)
                    self._shell(alvo, acordar, espera=5)
            # Na troca a velha ainda escreve no log dela: a nova usa o outro
            # nome (os dois se revezam, como no espelhar).
            nome_log = "log_app_%s.txt" % seguro
            if troca and str(log_velho).endswith(nome_log):
                nome_log = "log_app_%s_2.txt" % seguro
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
            if troca:
                return sessao
            self.pedidos.put(("subiu", nome, sessao))
            self._garantir_vigia_sono(alvo)
            self._garantir_vigia_foco(alvo)
        except Exception as erro:
            log.exception("falha ao abrir o app %s", pacote)
            if troca:
                return None
            self.pedidos.put(("falhou", nome, "Falha inesperada: %s" % erro))

    def _serial_conhecido(self) -> str:
        """(r149) O celular ja lido (sem gastar um `adb devices`); sem ele,
        procura. Se o conhecido tiver saido da rede, o comando falha e quem
        chamou ja trata vazio -- e o proximo `achar` de uma partida corrige."""
        serial = (self.celular or {}).get("serial", "")
        return serial or celular.achar(self.config.adb_exe,
                                       self.config.ip_reserva)

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
        """ "+par" com um celular lido (o icone ganha a borda verde)."""
        return "+par" if (self.celular or {}).get("id") else ""

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

    def _partida(self, nome: str) -> None:
        """Roda fora do laco: acha o celular e sobe o scrcpy."""
        try:
            alvo = celular.achar(self.config.adb_exe, self.config.ip_reserva)
            if not alvo:
                self.pedidos.put(("falhou", nome, TEXTO_SEM_CELULAR))
                return

            # (r139) O endereco de reserva e so para a PROXIMA vez: pergunta
            # ao celular em paralelo, sem segurar esta partida.
            def guardar_endereco():
                try:
                    endereco = celular.endereco_na_rede(self.config.adb_exe,
                                                        alvo)
                    if endereco:
                        self.config.lembrar_ip(endereco)
                except Exception as erro:
                    log.debug("endereco do celular: %s", erro)

            threading.Thread(target=guardar_endereco, daemon=True,
                             name="endereco").start()

            # O icone da janela do espelhamento. Falhar aqui nao impede
            # nada: a sessao sobe com o icone padrao do scrcpy.
            desenho = icone.gravar_para_janela(caminhos.pasta_dados(),
                                               self.config.scrcpy_exe)

            perfil = self.perfil_para_subir(nome)
            sessao = Sessao(nome)
            if _tempo_de_tela_ms(perfil):
                # O tempo de tela de ANTES, guardado para a troca sem
                # desligar poder devolve-lo no fim (ver `_troca`).
                sessao.tempo_original = self._ler_tempo_de_tela(alvo)
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

    def _parar_borda(self) -> None:
        # O radio NAO desliga aqui: outro modo pode estar no ar. Quem cuida e
        # o `_conferir_radio` (a conversa fechada abaixo reabre sozinha).
        self.borda_calibracao = ""
        if self.borda is not None:
            self.borda.parar()
            self.borda = None
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

    def perfil_para_subir(self, nome: str) -> dict:
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
        q = self.config.qualidade
        qualidade.aplicar_no_perfil(perfil, q.get("video"), q.get("audio"))
        # O modo pode usar outra predefinicao (espelhar e extensao tem a
        # fileira "qualidade"; vazio = a de opcoes).
        if perfil.get("predef"):
            video_p, audio_p = qualidade.valores_da_predef(q, perfil["predef"])
            qualidade.aplicar_no_perfil(perfil, video_p, audio_p)
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
            time.sleep(self.VIGIA_CONEXAO_S)

    def _dispositivos(self, vistos: dict) -> None:
        """Do laco: a lista de celulares do adb mudou."""
        prontos = {s for s, e in vistos.items() if e == "device"}
        antes = getattr(self, "_prontos", None)
        self._prontos = prontos
        atual = (self.celular or {}).get("serial", "")
        if atual and atual not in prontos:
            self.anotar("celular DESCONECTADO (%s)" % atual)
            self.celular = {}
            self._cel_preparado = None
            self._lendo_celular = False
            self._avisar_mudanca()
            atual = ""
        if not atual and prontos and prontos != antes:
            escolhido = celular.escolher_serial(
                "\n".join("%s\tdevice" % s for s in sorted(prontos)))
            if escolhido:
                self.anotar("celular CONECTADO (%s)" % escolhido)
                self._ler_o_celular(escolhido)

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
                    "'^ *(level|AC powered|USB powered):'", tempo=6)
                import re as _re
                for linha in saida.stdout.decode("utf-8",
                                                 "replace").splitlines():
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

    def ler_celular_agora(self) -> None:
        """Logo depois de parear: acha o celular (o endereco que o parear
        guarda nem sempre e o que o adb usa) e le tudo dele."""
        def achar():
            alvo = celular.achar(self.config.adb_exe, self.config.ip_reserva)
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
    BATERIA_LACO = (
        "m=scrcpyf_bateria; B=/sys/class/power_supply/battery; u=; "
        "while :; do if [ -r $B/capacity ]; then c=$(cat $B/capacity); "
        "s=$(cat $B/status); else d=$(dumpsys battery); "
        "c=$(echo \"$d\" | grep -m1 ' level:' | tr -dc 0-9); "
        "s=$(echo \"$d\" | grep -m1 ' status:' | tr -dc 0-9); fi; "
        "if [ \"$c $s\" != \"$u\" ]; then echo \"@b $c $s\"; u=\"$c $s\"; fi; "
        "sleep 2; done")
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
                estado = partes[2] if len(partes) > 2 else ""
                info = {"serial": serial, "bateria": int(partes[1]),
                        "carregando": estado in ("Charging", "Full", "2",
                                                 "5")}
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
        if not self.sessoes:
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
        perfil = self.perfil_para_subir(nome)
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
            try:
                textos.append(self._procurar_app(manual))
            except Exception:
                log.exception("procurar o scrcpy-f")
            return " · ".join(t for t in textos if t)
        finally:
            trava.release()

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
            return self._instalar_scrcpy(avisar)
        finally:
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
            if nome.startswith(APP) and sessao is not None:
                self._app_fechou(nome, sessao)     # fechou a janela no X
            self.avisar_na_tela(nome, "caiu")
        if caiu:
            self._avisar_mudanca()

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
            self.celular = dict(antigo, **info) if (
                antigo.get("serial") == info.get("serial")) else info
            if self.celular != antigo:
                self._avisar_mudanca()
            # Primeira leitura deste celular: prepara tudo em segundo plano
            # (apps, icones, status), para a janela abrir ja pronta.
            ident = self.celular.get("id")
            if ident and ident != getattr(self, "_cel_preparado", None):
                self._cel_preparado = ident
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
        if evento in ("entrou", "voltou"):
            self.borda_estado = "dentro" if evento == "entrou" else "fora"
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
