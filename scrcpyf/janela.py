"""
A janela do scrcpy-f -- visual "painel de estudio" (21/set/2026).

O QUE MUDOU EM RELACAO A `interface.py`
----------------------------------------
Ele achou o visual antigo "com cara de feito com IA e sem personalidade" e
desenhou este junto comigo (mockups `scrcpy-f-opcao-a-v2/v3`,
`scrcpy-f-extensao-v4`, `scrcpy-f-posicionar`):

- janela DEITADA e de tamanho fixo (680 x 320); nada cresce ao trocar de tela;
- a lista da esquerda: ESPELHAR (1), EXTENSAO (2), PAREAR e, no rodape,
  OPCOES. Os numeros sao a tecla do atalho (Ctrl+Alt+1 / 2);
- as abas de cima dependem do item: modos = basico / avancado (a extensao
  tem ainda "personalizar"), parear = procurar / cabo usb / codigo, opcoes =
  geral / atalhos;
- espelhar e som viraram UM modo: embaixo do ligar, "imagem e som / so som /
  so imagem" (o `Programa.perfil_para_subir` traduz);
- o Configurar separado virou o item PAREAR, e a pasta do scrcpy mora em
  OPCOES > GERAL;
- em PERSONALIZAR, um clique no mapa faz a janela crescer para 960 e mostrar
  todos os monitores do jeito que estao na mesa, para arrastar o celular.

O que continua igual por baixo: o relogio que move o programa (`_girar`), a
janela nascer escondida perto da bandeja, Esc/X escondem, segurar o X por 1 s
fecha o programa, o gravador de atalhos.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import traceback

from . import (VERSAO, atalhos as atalhos_mod, conexao, inicio_windows,
               moldura, monitores as mon, qualidade, sistema)
from . import estudio as E
from .programa import APP, DEX, conteudo_do

log = logging.getLogger(__name__)

PASSO_MS = 100
PASSO_PARADO_MS = 250
SEGURAR_X_MS = 1000
DICA_X = "segure para sair"
# ANIMACAO POR TEMPO, NAO POR QUADRO (21/set/2026, "deixe tudo suave"): cada
# quadro calcula onde a animacao DEVERIA estar pelo relogio. Contar quadros
# fazia um quadro atrasado virar um tranco e a animacao ficar mais longa.
# 10 ms: no Windows o `after` arredonda para o tique do sistema; pedir 16
# as vezes caia em 31 ms (meia velocidade).
MS_QUADRO = 10
MS_MOSTRAR = 190
MS_ESCONDER = 150
MS_DESLIZE = 210
MS_GRANDE = 260
MS_TROCA_DICA = 200      # "segure para sair" some, "saindo…" aparece
MS_SAINDO = 250          # "saindo…" fica na tela antes de fechar
VERMELHO_SAINDO = "#FF1A1A"   # bem vermelho (pedido dele)
# O brilho das letras acesas: (raio em px, forca). Mais longe, mais fraco.
HALO = ((E.px(2), 0.20), (E.px(1), 0.42))
SALTO_PX = E.px(10)
# A janela crescendo para o mapa grande (e voltando).
ORDEM_DOS_ITENS = ["jogo", "extensao", "apps", "celular", "parear",
                   "opcoes"]
# APPS: quantos icones de apps abertos
# cabem ao lado de OPCOES e as cores da inicial de quem ainda nao tem
# icone.
CORES_DE_APP = ("#3A6EA5", "#5B8C5A", "#A0522D", "#7A5195",
                "#B8860B", "#2F7F7F", "#8B3A3A", "#4F5D75")

PEDIDO_DO_ATALHO = {
    "alternar_jogo": "jogo",
    "alternar_extensao": "extensao",
    # O atalho da janela abre E devolve (pedido dele, 21/set/2026); a
    # bandeja e a segunda instancia continuam so abrindo ("mostrar").
    "mostrar_janela": "alternar_janela",
    "fixar_espelhamento": "fixar_espelhamento",
    "so_tela": "so_tela",
    "so_som": "so_som",
    "trocar_janelas": "trocar_janelas",
}

# REORGANIZACAO DE 23/set/2026 (pedido dele: nomes sem duvida, abas em
# ordem alfabetica -- menos a PRIMEIRA de cada item, que e a tela que abre
# ao entrar nele). As
# CHAVES continuam as de antes (config e codigo); so o que aparece mudou.
ABAS = {
    "jogo": [("basico", "espelhar")],
    "extensao": [("basico", "básico"), ("personalizar", "marca"),
                 ("avancado", "som e controles")],
    "apps": [("lista", "apps"), ("aparencia", "ajustes"),
             ("personalizados", "personalizados")],
    "celular": [("status", "celular")],
    "parear": [("procurar", "procurar"), ("cabo", "pelo cabo"),
               ("codigo", "por código")],
    "opcoes": [("geral", "geral"), ("atalhos", "atalhos"),
               ("qualidade", "qualidade")],
}

# O que depende da versao do Android (documentacao do scrcpy): som no
# pc = Android 11 (API 30); tocar no pc E no celular = 13 (API 33); app em
# janela propria (tela virtual) = 10 (API 29). Sem celular lido, nada trava.
APPS_RECENTES = 8
# APPS > ajustes que mudam a janela de um app aberto (os outros so mudam a
# lista): reabrem os apps abertos (r123).
AJUSTES_DA_JANELA_DO_APP = ("onde", "tela")
# Ajustes do app que NAO mexem na janela aberta (nao reabrem) -- r134.
AJUSTES_SEM_REABRIR = ("jogo", "ao_fechar")
# Ao fechar a janela de um app (r134).
AO_FECHAR = [("fechar", "fechar o app"), ("deixar", "deixar aberto")]
# Telas que ficam guardadas (escondidas) ao sair e voltam prontas (r115/116).
TELAS_GUARDADAS = ("_tela_apps_lista", "_tela_opcoes_qualidade",
                   "_tela_opcoes_atalhos")
TELAS_DO_APP = [("celular", "do celular"), ("pc", "do monitor do pc")]   # quantos aparecem no grupo "recentes" da lista

PRECISA = {"som": (30, "11"), "pc_cel": (33, "13"), "apps": (29, "10")}

CONTEUDOS = [("ambos", "imagem+som"), ("som", "só som"),
             ("imagem", "só imagem")]

# Nomes curtos para as fileiras do avancado (cabem na coluna de 78 px).
NOME_CURTO = {
    ("video", "codec"): "codec", ("video", "bitrate"): "mb/s",
    ("video", "fps_max"): "quadros", ("video", "resolucao_max"): "resolução",
    ("video", "buffer_ms"): "atraso ms", ("audio", "origem"): "toca em",
    ("audio", "codec"): "codec", ("audio", "bitrate"): "kb/s",
    ("audio", "buffer_ms"): "atraso ms",
}
ROTULO_CURTO = {"output": "pc", "playback": "pc+cel", "mic": "mic",
                "H.264": "h264", "H.265": "h265"}

SUB_PARADO = {
    "ambos": "a tela e o som do celular vêm para o pc.",
    "som": "você joga no celular e o som sai no pc.",
    "imagem": "a tela do celular aparece aqui no pc.",
}
SUB_NO_AR = {
    "ambos": "a tela e o som do celular estão no pc.",
    "som": "o som do celular está saindo no pc.",
    "imagem": "a tela do celular está no pc.",
}


class Janela(tk.Tk):
    """A janela do programa. Nasce escondida; `mostrar` a traz."""

    def __init__(self, programa, motor=None) -> None:
        super().__init__()
        self.withdraw()               # antes de qualquer widget: sem piscar

        self.programa = programa
        self._config = programa.config
        self.motor = motor

        self.title("scrcpy-f")
        self.configure(bg=E.FUNDO)
        self.resizable(False, False)
        moldura.preparar(self)

        self._item = "jogo"
        # (r168) PAGINA INICIAL (pedido dele, 25/set/2026): ligada, o
        # programa abre na aba escolhida em OPCOES; desligada, em ESPELHAR.
        inicial = self._config.opcoes.get("pagina_inicial")
        if self._config.opcao("pagina_inicial_ligada") and \
                inicial in ORDEM_DOS_ITENS:
            self._item = inicial
        # (r180) Sem o scrcpy so OPCOES abre (pedido dele).
        if not self._config.instalacao_ok:
            self._item = "opcoes"
        self._aba = {"jogo": "basico", "extensao": "basico", "apps": "lista",
                     "celular": "status",
                     "parear": "procurar", "opcoes": "geral"}
        # Apps em janela propria: a lista vem do celular (uns segundos) e
        # fica guardada ate ele pedir "atualizar".
        self._apps: list | None = None
        self._apps_carregando = False
        self._apps_erro = ""
        self._apps_pintado = None
        # tela -> (palco, _ui, assinatura) das telas escondidas (r115/r116)
        self._guardadas: dict = {}
        self._fotos: dict = {}
        self._icones_versao = 0
        self._icones_buscando = False
        self._app_configurado = None
        self._escolhendo_app = False
        self._busca_escolha = ""
        # Status do celular e o quadro de uso de um app.
        self._status_em = 0.0
        self._status_pintado = None
        self._dica = None
        self._dica_de = None
        self._dica_id = None
        self._uso_cache: dict = {}
        # O nome que o atalho de cada app mostra (gravado no config).
        atalhos_mod.NOMES_DE_APP.update(
            programa.config.apps.get("nomes") or {})
        self._grande = False
        self._visivel = False
        self._escondendo = False
        self._anims: dict[str, str] = {}
        self._pos: tuple[int, int] | None = None
        self._falta_arrumar_a_barra = True
        self._anotou_a_frente = False
        self._anotou_escondida = False
        self._estado_do_icone = None
        self._x_apertado_id = None
        self._ui: dict = {}
        self._itens: dict[str, E.Item] = {}
        self._abas_w: list = []
        self._da_outra_thread: queue.Queue = queue.Queue()
        self._erros_do_relogio: set[str] = set()
        self._ja_avisou_gravacao = False
        self._windows_ligado: bool | None = None

        # Parear
        self._trabalhando = False
        self._parar_trabalho = threading.Event()
        self._status_parear = ("", E.TEXTO_2)
        self._achados: list | None = None
        self._ja_procurou = False
        self._celular_ok = False

        # Atalhos (gravador)
        self._gravando: str | None = None
        self._segurando: dict[int, str] = {}
        self._combinacao = ""
        self._tecla_final = ""
        self._recado = ""
        self._valida = False
        self._recusas_conhecidas: set[str] = set()
        self._atalhos_modo = "lista"
        self._pintado = None

        self._montar()

        self.protocol("WM_DELETE_WINDOW", self.esconder)
        self.bind("<Escape>", self._esc)
        self.bind("<KeyPress>", self._tecla_desceu, add="+")
        self.bind("<KeyRelease>", self._tecla_subiu, add="+")
        # Tecla solta que o Windows engoliu (Alt+Tab, tecla Win) no meio da
        # gravacao: sem isto o gesto nunca terminava.
        self.bind("<FocusOut>", self._perdeu_foco, add="+")
        # CAIXAS DE TEXTO (pedido dele, 23/set/2026): nao comecam
        # selecionadas -- o Tk seleciona tudo ao chegar pelo Tab
        # (<<TraverseIn>> da classe Entry); agora so poe o cursor no fim. E
        # clicar fora tira a selecao e o foco da caixa.
        self.bind_class("Entry", "<<TraverseIn>>",
                        lambda e: (e.widget.selection_clear(),
                                   e.widget.icursor("end")))
        self.bind_all("<Button-1>", self._clique_em_qualquer_lugar, add="+")
        self.bind_all("<Button-3>", self._clique_em_qualquer_lugar, add="+")
        self._menu_app = None

        programa.ouvintes.append(self._estado_mudou)
        programa.ao_mostrar = self.mostrar
        programa.ao_alternar_janela = self.alternar_pelo_atalho
        programa.ao_perfil_mudou = self._perfil_mudou_fora
        # De onde a janela veio da ultima vez que apareceu: "bandeja" ou
        # "barra" (minimizada). O atalho a devolve para la.
        self._origem = "bandeja"
        programa.ao_parear = self._abrir_parear

        if self.motor is not None and self.motor.disponivel:
            self._aplicar_atalhos()
        # O ultimo celular: lista e icones antes de ele responder.
        self.programa.carregar_ultimo_cache()
        if inicio_windows.disponivel():
            inicio_windows.arrumar()
            self._ler_o_windows()
        # O celular conecta sozinho ao abrir (pedido dele, 23/set/2026): nada
        # de entrar no PAREAR so para ver o quadradinho verde.
        self.after(1200, self._conectar_ao_abrir)
        self.bind_all("<MouseWheel>", self._roda_global, add="+")
        # (r121) Tab/Shift+Tab pulam as telas guardadas (escondidas atras).
        # O Tk anda pelo Tab com os eventos virtuais <<NextWindow>> e
        # <<PrevWindow>> (ligar em "<Tab>" nao pega -- conferido no Xvfb).
        self.bind_all("<<NextWindow>>", lambda e: self._tab(e, False))
        self.bind_all("<<PrevWindow>>", lambda e: self._tab(e, True))

        self.after(PASSO_MS, self._girar)

    # ==========================================================================
    # Montagem: barra, lista, conteudo
    # ==========================================================================

    def _montar(self) -> None:
        self.geometry("%dx%d" % (E.LARGURA, E.ALTURA_BARRA + 1 + E.ALTURA_CORPO))

        # -- barra --
        barra = tk.Frame(self, bg=E.FUNDO, height=E.ALTURA_BARRA)
        barra.pack(side="top", fill="x")
        barra.pack_propagate(False)
        self._barra = barra
        marca = tk.Canvas(barra, width=E.px(8), height=E.px(8), bg=E.FUNDO,
                          highlightthickness=0)
        marca.create_rectangle(0, 0, E.px(8), E.px(8), fill=E.ACENTO, outline=E.ACENTO)
        marca.pack(side="left", padx=(E.px(12), E.px(10)))
        nome = tk.Label(barra, text="SCRCPY-F", bg=E.FUNDO, fg=E.TEXTO,
                        font=E.fonte(E.ROTULO + 1, "bold"))
        nome.pack(side="left")
        self._abas_frame = tk.Frame(barra, bg=E.FUNDO)
        self._abas_frame.pack(side="left", padx=(E.px(22), E.px(0)), fill="y")

        fechar = tk.Label(barra, text="×", bg=E.FUNDO, fg=E.APAGADO,
                          font=E.fonte(12), cursor="hand2", padx=E.px(10))
        fechar.pack(side="right", fill="y")
        fechar.bind("<ButtonPress-1>", self._x_apertou)
        fechar.bind("<ButtonRelease-1>", self._x_soltou)
        fechar.bind("<Enter>", lambda _e: fechar.configure(fg=E.ERRO))
        fechar.bind("<Leave>", lambda _e: fechar.configure(fg=E.APAGADO))
        mini = tk.Label(barra, text="–", bg=E.FUNDO, fg=E.APAGADO,
                        font=E.fonte(11), cursor="hand2", padx=E.px(8))
        mini.pack(side="right", fill="y")
        mini.bind("<Button-1>", lambda _e: self.minimizar())
        mini.bind("<Enter>", lambda _e: mini.configure(fg=E.TEXTO))
        mini.bind("<Leave>", lambda _e: mini.configure(fg=E.APAGADO))
        # "segure para sair" em cinza, e o laranja vai tomando as letras uma
        # por uma, do "s" ao "r", no tempo do segurar (pedido dele,
        # 21/set/2026). A letra e monoespacada: o texto laranja por cima
        # (so as primeiras letras) cai exatamente em cima do cinza.
        fonte_dica = E.fonte(E.ROTULO)
        medida = tkfont.Font(font=fonte_dica)
        self._largura_letra = medida.measure("0")
        largura_dica = self._largura_letra * len(DICA_X) + E.px(10)
        self._dica_x = tk.Canvas(barra, width=largura_dica,
                                 height=E.ALTURA_BARRA, bg=E.FUNDO,
                                 highlightthickness=0)
        self._dica_x.pack(side="right", padx=(0, E.px(4)))
        self._fonte_dica = fonte_dica
        self._fonte_negrito = E.fonte(E.ROTULO, "bold")
        fechar.bind("<Enter>", lambda _e: (
            fechar.configure(fg=E.ERRO),
            self._x_apertado_id is None and self._pintar_dica(DICA_X)),
            add="+")
        fechar.bind("<Leave>", lambda _e: (
            fechar.configure(fg=E.APAGADO),
            self._x_apertado_id is None and self._pintar_dica("")),
            add="+")

        arrasto = moldura.Arrasto(self, ao_mover=self._arrastou)
        for pedaco in (barra, nome, marca):
            arrasto.ligar(pedaco)

        tk.Frame(self, bg=E.LINHA, height=1).pack(side="top", fill="x")

        # -- corpo --
        self._corpo = tk.Frame(self, bg=E.LINHA)
        self._corpo.pack(side="top", fill="both", expand=True)
        self._montar_normal()

    def _montar_normal(self) -> None:
        for f in self._corpo.winfo_children():
            f.destroy()
        lista = tk.Frame(self._corpo, bg=E.FUNDO, width=E.LARGURA_LISTA)
        lista.pack(side="left", fill="y")
        lista.pack_propagate(False)
        tk.Frame(self._corpo, bg=E.LINHA, width=1).pack(side="left", fill="y")
        self._area = tk.Frame(self._corpo, bg=E.FUNDO)
        self._area.pack(side="left", fill="both", expand=True)
        self._area.pack_propagate(False)

        dentro = tk.Frame(lista, bg=E.FUNDO)
        dentro.pack(fill="both", expand=True, padx=E.PADDING, pady=E.PADDING)
        E.Rotulo(dentro, "modos").pack(side="top", fill="x", pady=(E.px(0), E.px(8)))
        self._itens = {}
        for chave, rotulo, tecla_de in (("jogo", "espelhar", "alternar_jogo"),
                                        ("extensao", "extensão",
                                         "alternar_extensao")):
            it = E.Item(dentro, rotulo, lambda c=chave: self._escolher_item(c),
                        tecla=self._tecla_do(tecla_de))
            it.pack(side="top", fill="x", pady=(E.px(0), E.px(5)))
            self._itens[chave] = it
        it = E.Item(dentro, "apps", lambda: self._escolher_item("apps"))
        it.pack(side="top", fill="x", pady=(E.px(0), E.px(5)))
        self._itens["apps"] = it
        it = E.Item(dentro, "status", lambda: self._escolher_item("celular"))
        it.pack(side="top", fill="x", pady=(E.px(0), E.px(5)))
        self._itens["celular"] = it
        it = E.Item(dentro, "parear", lambda: self._escolher_item("parear"),
                    marca="conexao")
        it.pack(side="top", fill="x", pady=(E.px(6), E.px(0)))
        self._itens["parear"] = it
        # (r119, 24/set/2026) O nome verde + bateria embaixo do PAREAR SAIU
        # (pedido dele): o nome do celular agora e o titulo da aba do STATUS.

        rodape = tk.Frame(dentro, bg=E.FUNDO)
        rodape.pack(side="bottom", fill="x")
        tk.Frame(rodape, bg=E.LINHA, height=1).pack(side="top", fill="x",
                                                    pady=(E.px(0), E.px(8)))
        it = E.Item(rodape, "opções", lambda: self._escolher_item("opcoes"),
                    rodape=True)
        it.pack(side="top", fill="x")
        self._itens["opcoes"] = it
        self._travar_itens()

        # Teclado: setas andam pela lista (Enter/Espaco escolhem).
        for chave, item in self._itens.items():
            item.bind("<Up>", lambda _e, c=chave: self._focar_item(c, -1))
            item.bind("<Down>", lambda _e, c=chave: self._focar_item(c, +1))

        self._montar_abas()
        self._montar_conteudo()
        self._pre_geracao = getattr(self, "_pre_geracao", 0) + 1
        geracao = self._pre_geracao
        self.after(1500, lambda: self._pre_montar(geracao))

    def _pre_montar(self, geracao: int, tentativa: int = 0) -> None:
        """
        PRIMEIRA VISITA INSTANTANEA (r120): com o programa parado, monta
        escondidas as TELAS_GUARDADAS que ainda nao existem, uma por vez;
        a primeira entrada nelas ja cai no "reaproveitar". Espera a hora
        certa (sem animacao, sem lista enchendo, apps lidos para as telas
        que mostram apps) e desiste depois de ~1 min tentando.
        """
        if geracao != getattr(self, "_pre_geracao", 0) or self.programa._sair:
            return
        pular = self.__dict__.setdefault("_pre_pular", set())
        faltam = [t for t in TELAS_GUARDADAS if t not in self._guardadas
                  and t not in pular
                  and t != getattr(self, "_tela_atual", "")]
        if not faltam or tentativa > 60:
            return
        if not self._visivel:
            # (r122) Montada com a janela escondida, a tela nasce com tamanho
            # zero e a 1a visita mostrava o quadro quebrado (relato dele: "so
            # na primeira vez ao abrir o programa"). Espera a janela aparecer
            # -- sem gastar tentativa.
            self._pre_visivel_desde = None
            self.after(1000, lambda: self._pre_montar(geracao, tentativa))
            return
        # Acabou de aparecer: deixa a animacao de abrir e o 1o clique dele
        # passarem antes de pesar o Tk.
        desde = getattr(self, "_pre_visivel_desde", None)
        if desde is None or time.monotonic() - desde < 0.8:
            if desde is None:
                self._pre_visivel_desde = time.monotonic()
            self.after(400, lambda: self._pre_montar(geracao, tentativa))
            return
        tela = faltam[0]
        precisa_apps = tela in ("_tela_apps_lista", "_tela_opcoes_atalhos")
        ocupado = (self._grande or getattr(self, "_veu", None) is not None
                   or getattr(self, "_lotes_de", None)
                   or self._gravando is not None
                   or (precisa_apps and (self._apps_carregando
                                         or not self._apps)))
        if ocupado:
            self.after(1000, lambda: self._pre_montar(geracao, tentativa + 1))
            return
        if tela == "_tela_apps_lista" and self._falta("apps"):
            pular.add(tela)
            self.after(300, lambda: self._pre_montar(geracao, tentativa + 1))
            return
        salvo = self._ui
        self._ui = {}
        palco = tk.Frame(self._area, bg=E.FUNDO)
        palco.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        palco.lower()
        self._ui["_palco"] = palco
        try:
            getattr(self, tela)(palco)
            palco.update_idletasks()
            if tela == "_tela_apps_lista":
                # Montada escondida, a grade nasceu com a largura chutada e o
                # <Configure> que a corrige so vale para a tela a vista: sem
                # isto a primeira visita remontava a grade na frente dele.
                self._pintar_lista_apps()
                palco.update_idletasks()
            self._guardadas[tela] = (palco, self._ui, self._assinatura(tela))
        except Exception:
            log.exception("falha pre-montando %s", tela)
            pular.add(tela)
            try:
                palco.destroy()
            except tk.TclError:
                pass
        finally:
            self._ui = salvo
        if len(self._guardadas) and not any(
                t not in self._guardadas and t not in pular
                and t != getattr(self, "_tela_atual", "")
                for t in TELAS_GUARDADAS):
            self.programa.anotar("telas prontas de antemao: %s" % ", ".join(
                t[6:] for t in self._guardadas))
        self.after(300, lambda: self._pre_montar(geracao, tentativa + 1))

    def _focar_item(self, de: str, passo: int):
        ordem = ORDEM_DOS_ITENS
        destino = ordem[(ordem.index(de) + passo) % len(ordem)]
        item = self._itens.get(destino)
        if item is not None:
            item.focus_set()
        return "break"

    def _tecla_do(self, acao: str) -> str:
        """O numero da lista: a ultima tecla do atalho da acao ("1")."""
        teclas = atalhos_mod.guardados(self._config).get(acao, "")
        if not teclas:
            # Sem atalho o quadradinho continua, com um traco: os dois modos
            # ficam sempre iguais (ele estranhou um com numero e outro sem).
            return "–"
        return teclas.split("+")[-1].strip()[:3]

    def _montar_abas(self) -> None:
        for w in self._abas_frame.winfo_children():
            w.destroy()
        self._abas_w = []
        if self._grande:
            a = E.Aba(self._abas_frame, "posicionar o celular", lambda: None)
            a.pack(side="left", fill="y", padx=(E.px(0), E.px(16)))
            a.definir(True)
            self._sublinhar(a)
            return
        chaves = [c for c, _r in ABAS[self._item]]
        for chave, rotulo in ABAS[self._item]:
            if (self._item, chave) == ("celular", "status"):
                rotulo = self._aba_celular_rotulo = self._nome_do_celular()
            a = E.Aba(self._abas_frame, rotulo,
                      lambda c=chave: self._escolher_aba(c))
            a.pack(side="left", fill="y", padx=(E.px(0), E.px(16)))
            a.definir(chave == self._aba[self._item])
            if chave == self._aba[self._item]:
                self._sublinhar(a)
            # Teclado: setas trocam de aba.
            k = chaves.index(chave)
            a.bind("<Left>", lambda _e, k=k: self._aba_vizinha(k - 1))
            a.bind("<Right>", lambda _e, k=k: self._aba_vizinha(k + 1))
            self._abas_w.append(a)

    def _aba_vizinha(self, k: int):
        chaves = [c for c, _r in ABAS[self._item]]
        if 0 <= k < len(chaves):
            self._escolher_aba(chaves[k])
        return "break"

    def _focar_aba_escolhida(self) -> None:
        chaves = [c for c, _r in ABAS[self._item]]
        try:
            k = chaves.index(self._aba[self._item])
            self._abas_w[k].focus_set()
        except (ValueError, IndexError, tk.TclError):
            pass

    def _sublinhar(self, aba: tk.Label) -> None:
        """O sublinhado laranja da aba escolhida, grudado embaixo dela."""
        risco = tk.Frame(self._abas_frame, bg=E.ACENTO, height=E.px(2))

        def pos(_e=None):
            try:
                risco.place(in_=aba, relx=0, rely=1.0, y=-E.px(2),
                            relwidth=1.0)
            except tk.TclError:
                pass
        aba.after_idle(pos)

    def _esvaziar_caixas(self) -> None:
        """Trocou de tela: o que foi digitado nas caixas nao fica (pedido
        dele, 23/set/2026)."""
        self._apps_busca = ""
        self._busca_escolha = ""
        self._renomeando = None

    def _escolher_item(self, item: str) -> None:
        if item == self._item:
            return
        if item != "opcoes" and not self._config.instalacao_ok:
            return                          # (r180) travado sem o scrcpy
        self._esvaziar_caixas()
        self._cancelar_gravacao(sem_tela=True)
        self._atalhos_modo = "lista"
        self._item = item
        self._montar_abas()
        # ANIMACAO (pedido dele, 23/set/2026): os modos ficam na esquerda,
        # entao a tela nova sai da borda ESQUERDA para a direita.
        self._montar_conteudo(deslizar=("x", -1))
        # O anel de foco acompanha o item escolhido (clique ou teclado).
        novo = self._itens.get(item)
        if novo is not None:
            novo.focus_set()

    def _escolher_aba(self, aba: str) -> None:
        if aba == self._aba[self._item]:
            return
        self._esvaziar_caixas()
        self._cancelar_gravacao(sem_tela=True)
        # A aba com o foco e destruida ao remontar: o foco volta para a nova.
        foco_nas_abas = self.focus_get() in self._abas_w
        self._aba[self._item] = aba
        self._montar_abas()
        if foco_nas_abas:
            self._focar_aba_escolhida()
        # ...e trocar de ABA puxa de cima para baixo.
        self._montar_conteudo(deslizar=("y", -1))

    def abrir_em(self, item: str, aba: str | None = None) -> None:
        """Poe a janela num item (e aba) antes de mostrar."""
        if item != "opcoes" and not self._config.instalacao_ok:
            item, aba = "opcoes", "geral"     # (r180) travado sem o scrcpy
        self._esvaziar_caixas()
        self._cancelar_gravacao(sem_tela=True)
        self._atalhos_modo = "lista"
        if self._grande:
            self._fechar_grande(animar=False)
        self._item = item
        if aba:
            self._aba[item] = aba
        self._montar_abas()
        self._montar_conteudo()

    def _abrir_parear(self) -> None:
        """O celular nao apareceu: a janela abre direto no parear."""
        self.abrir_em("parear", "procurar")
        self._ja_procurou = False
        self.mostrar()
        self._talvez_procurar()

    def _travar_itens(self) -> None:
        """(r180) SEM O SCRCPY, SO OPCOES (pedido dele): os outros itens da
        lista ficam apagados e nao abrem ate ele ser instalado ou escolhido.
        Chamado ao montar a lista e a cada tela montada (instalou, trocou a
        pasta -> destrava sozinho)."""
        travar = not self._config.instalacao_ok
        for chave, it in getattr(self, "_itens", {}).items():
            if chave != "opcoes" and it.winfo_exists():
                it.travar(travar)

    def _montar_conteudo(self, deslizar=None) -> None:
        """
        Monta a tela do item/aba. `deslizar` = ("x" ou "y", +1/-1): a tela
        nova entra deslizando (troca de aba = de lado, troca de item = de
        cima/baixo). Remontar por causa de um ajuste NAO desliza: seria a
        tela pulando a cada clique.
        """
        self._cancelar_deslize()
        self._travar_itens()
        # SEM PISCAR: a tela nova e montada POR CIMA da velha e so depois a
        # velha sai. Apagar primeiro deixava a area vazia por um instante,
        # e no Windows isso aparece como a aba inteira piscando.
        # ABA APPS INSTANTANEA (r115, 23/set/2026; medicao: a aba era
        # refeita do zero a cada visita, ~350 ms). Saindo da lista de apps
        # por navegacao, a tela so e ESCONDIDA e guardada com o seu `_ui`;
        # voltando, e mostrada de novo e `_pintar_lista_apps` so mexe no que
        # mudou. Remontagem por ajuste (sem `deslizar`) descarta a guardada.
        # (r116) Vale tambem para OPCOES > qualidade e > atalhos; essas
        # guardam uma ASSINATURA do que mostram e, se mudou enquanto
        # estavam escondidas, sao remontadas em vez de reaproveitadas.
        tela = "_tela_%s_%s" % (self._item, self._aba[self._item])
        g = self._guardadas
        for k in [k for k, v in g.items() if not v[0].winfo_exists()]:
            del g[k]
        saindo = self._ui.get("_palco")
        atual = getattr(self, "_tela_atual", "")
        if deslizar and atual in TELAS_GUARDADAS and tela != atual and \
                saindo is not None and saindo.winfo_exists() and \
                (atual != "_tela_apps_lista" or (
                    self._ui.get("rolagem_apps") is not None and
                    not self._falta("apps"))):
            velha = g.pop(atual, None)
            if velha is not None and velha[0] is not saindo:
                velha[0].destroy()
            g[atual] = (saindo, self._ui, self._assinatura(atual))
        guardada = g.get(tela)
        reusar = guardada is not None and bool(deslizar) and \
            not (tela == "_tela_apps_lista" and self._falta("apps")) and \
            guardada[2] == self._assinatura(tela)
        if guardada is not None and not reusar:
            guardada[0].destroy()           # remontagem de verdade
            del g[tela]
        velhas = [f for f in self._area.winfo_children()
                  if all(f is not v[0] for v in g.values())]
        self._pintado = None
        if reusar:
            palco, self._ui, _assin = g.pop(tela)
            palco.place(x=0, y=0, relwidth=1.0, relheight=1.0)
            palco.lower()       # como a nova: so vem pra frente pronta
        else:
            self._ui = {}
            palco = tk.Frame(self._area, bg=E.FUNDO)
            palco.place(x=0, y=0, relwidth=1.0, relheight=1.0)
            # (r117) Montada ATRAS da velha e so vem pra frente pronta: por
            # cima, o Windows mostrava as fileiras pela metade (print dele,
            # atalhos sem nome/icone por um instante).
            palco.lower()
            self._ui["_palco"] = palco
        self._tela_atual = tela
        # CORTINA (23/set/2026): mover a tela inteira deixava restos no
        # Windows (lado cortado, barra de rolagem dupla). Agora a tela nova
        # e montada NO LUGAR, embaixo de um veu da cor do fundo, e o veu
        # recua a partir da borda de onde a tela "vem".
        veu = None
        if deslizar and self._visivel and moldura.animacoes_ligadas():
            veu = tk.Frame(self._area, bg=E.FUNDO)
            veu.place(x=0, y=0, relwidth=1.0, relheight=1.0)
            self._veu = veu
        try:
            if reusar:
                if tela == "_tela_apps_lista":
                    # Largura de agora antes de conferir (a grade depende).
                    palco.update_idletasks()
                    self._pintar_lista_apps()  # so o que mudou enquanto fora
            else:
                getattr(self, tela)(palco)
            if self._item == "apps" and self._falta("apps"):
                self._cortina(palco, "apps", "apps em janela")
        except Exception:
            log.exception("falha montando %s", tela)
            E.Texto(palco, "Não consegui montar esta tela.",
                    cor=E.ERRO).pack(padx=E.PADDING, pady=E.PADDING,
                                     anchor="w")
        self._repintar()
        self._atualizar_previa()
        # (r118) PINTURA CONGELADA NA TROCA: o Windows pintava a tela nova
        # aos pedacos (textos cortados, bordas abertas -- print dele). Com a
        # area travada, ele segue vendo a velha; liberada, pinta tudo junto.
        self._congelar_area(True)
        try:
            try:
                palco.update_idletasks()
                palco.lift()
                if veu is not None:
                    veu.lift()
            except tk.TclError:
                pass
            for f in velhas:
                f.destroy()
            # Guardadas ATRAS da tela atual, no lugar. `place_forget` (r120)
            # trouxe de volta o quadro quebrado na troca (print dele, r121):
            # a trava de pintura nao cobre o remonte. O Tab do teclado nao
            # entra nelas por causa do `_tab` (r121).
            for v in g.values():
                v[0].lower()
        finally:
            self._congelar_area(False, (palco, veu))
        self.after(700, self._conferir_textos)
        if veu is not None:
            self._revelar(veu, *deslizar)

    def _agendar_renovar(self) -> None:
        """Chegaram apps/icones novos ou mudou o visual: as telas guardadas
        sao postas em dia ESCONDIDAS, logo depois, e nao na hora em que ele
        entra nelas (era o "engasgo" da 1a visita -- r121)."""
        if getattr(self, "_renovar_id", None):
            try:
                self.after_cancel(self._renovar_id)
            except Exception:
                pass
        self._renovar_id = self.after(400, self._renovar_guardadas)

    def _renovar_guardadas(self, tentativa: int = 0) -> None:
        self._renovar_id = None
        g = self._guardadas
        if not g or self.programa._sair:
            return
        if getattr(self, "_veu", None) is not None or \
                getattr(self, "_lotes_de", None):
            if tentativa < 30:
                self._renovar_id = self.after(
                    300, lambda: self._renovar_guardadas(tentativa + 1))
            return
        refazer = False
        for tela, (palco, ui, assin) in list(g.items()):
            if not palco.winfo_exists():
                del g[tela]
                continue
            if tela == "_tela_apps_lista":
                salvo = self._ui
                self._ui = ui
                try:
                    self._pintar_lista_apps()
                except Exception:
                    log.exception("falha pondo a lista guardada em dia")
                finally:
                    self._ui = salvo
            elif assin != self._assinatura(tela):
                palco.destroy()
                del g[tela]
                refazer = True
        if refazer:
            self._pre_geracao = getattr(self, "_pre_geracao", 0) + 1
            geracao = self._pre_geracao
            self.after(300, lambda: self._pre_montar(geracao))

    def _tab(self, evento, voltar: bool):
        """
        Tab do teclado como o do Tk, mas sem entrar nas telas guardadas: elas
        ficam atras da tela atual (no lugar, para voltarem prontas) e o Tk
        as trataria como visiveis. (r121)
        """
        escondidas = [str(v[0]) for v in self._guardadas.values()]
        w = evento.widget
        if isinstance(w, str):
            return "break"
        for _ in range(600):
            try:
                w = w.tk_focusPrev() if voltar else w.tk_focusNext()
            except (tk.TclError, KeyError):
                return "break"
            if w is None or w is evento.widget:
                return "break"
            nome = str(w)
            if not any(nome == g or nome.startswith(g + ".")
                       for g in escondidas):
                w.focus_set()
                return "break"
        return "break"

    def _congelar_area(self, travar: bool, pintar=()) -> None:
        """
        Liga/desliga a pintura da area das telas (so no Windows; r118).
        Travada: o Windows nao mostra nada novo ali. Liberada: pinta de uma
        vez SO o que esta a vista (`pintar`: a tela atual e o veu) e o Tk
        termina o que faltava na hora. (r121) Antes repintava a area inteira,
        inclusive as telas guardadas atras -- centenas de blocos a cada
        troca, o "engasgo". Nunca levanta -- falhar aqui so volta ao antigo.
        """
        if not moldura.NO_WINDOWS:
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            h = self._area.winfo_id()
            u.SendMessageW(h, 0x000B, 0 if travar else 1, 0)  # WM_SETREDRAW
            if not travar:
                # INVALIDATE | ERASE | ALLCHILDREN | UPDATENOW
                todos = 0x0001 | 0x0004 | 0x0080 | 0x0100
                alvos = [w for w in pintar if w is not None]
                if not alvos:
                    u.RedrawWindow(h, None, None, todos)
                for w in alvos:
                    try:
                        u.RedrawWindow(w.winfo_id(), None, None, todos)
                    except tk.TclError:
                        pass
                self._area.update_idletasks()
        except Exception:
            log.exception("falha travando a pintura da area")

    def _assinatura(self, tela: str):
        """
        O que a tela guardada mostra (r116): mudou enquanto ela estava
        escondida -> remonta. A lista de apps nao precisa (a pintura dela ja
        compara tudo). Erro aqui = nunca reaproveita (object() != object()).
        """
        try:
            if tela == "_tela_opcoes_qualidade":
                return (repr(self._config.qualidade),
                        getattr(self, "_renomeando", None))
            if tela == "_tela_opcoes_atalhos":
                m = self.motor
                return (repr(list(atalhos_mod.em_ordem(self._config))),
                        repr(self._gravando),
                        getattr(self, "_atalhos_modo", "lista"),
                        repr(m.falhas()) if m is not None and m.disponivel
                        else None,
                        tuple(a[1] for a in (self._apps or [])),
                        self._icones_versao, self._apps_carregando)
        except Exception:
            return object()
        return None

    # -- animacao -------------------------------------------------------------

    def _animar(self, chave: str, duracao_ms: float, a_cada, fim=None) -> None:
        """
        Roda `a_cada(t)` com t de 0 a 1 pelo RELOGIO (ver MS_QUADRO) e chama
        `fim` no final. Uma animacao nova com a mesma chave cancela a velha.
        """
        self._parar_animacao(chave)
        inicio = time.monotonic()

        def passo():
            t = min(1.0, (time.monotonic() - inicio) * 1000.0 / duracao_ms)
            try:
                a_cada(t)
            except tk.TclError:
                self._anims.pop(chave, None)
                return
            if t < 1.0:
                self._anims[chave] = self.after(MS_QUADRO, passo)
            else:
                self._anims.pop(chave, None)
                if fim is not None:
                    fim()

        self._anims[chave] = self.after(MS_QUADRO, passo)

    def _parar_animacao(self, chave: str) -> None:
        ident = self._anims.pop(chave, None)
        if ident is not None:
            try:
                self.after_cancel(ident)
            except Exception:
                pass

    @staticmethod
    def _saida(t: float) -> float:
        """Rapida no comeco, pousando devagar (entradas)."""
        return 1.0 - (1.0 - t) ** 3

    @staticmethod
    def _entrada(t: float) -> float:
        """Devagar no comeco, acelerando (saidas)."""
        return t * t

    @staticmethod
    def _meio(t: float) -> float:
        """Devagar nas duas pontas (mudanca de tamanho)."""
        return t * t * (3.0 - 2.0 * t)

    def _cancelar_deslize(self) -> None:
        self._parar_animacao("deslize")
        veu = getattr(self, "_veu", None)
        self._veu = None
        if veu is not None:
            try:
                veu.destroy()
            except tk.TclError:
                pass

    def _revelar(self, veu: tk.Frame, eixo: str, sinal: int) -> None:
        """
        O veu recua da borda ate sumir, pousando devagar: sinal -1 = a tela
        aparece a partir da esquerda (eixo x) ou de cima (eixo y); +1 = da
        direita / de baixo. A tela embaixo nao se mexe.
        """
        def a_cada(t):
            p = self._saida(t)
            resto = 1.0 - p
            inicio = p if sinal < 0 else 0.0
            if eixo == "x":
                veu.place_configure(relx=inicio, rely=0,
                                    relwidth=resto, relheight=1.0)
            else:
                veu.place_configure(relx=0, rely=inicio,
                                    relwidth=1.0, relheight=resto)

        def fim():
            if getattr(self, "_veu", None) is veu:
                self._veu = None
            try:
                veu.destroy()
            except tk.TclError:
                pass

        veu.lift()
        a_cada(0.0)
        self._animar("deslize", MS_DESLIZE, a_cada, fim)

    def _duas(self, pai) -> tuple[tk.Frame, tk.Frame]:
        caixa = tk.Frame(pai, bg=E.LINHA)
        caixa.pack(fill="both", expand=True)
        esq = tk.Frame(caixa, bg=E.FUNDO)
        esq.place(relx=0, rely=0, relwidth=0.5, relheight=1.0, width=-1)
        dir_ = tk.Frame(caixa, bg=E.FUNDO)
        dir_.place(relx=0.5, rely=0, relwidth=0.5, relheight=1.0)
        a = tk.Frame(esq, bg=E.FUNDO)
        a.pack(fill="both", expand=True, padx=E.PADDING, pady=E.PADDING)
        b = tk.Frame(dir_, bg=E.FUNDO)
        b.pack(fill="both", expand=True, padx=E.PADDING, pady=E.PADDING)
        return a, b

    def _uma(self, pai) -> tk.Frame:
        f = tk.Frame(pai, bg=E.FUNDO)
        f.pack(fill="both", expand=True, padx=E.PADDING, pady=E.PADDING)
        return f

    # -- pecas reaproveitadas --------------------------------------------------

    def _estado(self, pai, chave: str) -> None:
        """O bloco "ESTADO / texto grande. / explicacao" dos modos."""
        E.Rotulo(pai, "estado").pack(side="top", fill="x", pady=(E.px(0), E.px(6)))
        linha = tk.Frame(pai, bg=E.FUNDO)
        linha.pack(side="top", fill="x")
        texto = tk.Label(linha, text="", bg=E.FUNDO, fg=E.TEXTO,
                         font=E.fonte(E.GRANDE))
        texto.pack(side="left")
        ponto = tk.Label(linha, text=".", bg=E.FUNDO, fg=E.ACENTO,
                         font=E.fonte(E.GRANDE))
        ponto.pack(side="left")
        sub = E.Texto(pai, "", largura=E.px(210))
        sub.pack(side="top", fill="x", pady=(E.px(6), E.px(0)))
        self._ui["estado"] = texto
        self._ui["sub"] = sub

    def _medidas(self, pai, pares) -> None:
        caixa = tk.Frame(pai, bg=E.LINHA, highlightthickness=0)
        caixa.pack(side="top", fill="x", pady=(E.px(12), E.px(0)))
        self._ui["medidas"] = []
        for i, (valor, rotulo) in enumerate(pares):
            c = tk.Frame(caixa, bg=E.FUNDO)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 1, 0),
                   pady=1)
            caixa.grid_columnconfigure(i, weight=1, uniform="m")
            v = tk.Label(c, text=valor, bg=E.FUNDO, fg=E.TEXTO,
                         font=E.fonte(E.CORPO + 1), anchor="w")
            v.pack(side="top", fill="x", padx=E.px(6), pady=(E.px(5), E.px(0)))
            tk.Label(c, text=rotulo.upper(), bg=E.FUNDO, fg=E.APAGADO,
                     font=E.fonte(E.ROTULO - 1), anchor="w").pack(
                side="top", fill="x", padx=E.px(6), pady=(E.px(0), E.px(5)))
            self._ui["medidas"].append(v)

    def _caixa(self, pai, texto: str = "", ao_mudar=None,
               ipady: int = 4) -> tk.Entry:
        """
        CAIXA DE TEXTO DA CASA (pedido dele, 23/set/2026): com um x no fim que
        apaga tudo. Quem chama empacota `campo.master` (a moldura).
        """
        moldura = tk.Frame(pai, bg=E.FUNDO_FUNDO, highlightthickness=1,
                           highlightbackground=E.LINHA_FORTE)
        campo = tk.Entry(moldura, font=E.fonte(E.CORPO), bg=E.FUNDO_FUNDO,
                         fg=E.TEXTO, insertbackground=E.TEXTO, relief="flat",
                         highlightthickness=0, bd=0)
        campo.pack(side="left", fill="x", expand=True, ipady=E.px(ipady),
                   padx=(E.px(6), E.px(0)))
        x = tk.Label(moldura, text="×", bg=E.FUNDO_FUNDO, fg=E.APAGADO,
                     font=E.fonte(E.CORPO), cursor="hand2", padx=E.px(8))
        x.pack(side="right", fill="y")

        def limpar(_e=None):
            campo.delete(0, "end")
            if ao_mudar is not None:
                ao_mudar()
            return "break"

        x.bind("<Button-1>", limpar)
        x.bind("<Enter>", lambda _e: x.configure(fg=E.ERRO))
        x.bind("<Leave>", lambda _e: x.configure(fg=E.APAGADO))
        campo.bind("<FocusIn>", lambda _e: moldura.configure(
            highlightbackground=E.ACENTO), add="+")
        campo.bind("<FocusOut>", lambda _e: moldura.configure(
            highlightbackground=E.LINHA_FORTE), add="+")
        if texto:
            campo.insert(0, texto)
        return campo

    def _chave(self, pai, titulo: str, ligado: bool, ao_virar,
               explicacao: str = "", travada: bool = False,
               borda: bool = True) -> E.Chave:
        linha = tk.Frame(pai, bg=E.FUNDO)
        linha.pack(side="top", fill="x")
        textos = tk.Frame(linha, bg=E.FUNDO)
        textos.pack(side="left", fill="x", expand=True, pady=E.px(7))
        tk.Label(textos, text=titulo.upper(), bg=E.FUNDO, fg=E.TEXTO,
                 font=E.fonte(E.PEQUENA), anchor="w").pack(side="top", fill="x")
        if explicacao:
            tk.Label(textos, text=explicacao, bg=E.FUNDO, fg=E.APAGADO,
                     font=E.fonte(E.ROTULO), anchor="w", justify="left",
                     wraplength=E.px(190)).pack(side="top", fill="x")
        c = E.Chave(linha, ligado, ao_virar, travada=travada)
        c.pack(side="right")
        if borda:
            tk.Frame(pai, bg=E.LINHA, height=1).pack(side="top", fill="x")
        return c

    def _fila(self, pai, nome: str, opcoes, valor, ao_escolher) -> E.Segmentado:
        linha = tk.Frame(pai, bg=E.FUNDO)
        linha.pack(side="top", fill="x", pady=(E.px(0), E.px(6)))
        tk.Label(linha, text=nome.upper(), bg=E.FUNDO, fg=E.TEXTO_2,
                 font=E.fonte(E.ROTULO), width=11, anchor="w").pack(side="left")
        s = E.Segmentado(linha, opcoes, valor, ao_escolher)
        s.pack(side="left", fill="x", expand=True)
        return s

    # ==========================================================================
    # ESPELHAR
    # ==========================================================================

    def _perfil_jogo(self) -> dict:
        return self._config.perfil("jogo")

    def _tela_jogo_basico(self, area) -> None:
        esq, dir_ = self._duas(area)
        perfil = self._perfil_jogo()
        conteudo = conteudo_do(perfil)

        self._estado(esq, "jogo")
        acao = E.Botao(esq, "ligar", lambda: self._botao_principal("jogo"),
                       tipo="acao")
        acao.pack(side="top", fill="x", pady=(E.px(14), E.px(0)))
        self._ui["acao"] = acao
        E.Rotulo(esq, "o que vem do celular").pack(side="top", fill="x",
                                                   pady=(E.px(14), E.px(6)))
        if self._falta("som") and conteudo != "imagem":
            perfil["conteudo"] = conteudo = "imagem"
            self._gravou("jogo", "conteudo = imagem (Android sem som no pc)")
        seg = E.Segmentado(esq, CONTEUDOS, conteudo, self._escolheu_conteudo)
        seg.pack(side="top", fill="x")
        if self._falta("som"):
            seg.habilitar(False)
            E.Texto(esq, "som no pc precisa do android %s ou mais novo."
                    % self._falta("som"), cor=E.APAGADO, tamanho=E.ROTULO,
                    largura=E.px(220)).pack(side="top", fill="x",
                                            pady=(E.px(4), E.px(0)))

        # ONDE O SOM TOCA (23/set/2026): o nivel saiu -- a qualidade agora e
        # uma so, em OPCOES > qualidade (o link fica nas medidas, embaixo).
        E.Rotulo(dir_, "onde o som toca").pack(side="top", fill="x",
                                               pady=(E.px(0), E.px(6)))
        opcoes = [o for o in qualidade.ONDE if o[0] != "celular"]
        if self._falta("pc_cel"):
            opcoes = [o for o in opcoes if o[0] != "ambos"]
        onde = qualidade.onde_do_perfil(dict(perfil, audio=dict(
            perfil.get("audio") or {}, ligado=True)))
        s_onde = E.Segmentado(dir_, opcoes, onde, self._escolheu_onde_jogo)
        s_onde.pack(side="top", fill="x", pady=(E.px(0), E.px(6)))
        if conteudo == "imagem" or self._falta("som"):
            s_onde.habilitar(False)
        sessao = perfil.get("sessao") or {}
        self._chave(dir_, "por cima das outras janelas",
                    bool((perfil.get("janela") or {}).get("sempre_no_topo"))
                    and conteudo != "som",
                    lambda v: self.programa.fixar_espelhamento(v, avisar=False),
                    travada=(conteudo == "som"))
        self._chave(dir_, "apagar a tela do celular",
                    bool(sessao.get("apagar_tela")) and conteudo != "som",
                    lambda v: self._virar_campo("jogo", "sessao",
                                                "apagar_tela", v),
                    explicacao=("não vale no só som: você está jogando nele"
                                if conteudo == "som" else
                                "o celular fica de tela preta enquanto espelha"),
                    travada=(conteudo == "som"))
        # As medidas (resolucao/quadros/mb/s) sairam: a fileira de
        # qualidade diz o mesmo e nao cabia tudo (23/set/2026).
        self._fileira_predef(dir_, "jogo")

    def _nome_da_qualidade(self) -> str:
        q = self._config.qualidade
        atual = qualidade.predef_atual(q)
        for c, n, _v, _a, _f in qualidade.todas_predef(q):
            if c == atual:
                return n
        return "ajustada"

    def _fileira_predef(self, pai, nome: str) -> None:
        """
        QUAL PREDEFINICAO ESTE MODO USA (pedido dele, 23/set/2026): padrao =
        a escolhida em OPCOES > qualidade; ou qualquer uma das outras. Criar
        e mudar predefinicao continua so em opcoes.
        """
        perfil = self._config.perfil(nome)
        E.Rotulo(pai, "qualidade").pack(side="top", fill="x",
                                        pady=(E.px(14), E.px(6)))
        todas = qualidade.todas_predef(self._config.qualidade)
        fixas = [(c, n) for c, n, _v, _a, f in todas if f]
        minhas = [(c, _encurtar(n, 11)) for c, n, _v, _a, f in todas
                  if not f]
        # Sem "padrao" (pedido dele, 23/set/2026): aparece marcada a que
        # vale de verdade -- a do modo, senao a de opcoes.
        atual = perfil.get("predef") or \
            qualidade.predef_atual(self._config.qualidade)
        # Duas fileiras: as fixas e, embaixo, as dele (se houver) -- todas
        # numa fileira so nao cabem em meia janela.
        for grupo in (fixas, minhas):
            if grupo:
                E.Segmentado(pai, grupo,
                             atual if atual in dict(grupo) else None,
                             lambda v: self._escolheu_predef_do_modo(
                                 nome, v)).pack(side="top", fill="x",
                                                pady=(E.px(0), E.px(4)))

    def _escolheu_predef_do_modo(self, nome: str, ident: str) -> None:
        perfil = self._config.perfil(nome)
        if ident:
            perfil["predef"] = ident
        else:
            perfil.pop("predef", None)
        self._gravou(nome, "predefinicao = %s" % (ident or "padrao"))
        self._montar_conteudo()

    def _escolheu_onde_jogo(self, onde: str) -> None:
        """Espelhar: o som vem ou nao pelo "o que vem do celular"; aqui so se
        ele toca so no PC ou no PC e no celular."""
        audio = self._perfil_jogo().setdefault("audio", {})
        audio["fonte"] = "playback" if onde == "ambos" else "output"
        audio["duplicar"] = onde == "ambos"
        self._gravou("jogo", "onde o som toca = %s" % onde)

    def _escolheu_onde(self, nome: str, onde: str) -> None:
        qualidade.aplicar_onde(self._config.perfil(nome), onde)
        self._gravou(nome, "onde o som toca = %s" % onde)
        self._montar_conteudo()

    def _opcoes_de_onde(self, com_celular: bool = True) -> list:
        opcoes = list(qualidade.ONDE)
        if not com_celular:
            opcoes = [o for o in opcoes if o[0] != "celular"]
        if self._falta("pc_cel"):
            opcoes = [o for o in opcoes if o[0] != "ambos"]
        return opcoes

    # ==========================================================================
    # EXTENSAO
    # ==========================================================================

    def _perfil_ext(self) -> dict:
        return self._config.perfil("extensao")

    def _monitores(self) -> list[dict]:
        """
        A lista vale por um segundo: arrastar o celular no mapa grande
        redesenha a cada pixel, e perguntar ao Windows a cada vez travava o
        arraste (monitor nao aparece e some nesse intervalo).
        """
        agora = time.monotonic()
        guardada = getattr(self, "_monitores_guardados", None)
        if guardada and agora - guardada[1] < 1.0:
            return guardada[0]
        lista = mon.listar(reserva=(self.winfo_screenwidth(),
                                    self.winfo_screenheight())) or []
        self._monitores_guardados = (lista, agora)
        return lista

    def _borda(self) -> dict:
        return dict(self._perfil_ext().get("borda") or {})

    def _borda_resolvida(self, lista=None) -> dict:
        lista = lista if lista is not None else self._monitores()
        return mon.resolver(lista, self._borda()) if lista else {}

    def _tela_extensao_basico(self, area) -> None:
        esq, dir_ = self._duas(area)
        self._estado(esq, "extensao")
        lista = self._monitores()
        b = self._borda_resolvida(lista)
        valores = self._valores_da_borda(lista, b)
        self._medidas(esq, list(zip(valores, ("monitor", "lado", "altura"))))
        acao = E.Botao(esq, "ligar", lambda: self._botao_principal("extensao"),
                       tipo="acao")
        acao.pack(side="top", fill="x", pady=(E.px(12), E.px(0)))
        self._ui["acao"] = acao

        E.Rotulo(dir_, "onde o celular fica").pack(side="top", fill="x",
                                                   pady=(E.px(0), E.px(6)))
        topo = tk.Frame(dir_, bg=E.FUNDO)
        topo.pack(side="top", fill="x", pady=(E.px(0), E.px(6)))
        if len(lista) > 1:
            E.Segmentado(topo, [(m["nome"], "tela %d" % (k + 1))
                                for k, m in enumerate(lista)],
                         b.get("monitor"), self._escolheu_monitor).pack(
                side="left")
            E.Botao(topo, "identificar", self._identificar_monitores,
                    tipo="discreto").pack(side="right")
        mapa = tk.Canvas(dir_, width=E.px(240), height=E.px(112), bg=E.FUNDO_FUNDO,
                         highlightthickness=1, highlightbackground=E.LINHA)
        mapa.pack(side="top", fill="x")
        self._ui["mapa"] = mapa
        mapa.bind("<Configure>", lambda _e: self._desenhar_mapa_pequeno())
        E.Texto(dir_, "clique numa das quatro vagas. posição exata e "
                      "tamanho: aba personalizar.", cor=E.APAGADO,
                largura=E.px(230)).pack(side="top", fill="x", pady=(E.px(6), E.px(0)))

    def _valores_da_borda(self, lista, b) -> tuple[str, str, str]:
        i = mon.indice_do_monitor(lista, b.get("monitor", "")) if b else None
        if b.get("lado") in ("esquerda", "direita"):
            altura = "em cima" if b.get("centro", 0.5) <= 0.5 else "embaixo"
        else:
            altura = "personal."
        lado = {"esquerda": "esquerda", "direita": "direita",
                "cima": "em cima", "baixo": "embaixo"}.get(b.get("lado", ""),
                                                          "—")
        return ("tela %d" % ((i or 0) + 1), lado, altura)

    def _atualizar_basico(self) -> None:
        """
        Troca de vaga ou de monitor SEM remontar a aba: so o mapa e as tres
        medidas mudam. Remontar fazia a aba inteira piscar (queixa dele).
        """
        lista = self._monitores()
        b = self._borda_resolvida(lista)
        for rotulo, valor in zip(self._ui.get("medidas", []),
                                 self._valores_da_borda(lista, b)):
            try:
                rotulo.configure(text=valor)
            except tk.TclError:
                pass
        self._desenhar_mapa_pequeno()

    def _desenhar_mapa_pequeno(self) -> None:
        c = self._ui.get("mapa")
        if c is None or not c.winfo_exists():
            return
        c.delete("all")
        W, H = max(E.px(120), c.winfo_width()), max(E.px(80), c.winfo_height())
        self._grade(c, W, H, E.px(12))
        lista = self._monitores()
        b = self._borda_resolvida(lista)
        if not b:
            return
        i = mon.indice_do_monitor(lista, b["monitor"])
        m = lista[i]
        livres = mon.lados_livres(lista)
        # o monitor, com espaco dos lados para as vagas
        caixa_l, caixa_a = W - E.px(90), H - E.px(24)
        esc = min(caixa_l / m["l"], caixa_a / m["a"])
        ml, ma = m["l"] * esc, m["a"] * esc
        x0, y0 = (W - ml) / 2, (H - ma) / 2
        x1, y1 = x0 + ml, y0 + ma
        c.create_rectangle(x0, y0, x1, y1, outline=E.TEXTO_2)
        c.create_text(x0 + E.px(6), y0 + E.px(6), text="tela %d" % (i + 1), anchor="nw",
                      fill=E.TEXTO_2, font=E.fonte(E.ROTULO))
        tl, ta = E.px(14), min(E.px(30), ma / 2 - E.px(3))
        for lado, x in (("esquerda", x0 - E.px(6) - tl),
                        ("direita", x1 + E.px(6))):
            livre = (i, lado) in livres
            for alto, y in ((True, y0), (False, y1 - ta)):
                atual = (b["lado"] == lado and
                         ((b["centro"] <= 0.5) == alto))
                tag = "vaga_%s_%d" % (lado, alto)
                if atual:
                    c.create_rectangle(x, y, x + tl, y + ta, outline=E.ACENTO,
                                       fill=E.ACENTO_ESCURO, tags=tag)
                    ex = x1 - E.px(2) if lado == "direita" else x0 - 1
                    c.create_rectangle(ex, y + E.px(2), ex + E.px(3),
                                       y + ta - E.px(2),
                                       fill=E.ACENTO, outline=E.ACENTO)
                else:
                    # PREENCHIDA com o fundo: retangulo vazio no canvas so
                    # recebe o clique na linha da borda -- clicar no meio da
                    # vaga nao fazia nada (queixa dele).
                    c.create_rectangle(x, y, x + tl, y + ta,
                                       outline=("#55535A" if livre
                                                else "#2A2A30"),
                                       fill=E.FUNDO_FUNDO,
                                       dash=(E.px(2), E.px(2)), tags=tag)
                if livre:
                    c.tag_bind(tag, "<Button-1>",
                               lambda _e, l=lado, a=alto: self._escolheu_vaga(
                                   l, a))
                    c.tag_bind(tag, "<Enter>",
                               lambda _e: c.configure(cursor="hand2"))
                    c.tag_bind(tag, "<Leave>",
                               lambda _e: c.configure(cursor=""))
        if b["lado"] in ("cima", "baixo"):
            # posicao personalizada: em cima ou embaixo do monitor
            meio = x0 + ml * b["centro"]
            comp = max(E.px(12), ml * b["tamanho"] * 0.5)
            y = y0 - E.px(16) if b["lado"] == "cima" else y1 + E.px(4)
            c.create_rectangle(meio - comp / 2, y, meio + comp / 2,
                               y + E.px(12),
                               outline=E.ACENTO, fill=E.ACENTO_ESCURO)

    def _grade(self, c, W, H, passo) -> None:
        for x in range(0, int(W), passo):
            c.create_line(x, 0, x, H, fill="#1E1E24", tags="grade")
        for y in range(0, int(H), passo):
            c.create_line(0, y, W, y, fill="#1E1E24", tags="grade")

    def _escolheu_vaga(self, lado: str, alto: bool) -> None:
        b = self._borda_resolvida()
        t = b.get("tamanho", 0.5)
        centro = t / 2 if alto else 1 - t / 2
        self._salvar_borda({"monitor": b.get("monitor"), "lado": lado,
                            "centro": centro, "tamanho": t})
        self._atualizar_basico()

    def _escolheu_monitor(self, nome: str) -> None:
        lista = self._monitores()
        i = mon.indice_do_monitor(lista, nome)
        if i is None:
            return
        b = self._borda_resolvida(lista)
        lado = b.get("lado", "direita")
        livres = mon.lados_livres(lista)
        if (i, lado) not in livres:
            outros = [l for (j, l) in livres if j == i]
            lado = next((l for l in ("direita", "esquerda") if l in outros),
                        outros[0] if outros else lado)
        self._salvar_borda({"monitor": nome, "lado": lado,
                            "centro": b.get("centro", 0.5),
                            "tamanho": b.get("tamanho", 0.5)})
        self._atualizar_basico()

    def _salvar_borda(self, nova: dict, gravar: bool = True) -> None:
        """Grava o lugar do celular SEM perder o estilo guardado junto."""
        perfil = self._perfil_ext()
        borda = dict(perfil.get("borda") or {})
        borda.update({k: v for k, v in nova.items() if v is not None})
        perfil["borda"] = borda
        if gravar:
            ok = self._config.gravar()
            self.programa.anotar(
                "borda: celular em %s/%s, centro %.2f, trecho %.2f%s" % (
                    borda.get("monitor"), borda.get("lado"),
                    float(borda.get("centro", 0)),
                    float(borda.get("tamanho", 0)),
                    "" if ok else " (NAO GRAVOU)"))
            self._conferir_gravacao(ok)
            self.programa.mudou_a_borda()
        self.programa.previa_da_borda(self._visivel, borda)

    def _identificar_monitores(self) -> None:
        """Um numero grande no meio de cada monitor, por dois segundos."""
        for k, m in enumerate(self._monitores()):
            t = tk.Toplevel(self)
            t.overrideredirect(True)
            try:
                t.attributes("-topmost", True)
            except tk.TclError:
                pass
            t.configure(bg=E.FUNDO, highlightthickness=2,
                        highlightbackground=E.ACENTO)
            tk.Label(t, text=str(k + 1), bg=E.FUNDO, fg=E.ACENTO,
                     font=E.fonte(90, "bold")).pack(padx=E.px(40), pady=(E.px(4), E.px(0)))
            tk.Label(t, text="TELA %d" % (k + 1), bg=E.FUNDO, fg=E.TEXTO_2,
                     font=E.fonte(E.CORPO)).pack(pady=(E.px(0), E.px(14)))
            t.update_idletasks()
            l, a = t.winfo_reqwidth(), t.winfo_reqheight()
            t.geometry("+%d+%d" % (m["x"] + (m["l"] - l) // 2,
                                   m["y"] + (m["a"] - a) // 2))
            t.after(2000, t.destroy)

    def _tela_extensao_avancado(self, area) -> None:
        esq, dir_ = self._duas(area)
        perfil = self._perfil_ext()
        E.Rotulo(esq, "onde o som toca").pack(side="top", fill="x",
                                              pady=(E.px(0), E.px(6)))
        E.Segmentado(esq, self._opcoes_de_onde(),
                     qualidade.onde_do_perfil(perfil),
                     lambda v: self._escolheu_onde("extensao", v)).pack(
            side="top", fill="x")
        E.Texto(esq, "celular: o som fica nele. pc: vem para o pc junto "
                     "com o mouse.", cor=E.APAGADO, tamanho=E.ROTULO,
                largura=E.px(230)).pack(side="top", fill="x",
                                        pady=(E.px(6), E.px(0)))
        self._fileira_predef(esq, "extensao")
        if self._falta("som"):
            self._cortina(esq.master, "som", "som do celular no pc")

        controle = perfil.get("controle") or {}
        E.Rotulo(dir_, "controles").pack(side="top", fill="x", pady=(E.px(0), E.px(2)))
        self._chave(dir_, "controle de videogame",
                    bool(controle.get("joystick", True)),
                    lambda v: self._virar_campo("extensao", "controle",
                                                "joystick", v),
                    explicacao="o controle do pc vira controle do celular")
        self._chave(dir_, "teclado e mouse", True, lambda v: None,
                    explicacao="sempre: é o que a extensão faz", travada=True)
        E.Rotulo(dir_, "no celular").pack(side="top", fill="x", pady=(E.px(12), E.px(4)))
        E.Texto(dir_, "volume: ctrl+alt  =  −  0\n"
                      "voltar ao pc: tab 2x ou empurrar a borda\n"
                      "acentos: teclado físico › scrcpy › seu layout",
                largura=E.px(230)).pack(side="top", fill="x")

    def _tela_extensao_personalizar(self, area) -> None:
        esq, dir_ = self._duas(area)
        lista = self._monitores()
        b = self._borda_resolvida(lista)
        borda_toda = self._borda()

        E.Rotulo(esq, "celular na tela").pack(side="top", fill="x", pady=(E.px(0), E.px(6)))
        self._ui["seg_lado"] = self._fila(
            esq, "lado", [("esquerda", "esq"), ("direita", "dir"),
                          ("cima", "cima"), ("baixo", "baixo")],
            b.get("lado"), self._escolheu_lado)
        t = float(b.get("tamanho", 0.5))
        cen = float(b.get("centro", 0.5))
        pos_v = 0.5 if t >= 1 else (cen - t / 2) / max(0.001, 1 - t)
        self._rotulo_valor(esq, "posição", "%d%%" % round(pos_v * 100), "pos")
        E.Deslizador(esq, pos_v, lambda v: self._mexeu_posicao(v, False),
                     lambda v: self._mexeu_posicao(v, True)).pack(
            side="top", fill="x", pady=(E.px(0), E.px(6)))
        self._rotulo_valor(esq, "tamanho da marca",
                           "%d%%" % round(t * 100), "tam")
        E.Deslizador(esq, (t - 0.15) / 0.85,
                     lambda v: self._mexeu_tamanho(v, False),
                     lambda v: self._mexeu_tamanho(v, True)).pack(
            side="top", fill="x", pady=(E.px(0), E.px(6)))
        # O texto entra ANTES no rodape e o mapa ocupa todo o resto da coluna
        # (pedido dele: o mapa crescer e empurrar o texto para baixo).
        E.Texto(esq, "clique no mapa para abrir grande", cor=E.APAGADO).pack(
            side="bottom", fill="x", pady=(E.px(4), 0))
        mapa = tk.Canvas(esq, height=E.px(52), bg=E.FUNDO_FUNDO,
                         highlightthickness=1, highlightbackground=E.LINHA,
                         cursor="hand2")
        mapa.pack(side="top", fill="both", expand=True)
        mapa.bind("<Button-1>", lambda _e: self._abrir_grande())
        mapa.bind("<Configure>", lambda _e: self._desenhar_mapa_mini(mapa))
        self._ui["mapa_mini"] = mapa

        E.Rotulo(dir_, "marca na tela").pack(side="top", fill="x", pady=(E.px(0), E.px(6)))
        tk.Label(dir_, text="COR", bg=E.FUNDO, fg=E.TEXTO_2,
                 font=E.fonte(E.ROTULO), anchor="w").pack(side="top", fill="x")
        cores = tk.Frame(dir_, bg=E.FUNDO)
        cores.pack(side="top", fill="x", pady=(E.px(3), E.px(8)))
        atual = str(borda_toda.get("cor") or "#FF5A1F").upper()
        for cor in E.CORES_DA_MARCA:
            q = tk.Canvas(cores, width=E.px(20), height=E.px(20), bg=E.FUNDO,
                          highlightthickness=1, cursor="hand2",
                          highlightbackground=(E.TEXTO if cor.upper() == atual
                                               else E.FUNDO))
            q.create_rectangle(E.px(3), E.px(3), E.px(18), E.px(18), fill=cor,
                               outline=cor)
            q.pack(side="left", padx=(E.px(0), E.px(4)))
            q.bind("<Button-1>", lambda _e, cc=cor: self._escolheu_cor(cc))
            self._ui.setdefault("cores", []).append((cor.upper(), q))
        mais = tk.Label(cores, text="+", bg=E.FUNDO, fg=E.TEXTO_2,
                        font=E.fonte(E.CORPO), cursor="hand2", width=2,
                        highlightthickness=1, highlightbackground=E.LINHA_FORTE)
        mais.pack(side="left")
        mais.bind("<Button-1>", lambda _e: self._escolher_outra_cor())
        if atual not in [c.upper() for c in E.CORES_DA_MARCA]:
            q = tk.Canvas(cores, width=E.px(20), height=E.px(20), bg=E.FUNDO,
                          highlightthickness=1, highlightbackground=E.TEXTO)
            q.create_rectangle(E.px(3), E.px(3), E.px(18), E.px(18), fill=atual,
                               outline=atual)
            q.pack(side="left", padx=(E.px(4), E.px(0)))
            self._ui["cor_propria"] = q

        transp = float(borda_toda.get("transparencia", 0.45))
        self._rotulo_valor(dir_, "transparência", "%d%%" % round(transp * 100),
                           "transp")
        E.Deslizador(dir_, transp / 0.9,
                     lambda v: self._mexeu_transparencia(v, False),
                     lambda v: self._mexeu_transparencia(v, True)).pack(
            side="top", fill="x", pady=(E.px(0), E.px(6)))
        self._fila(dir_, "espessura", [(2, "2"), (3, "3"), (4, "4"), (6, "6"),
                                       (8, "8")],
                   int(borda_toda.get("espessura", 3)),
                   lambda v: self._salvar_estilo(espessura=int(v)))
        self._chave(dir_, "brilhar ao passar",
                    bool(borda_toda.get("brilhar", True)),
                    lambda v: self._salvar_estilo(brilhar=bool(v)),
                    explicacao="a marca acende quando o mouse troca de tela",
                    borda=False)

    def _rotulo_valor(self, pai, nome: str, valor: str, chave: str) -> None:
        linha = tk.Frame(pai, bg=E.FUNDO)
        linha.pack(side="top", fill="x")
        tk.Label(linha, text=nome.upper(), bg=E.FUNDO, fg=E.TEXTO_2,
                 font=E.fonte(E.ROTULO), anchor="w").pack(side="left")
        v = tk.Label(linha, text=valor, bg=E.FUNDO, fg=E.TEXTO,
                     font=E.fonte(E.ROTULO))
        v.pack(side="right")
        self._ui["val_" + chave] = v

    def _desenhar_mapa_mini(self, c) -> None:
        if not c.winfo_exists():
            return
        c.delete("all")
        W, H = max(E.px(100), c.winfo_width()), max(E.px(40), c.winfo_height())
        self._grade(c, W, H, E.px(10))
        self._desenhar_monitores(c, W, H, margem=E.px(18), rotulos=False)

    def _escolheu_lado(self, lado: str) -> None:
        lista = self._monitores()
        b = self._borda_resolvida(lista)
        i = mon.indice_do_monitor(lista, b.get("monitor", ""))
        if (i, lado) not in mon.lados_livres(lista):
            # Lado encostado em outro monitor: o mouse passaria para ele.
            self.programa.anotar("borda: lado %s ocupado por outro monitor"
                                 % lado)
            seg = self._ui.get("seg_lado")
            if seg is not None:
                seg.definir(b.get("lado"))       # volta, sem piscar a aba
            return
        self._salvar_borda({"lado": lado, "monitor": b.get("monitor"),
                            "centro": b.get("centro", 0.5),
                            "tamanho": b.get("tamanho", 0.5)})
        mapa = self._ui.get("mapa_mini")
        if mapa is not None:
            self._desenhar_mapa_mini(mapa)

    def _mexeu_posicao(self, v: float, soltou: bool) -> None:
        b = self._borda_resolvida()
        t = float(b.get("tamanho", 0.5))
        centro = t / 2 + v * max(0.0, 1 - t)
        self._ui.get("val_pos") and self._ui["val_pos"].configure(
            text="%d%%" % round(v * 100))
        self._salvar_borda(dict(b, centro=centro), gravar=soltou)

    def _mexeu_tamanho(self, v: float, soltou: bool) -> None:
        b = self._borda_resolvida()
        t = 0.15 + v * 0.85
        centro = min(1 - t / 2, max(t / 2, float(b.get("centro", 0.5))))
        self._ui.get("val_tam") and self._ui["val_tam"].configure(
            text="%d%%" % round(t * 100))
        self._salvar_borda(dict(b, tamanho=t, centro=centro), gravar=soltou)

    def _mexeu_transparencia(self, v: float, soltou: bool) -> None:
        tr = round(v * 0.9, 2)
        self._ui.get("val_transp") and self._ui["val_transp"].configure(
            text="%d%%" % round(tr * 100))
        self._salvar_estilo(transparencia=tr, gravar=soltou)

    def _escolheu_cor(self, cor: str) -> None:
        self._salvar_estilo(cor=cor)
        prontas = self._ui.get("cores", [])
        if cor.upper() in [c for c, _q in prontas] and \
                not self._ui.get("cor_propria"):
            for c, q in prontas:
                q.configure(highlightbackground=E.TEXTO if c == cor.upper()
                            else E.FUNDO)
        else:
            self._montar_conteudo()       # cor escolhida a mao: novo quadrado

    def _escolher_outra_cor(self) -> None:
        from tkinter import colorchooser
        atual = str(self._borda().get("cor") or "#FF5A1F")
        try:
            _rgb, hexa = colorchooser.askcolor(color=atual, parent=self,
                                               title="Cor da marca")
        except Exception:
            hexa = None
        if hexa:
            self._escolheu_cor(hexa.upper())

    def _salvar_estilo(self, gravar: bool = True, **campos) -> None:
        perfil = self._perfil_ext()
        borda = dict(perfil.get("borda") or {})
        borda.update(campos)
        perfil["borda"] = borda
        self.programa.aplicar_estilo_da_faixa()
        self.programa.previa_da_borda(self._visivel, borda)
        if gravar:
            ok = self._config.gravar()
            self.programa.anotar("marca: %s%s" % (
                ", ".join("%s=%s" % kv for kv in campos.items()),
                "" if ok else " (NAO GRAVOU)"))
            self._conferir_gravacao(ok)

    # -- monitores desenhados em escala (mini e grande) -----------------------

    def _desenhar_monitores(self, c, W, H, margem: int, rotulos: bool = True):
        """
        Todos os monitores nas posicoes e proporcoes de verdade, mais o
        celular e a marca. Devolve a conversao usada (para o arraste).
        """
        lista = self._monitores()
        if not lista:
            return None
        bx0 = min(m["x"] for m in lista)
        by0 = min(m["y"] for m in lista)
        bx1 = max(m["x"] + m["l"] for m in lista)
        by1 = max(m["y"] + m["a"] for m in lista)
        esc = min((W - 2 * margem) / max(1, bx1 - bx0),
                  (H - 2 * margem) / max(1, by1 - by0))
        ox = (W - (bx1 - bx0) * esc) / 2 - bx0 * esc
        oy = (H - (by1 - by0) * esc) / 2 - by0 * esc
        conv = (esc, ox, oy)
        b = self._borda_resolvida(lista)
        for k, m in enumerate(lista):
            x0, y0 = ox + m["x"] * esc, oy + m["y"] * esc
            x1, y1 = x0 + m["l"] * esc, y0 + m["a"] * esc
            sel = b and m["nome"] == b.get("monitor")
            c.create_rectangle(x0, y0, x1, y1,
                               outline=E.TEXTO if sel else E.TEXTO_2)
            if rotulos:
                c.create_text(x0 + E.px(10), y0 + E.px(10), anchor="nw",
                              text="tela %d" % (k + 1), fill=E.TEXTO if sel
                              else E.TEXTO_2, font=E.fonte(E.CORPO))
                c.create_text(x0 + E.px(10), y0 + E.px(28), anchor="nw",
                              text="%d × %d" % (m["l"], m["a"]),
                              fill=E.APAGADO, font=E.fonte(E.ROTULO))
        alvo = mon.trecho(lista, b) if b else None
        if alvo:
            m, lado, ini, fim = alvo
            grossura = max(E.px(8), min(E.px(46),
                                        0.045 * min(W, H) * (3 if rotulos else 1)))
            folga = E.px(6) if rotulos else E.px(3)
            if lado in ("esquerda", "direita"):
                ya, yb = oy + ini * esc, oy + fim * esc
                if lado == "direita":
                    ex = ox + (m["x"] + m["l"]) * esc
                    c.create_rectangle(ex - 3, ya, ex, yb, fill=E.ACENTO,
                                       outline=E.ACENTO)
                    c.create_rectangle(ex + folga, ya, ex + folga + grossura,
                                       yb, outline=E.ACENTO,
                                       fill=E.ACENTO_ESCURO, tags="celular")
                else:
                    ex = ox + m["x"] * esc
                    c.create_rectangle(ex, ya, ex + 3, yb, fill=E.ACENTO,
                                       outline=E.ACENTO)
                    c.create_rectangle(ex - folga - grossura, ya, ex - folga,
                                       yb, outline=E.ACENTO,
                                       fill=E.ACENTO_ESCURO, tags="celular")
            else:
                xa, xb = ox + ini * esc, ox + fim * esc
                if lado == "baixo":
                    ey = oy + (m["y"] + m["a"]) * esc
                    c.create_rectangle(xa, ey - 3, xb, ey, fill=E.ACENTO,
                                       outline=E.ACENTO)
                    c.create_rectangle(xa, ey + folga, xb, ey + folga + grossura,
                                       outline=E.ACENTO, fill=E.ACENTO_ESCURO,
                                       tags="celular")
                else:
                    ey = oy + m["y"] * esc
                    c.create_rectangle(xa, ey, xb, ey + 3, fill=E.ACENTO,
                                       outline=E.ACENTO)
                    c.create_rectangle(xa, ey - folga - grossura, xb,
                                       ey - folga, outline=E.ACENTO,
                                       fill=E.ACENTO_ESCURO, tags="celular")
        return conv

    # -- o mapa grande ------------------------------------------------------------

    def _abrir_grande(self) -> None:
        """A janela cresce para 960 e vira so o mapa (pedido dele)."""
        if self._grande:
            return
        self._grande = True
        self._cancelar_deslize()
        x, y = self.winfo_x(), self.winfo_y()
        l0, a0 = self.winfo_width(), self.winfo_height()
        largura, altura = self._tamanho_grande()
        nx = x - (largura - E.LARGURA) // 2
        ny = y - (altura - self.winfo_height()) // 2
        nx, ny = self._dentro_da_tela(nx, ny, largura, altura)
        self._pos = (nx, ny)
        for f in self._corpo.winfo_children():
            f.destroy()
        self._montar_abas()
        # A janela cresce VAZIA e o mapa entra no fim: redesenhar os
        # monitores a cada quadro do crescimento deixaria a animacao lenta.
        tk.Frame(self._corpo, bg=E.FUNDO).pack(fill="both", expand=True)
        self._animar_janela((x, y, l0, a0), (nx, ny, largura, altura),
                            self._montar_grande)

    def _montar_grande(self) -> None:
        if not self._grande:
            return
        for f in self._corpo.winfo_children():
            f.destroy()
        fundo = tk.Frame(self._corpo, bg=E.FUNDO)
        fundo.pack(fill="both", expand=True)
        palco = tk.Canvas(fundo, bg=E.FUNDO_FUNDO, highlightthickness=1,
                          highlightbackground=E.LINHA, cursor="fleur")
        palco.pack(side="top", fill="both", expand=True, padx=E.PADDING,
                   pady=(E.PADDING, E.px(8)))
        rodape = tk.Frame(fundo, bg=E.FUNDO)
        rodape.pack(side="top", fill="x", padx=E.PADDING, pady=(0, E.PADDING))
        self._ui = {"palco": palco}
        self._ui["leitura"] = tk.Label(rodape, text="", bg=E.FUNDO, fg=E.TEXTO_2,
                                      font=E.fonte(E.ROTULO + 1), anchor="w")
        self._ui["leitura"].pack(side="left")
        E.Botao(rodape, "pronto", self._fechar_grande, tipo="acao").pack(
            side="right")
        tk.Label(rodape, text="arraste o celular · + e − mudam o "
                              "tamanho · esc volta",
                 bg=E.FUNDO, fg=E.APAGADO, font=E.fonte(E.ROTULO)).pack(
            side="right", padx=E.px(16))
        palco.bind("<Configure>", lambda _e: self._desenhar_grande(True))
        palco.bind("<B1-Motion>", self._arrastou_celular)
        palco.bind("<Button-1>", self._arrastou_celular)
        palco.bind("<ButtonRelease-1>", lambda _e: self._salvar_borda(
            self._borda_resolvida(), gravar=True))
        # Tamanho pelo teclado: + e - (a roda do mouse so rola).
        for tecla, passo in (("<KeyPress-plus>", 120), ("<KeyPress-equal>", 120),
                             ("<KP_Add>", 120), ("<KeyPress-minus>", -120),
                             ("<KP_Subtract>", -120)):
            palco.bind(tecla, lambda _e, d=passo: self._roda_no_grande(
                type("Roda", (), {"delta": d})()))
        palco.focus_set()
        self._atualizar_previa()

    def _desenhar_grande(self, com_grade: bool = False) -> None:
        """
        `com_grade` so quando o palco muda de tamanho: no arraste o fundo
        quadriculado fica e so os monitores e o celular sao refeitos.
        """
        c = self._ui.get("palco")
        if c is None or not c.winfo_exists():
            return
        W, H = c.winfo_width(), c.winfo_height()
        if com_grade or not c.find_withtag("grade"):
            c.delete("all")
            self._grade(c, W, H, E.px(16))
        else:
            c.delete("!grade")
        self._conv = self._desenhar_monitores(c, W, H, margem=E.px(90))
        b = self._borda_resolvida()
        lista = self._monitores()
        i = mon.indice_do_monitor(lista, b.get("monitor", "")) if b else None
        if b:
            self._ui["leitura"].configure(
                text="MONITOR  tela %d    LADO  %s    POSIÇÃO  %d%%    "
                     "TAMANHO  %d%%" % (
                         (i or 0) + 1, b["lado"],
                         round(b["centro"] * 100), round(b["tamanho"] * 100)))

    def _arrastou_celular(self, e) -> None:
        """O celular gruda na beira livre de monitor mais perto do ponteiro."""
        conv = getattr(self, "_conv", None)
        lista = self._monitores()
        if not conv or not lista:
            return
        esc, ox, oy = conv
        px, py = (e.x - ox) / esc, (e.y - oy) / esc      # em pixels reais
        melhor = None
        for i, lado in mon.lados_livres(lista):
            m = lista[i]
            if lado in ("esquerda", "direita"):
                ex = m["x"] if lado == "esquerda" else m["x"] + m["l"]
                ya = min(max(py, m["y"]), m["y"] + m["a"])
                d = abs(px - ex) + abs(py - ya)
                frac = (ya - m["y"]) / m["a"]
            else:
                ey = m["y"] if lado == "cima" else m["y"] + m["a"]
                xa = min(max(px, m["x"]), m["x"] + m["l"])
                d = abs(py - ey) + abs(px - xa)
                frac = (xa - m["x"]) / m["l"]
            if melhor is None or d < melhor[0]:
                melhor = (d, m["nome"], lado, frac)
        if melhor is None:
            return
        _d, nome, lado, frac = melhor
        b = self._borda_resolvida(lista)
        t = float(b.get("tamanho", 0.5))
        centro = min(1 - t / 2, max(t / 2, frac))
        self._salvar_borda({"monitor": nome, "lado": lado, "centro": centro,
                            "tamanho": t}, gravar=False)
        self._desenhar_grande()

    def _roda_no_grande(self, e) -> None:
        b = self._borda_resolvida()
        t = float(b.get("tamanho", 0.5)) + (0.05 if e.delta > 0 else -0.05)
        t = min(1.0, max(0.15, t))
        centro = min(1 - t / 2, max(t / 2, float(b.get("centro", 0.5))))
        # Previa na hora; gravar no disco so quando a roda parar (cada tique
        # gravava o config e escrevia uma linha no relatorio).
        self._salvar_borda(dict(b, tamanho=t, centro=centro), gravar=False)
        self._desenhar_grande()
        if getattr(self, "_roda_id", None) is not None:
            self.after_cancel(self._roda_id)
        self._roda_id = self.after(400, self._roda_parou)

    def _roda_parou(self) -> None:
        self._roda_id = None
        self._salvar_borda(self._borda_resolvida(), gravar=True)

    def _fechar_grande(self, animar: bool = True) -> None:
        if not self._grande:
            return
        self._grande = False
        x, y = self.winfo_x(), self.winfo_y()
        l0, a0 = self.winfo_width(), self.winfo_height()
        altura = E.ALTURA_BARRA + 1 + E.ALTURA_CORPO
        nx = x + (l0 - E.LARGURA) // 2
        ny = y + (a0 - altura) // 2
        nx, ny = self._dentro_da_tela(nx, ny, E.LARGURA, altura)
        self._pos = (nx, ny)
        if not animar or not self._visivel:
            self._parar_anim_janela()
            self.geometry("%dx%d+%d+%d" % (E.LARGURA, altura, nx, ny))
            self._montar_normal()
            return
        for f in self._corpo.winfo_children():
            f.destroy()
        tk.Frame(self._corpo, bg=E.FUNDO).pack(fill="both", expand=True)
        self._animar_janela((x, y, l0, a0), (nx, ny, E.LARGURA, altura),
                            self._montar_normal)

    def _parar_anim_janela(self) -> None:
        self._parar_animacao("janela")

    def _animar_janela(self, de, para, ao_fim) -> None:
        """A janela muda de tamanho e lugar suavemente (de/para = x, y, l, a)."""
        self._parar_anim_janela()
        if not moldura.animacoes_ligadas():
            self.geometry("%dx%d+%d+%d" % (para[2], para[3], para[0], para[1]))
            ao_fim()
            return

        def a_cada(t):
            k = self._meio(t)
            x, y, l, a = (round(d + (p - d) * k) for d, p in zip(de, para))
            self.geometry("%dx%d+%d+%d" % (l, a, x, y))

        self._animar("janela", MS_GRANDE, a_cada, ao_fim)

    def _tamanho_grande(self) -> tuple[int, int]:
        """Em 150% o mapa grande passa de 1400 px: cabe na tela, no maximo."""
        largura = E.LARGURA_GRANDE
        altura = E.ALTURA_BARRA + 1 + E.ALTURA_GRANDE_CORPO
        try:
            _x0, _y0, lu, au = moldura.area_util(self)
            largura = min(largura, lu - E.px(16))
            altura = min(altura, au - E.px(16))
        except Exception:
            pass
        return largura, altura

    def _dentro_da_tela(self, x: int, y: int, l: int, a: int):
        try:
            x0, y0, lu, au = moldura.area_util(self, (x + l // 2, y + a // 2))
        except Exception:
            return x, y
        x = max(x0, min(x, x0 + lu - l))
        y = max(y0, min(y, y0 + au - a))
        return x, y

    # ==========================================================================
    # PAREAR (o antigo Configurar, dentro da janela)
    # ==========================================================================

    # ==========================================================================
    # APPS (em janela propria, tela virtual -- "parecido com o TabDesk")
    # ==========================================================================
    #
    # Pedidos dele (23/set/2026): grade com icone e nome (ou lista), barra
    # de rolagem e os grupos fixados · recentes · todos. Reorganizado no
    # mesmo dia: abas apps · ajustes · personalizados; a qualidade foi para
    # OPCOES > qualidade e os atalhos para OPCOES > atalhos.

    def _tela_apps_lista(self, area) -> None:
        if self._sem_pasta(area):
            return
        area = self._uma(area)            # a mesma margem das outras telas
        topo = tk.Frame(area, bg=E.FUNDO)
        topo.pack(side="top", fill="x")
        E.Botao(topo, "atualizar", lambda: self._carregar_apps(forcar=True),
                tipo="discreto").pack(side="right")
        busca = self._caixa(topo, getattr(self, "_apps_busca", ""),
                            self._buscou_app)
        busca.master.pack(side="left", fill="x", expand=True,
                          padx=(E.px(0), E.px(8)))
        busca.bind("<KeyRelease>", lambda _e: self._buscou_app())
        busca.bind("<Return>", lambda _e: self._abrir_primeiro_app())
        self._ui["busca_apps"] = busca
        aviso = tk.Label(area, text="", bg=E.FUNDO, fg=E.APAGADO,
                         font=E.fonte(E.ROTULO), anchor="w")
        aviso.pack(side="bottom", fill="x", pady=(E.px(4), E.px(0)))
        self._ui["aviso_apps"] = aviso
        caixa = tk.Frame(area, bg=E.FUNDO)
        caixa.pack(side="top", fill="both", expand=True,
                   pady=(E.px(8), E.px(0)))
        rolagem = _Rolagem(caixa)
        # A grade muda o numero de colunas quando a largura aparece.
        rolagem.canvas.bind("<Configure>",
                            lambda _e: self._pintar_lista_apps(), add="+")
        self._ui["rolagem_apps"] = rolagem
        self._apps_pintado = None
        self._pintar_lista_apps()
        # A busca NAO pega o foco sozinha (pedido dele, 23/set/2026).
        if not any(a[1] != DEX for a in (self._apps or [])) and \
                not self._apps_carregando:
            self._carregar_apps()

    def _buscou_app(self) -> None:
        """Filtra 120 ms depois da ultima tecla: montar a grade a cada letra
        pesaria com muitos apps."""
        b = self._ui.get("busca_apps")
        self._apps_busca = b.get() if b is not None else ""
        if getattr(self, "_busca_id", None):
            self.after_cancel(self._busca_id)
        self._busca_id = self.after(120, self._pintar_lista_apps)

    def _apps_filtrados(self) -> list:
        """Os que batem com a busca: os dele, depois os do sistema, por nome."""
        if not self._apps:
            return []
        termo = (getattr(self, "_apps_busca", "") or "").strip().lower()
        itens = [a for a in self._apps if not termo
                 or termo in a[0].lower() or termo in a[1].lower()]
        # So pelo nome (antes os do sistema iam para o fim e a lista parecia
        # fora de ordem -- 23/set/2026).
        itens.sort(key=lambda a: a[0].lower())
        return itens

    def _abrir_primeiro_app(self):
        """Enter na busca: abre (ou traz para a frente) o primeiro da lista."""
        abertos = self.programa.apps_abertos()
        itens = sorted(self._apps_filtrados(),
                       key=lambda a: a[1] not in abertos)
        if itens:
            self._clicou_app(itens[0][1], itens[0][0])
        return "break"

    def _clicou_app(self, pacote: str, nome: str) -> None:
        """Clique: aberto vem para a frente; fechado abre."""
        if self.programa.ativo(APP + pacote):
            self.programa.trazer_app(pacote)
        else:
            self.programa.alternar_app(pacote, nome)
        self._repintar()

    def _fechar_app(self, pacote: str) -> None:
        self.programa.desligar(APP + pacote)
        self._repintar()

    def _configurar_app(self, pacote: str, nome: str) -> None:
        """"personalizar" no menu do app: a aba personalizados abre nele."""
        self._app_configurado = (pacote, nome)
        self._escolhendo_app = False
        if self._aba.get("apps") == "personalizados":
            self._montar_conteudo()
        else:
            self._escolher_aba("personalizados")

    # -- menu do botao direito num app (23/set/2026) ------------------------

    def _menu_do_app(self, evento, pacote: str, nome: str) -> None:
        self._fechar_menu_app()
        fixado = pacote in self._config.fixados()
        jogo = self.programa.e_jogo(pacote)
        menu = tk.Toplevel(self)
        menu.overrideredirect(True)
        menu.attributes("-topmost", True)
        menu.configure(bg=E.LINHA_FORTE)
        corpo = tk.Frame(menu, bg=E.FUNDO_FUNDO)
        corpo.pack(padx=1, pady=1)
        # TELA CHEIA (pedido dele, 24/set/2026): fechado abre em tela cheia
        # (so desta vez); aberto troca pela troca rapida, sem reiniciar.
        p = self.programa
        if pacote == DEX:
            cheia = []
        elif not p.ativo(APP + pacote) and not p.ocupado(APP + pacote):
            cheia = [("abrir em tela cheia", lambda: (
                p.alternar_app(pacote, nome, tela_cheia=True),
                self._repintar()))]
        elif p.em_tela_cheia(pacote):
            cheia = [("sair da tela cheia",
                      lambda: p.reabrir_app(pacote, tela_cheia=False))]
        else:
            cheia = [("tela cheia",
                      lambda: p.reabrir_app(pacote, tela_cheia=True))]
        opcoes = cheia + [
                  ("personalizar", lambda: self._configurar_app(pacote, nome)),
                  ("desafixar" if fixado else "fixar na lista",
                   lambda: self._fixar_app(pacote, not fixado)),
                  ("desmarcar como jogo" if jogo else "marcar como jogo",
                   lambda: self._marcar_jogo(pacote, not jogo)),
                  # (r159) I2 da v1.0: atalho com o nome e o icone do app.
                  ("criar atalho na área de trabalho",
                   lambda: self._criar_atalho_desktop(pacote, nome))]
        for texto, acao in opcoes:
            item = tk.Label(corpo, text=texto, bg=E.FUNDO_FUNDO, fg=E.TEXTO,
                            font=E.fonte(E.PEQUENA), anchor="w",
                            cursor="hand2", padx=E.px(12), pady=E.px(5))
            item.pack(side="top", fill="x")
            item.bind("<Enter>", lambda _e, w=item: w.configure(
                bg=E.LINHA, fg=E.ACENTO))
            item.bind("<Leave>", lambda _e, w=item: w.configure(
                bg=E.FUNDO_FUNDO, fg=E.TEXTO))
            item.bind("<Button-1>", lambda _e, a=acao: (
                self._fechar_menu_app(), a(), "break")[2])
        menu.geometry("+%d+%d" % (evento.x_root + E.px(2),
                                  evento.y_root + E.px(2)))
        menu.bind("<Escape>", lambda _e: self._fechar_menu_app())
        self._menu_app = menu
        self._dica_cancelar()
        self._dica_esconder()

    def _criar_atalho_desktop(self, pacote: str, nome: str) -> None:
        """(r160: o nome _criar_atalho ja era o do atalho de TECLADO, mais
        abaixo -- o de la escondia este e o clique nao fazia nada.)
        Numa thread (o Windows cria o atalho em ~1 s); o aviso de pronto
        vem pela notificacao da bandeja."""
        def trabalho():
            ok, texto = self.programa.criar_atalho(pacote, nome)
            b = self.programa.bandeja
            cfg = self._config
            if ok and b is not None and cfg.opcao("notificacoes") and \
                    cfg.opcao("aviso_atalho"):
                b.notificar("Atalho criado",
                            "%s está na área de trabalho." % nome)
            elif not ok:
                sistema.avisar("Não consegui criar o atalho de %s.\n\n%s"
                               % (nome, texto))

        threading.Thread(target=trabalho, daemon=True,
                         name="atalho-criar").start()

    def _fechar_menu_app(self) -> None:
        menu, self._menu_app = getattr(self, "_menu_app", None), None
        if menu is not None:
            try:
                menu.destroy()
            except tk.TclError:
                pass

    def _marcar_jogo(self, pacote: str, sim: bool) -> None:
        """JOGO (pedido dele, 23/set/2026): abre no formato do monitor do
        pc -- para quando o celular nao diz que o app e jogo."""
        # Igual ao que o celular diz = nao precisa guardar nada.
        detectado = pacote in self.programa.jogos_detectados
        self._virar_app(pacote, "jogo", "" if sim == detectado else sim)
        if self._aba.get("apps") == "personalizados":
            self._montar_conteudo()

    def _fixar_app(self, pacote: str, sim: bool) -> None:
        self._conferir_gravacao(self._config.fixar(pacote, sim))
        self.programa.anotar("app %s: %s" % (pacote,
                                             "fixado" if sim else "desafixado"))
        self._pintar_lista_apps()

    def _clique_em_qualquer_lugar(self, evento) -> None:
        """
        Clique em qualquer lugar da janela: fecha o menu de app (se o clique
        foi fora dele) e tira a selecao/o foco da caixa de texto que nao foi
        clicada (pedido dele, 23/set/2026).
        """
        w = evento.widget
        menu = getattr(self, "_menu_app", None)
        try:
            if menu is not None and not str(w).startswith(str(menu)):
                self._fechar_menu_app()
            foco = self.focus_get()
            if isinstance(foco, tk.Entry) and w is not foco:
                foco.selection_clear()
                if not isinstance(w, tk.Entry):
                    self.focus_set()
        except (tk.TclError, KeyError):
            pass

    def _carregar_apps(self, forcar: bool = False) -> None:
        """
        Pergunta a lista ao celular e depois busca os icones que faltam
        (`forcar`: todos de novo), tudo fora da thread da tela. A lista
        aparece assim que chega, com a letra no lugar do icone; os icones
        entram quando terminam de chegar.
        """
        if self._apps_carregando:
            return
        if not forcar and getattr(self.programa, "apps_do_celular", None):
            self._conferir_cache()
            if any(a[1] != DEX for a in (self._apps or [])):
                return
        self._apps_carregando = True
        self._apps_erro = ""
        self._pintar_lista_apps()
        pasta = self.programa.pasta_de_icones()

        def trabalho():
            try:
                apps, erro = self.programa.listar_apps()
            except Exception as falha:
                log.exception("lista de apps")
                apps, erro = [], "algo deu errado: %s" % falha
            self._da_outra_thread.put(
                lambda: self._apps_chegaram(apps, erro))
            faltam = [p for _n, p, _s in apps
                      if forcar or not (pasta / (p + ".png")).exists()]
            if not faltam:
                return
            self._da_outra_thread.put(lambda: self._icones_buscando_agora(True))
            try:
                self.programa.buscar_icones(faltam)
            except Exception:
                log.exception("icones dos apps")
            self._da_outra_thread.put(lambda: self._icones_buscando_agora(False))

        threading.Thread(target=trabalho, daemon=True, name="apps").start()

    def _conferir_cache(self) -> None:
        """A lista e os icones preparados pelo programa ao conectar entram
        aqui sem ninguem pedir (ver `Programa._preparar_celular`)."""
        p = self.programa
        v = getattr(p, "apps_versao", 0)
        if v != getattr(self, "_apps_versao_vista", 0):
            self._apps_versao_vista = v
            apps = getattr(p, "apps_do_celular", None)
            if apps:
                self._apps_chegaram(list(apps), "")
        v = getattr(p, "icones_versao", 0)
        if v != getattr(self, "_icones_versao_vista", 0):
            self._icones_versao_vista = v
            self._icones_buscando_agora(False)

    def _apps_chegaram(self, apps, erro: str) -> None:
        self._apps_carregando = False
        if apps:
            self._apps = list(apps)
        elif self._apps is None:
            self._apps = []
        self._apps_erro = erro
        self._agendar_renovar()
        self._pintar_lista_apps()
        # Quem lista os apps remonta quando a lista chega.
        if self._gravando is None and (
                (self._item == "apps" and self._aba.get("apps") ==
                 "personalizados") or
                (self._item == "opcoes" and self._aba.get("opcoes") ==
                 "atalhos")):
            self._montar_conteudo()

    def _icones_buscando_agora(self, sim: bool) -> None:
        self._icones_buscando = sim
        if not sim:
            # Chegaram: esquece as imagens montadas (inclusive os "nao tem")
            # e redesenha a lista e os icones do rodape.
            self._fotos.clear()
            self._icones_versao += 1
            self._agendar_renovar()
        self._pintar_lista_apps()

    def _pintar_aviso_apps(self) -> None:
        aviso = self._ui.get("aviso_apps")
        if aviso is None or not aviso.winfo_exists():
            return
        if self._apps_carregando and self._apps:
            texto, cor = "atualizando a lista…", E.APAGADO
        elif self._icones_buscando:
            texto, cor = "buscando os ícones no celular…", E.APAGADO
        elif self._apps_erro and self._apps:
            texto, cor = "✗  " + self._apps_erro, E.ERRO
        else:
            texto, cor = "", E.APAGADO
        if aviso.cget("text") != texto:
            aviso.configure(text=texto, fg=cor)

    def _ligar_cliques(self, pecas, pacote: str, nome: str, borda=None,
                       aberto: bool = False) -> None:
        def clicar(e=None):
            if e is not None:       # o "break" impede o clique geral
                self._clique_em_qualquer_lugar(e)
            self._clicou_app(pacote, nome)
            return "break"

        def ajustar(e=None):
            if e is not None:
                self._clique_em_qualquer_lugar(e)
                self._menu_do_app(e, pacote, nome)
            else:
                self._configurar_app(pacote, nome)
            return "break"

        def entrar(_e=None):
            if borda is not None and not aberto:
                borda.configure(highlightbackground=E.LINHA_FORTE)

        def sair(_e=None):
            if borda is not None and not aberto:
                borda.configure(highlightbackground=E.FUNDO
                                if self._config.apps.get("visual", "grade")
                                == "grade" else E.LINHA)

        for peca in pecas:
            peca.bind("<Button-1>", clicar)
            peca.bind("<Button-3>", ajustar)
            peca.bind("<Enter>", entrar)
            peca.bind("<Leave>", sair)
            # Parar o mouse em cima: o quadro com o uso do app no celular.
            if borda is not None:
                peca.bind("<Enter>", lambda _e: self._dica_entrou(
                    pacote, nome, borda), add="+")
                peca.bind("<Leave>", lambda _e: self._dica_saiu(borda),
                          add="+")

    def _foto(self, pacote: str, lado: int):
        """O icone guardado do app, no tamanho pedido (ou None)."""
        chave = (pacote, lado)
        if chave in self._fotos:
            return self._fotos[chave]
        foto = None
        arquivo = self.programa.pasta_de_icones() / (pacote + ".png")
        if arquivo.exists():
            try:
                from PIL import Image, ImageTk
                filtro = getattr(Image, "Resampling", Image).LANCZOS
                with Image.open(arquivo) as img:
                    pronta = img.convert("RGBA").resize((lado, lado), filtro)
                foto = ImageTk.PhotoImage(pronta, master=self)
            except Exception:
                foto = None
        self._fotos[chave] = foto
        return foto

    def _icone_app(self, pai, pacote: str, nome: str, lado: int) -> tk.Canvas:
        """
        O icone de verdade; sem ele -- ou com os icones desligados em APPS >
        aparencia (pedido dele, 23/set/2026) -- a inicial num quadrado.
        """
        c = tk.Canvas(pai, width=lado, height=lado, bg=E.FUNDO,
                      highlightthickness=0, bd=0)
        foto = None if self._config.apps.get("sem_icones") else \
            self._foto(pacote, lado)
        if foto is not None:
            c.create_image(lado // 2, lado // 2, image=foto)
            return c
        cor = CORES_DE_APP[sum(map(ord, pacote)) % len(CORES_DE_APP)]
        c.create_rectangle(0, 0, lado - 1, lado - 1, fill=cor, width=0)
        c.create_text(lado // 2, lado // 2, text=(nome[:1] or "?").upper(),
                      fill="#FFFFFF",
                      font=E.fonte(E.CORPO if lado >= E.px(30) else E.ROTULO,
                                   "bold"))
        return c

    def _pintar_lista_apps(self) -> None:
        """
        Remonta a lista so quando algo que ela mostra mudou. RAPIDO (23/set/
        2026, "as abas com a lista de apps demoram"):
        - abriu/fechou um app (so a borda muda): refaz SO os blocos daquele
          app, sem mexer no resto;
        - lista nova: os primeiros blocos entram na hora e o resto em lotes,
          sem travar a janela (`_em_lotes`).
        """
        self._pintar_aviso_apps()
        rol = self._ui.get("rolagem_apps")
        if rol is None or not rol.canvas.winfo_exists():
            return
        p = self.programa
        geral = self._config.apps
        itens = self._apps_filtrados()
        abertos = frozenset(p.apps_abertos())
        subindo = frozenset(a[1] for a in itens if p.app_subindo(a[1]))
        visual = geral.get("visual", "grade")
        medidas = self._medidas_dos_apps()
        colunas = self._colunas_de_apps(rol, medidas[0])
        # FIXADOS · RECENTES · TODOS (pedido dele, 23/set/2026), como a tela
        # inicial do celular: fixados na ordem em que ele fixou; recentes =
        # os ultimos abertos, sem repetir fixado; todos = a gaveta inteira.
        fixados = tuple(self._config.fixados())
        recentes = tuple(x for x in self._config.recentes()
                         if x not in fixados)[:APPS_RECENTES]
        base = (self._apps is None, self._apps_carregando, self._apps_erro,
                tuple(a[1] for a in itens), visual, medidas, colunas,
                self._icones_versao, fixados, recentes)
        estado = (abertos, subindo)
        antes = self._apps_pintado
        if antes == (base, estado):
            return
        blocos = getattr(self, "_blocos_app", None) or {}
        if antes is not None and antes[0] == base and blocos and \
                str(rol.canvas) not in getattr(self, "_lotes_de", ()):
            mudou = (antes[1][0] ^ abertos) | (antes[1][1] ^ subindo)
            self._apps_pintado = (base, estado)
            for chave, info in list(blocos.items()):
                if chave[1] in mudou:
                    self._refazer_bloco(chave, info, abertos, subindo)
            return
        # Mesma busca e mesmos grupos = mesmo ponto da rolagem.
        manter = (antes is not None and antes[0][3] == base[3]
                  and antes[0][-2:] == base[-2:])
        self._apps_pintado = (base, estado)
        self._blocos_app = {}
        rol.limpar(manter)
        dentro = rol.dentro
        if not self._apps:
            if self._apps_carregando:
                texto, cor = "lendo os apps do celular…", E.APAGADO
            elif self._apps_erro:
                texto, cor = "✗  " + self._apps_erro, E.ERRO
            else:
                texto, cor = ("nenhum app lido ainda. clique em atualizar.",
                              E.APAGADO)
            E.Texto(dentro, texto, cor=cor, largura=E.px(420)).pack(
                side="top", fill="x")
            return
        if not itens:
            E.Texto(dentro, "nenhum app com esse nome.", cor=E.APAGADO).pack(
                side="top", fill="x")
            return
        por_pacote = {a[1]: a for a in itens}
        grupos = [("fixados", [por_pacote[x] for x in fixados
                               if x in por_pacote]),
                  ("recentes", [por_pacote[x] for x in recentes
                                if x in por_pacote]),
                  ("todos os apps", itens)]
        cheios = [(titulo, lista) for titulo, lista in grupos if lista]
        trabalhos = []
        for i, (titulo, lista) in enumerate(cheios):
            if len(cheios) > 1:
                E.Rotulo(dentro, titulo).pack(
                    side="top", fill="x",
                    pady=(E.px(0) if i == 0 else E.px(10), E.px(4)))
            grupo = tk.Frame(dentro, bg=E.FUNDO)
            grupo.pack(side="top", fill="x")
            for k, (nome, pacote, _sis) in enumerate(lista):
                trabalhos.append((titulo, grupo, k, nome, pacote))
        ctx = (visual, colunas, medidas)

        def fazer(trab):
            titulo, grupo, k, nome, pacote = trab
            w = self._montar_bloco(grupo, k, nome, pacote, abertos, subindo,
                                   ctx)
            self._blocos_app[(titulo, pacote)] = (w, grupo, k, nome, ctx)

        # Na hora so o que cabe na tela (~3 fileiras); o resto em lotes.
        primeiro = max(12, colunas * 3)
        self._em_lotes(rol.canvas, trabalhos, fazer, primeiro=primeiro)

    def _medidas_dos_apps(self) -> tuple:
        """(largura e altura do bloco na grade, icone na grade, icone na
        lista, com icone?) -- tudo vem de APPS > aparencia."""
        geral = self._config.apps
        tam = geral.get("tamanho", "m")
        icone = {"p": E.px(28), "g": E.px(48)}.get(tam, E.px(36))
        na_lista = {"p": E.px(16), "g": E.px(26)}.get(tam, E.px(20))
        # Icones desligados = o quadrado com a letra no lugar do icone
        # (pedido dele, 23/set/2026); o bloco fica do mesmo tamanho.
        com = True
        lado = icone + E.px(40)
        altura = icone + E.px(36)
        return (lado, altura, icone, na_lista, com)

    def _colunas_de_apps(self, rol, lado: int) -> int:
        largura = rol.canvas.winfo_width()
        if largura < E.px(60):
            largura = self._area.winfo_width() - 2 * E.PADDING - E.px(14)
        if largura < E.px(60):
            largura = E.LARGURA - E.LARGURA_LISTA - E.px(50)
        return max(1, largura // lado)

    def _montar_bloco(self, grupo, k, nome, pacote, abertos, subindo, ctx):
        visual, colunas, medidas = ctx
        if visual == "lista":
            return self._linha_de_app(grupo, nome, pacote, pacote in abertos,
                                      pacote in subindo, medidas)
        bloco = self._bloco_de_app(grupo, nome, pacote, pacote in abertos,
                                   pacote in subindo, medidas)
        bloco.grid(row=k // colunas, column=k % colunas,
                   pady=(E.px(0), E.px(2)))
        return bloco

    def _refazer_bloco(self, chave, info, abertos, subindo) -> None:
        """Refaz UM bloco no mesmo lugar (abriu/fechou o app)."""
        velho, grupo, k, nome, ctx = info
        try:
            novo = self._montar_bloco(grupo, k, nome, chave[1], abertos,
                                      subindo, ctx)
            if ctx[0] == "lista":
                novo.pack_configure(after=velho)
            velho.destroy()
        except tk.TclError:
            return
        self._blocos_app[chave] = (novo, grupo, k, nome, ctx)

    def _em_lotes(self, dono, trabalhos, fazer, primeiro: int = 28,
                  lote: int = 24, ao_fim=None) -> None:
        """
        Faz os primeiros `primeiro` na hora e o resto em lotes, um lote por
        volta do Tk: a tela aparece ja com o que cabe nela e o resto chega
        sem travar. Se `dono` sumir (trocou de tela) ou outra lista comecar
        NO MESMO `dono`, para.

        (r120) A vez e POR DONO: com as telas guardadas, sair da lista de
        apps no meio dos lotes e abrir os atalhos (outra lista) parava os
        lotes dos apps para sempre -- a lista guardada voltava pela metade.
        `_lotes_de` = donos com lotes ainda por fazer.
        """
        chave = str(dono)
        geracoes = self.__dict__.setdefault("_lote_geracoes", {})
        pendentes = self.__dict__.setdefault("_lotes_de", set())
        geracao = geracoes.get(chave, 0) + 1
        geracoes[chave] = geracao
        for trab in trabalhos[:primeiro]:
            fazer(trab)
        resto = list(trabalhos[primeiro:])
        if resto:
            pendentes.add(chave)
        else:
            pendentes.discard(chave)

        def parar():
            pendentes.discard(chave)
            if geracoes.get(chave) == geracao:
                geracoes.pop(chave, None)

        def proximo():
            if geracoes.get(chave) != geracao:
                return
            try:
                if not dono.winfo_exists():
                    parar()
                    return
                for trab in resto[:lote]:
                    fazer(trab)
            except tk.TclError:
                parar()
                return
            del resto[:lote]
            if resto:
                self.after(1, proximo)
            else:
                pendentes.discard(chave)
                if ao_fim is not None:
                    ao_fim()

        if resto:
            self.after(1, proximo)
        elif ao_fim is not None:
            self.after(1, ao_fim)       # depois de medir o "na hora"

    def _bloco_de_app(self, pai, nome: str, pacote: str, aberto: bool,
                      subindo: bool, medidas) -> tk.Frame:
        """Um app na grade: icone e nome embaixo (ou so o nome, se os icones
        estiverem desligados); aberto = borda laranja e um x para fechar."""
        lado, altura, icone_px, _na_lista, com = medidas
        bloco = tk.Frame(pai, bg=E.FUNDO, width=lado, height=altura,
                         highlightthickness=1,
                         highlightbackground=E.ACENTO if aberto else E.FUNDO,
                         cursor="hand2")
        bloco.pack_propagate(False)
        pecas = [bloco]
        texto = "abrindo…" if subindo else nome
        cor = E.ACENTO if aberto else E.TEXTO_2
        if com:
            icone = self._icone_app(bloco, pacote, nome, icone_px)
            icone.configure(cursor="hand2")
            icone.pack(side="top", pady=(E.px(7), E.px(3)))
            pecas.append(icone)
            cabe = max(4, (lado - E.px(6)) // self._letra_do_rotulo())
            rotulo = tk.Label(bloco, text=_encurtar(texto, cabe), bg=E.FUNDO,
                              fg=cor, font=E.fonte(E.ROTULO), cursor="hand2")
            rotulo.pack(side="top")
        else:
            rotulo = tk.Label(bloco, text=texto, bg=E.FUNDO, fg=cor,
                              font=E.fonte(E.ROTULO), cursor="hand2",
                              wraplength=lado - E.px(8), justify="center")
            rotulo.pack(expand=True)
        pecas.append(rotulo)
        self._ligar_cliques(pecas, pacote, nome, bloco, aberto)
        if aberto:
            fechar = tk.Label(bloco, text="×", bg=E.FUNDO, fg=E.APAGADO,
                              font=E.fonte(E.CORPO), cursor="hand2")
            fechar.place(relx=1.0, x=-E.px(2), y=E.px(0), anchor="ne")
            fechar.bind("<Enter>", lambda _e: fechar.configure(fg=E.ERRO))
            fechar.bind("<Leave>", lambda _e: fechar.configure(fg=E.APAGADO))
            fechar.bind("<Button-1>",
                        lambda _e: (self._fechar_app(pacote), "break")[1])
        return bloco

    def _letra_do_rotulo(self) -> int:
        """Largura de uma letra da fonte dos nomes (e monoespacada)."""
        if not getattr(self, "_letra_rotulo", 0):
            import tkinter.font as tkfont
            try:
                self._letra_rotulo = max(1, tkfont.Font(
                    root=self, font=E.fonte(E.ROTULO)).measure("M"))
            except Exception:
                self._letra_rotulo = E.px(6)
        return self._letra_rotulo

    def _linha_de_app(self, pai, nome: str, pacote: str, aberto: bool,
                      subindo: bool, medidas) -> None:
        """Um app na lista: icone pequeno, nome e, se aberto, "fechar"."""
        _lado, _alt, _ig, icone_px, com = medidas
        linha = tk.Frame(pai, bg=E.FUNDO, highlightthickness=1,
                         highlightbackground=E.ACENTO if aberto else E.LINHA,
                         cursor="hand2")
        linha.pack(side="top", fill="x", pady=(E.px(0), E.px(3)))
        pecas = [linha]
        if com:
            icone = self._icone_app(linha, pacote, nome, icone_px)
            icone.configure(cursor="hand2")
            icone.pack(side="left", padx=E.px(6), pady=E.px(3))
            pecas.append(icone)
        if aberto:
            E.Botao(linha, "fechar", lambda: self._fechar_app(pacote),
                    tipo="contorno").pack(side="right", padx=E.px(4),
                                          pady=E.px(2))
        rotulo = tk.Label(linha, text=("abrindo…  " if subindo else "")
                          + nome.upper()[:40], bg=E.FUNDO,
                          fg=E.ACENTO if aberto else E.TEXTO,
                          font=E.fonte(E.PEQUENA), anchor="w", cursor="hand2")
        rotulo.pack(side="left", fill="x", expand=True,
                    padx=(E.px(0) if com else E.px(8), E.px(0)),
                    pady=(E.px(0) if com else E.px(6)))
        pecas.append(rotulo)
        self._ligar_cliques(pecas, pacote, nome, linha, aberto)
        return linha

    def _roda_global(self, evento):
        """A roda do mouse rola a lista que estiver debaixo do ponteiro -- no
        Windows a roda vai para quem tem o foco (a busca), e nao para quem
        esta debaixo do ponteiro."""
        try:
            alvo = self.winfo_containing(evento.x_root, evento.y_root)
        except Exception:
            return None
        if alvo is None:
            return None
        for chave in ("rolagem_apps", "rolagem_atalhos", "rolagem_escolha",
                      "rolagem_editor", "rolagem_pers", "rolagem_geral"):
            rol = self._ui.get(chave)
            if rol is not None and rol.canvas.winfo_exists() and \
                    str(alvo).startswith(str(rol.canvas)):
                return rol.roda(evento)
        return None

    # -- APPS > aparencia ------------------------------------------------------

    def _tela_apps_aparencia(self, area) -> None:
        esq, dir_ = self._duas(area)
        geral = self._config.apps
        E.Rotulo(esq, "como mostrar").pack(side="top", fill="x",
                                           pady=(E.px(0), E.px(6)))
        E.Segmentado(esq, [("grade", "grade"), ("lista", "lista")],
                     geral.get("visual", "grade"),
                     lambda v: self._virar_apps("visual", v)).pack(
            side="top", fill="x")
        self._chave(esq, "mostrar os ícones", not geral.get("sem_icones"),
                    lambda v: self._virar_apps("sem_icones", "" if v else True),
                    explicacao="desligado: a letra no lugar do ícone")
        E.Rotulo(esq, "tamanho dos ícones").pack(side="top", fill="x",
                                                 pady=(E.px(10), E.px(6)))
        E.Segmentado(esq, [("p", "pequeno"), ("m", "médio"),
                           ("g", "grande")],
                     geral.get("tamanho", "m"),
                     lambda v: self._virar_apps("tamanho",
                                                "" if v == "m" else v)).pack(
            side="top", fill="x")
        # AO FECHAR A JANELA (pedido dele, 24/set/2026): fecha o app no
        # celular (como tirar dos recentes) ou deixa aberto.
        E.Rotulo(esq, "ao fechar a janela do app").pack(
            side="top", fill="x", pady=(E.px(10), E.px(6)))
        E.Segmentado(esq, AO_FECHAR, geral.get("ao_fechar", "fechar"),
                     lambda v: self._virar_apps(
                         "ao_fechar", "" if v == "fechar" else v)).pack(
            side="top", fill="x")
        E.Texto(esq, "fechar = como tirar o app dos recentes do celular. as "
                     "notificações continuam.",
                cor=E.APAGADO, tamanho=E.ROTULO, largura=E.px(230)).pack(
            side="top", fill="x", pady=(E.px(6), E.px(0)))

        # ONDE O SOM TOCA nos apps (23/set/2026). O som e o do celular
        # inteiro (o Android nao separa por app); de fabrica fica nele.
        caixa_som = tk.Frame(dir_, bg=E.FUNDO)
        caixa_som.pack(side="top", fill="x")
        E.Rotulo(caixa_som, "onde o som toca").pack(
            side="top", fill="x", pady=(E.px(0), E.px(6)))
        E.Segmentado(caixa_som, self._opcoes_de_onde(),
                     geral.get("onde", "celular"),
                     lambda v: self._virar_apps(
                         "onde", "" if v == "celular" else v)).pack(
            side="top", fill="x")
        E.Texto(caixa_som, "vale para todos os apps; cada um pode mudar em "
                           "personalizados. o som é o do celular inteiro.",
                cor=E.APAGADO, tamanho=E.ROTULO, largura=E.px(230)).pack(
            side="top", fill="x", pady=(E.px(6), E.px(0)))
        if self._falta("som"):
            self._cortina(caixa_som, "som", "som do celular no pc", curta=True)
        # TAMANHO DA TELA DO APP (23/set/2026): a do celular ou a do monitor
        # do pc (o jogo abre na resolucao e no formato do monitor).
        E.Rotulo(dir_, "tamanho da tela do app").pack(
            side="top", fill="x", pady=(E.px(14), E.px(6)))
        E.Segmentado(dir_, TELAS_DO_APP, geral.get("tela", "celular"),
                     lambda v: self._virar_apps(
                         "tela", "" if v == "celular" else v)).pack(
            side="top", fill="x")
        E.Texto(dir_, "monitor do pc: o app abre deitado, na resolução do "
                      "monitor principal. app marcado como jogo abre sempre "
                      "assim.",
                cor=E.APAGADO, tamanho=E.ROTULO, largura=E.px(230)).pack(
            side="top", fill="x", pady=(E.px(6), E.px(0)))


    def _linha_de_atalho_livre(self, pai, acao: str, app, recusado: bool):
        """Uma acao que pode ganhar atalho: nome, as teclas (ou "clique para
        definir") e um x para tirar. Clique na linha = gravar."""
        teclas = self._config.atalhos.get(acao, "")
        erro = recusado and bool(teclas)
        linha = tk.Frame(pai, bg=E.FUNDO, highlightthickness=1,
                         highlightbackground=E.ERRO if erro else E.LINHA,
                         cursor="hand2")
        linha.pack(side="top", fill="x", pady=(E.px(0), E.px(4)))
        pecas = [linha]
        if app is not None:
            icone = self._icone_app(linha, app[0], app[1], E.px(16))
            icone.configure(cursor="hand2")
            icone.pack(side="left", padx=(E.px(8), E.px(0)))
            pecas.append(icone)
        rotulo = tk.Label(linha, text=atalhos_mod.rotulo(acao).upper(),
                          bg=E.FUNDO, fg=E.TEXTO, font=E.fonte(E.PEQUENA),
                          anchor="w", cursor="hand2")
        rotulo.pack(side="left", padx=(E.px(8), E.px(0)), pady=E.px(6))
        pecas.append(rotulo)
        if teclas:
            tirar = tk.Label(linha, text="×", bg=E.FUNDO, fg=E.APAGADO,
                             font=E.fonte(E.CORPO), cursor="hand2",
                             padx=E.px(8))
            tirar.pack(side="right")
            tirar.bind("<Enter>", lambda _e: tirar.configure(fg=E.ERRO))
            tirar.bind("<Leave>", lambda _e: tirar.configure(fg=E.APAGADO))
            tirar.bind("<Button-1>", lambda _e: (self._tirar_atalho(acao),
                                                 "break")[1])
        teclas_rot = tk.Label(
            linha, text=teclas.replace("+", " + ").upper() if teclas
            else "clique para definir", bg=E.FUNDO,
            fg=(E.ERRO if erro else E.TEXTO) if teclas else E.APAGADO,
            font=E.fonte(E.ROTULO + (1 if teclas else 0)), cursor="hand2")
        teclas_rot.pack(side="right", padx=(E.px(8), E.px(8) if not teclas
                                            else E.px(0)))
        pecas.append(teclas_rot)
        nome = app[1] if app else None

        def gravar(_e=None):
            self._gravar_atalho_de(acao, nome)
            return "break"

        for peca in pecas:
            peca.bind("<Button-1>", gravar)

    # -- APPS > opcoes ---------------------------------------------------------

    # -- APPS > personalizados (23/set/2026) ---------------------------------
    #
    # Pedido dele: os ajustes de UM app saem de opcoes e ganham aba propria.
    # Entrando: os apps que ja tem ajuste proprio e um "+" para escolher
    # outro; escolhido, os ajustes de imagem e som dele sao editados aqui.
    # Personalizar NAO poe o app em destaque na lista (isso e o "fixar").

    def _nome_do_app(self, pacote: str) -> str:
        for nome, p, _s in (self._apps or []):
            if p == pacote:
                return nome
        return (self._config.apps.get("nomes") or {}).get(pacote) or pacote

    def _tela_apps_personalizados(self, area) -> None:
        f = self._uma(area)
        if self._escolhendo_app:
            cabeca = tk.Frame(f, bg=E.FUNDO)
            cabeca.pack(side="top", fill="x", pady=(E.px(0), E.px(8)))
            E.Botao(cabeca, "‹ voltar", self._voltar_personalizados,
                    tipo="discreto").pack(side="left")
            tk.Label(cabeca, text="ESCOLHA O APP", bg=E.FUNDO, fg=E.TEXTO,
                     font=E.fonte(E.PEQUENA), anchor="w").pack(
                side="left", fill="x", expand=True, padx=(E.px(10), E.px(0)))
            self._escolher_app(f)
            return
        if self._app_configurado:
            self._editor_de_um_app(f, *self._app_configurado)
            return
        topo = tk.Frame(f, bg=E.FUNDO)
        topo.pack(side="top", fill="x", pady=(E.px(0), E.px(8)))
        E.Rotulo(topo, "apps com ajuste próprio").pack(side="left")
        E.Botao(topo, "+  adicionar app", self._trocar_app_configurado,
                tipo="acao").pack(side="right")
        pacotes = sorted(self._config.personalizados(),
                         key=lambda p: self._nome_do_app(p).lower())
        if not pacotes:
            E.Texto(f, "nenhum app personalizado ainda. clique em + para "
                       "escolher um e mudar a imagem e o som só dele.",
                    cor=E.APAGADO, largura=E.px(440)).pack(
                side="top", fill="x", pady=(E.px(6), E.px(0)))
            return
        caixa = tk.Frame(f, bg=E.FUNDO)
        caixa.pack(side="top", fill="both", expand=True)
        rol = _Rolagem(caixa)
        self._ui["rolagem_pers"] = rol
        for pacote in pacotes:
            nome = self._nome_do_app(pacote)
            conf = self._config.app(pacote)
            linha = tk.Frame(rol.dentro, bg=E.FUNDO, highlightthickness=1,
                             highlightbackground=E.LINHA, cursor="hand2")
            linha.pack(side="top", fill="x", pady=(E.px(0), E.px(3)))
            ic = self._icone_app(linha, pacote, nome, E.px(20))
            ic.configure(cursor="hand2")
            ic.pack(side="left", padx=E.px(6), pady=E.px(4))
            rot = tk.Label(linha, text=nome.upper()[:40], bg=E.FUNDO,
                           fg=E.TEXTO, font=E.fonte(E.PEQUENA), anchor="w",
                           cursor="hand2")
            rot.pack(side="left", fill="x", expand=True)
            resumo = tk.Label(linha, text=self._resumo_do_app(conf),
                              bg=E.FUNDO, fg=E.TEXTO_2,
                              font=E.fonte(E.ROTULO), cursor="hand2")
            resumo.pack(side="right", padx=E.px(8))
            for peca in (linha, ic, rot, resumo):
                peca.bind("<Button-1>", lambda _e, p=pacote, n=nome: (
                    self._editar_personalizado(p, n)))
                peca.bind("<Enter>", lambda _e, w=linha: w.configure(
                    highlightbackground=E.ACENTO))
                peca.bind("<Leave>", lambda _e, w=linha: w.configure(
                    highlightbackground=E.LINHA))

    def _resumo_do_app(self, conf: dict) -> str:
        """O que o app tem de proprio, em poucas palavras."""
        partes = []
        if conf.get("predef"):
            for c, n, _v, _a, _f in qualidade.todas_predef(
                    self._config.qualidade):
                if c == conf["predef"]:
                    partes.append(n)
        if conf.get("video_fino"):
            partes.append("imagem")
        if conf.get("audio_fino"):
            partes.append("som")
        if conf.get("onde"):
            partes.append("toca: " + dict(qualidade.ONDE).get(conf["onde"], ""))
        if conf.get("jogo") is True:
            partes.append("jogo")
        elif conf.get("jogo") is False:
            partes.append("não é jogo")
        if conf.get("tela"):
            partes.append("tela " + dict(TELAS_DO_APP).get(conf["tela"], ""))
        return " · ".join(partes)

    def _editar_personalizado(self, pacote: str, nome: str) -> None:
        self._app_configurado = (pacote, nome)
        self._escolhendo_app = False
        self._montar_conteudo()

    def _voltar_personalizados(self) -> None:
        self._app_configurado = None
        self._escolhendo_app = False
        self._montar_conteudo()

    def _limpar_personalizado(self, pacote: str) -> None:
        self._conferir_gravacao(self._config.limpar_app(pacote))
        self.programa.anotar("app %s: tudo volta ao padrao" % pacote)
        self._agendar_reabrir({pacote})
        self._voltar_personalizados()

    def _editor_de_um_app(self, pai, pacote: str, nome: str) -> None:
        """
        Os ajustes de UM app (23/set/2026). Tudo comeca em "padrao" = segue
        OPCOES > qualidade (e APPS > ajustes, no onde o som toca); so o que
        for escolhido aqui vale por cima, so para este app. Uma coluna com
        rolagem: as fileiras tem uma opcao a mais ("padrao") e nao cabem em
        meia largura.
        """
        cabeca = tk.Frame(pai, bg=E.FUNDO)
        cabeca.pack(side="top", fill="x", pady=(E.px(0), E.px(8)))
        E.Botao(cabeca, "‹ voltar", self._voltar_personalizados,
                tipo="discreto").pack(side="left")
        self._icone_app(cabeca, pacote, nome, E.px(20)).pack(
            side="left", padx=(E.px(10), E.px(0)))
        if pacote in self._config.personalizados():
            E.Botao(cabeca, "tirar dos personalizados",
                    lambda: self._limpar_personalizado(pacote),
                    tipo="discreto").pack(side="right")
        tk.Label(cabeca, text=nome.upper(), bg=E.FUNDO, fg=E.TEXTO,
                 font=E.fonte(E.PEQUENA), anchor="w").pack(
            side="left", fill="x", expand=True, padx=(E.px(8), E.px(4)))
        caixa = tk.Frame(pai, bg=E.FUNDO)
        caixa.pack(side="top", fill="both", expand=True)
        rol = _Rolagem(caixa)
        self._ui["rolagem_editor"] = rol
        corpo = rol.dentro
        deste = self._config.app(pacote)
        # SEM "PADRAO" (pedido dele, 23/set/2026): cada fileira mostra
        # marcado o que vale hoje para este app (o de opcoes / apps >
        # ajustes, ou o que ele ja escolheu aqui). Clicar grava so neste app.
        q = self._config.qualidade
        predef = deste.get("predef") or qualidade.predef_atual(q)
        base_v, base_a = qualidade.valores_da_predef(q, deste["predef"]) \
            if deste.get("predef") else (None, None)
        base_v = base_v or (q.get("video") or {})
        base_a = base_a or (q.get("audio") or {})
        fino_v = deste.get("video_fino") or {}
        fino_a = deste.get("audio_fino") or {}

        E.Rotulo(corpo, "predefinição").pack(side="top", fill="x",
                                             pady=(E.px(0), E.px(6)))
        E.Segmentado(corpo, [(c, n) for c, n, _v, _a, _f in
                             qualidade.todas_predef(q)], predef,
                     lambda v: self._mudou_no_app(pacote, "predef", v)).pack(
            side="top", fill="x", pady=(E.px(0), E.px(10)))

        E.Rotulo(corpo, "imagem").pack(side="top", fill="x",
                                       pady=(E.px(0), E.px(6)))
        for ajuste in qualidade.AJUSTES_VIDEO:
            campo = ajuste["campo"]
            self._fila(corpo, NOME_CURTO.get(("video", campo), campo),
                       self._opcoes_curtas(ajuste),
                       fino_v.get(campo, base_v.get(campo)),
                       lambda v, c=campo: self._fino_do_app(pacote, "video",
                                                            c, v))

        caixa_som = tk.Frame(corpo, bg=E.FUNDO)
        caixa_som.pack(side="top", fill="x")
        E.Rotulo(caixa_som, "som").pack(side="top", fill="x",
                                        pady=(E.px(8), E.px(6)))
        codec = fino_a.get("codec", base_a.get("codec"))
        for ajuste in qualidade.AJUSTES_AUDIO:
            campo = ajuste["campo"]
            if campo == "origem":
                continue
            s = self._fila(caixa_som, NOME_CURTO.get(("audio", campo), campo),
                           self._opcoes_curtas(ajuste),
                           fino_a.get(campo, base_a.get(campo)),
                           lambda v, c=campo: self._fino_do_app(pacote, "audio",
                                                                c, v))
            if campo == "bitrate" and codec in qualidade.SEM_TAXA:
                s.habilitar(False)
        E.Rotulo(caixa_som, "onde o som toca").pack(
            side="top", fill="x", pady=(E.px(8), E.px(6)))
        E.Segmentado(caixa_som, self._opcoes_de_onde(),
                     deste.get("onde") or self._config.apps.get("onde")
                     or "celular",
                     lambda v: self._mudou_no_app(pacote, "onde", v)).pack(
            side="top", fill="x", pady=(E.px(0), E.px(6)))
        jogo = self.programa.e_jogo(pacote)
        self._chave(corpo, "é um jogo", jogo,
                    lambda v: self._marcar_jogo(pacote, v),
                    explicacao=("o celular diz que é jogo. " if pacote in
                                self.programa.jogos_detectados else "") +
                    "abre deitado, no formato do monitor do pc",
                    borda=False)
        E.Rotulo(corpo, "tamanho da tela do app").pack(
            side="top", fill="x", pady=(E.px(8), E.px(6)))
        E.Segmentado(corpo, TELAS_DO_APP,
                     deste.get("tela") or ("pc" if jogo else None)
                     or self._config.apps.get("tela") or "celular",
                     lambda v: self._mudou_no_app(pacote, "tela", v)).pack(
            side="top", fill="x", pady=(E.px(0), E.px(6)))
        E.Rotulo(corpo, "ao fechar a janela").pack(
            side="top", fill="x", pady=(E.px(8), E.px(6)))
        E.Segmentado(corpo, AO_FECHAR,
                     deste.get("ao_fechar")
                     or self._config.apps.get("ao_fechar") or "fechar",
                     lambda v: self._mudou_no_app(pacote, "ao_fechar", v)).pack(
            side="top", fill="x", pady=(E.px(0), E.px(6)))
        # (r148) TECLADO DO CELULAR NA JANELA (pedido dele, 25/set/2026):
        # desligado de fabrica, com o aviso de QUANDO ligar.
        self._chave(corpo, "mostrar o teclado do celular",
                    bool(deste.get("teclado_celular")),
                    lambda v: self._virar_app(pacote, "teclado_celular",
                                              True if v else ""),
                    explicacao="ligue só se o app não mostra a caixa de texto "
                               "sem o teclado na tela (ex.: repostar no "
                               "instagram). o teclado do pc continua "
                               "digitando normal.",
                    borda=False)
        E.Texto(corpo, "o que você escolher aqui vale só para este app, e já "
                       "vale na janela aberta.",
                cor=E.APAGADO, tamanho=E.ROTULO, largura=E.px(480)).pack(
            side="top", fill="x", pady=(E.px(4), E.px(0)))
        if self._falta("som"):
            self._cortina(caixa_som, "som", "som do celular no pc", curta=True)

    def _opcoes_curtas(self, ajuste) -> list:
        return [(v, ROTULO_CURTO.get(str(v), ROTULO_CURTO.get(r, r.lower())))
                for v, r in ajuste["opcoes"]]

    def _mudou_no_app(self, pacote: str, campo: str, valor) -> None:
        if campo == "predef":
            # Escolher a predefinicao poe as fileiras todas nela.
            self._config.definir_app(pacote, "video_fino", "")
            self._config.definir_app(pacote, "audio_fino", "")
        self._virar_app(pacote, campo, valor or "")
        if campo == "predef":
            self.after_idle(self._montar_conteudo)

    def _fino_do_app(self, pacote: str, secao: str, campo: str, valor) -> None:
        chave = secao + "_fino"
        fino = dict(self._config.app(pacote).get(chave) or {})
        if valor in (None, ""):
            fino.pop(campo, None)
        else:
            fino[campo] = valor
        self._virar_app(pacote, chave, fino or "")
        if secao == "audio" and campo == "codec":
            self.after_idle(self._montar_conteudo)   # o kb/s acende ou apaga

    # -- versao do Android e a cortina -----------------------------------------
    #
    # Pedido dele (23/set/2026): o que o celular conectado nao faz fica
    # travado atras de uma cortina que tampa tudo, "tipo o FAH" (la, a
    # cortina de APO por cima do card). A versao vem de `Programa.celular`
    # (getprop, lido ao conectar); sem celular lido, nada trava.

    def _sdk(self):
        sdk = (getattr(self.programa, "celular", None) or {}).get("sdk")
        return sdk if isinstance(sdk, int) else None

    def _falta(self, recurso: str):
        """None = o celular faz; senao o Android minimo (texto, "11")."""
        sdk = self._sdk()
        minimo, nome = PRECISA[recurso]
        return nome if sdk is not None and sdk < minimo else None

    def _cortina(self, pai, recurso: str, titulo: str,
                 curta: bool = False) -> tk.Frame:
        """Tampa `pai` inteiro: nada atras recebe clique nem roda."""
        versao = (self.programa.celular or {}).get("android") or \
            str(self._sdk() or "?")
        cortina = tk.Frame(pai, bg=E.FUNDO, cursor="arrow")
        cortina.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        cortina.lift()
        caixa = tk.Frame(cortina, bg=E.FUNDO_FUNDO, highlightthickness=1,
                         highlightbackground=E.LINHA_FORTE)
        caixa.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(caixa, text=titulo.upper() + " · INDISPONÍVEL",
                 bg=E.FUNDO_FUNDO, fg=E.TEXTO,
                 font=E.fonte(E.PEQUENA, "bold")).pack(
            side="top", padx=E.px(14), pady=(E.px(8 if curta else 12),
                                             E.px(3)))
        tk.Label(caixa, text="não funciona no android %s.\nprecisa do "
                 "android %s ou mais novo." % (versao, PRECISA[recurso][1]),
                 bg=E.FUNDO_FUNDO, fg=E.TEXTO_2, font=E.fonte(E.ROTULO),
                 justify="center", wraplength=E.px(260)).pack(
            side="top", padx=E.px(14), pady=(E.px(0),
                                             E.px(8 if curta else 12)))
        for w in (cortina, caixa):
            w.bind("<Button-1>", lambda _e: "break")
        return cortina

    def _trocar_app_configurado(self) -> None:
        self._escolhendo_app = True
        self._montar_conteudo()

    def _escolher_app(self, pai) -> None:
        """Busca + lista curta com rolagem; clique escolhe o app."""
        busca = self._caixa(pai, self._busca_escolha,
                            lambda: pintar(), ipady=3)
        busca.master.pack(side="top", fill="x")
        caixa = tk.Frame(pai, bg=E.FUNDO)
        caixa.pack(side="top", fill="both", expand=True,
                   pady=(E.px(6), E.px(0)))
        rol = _Rolagem(caixa)
        self._ui["rolagem_escolha"] = rol
        if self._apps is None and not self._apps_carregando:
            self._carregar_apps()

        def escolher(pacote, nome):
            self._app_configurado = (pacote, nome)
            self._escolhendo_app = False
            self._montar_conteudo()

        def pintar(_e=None):
            self._busca_escolha = busca.get()
            termo = self._busca_escolha.strip().lower()
            rol.limpar()
            apps = sorted((a for a in (self._apps or [])
                           if not termo or termo in a[0].lower()),
                          key=lambda a: (a[2], a[0].lower()))
            if not self._apps:
                E.Texto(rol.dentro, "lendo os apps do celular…"
                        if self._apps_carregando else "nenhum app lido.",
                        cor=E.APAGADO).pack(side="top", fill="x")
                return
            for nome, pacote, _sis in apps[:80]:
                linha = tk.Frame(rol.dentro, bg=E.FUNDO, cursor="hand2")
                linha.pack(side="top", fill="x", pady=(E.px(0), E.px(2)))
                pecas = [linha]
                if True:
                    ic = self._icone_app(linha, pacote, nome, E.px(16))
                    ic.pack(side="left", padx=(E.px(2), E.px(6)))
                    pecas.append(ic)
                rot = tk.Label(linha, text=nome, bg=E.FUNDO, fg=E.TEXTO_2,
                               font=E.fonte(E.PEQUENA), anchor="w",
                               cursor="hand2")
                rot.pack(side="left", fill="x", expand=True)
                pecas.append(rot)
                for peca in pecas:
                    peca.bind("<Button-1>", lambda _e, pk=pacote, n=nome:
                              escolher(pk, n))

        busca.bind("<KeyRelease>", pintar)
        pintar()
        self.after(30, lambda: busca.winfo_exists() and busca.focus_set())

    def _conferir_textos(self) -> None:
        """
        TEXTO CORTADO (pedido dele, 23/set/2026: "verifique todos os textos
        pra nada cortar nas caixas"). A letra do Windows dele nao e a mesma de
        quem desenha, entao a conferencia roda AQUI, no PC dele: cada texto
        que ficou menor do que precisa vai para o relatorio, uma vez so.
        """
        vistos = getattr(self, "_cortes_anotados", None)
        if vistos is None:
            vistos = self._cortes_anotados = set()
        tela = "%s/%s" % (self._item, self._aba.get(self._item, ""))
        limite = self.winfo_rootx() + self.winfo_width()

        def olhar(w):
            for f in w.winfo_children():
                try:
                    if not f.winfo_ismapped():
                        continue
                    if isinstance(f, tk.Label):
                        texto = str(f.cget("text"))
                        wrap = str(f.cget("wraplength")) not in ("", "0")
                        larg, pede = f.winfo_width(), f.winfo_reqwidth()
                        passa = f.winfo_rootx() + larg > limite + 1
                        if texto.strip() and not wrap and (larg + 1 < pede
                                                           or passa):
                            if (tela, texto) not in vistos:
                                vistos.add((tela, texto))
                                self.programa.anotar(
                                    "TEXTO CORTADO em %s: %r (%d de %d px)"
                                    % (tela, texto, larg, pede))
                except tk.TclError:
                    continue
                olhar(f)

        try:
            olhar(self._area)
        except tk.TclError:
            pass

    def _gravar_atalho_de(self, acao: str, nome=None) -> None:
        if nome and acao.startswith(atalhos_mod.APP):
            pacote = acao[len(atalhos_mod.APP):]
            self._config.apps.setdefault("nomes", {})[pacote] = nome
            atalhos_mod.NOMES_DE_APP[pacote] = nome
        self._criar_atalho(acao)

    def _virar_apps(self, campo: str, valor) -> None:
        self._conferir_gravacao(self._config.definir_apps(campo, valor))
        self.programa.anotar("apps (todos): %s = %s" % (campo, valor))
        self._apps_pintado = None
        self._agendar_renovar()
        if campo in AJUSTES_DA_JANELA_DO_APP:
            self._agendar_reabrir(self.programa.apps_abertos())

    def _agendar_reabrir(self, pacotes) -> None:
        """
        AJUSTE SEM FECHAR A JANELA (r123): os apps abertos afetados reabrem
        sozinhos ~1 s depois do ULTIMO clique -- mexer em varias fileiras
        seguidas nao reabre a cada uma.
        """
        pend = self.__dict__.setdefault("_reabrir_pend", set())
        pend |= set(pacotes)
        if not pend:
            return
        if getattr(self, "_reabrir_id", None):
            try:
                self.after_cancel(self._reabrir_id)
            except Exception:
                pass
        # 250 ms (pedido dele, 24/set/2026; era 1 s).
        self._reabrir_id = self.after(250, self._reabrir_agora)

    def _reabrir_agora(self) -> None:
        self._reabrir_id = None
        pend, self._reabrir_pend = self._reabrir_pend, set()
        abertos = self.programa.apps_abertos()
        for pacote in sorted(pend):
            if pacote in abertos:
                self.programa.reabrir_app(pacote)

    def _virar_app(self, pacote: str, campo: str, valor) -> None:
        antes = pacote in self._config.personalizados()
        self._conferir_gravacao(self._config.definir_app(pacote, campo, valor))
        self.programa.anotar("app %s: %s = %s" % (pacote, campo, valor))
        if campo not in AJUSTES_SEM_REABRIR or (
                campo == "jogo" and not self._config.app(pacote).get("tela")):
            # "jogo" so muda a janela quando decide a tela (sem tela a mao).
            self._agendar_reabrir({pacote})
        # Virou (ou deixou de ser) personalizado: o "voltar tudo ao padrao"
        # aparece/some no editor.
        if antes != (pacote in self._config.personalizados()) and \
                self._aba.get("apps") == "personalizados":
            self.after_idle(self._montar_conteudo)

    # ==========================================================================
    # STATUS DO CELULAR (bateria, disco, RAM, CPU, GPU e o que mais pesa)
    # ==========================================================================
    #
    # Pedido dele (23/set/2026): item proprio na lista, atualizando a cada
    # 750 ms SEM PISCAR. A tela e montada uma vez; depois so os textos e as
    # barras mudam no lugar. Os numeros chegam de `Programa.status_atual`,
    # que dois processos no celular alimentam so enquanto esta tela esta a
    # vista (ver `_conferir_status`).

    LINHAS_DE_PESADOS = 5

    def _tela_celular_status(self, area) -> None:
        esq, dir_ = self._duas(area)
        ui = {}
        E.Rotulo(esq, "bateria").pack(side="top", fill="x")
        linha = tk.Frame(esq, bg=E.FUNDO)
        linha.pack(side="top", fill="x", pady=(E.px(2), E.px(8)))
        ui["bateria"] = tk.Label(linha, text="—", bg=E.FUNDO, fg=E.TEXTO,
                                 font=E.fonte(E.GRANDE))
        ui["bateria"].pack(side="left")
        ui["detalhe"] = tk.Label(linha, text="", bg=E.FUNDO, fg=E.TEXTO_2,
                                 font=E.fonte(E.PEQUENA))
        ui["detalhe"].pack(side="left", padx=(E.px(10), E.px(0)),
                           pady=(E.px(8), E.px(0)))
        for nome in ("disco", "ram", "cpu", "gpu"):
            ui[nome] = self._medidor(esq, nome)
        E.Rotulo(dir_, "o que mais pesa agora").pack(
            side="top", fill="x", pady=(E.px(0), E.px(4)))
        tabela = tk.Frame(dir_, bg=E.FUNDO)
        tabela.pack(side="top", fill="x")
        tabela.grid_columnconfigure(0, weight=1)
        # Largura fixa para CPU e RAM: numero mudando de tamanho nao
        # empurra as colunas (sem tremer a cada 0,75 s).
        tabela.grid_columnconfigure(1, minsize=E.px(38))
        tabela.grid_columnconfigure(2, minsize=E.px(44))
        for col, titulo in enumerate(("app", "cpu", "ram")):
            tk.Label(tabela, text=titulo.upper(), bg=E.FUNDO, fg=E.APAGADO,
                     font=E.fonte(E.ROTULO),
                     anchor="w" if col == 0 else "e").grid(
                row=0, column=col, sticky="ew",
                padx=(E.px(0), E.px(0) if col == 2 else E.px(10)),
                pady=(E.px(0), E.px(3)))
        pesados = []
        for i in range(self.LINHAS_DE_PESADOS):
            trio = []
            for col in range(3):
                rotulo = tk.Label(tabela, text="", bg=E.FUNDO,
                                  fg=E.TEXTO_2 if col == 0 else E.TEXTO,
                                  font=E.fonte(E.PEQUENA),
                                  anchor="w" if col == 0 else "e")
                rotulo.grid(row=i + 1, column=col, sticky="ew",
                            padx=(E.px(0), E.px(0) if col == 2
                                  else E.px(10)), pady=(E.px(0), E.px(2)))
                trio.append(rotulo)
            pesados.append(trio)
        ui["pesados"] = pesados
        ui["aviso"] = E.Texto(dir_, "", cor=E.APAGADO, tamanho=E.ROTULO,
                              largura=E.px(230))
        ui["aviso"].pack(side="bottom", fill="x")
        self._ui["status"] = ui
        self._status_pintado = None
        self._conferir_status()

    def _medidor(self, pai, nome: str) -> dict:
        """Nome e valor numa linha, e uma barra fina embaixo."""
        linha = tk.Frame(pai, bg=E.FUNDO)
        linha.pack(side="top", fill="x", pady=(E.px(4), E.px(2)))
        tk.Label(linha, text=nome.upper(), bg=E.FUNDO, fg=E.APAGADO,
                 font=E.fonte(E.ROTULO)).pack(side="left")
        valor = tk.Label(linha, text="—", bg=E.FUNDO, fg=E.TEXTO,
                         font=E.fonte(E.PEQUENA))
        valor.pack(side="right")
        barra = tk.Canvas(pai, height=E.px(4), bg=E.LINHA,
                          highlightthickness=0, bd=0)
        barra.pack(side="top", fill="x", pady=(E.px(0), E.px(4)))
        cheio = barra.create_rectangle(0, 0, 0, E.px(4), fill=E.ACENTO,
                                       width=0)
        m = {"valor": valor, "barra": barra, "cheio": cheio, "fracao": 0.0}
        barra.bind("<Configure>", lambda _e: self._encher(m))
        return m

    def _encher(self, m: dict) -> None:
        barra, fracao = m["barra"], max(0.0, min(1.0, m["fracao"]))
        cor = E.ERRO if fracao >= 0.9 else (E.ALERTA if fracao >= 0.75
                                            else E.ACENTO)
        try:
            barra.coords(m["cheio"], 0, 0, int(barra.winfo_width() * fracao),
                         E.px(4))
            barra.itemconfigure(m["cheio"], fill=cor)
        except tk.TclError:
            pass

    def _conferir_status(self) -> None:
        """
        Do relogio (100 ms): com a tela "status" a vista, mantem os medidores
        do celular ligados e troca os numeros que mudaram; fora dela, desliga
        os medidores -- o celular so e consultado enquanto se olha.
        """
        ui = self._ui.get("status")
        a_vista = (self._item == "celular" and self._visivel
                   and not self._grande and ui is not None)
        # RELOGIO PROPRIO (r96): isto so rodava quando o estado do programa
        # mudava (`_repintar`), por isso os numeros so trocavam ao sair e
        # entrar na aba. Com a tela a vista, confere de novo a cada 100 ms.
        if a_vista and not getattr(self, "_status_tique", None):
            def tique():
                self._status_tique = None
                self._conferir_status()
            self._status_tique = self.after(100, tique)
        if not a_vista:
            if getattr(self.programa, "_status_procs", None) and \
                    time.monotonic() > getattr(self.programa,
                                               "_status_previa_ate", 0):
                self.programa.desligar_status()
            return
        if self.programa.status_morreu():
            self.programa.anotar("status: medidor caiu; religando")
            self.programa.desligar_status()
            self._status_em = 0.0
        if not getattr(self.programa, "_status_procs", None) and \
                time.monotonic() - self._status_em >= 3.0:
            self._status_em = time.monotonic()
            threading.Thread(target=self.programa.ligar_status, daemon=True,
                             name="status-liga").start()
        s = getattr(self.programa, "status_atual", None)
        if s is self._status_pintado:
            return
        self._status_pintado = s
        try:
            self._pintar_status_celular(ui, s or {})
        except tk.TclError:
            pass

    def _pintar_status_celular(self, ui: dict, s: dict) -> None:
        def por(rotulo, texto, cor=None):
            if rotulo.cget("text") != texto:
                rotulo.configure(text=texto)
            if cor is not None and rotulo.cget("fg") != cor:
                rotulo.configure(fg=cor)

        bat = s.get("bateria")
        por(ui["bateria"], "%d%%" % bat if isinstance(bat, int) else "—",
            E.ALERTA if isinstance(bat, int) and bat <= 15 else E.TEXTO)
        detalhe = []
        if s.get("carregando"):
            detalhe.append("carregando")
        if s.get("temperatura") is not None:
            detalhe.append(("%.1f °C" % s["temperatura"]).replace(".", ","))
        por(ui["detalhe"], " · ".join(detalhe))

        def medir(nome, texto, fracao):
            m = ui[nome]
            por(m["valor"], texto)
            if abs(m["fracao"] - fracao) > 0.001:
                m["fracao"] = fracao
                self._encher(m)

        if s.get("disco_total"):
            livre, total = s["disco_livre"], s["disco_total"]
            medir("disco", "%s livres de %s" % (_gb(livre), _gb(total)),
                  1 - livre / total)
        if s.get("ram_total"):
            usada, total = s["ram_usada"], s["ram_total"]
            medir("ram", "%s de %s" % (_gb(usada), _gb(total)), usada / total)
        for nome in ("cpu", "gpu"):
            if s.get(nome) is not None:
                medir(nome, "%d%%" % s[nome], s[nome] / 100.0)

        nomes = {a[1]: a[0] for a in (self._apps or [])}
        pesados = s.get("pesados") or []
        for i, (rot_nome, rot_cpu, rot_ram) in enumerate(ui["pesados"]):
            if i < len(pesados):
                processo, cpu, ram = pesados[i]
                bruto = processo.split("/")[-1].split(":")[0]
                por(rot_nome, _encurtar(nomes.get(bruto, bruto), 22))
                # Media de ~2 s dividida pelos nucleos: app leve fica abaixo
                # de 1%; com uma casa ele nao aparece sempre como "0%".
                texto_cpu = ("%.0f%%" % cpu) if cpu >= 10 else \
                    ("%.1f%%" % cpu).replace(".", ",")
                por(rot_cpu, texto_cpu, E.ACENTO if cpu >= 20 else E.TEXTO)
                por(rot_ram, ram)
            else:
                por(rot_nome, "")
                por(rot_cpu, "")
                por(rot_ram, "")
        if s.get("erro"):
            por(ui["aviso"], "✗  " + s["erro"], E.ERRO)
        elif not s:
            por(ui["aviso"], "lendo o celular…", E.APAGADO)
        else:
            por(ui["aviso"], "ao vivo · a cada 0,25 s com esta tela aberta",
                E.APAGADO)

    # -- quadro de uso de um app (parar o mouse em cima) ------------------------

    def _dica_entrou(self, pacote: str, nome: str, dono) -> None:
        self._dica_cancelar()
        self._dica_id = self.after(600, lambda: self._dica_mostrar(
            pacote, nome, dono))

    def _dica_saiu(self, dono) -> None:
        # Passar do bloco para o icone ou o nome dentro dele nao conta.
        try:
            x, y = self.winfo_pointerxy()
            alvo = self.winfo_containing(x, y)
            if alvo is not None and str(alvo).startswith(str(dono)):
                return
        except Exception:
            pass
        self._dica_cancelar()
        self._dica_esconder()

    def _dica_cancelar(self) -> None:
        if self._dica_id:
            try:
                self.after_cancel(self._dica_id)
            except Exception:
                pass
            self._dica_id = None

    def _dica_esconder(self) -> None:
        if self._dica is not None:
            try:
                self._dica.destroy()
            except Exception:
                pass
            self._dica = None
            self._dica_de = None

    def _dica_mostrar(self, pacote: str, nome: str, dono) -> None:
        self._dica_id = None
        if not dono.winfo_exists():
            return
        self._dica_esconder()
        dica = tk.Toplevel(self)
        dica.overrideredirect(True)
        dica.attributes("-topmost", True)
        dica.configure(bg=E.LINHA_FORTE)
        corpo = tk.Frame(dica, bg=E.FUNDO_FUNDO)
        corpo.pack(padx=1, pady=1)
        tk.Label(corpo, text=nome.upper(), bg=E.FUNDO_FUNDO, fg=E.TEXTO,
                 font=E.fonte(E.PEQUENA), anchor="w").pack(
            side="top", fill="x", padx=E.px(8), pady=(E.px(5), E.px(1)))
        texto = tk.Label(corpo, text="lendo o uso…", bg=E.FUNDO_FUNDO,
                         fg=E.TEXTO_2, font=E.fonte(E.ROTULO), anchor="w",
                         justify="left")
        texto.pack(side="top", fill="x", padx=E.px(8), pady=(E.px(0),
                                                             E.px(6)))
        x, y = self.winfo_pointerxy()
        dica.geometry("+%d+%d" % (x + E.px(14), y + E.px(16)))
        self._dica = dica
        self._dica_de = pacote

        guardado = self._uso_cache.get(pacote)
        if guardado and time.monotonic() - guardado[0] < 3.0:
            self._dica_texto(pacote, guardado[1], texto)

        # AO VIVO (pedido dele, 23/set/2026): enquanto o quadro estiver
        # aberto, le de novo assim que a leitura anterior termina (cada uma
        # leva ~1 s no celular). Fechou o quadro ou mudou de app, para.
        def trabalho():
            try:
                uso = self.programa.uso_do_app(pacote)
            except Exception:
                uso = {}
            self._da_outra_thread.put(lambda: chegou(uso))

        def chegou(uso):
            self._uso_cache[pacote] = (time.monotonic(), uso)
            self._dica_texto(pacote, uso, texto)
            if self._dica is dica and self._dica_de == pacote and \
                    uso and not uso.get("parado") and pacote != DEX:
                self.after(250, lambda: (
                    self._dica is dica and self._dica_de == pacote and
                    threading.Thread(target=trabalho, daemon=True,
                                     name="uso").start()))

        threading.Thread(target=trabalho, daemon=True, name="uso").start()

    def _dica_texto(self, pacote: str, uso: dict, rotulo) -> None:
        if self._dica_de != pacote or not rotulo.winfo_exists():
            return
        if pacote == DEX:
            texto = "a área de trabalho do samsung,\nnuma janela do pc"
        elif not uso:
            texto = "não consegui ler agora"
        elif uso.get("parado"):
            texto = "não está rodando no celular"
        else:
            texto = ("cpu %s   ram %s\nmemória de vídeo %s" % (
                ("%.0f%%" % uso.get("cpu", 0)), _mb(uso.get("ram", 0)),
                _mb(uso.get("video", 0))))
        rotulo.configure(text=texto)

    def _pasta_ok(self) -> bool:
        ok, _t = conexao.conferir_pasta(self._config.scrcpy)
        return ok

    def _sem_pasta(self, area) -> bool:
        """Sem o scrcpy nao da para parear: a tela manda para opcoes."""
        if self._pasta_ok():
            return False
        f = self._uma(area)
        E.Rotulo(f, "falta o scrcpy").pack(side="top", fill="x", pady=(E.px(0), E.px(6)))
        E.Texto(f, "primeiro escolha a pasta do scrcpy: é ele que conversa "
                   "com o celular.", cor=E.ALERTA, tamanho=E.CORPO,
                largura=E.px(440)).pack(side="top", fill="x")
        E.Botao(f, "ir para a pasta do scrcpy",
                lambda: self.abrir_em("opcoes", "geral"), tipo="acao").pack(
            side="top", anchor="w", pady=(E.px(14), E.px(0)))
        return True

    def _status(self, pai) -> None:
        texto, cor = self._status_parear
        s = E.Texto(pai, texto, cor=cor, largura=E.px(230))
        s.pack(side="top", fill="x", pady=(E.px(10), E.px(0)))
        self._ui["status"] = s

    def _pintar_status(self, texto: str, cor: str = E.TEXTO_2) -> None:
        self._status_parear = (texto, cor)
        s = self._ui.get("status")
        if s is not None:
            try:
                s.configure(text=texto, fg=cor)
            except tk.TclError:
                pass

    def _tela_parear_procurar(self, area) -> None:
        if self._sem_pasta(area):
            return
        esq, dir_ = self._duas(area)
        E.Rotulo(esq, "celular que o pc já alcança").pack(side="top", fill="x",
                                                          pady=(E.px(0), E.px(6)))
        E.Texto(esq, "pelo cabo ou sem fio, pareado antes — para usar sem "
                     "parear de novo.", largura=E.px(230)).pack(side="top", fill="x")
        b = E.Botao(esq, "procurar", self._procurar, tipo="acao")
        b.pack(side="top", fill="x", pady=(E.px(14), E.px(0)))
        b.definir(ligado=not self._trabalhando)
        self._ui["acao_parear"] = b
        self._status(esq)
        if self._config.ip_reserva and not self._status_parear[0]:
            self._pintar_status("último celular: %s" % self._config.ip_reserva,
                                E.APAGADO)

        E.Rotulo(dir_, "achados").pack(side="top", fill="x", pady=(E.px(0), E.px(6)))
        lista = tk.Frame(dir_, bg=E.FUNDO)
        lista.pack(side="top", fill="both", expand=True)
        self._ui["lista_parear"] = lista
        self._mostrar_achados()
        self.after(150, self._talvez_procurar)

    def _mostrar_achados(self) -> None:
        lista = self._ui.get("lista_parear")
        if lista is None or not lista.winfo_exists():
            return
        for f in lista.winfo_children():
            f.destroy()
        if self._achados is None:
            E.Texto(lista, "procurando…" if self._trabalhando else
                    "nada procurado ainda.", cor=E.APAGADO).pack(
                side="top", fill="x")
            return
        if not self._achados:
            E.Texto(lista, "nenhum celular apareceu. confira se a depuração "
                           "usb ou sem fio está ativada no celular, ou use as "
                           "abas cabo usb / código.", cor=E.APAGADO,
                    largura=E.px(230)).pack(side="top", fill="x")
            return
        for achado in self._achados[:5]:
            linha = tk.Frame(lista, bg=E.FUNDO, highlightthickness=1,
                             highlightbackground=E.LINHA)
            linha.pack(side="top", fill="x", pady=(E.px(0), E.px(5)))
            E.Botao(linha, "usar", lambda a=achado: self._usar(a),
                    tipo="acao" if len(self._achados) == 1 else "contorno"
                    ).pack(side="right", padx=E.px(4), pady=E.px(4))
            textos = tk.Frame(linha, bg=E.FUNDO)
            textos.pack(side="left", fill="x", expand=True, padx=E.px(8), pady=E.px(4))
            tk.Label(textos, text=achado.modelo.upper(), bg=E.FUNDO,
                     fg=E.TEXTO, font=E.fonte(E.PEQUENA), anchor="w").pack(
                side="top", fill="x")
            tk.Label(textos, text=("sem fio" + (" · %s" % achado.endereco
                                                if achado.endereco else ""))
                     if achado.sem_fio else "pelo cabo", bg=E.FUNDO,
                     fg=E.APAGADO, font=E.fonte(E.ROTULO), anchor="w").pack(
                side="top", fill="x")

    def _conectar_ao_abrir(self) -> None:
        """
        A mesma procura da aba "procurar", sozinha, logo depois de abrir. Com
        um celular so, sem fio, ele entra em uso na hora (ver `_terminou`):
        o nome acende verde embaixo do PAREAR e o primeiro "ligar" ja nao
        paga a espera da descoberta.
        """
        if self._trabalhando or self._celular_ok or not self._pasta_ok():
            return
        self._ja_procurou = True
        self._procurar()

    def _talvez_procurar(self) -> None:
        if (self._item == "parear" and self._aba["parear"] == "procurar"
                and not self._ja_procurou and not self._trabalhando
                and self._pasta_ok()):
            self._ja_procurou = True
            self._procurar()

    def _procurar(self) -> None:
        reserva = self._config.ip_reserva
        self._achados = None
        self._trabalhar("procurar", lambda adb, avisar, parar:
                        conexao.procurar(adb, reserva, avisar, parar))
        self._mostrar_achados()

    def _usar(self, achado) -> None:
        self.programa.anotar("usar: %s (%s)" % (achado.descricao,
                                               achado.serial))
        self._achados = None
        if not achado.sem_fio:
            # So no cabo: o mesmo caminho da aba "cabo usb", que abre a
            # conexao sem fio.
            self._conectar_cabo()
            return
        self._achados = None
        self._terminou(conexao.Resultado(
            True, "pronto: %s em uso, sem fio%s." % (
                achado.modelo, (" (%s)" % achado.endereco)
                if achado.endereco else ""),
            modelo=achado.modelo, endereco=achado.endereco))

    def _tela_parear_cabo(self, area) -> None:
        if self._sem_pasta(area):
            return
        esq, dir_ = self._duas(area)
        E.Rotulo(esq, "pelo cabo usb").pack(side="top", fill="x", pady=(E.px(0), E.px(6)))
        for n, passo in enumerate((
                "no celular, ative a depuração usb (opções do "
                "desenvolvedor).",
                "ligue o celular no pc pelo cabo, os dois no mesmo wi-fi.",
                "clique em conectar e aceite o aviso no celular.")):
            linha = tk.Frame(esq, bg=E.FUNDO)
            linha.pack(side="top", fill="x", pady=(E.px(0), E.px(6)))
            tk.Label(linha, text="%d" % (n + 1), bg=E.FUNDO, fg=E.ACENTO,
                     font=E.fonte(E.PEQUENA, "bold"), width=2,
                     anchor="nw").pack(side="left", anchor="n")
            E.Texto(linha, passo, largura=E.px(200)).pack(side="left", fill="x")
        E.Texto(esq, "no fim ele fica conectado sem fio e o cabo pode sair.",
                cor=E.APAGADO, largura=E.px(230)).pack(side="top", fill="x",
                                                 pady=(E.px(4), E.px(0)))
        E.Rotulo(dir_, "conectar").pack(side="top", fill="x", pady=(E.px(0), E.px(6)))
        b = E.Botao(dir_, "conectar", self._conectar_cabo, tipo="acao")
        b.pack(side="top", fill="x")
        b.definir(ligado=not self._trabalhando)
        self._ui["acao_parear"] = b
        self._status(dir_)

    def _conectar_cabo(self) -> None:
        self._trabalhar("cabo", conexao.conectar_pelo_cabo)

    def _tela_parear_codigo(self, area) -> None:
        if self._sem_pasta(area):
            return
        esq, dir_ = self._duas(area)
        E.Rotulo(esq, "sem fio, com código").pack(side="top", fill="x",
                                                  pady=(E.px(0), E.px(6)))
        E.Texto(esq, "no celular: opções do desenvolvedor › depuração sem "
                     "fio › \"parear o dispositivo com código de "
                     "pareamento\".\n\ndigite ao lado o endereço e o código "
                     "que aparecem na tela do celular.",
                largura=E.px(230)).pack(side="top", fill="x")
        self._ui["campo_endereco"] = self._campo(dir_, "endereço ip e porta",
                                                "ex.: 192.168.0.10:37123")
        self._ui["campo_codigo"] = self._campo(dir_, "código de pareamento",
                                              "6 números")
        self._ui["campo_codigo"].bind("<Return>", lambda _e: self._parear())
        b = E.Botao(dir_, "parear", self._parear, tipo="acao")
        b.pack(side="top", fill="x", pady=(E.px(12), E.px(0)))
        b.definir(ligado=not self._trabalhando)
        self._ui["acao_parear"] = b
        self._status(dir_)

    def _campo(self, pai, rotulo: str, dica: str) -> tk.Entry:
        linha = tk.Frame(pai, bg=E.FUNDO)
        linha.pack(side="top", fill="x", pady=(E.px(0), E.px(3)))
        tk.Label(linha, text=rotulo.upper(), bg=E.FUNDO, fg=E.TEXTO_2,
                 font=E.fonte(E.ROTULO), anchor="w").pack(side="left")
        tk.Label(linha, text=dica, bg=E.FUNDO, fg=E.APAGADO,
                 font=E.fonte(E.ROTULO), anchor="e").pack(side="right")
        campo = self._caixa(pai)
        campo.master.pack(side="top", fill="x", pady=(E.px(0), E.px(8)))
        return campo

    def _parear(self) -> None:
        e = self._ui.get("campo_endereco")
        c = self._ui.get("campo_codigo")
        if e is None or c is None:
            return
        endereco, codigo = e.get().strip(), c.get().strip()
        if not endereco or not codigo:
            self._pintar_status("preencha o endereço e o código.", E.ALERTA)
            return
        self._trabalhar("codigo", lambda adb, avisar, parar:
                        conexao.parear_por_codigo(adb, endereco, codigo,
                                                  avisar, parar))

    def _trabalhar(self, nome: str, funcao) -> None:
        """A conversa com o celular roda numa thread; a resposta volta pela fila."""
        if self._trabalhando:
            return
        adb = self._config.adb_exe
        self._trabalhando = True
        self._parar_trabalho.clear()
        b = self._ui.get("acao_parear")
        if b is not None:
            b.definir(ligado=False)
        self._pintar_status("começando…")
        self.programa.anotar("parear: %s" % nome)

        def avisar(texto):
            self._da_outra_thread.put(
                lambda t=texto: self._pintar_status(str(t).lower()))

        def rodar():
            try:
                resultado = funcao(adb, avisar, self._parar_trabalho)
            except Exception as erro:
                log.exception("conexao")
                resultado = conexao.Resultado(False,
                                              "algo deu errado: %s" % erro)
            self._da_outra_thread.put(lambda r=resultado: self._terminou(r))

        threading.Thread(target=rodar, daemon=True, name="parear").start()

    def _terminou(self, resultado) -> None:
        self._trabalhando = False
        self.programa.anotar("parear: %s -- %s" % (
            "OK" if resultado.ok else "falhou", resultado.texto))
        if resultado.ok and resultado.achados is None:
            self._celular_ok = True
            if getattr(resultado, "modelo", ""):
                self.programa.celular = dict(self.programa.celular,
                                             modelo=resultado.modelo)
            # A bateria ja aparece agora, sem esperar um modo ligar.
            # Le o celular JA (icone verde, cache, status): o endereco do
            # parear nem sempre e o nome que o adb usa para ele.
            self.programa.ler_celular_agora()
            if resultado.endereco:
                self._config.ip_reserva = resultado.endereco
                self._conferir_gravacao(self._config.gravar())
        b = self._ui.get("acao_parear")
        if b is not None:
            try:
                b.definir(ligado=True)
            except tk.TclError:
                pass
        if resultado.achados is not None:
            self._achados = list(resultado.achados)
            # CONEXAO MAIS SIMPLES (pedido dele, 23/set/2026): um celular so,
            # ja sem fio -> usa na hora, sem o passo "escolha qual usar".
            # Pelo cabo continua pedindo o clique: abrir o sem fio e mais
            # pesado e so faz sentido quando ele quer.
            if len(self._achados) == 1 and self._achados[0].sem_fio:
                self._usar(self._achados[0])
                return
            self._pintar_status(resultado.texto.lower(),
                                E.TEXTO_2 if resultado.ok else E.ALERTA)
            self._mostrar_achados()
        else:
            self._pintar_status(("✓  " if resultado.ok else "✗  ")
                                + resultado.texto.lower(),
                                E.VERDE if resultado.ok else E.ERRO)
            self._mostrar_achados()
        self._repintar()

    # ==========================================================================
    # OPCOES
    # ==========================================================================

    def _tela_opcoes_geral(self, area) -> None:
        esq, dir_ = self._duas(area)
        # (r168) A coluna ja passava da altura (o ultimo texto era cortado):
        # agora rola.
        rol = _Rolagem(esq)
        self._ui["rolagem_geral"] = rol
        # (r179) A LISTA FICA ONDE ESTAVA: cada chave remonta a tela e a
        # rolagem voltava ao topo (relato dele). Guarda a posicao a cada
        # rolada e devolve depois de montar.
        voltar_para = getattr(self, "_pos_geral", 0.0)

        def rolou(a, b, rol=rol):
            rol._rolou(a, b)
            if getattr(rol, "_devolvida", False):
                self._pos_geral = float(a)

        rol.canvas.configure(yscrollcommand=rolou)

        def devolver(final: bool, rol=rol):
            if rol.canvas.winfo_exists():
                rol.canvas.yview_moveto(voltar_para)
                rol._devolvida = final

        # Duas vezes: a altura da lista so e medida depois de desenhada.
        rol.canvas.after(30, lambda: devolver(False))
        rol.canvas.after(150, lambda: devolver(True))
        esq = rol.dentro
        E.Rotulo(esq, "programa").pack(side="top", fill="x", pady=(E.px(0), E.px(2)))
        ligada = self._config.opcao("pagina_inicial_ligada")
        # (r180) Tudo NO LUGAR (sem remontar = sem piscar).
        self._chave(esq, "página inicial", ligada,
                    lambda v: (self._virar_opcao("pagina_inicial_ligada", v),
                               self._pintar_escolha_inicial()),
                    explicacao="abrir sempre nesta aba:", borda=False)
        self._escolha_inicial(esq)
        tk.Frame(esq, bg=E.LINHA, height=1).pack(side="top", fill="x",
                                                 pady=(E.px(8), E.px(0)))
        self._chave(esq, "notificações", self._config.opcao("notificacoes"),
                    # (r171) Remonta: "ao criar atalho" trava/destrava NA
                    # HORA (antes so ao sair e voltar da aba).
                    lambda v: (self._virar_opcao("notificacoes", v),
                               self._acertar_sub_chaves()),
                    explicacao="avisos do windows ao ligar e desligar")
        # (r161) Pedido dele: desligar so o aviso de atalho criado.
        self._ui["chave_aviso_atalho"] = self._chave(
                    esq, "  └ ao criar atalho",
                    self._config.opcao("notificacoes")
                    and self._config.opcao("aviso_atalho"),
                    lambda v: self._virar_opcao("aviso_atalho", v),
                    explicacao="aviso de atalho criado na área de trabalho",
                    travada=not self._config.opcao("notificacoes"))
        if inicio_windows.disponivel():
            w = self._chave(esq, "abrir com o windows",
                            bool(self._windows_ligado),
                            lambda _v: self._virar_windows(),
                            explicacao="o programa já nasce na bandeja")
            self._ui["windows"] = w
            self._ui["chave_rapido"] = self._chave(
                        esq, "  └ iniciar mais rápido",
                        bool(self._windows_ligado)
                        and bool(getattr(self, "_rapido_ligado", False)),
                        lambda v: self._virar_rapido(v),
                        explicacao="abre junto com o login; pede o "
                                   "administrador uma vez",
                        travada=not self._windows_ligado)
        self._chave(esq, "mostrar a janela ao abrir",
                    self._config.opcao("abrir_janela_ao_iniciar"),
                    lambda v: self._virar_opcao("abrir_janela_ao_iniciar", v),
                    explicacao="desligado: abre só na bandeja", borda=False)

        E.Rotulo(dir_, "pasta do scrcpy").pack(side="top", fill="x",
                                               pady=(E.px(0), E.px(6)))
        pasta = self._config.scrcpy or "(nenhuma escolhida)"
        tk.Label(dir_, text=pasta, bg=E.FUNDO_FUNDO, fg=E.TEXTO,
                 font=E.fonte(E.PEQUENA), anchor="w", justify="left",
                 wraplength=E.px(220), padx=E.px(8), pady=E.px(6), highlightthickness=1,
                 highlightbackground=E.LINHA).pack(side="top", fill="x")
        ok, texto = conexao.conferir_pasta(self._config.scrcpy)
        cor = E.VERDE if ok else (E.APAGADO if not self._config.scrcpy
                                  else E.ERRO)
        s = E.Texto(dir_, ("✓  " if ok else ("" if not self._config.scrcpy
                                             else "✗  ")) + texto.lower(),
                    cor=cor, largura=E.px(230))
        s.pack(side="top", fill="x", pady=(E.px(6), E.px(0)))
        self._ui["status_pasta"] = s
        andamento = getattr(self, "_instalar_texto", None)
        if andamento:                       # (r166) instalando agora
            s.configure(text=andamento[0], fg=andamento[1])
        botoes = tk.Frame(dir_, bg=E.FUNDO)
        botoes.pack(side="top", fill="x", pady=(E.px(10), E.px(0)))
        # (r166) INSTALAR E O PRINCIPAL; "usar outra pasta" fica pequeno,
        # para quem nao tem administrador, nao alcanca o GitHub ou quer uma
        # versao especifica do scrcpy (decisao dele, 25/set/2026).
        # (r175) Com o scrcpy ja funcionando o botao vira "procurar
        # atualizacao" (pedido dele: clicar de novo reinstalava a mesma).
        if ok:
            E.Botao(botoes, "procurar atualização", self._procurar_agora,
                    tipo="acao").pack(side="left")
        else:
            E.Botao(botoes, "instalar", self._baixar,
                    tipo="acao").pack(side="left")
        outra = tk.Label(dir_, text="usar outra pasta", bg=E.FUNDO,
                         fg=E.APAGADO, font=E.fonte(E.PEQUENA), anchor="w",
                         cursor="hand2")
        outra.pack(side="top", fill="x", pady=(E.px(8), E.px(0)))
        outra.bind("<Button-1>", lambda _e: self._escolher_pasta())
        outra.bind("<Enter>", lambda _e: outra.configure(fg=E.TEXTO))
        outra.bind("<Leave>", lambda _e: outra.configure(fg=E.APAGADO))
        # (r167) ATUALIZACAO: prazo da procura + procurar agora.
        E.Rotulo(dir_, "procurar atualização").pack(
            side="top", fill="x", pady=(E.px(14), E.px(6)))
        E.Segmentado(dir_, (("diario", "dia"), ("semanal", "semana"),
                            ("mensal", "mês"), ("nunca", "nunca")),
                     self.programa.prazo_atualizacao(),
                     self._escolheu_prazo).pack(side="top", fill="x")
        # (r175) O "procurar agora" virou o botao de cima; aqui fica so o
        # resultado da ultima procura (ou, sem scrcpy, o link de procurar).
        agora = tk.Label(dir_, text=getattr(self, "_procura_texto", None)
                         or ("" if ok else "procurar agora"), bg=E.FUNDO,
                         fg=E.APAGADO, font=E.fonte(E.PEQUENA), anchor="w",
                         cursor="arrow" if ok else "hand2")
        agora.pack(side="top", fill="x", pady=(E.px(6), E.px(0)))
        if not ok:
            agora.bind("<Button-1>", lambda _e: self._procurar_agora())
            agora.bind("<Enter>", lambda _e: agora.configure(fg=E.TEXTO))
            agora.bind("<Leave>", lambda _e: agora.configure(fg=E.APAGADO))
        self._ui["procura"] = agora
        # side=bottom empilha de baixo para cima: o numero entra primeiro
        tk.Label(dir_, text="scrcpy-f %s" % VERSAO, bg=E.FUNDO, fg=E.TEXTO_2,
                 font=E.fonte(E.PEQUENA), anchor="w").pack(side="bottom",
                                                           fill="x")
        E.Rotulo(dir_, "versão").pack(side="bottom", fill="x", pady=(E.px(0), E.px(2)))

    # -- OPCOES > qualidade (23/set/2026) -------------------------------------
    #
    # Pedido dele: UMA qualidade para o programa inteiro (espelhar, extensao
    # e apps), com tres predefinicoes fixas e ate tres dele, que so aparecem
    # depois que ele criar. As fileiras ficam todas abertas.

    def _tela_opcoes_qualidade(self, area) -> None:
        q = self._config.qualidade
        f = self._uma(area)
        lista = qualidade.todas_predef(q)
        atual = qualidade.predef_atual(q)
        minha = next((x for x in lista if x[0] == atual and not x[4]), None)
        n_minhas = sum(1 for x in lista if not x[4])

        topo = tk.Frame(f, bg=E.FUNDO)
        topo.pack(side="top", fill="x", pady=(E.px(0), E.px(6)))
        E.Rotulo(topo, "predefinição").pack(side="left")
        if minha is not None:
            E.Botao(topo, "apagar", lambda: self._apagar_predef(minha[0]),
                    tipo="discreto").pack(side="right")
            E.Botao(topo, "renomear", lambda: self._renomear_predef(minha[0]),
                    tipo="discreto").pack(side="right", padx=(E.px(0), E.px(6)))
        if n_minhas < qualidade.MAX_MINHAS:
            E.Botao(topo, "+ salvar como nova", self._nova_predef,
                    tipo="discreto").pack(side="right", padx=(E.px(0), E.px(6)))
        E.Segmentado(f, [(c, n) for c, n, _v, _a, _f in lista], atual,
                     self._escolheu_predef).pack(side="top", fill="x")

        if minha is not None and getattr(self, "_renomeando", None) == minha[0]:
            linha = tk.Frame(f, bg=E.FUNDO)
            linha.pack(side="top", fill="x", pady=(E.px(6), E.px(0)))
            caixa = self._caixa(linha, minha[1], ipady=2)
            caixa.master.pack(side="left", fill="x", expand=True,
                              padx=(E.px(0), E.px(6)))
            ok = lambda _e=None: self._gravar_nome_predef(minha[0], caixa.get())
            caixa.bind("<Return>", ok)
            caixa.bind("<Escape>", lambda _e: self._renomear_predef(None))
            E.Botao(linha, "ok", ok, tipo="acao").pack(side="right")
            self.after(30, lambda: caixa.winfo_exists() and caixa.focus_set())
        else:
            if atual is None:
                texto = ("ajustada à mão. use \"+ salvar como nova\" para "
                         "guardar." if n_minhas < qualidade.MAX_MINHAS else
                         "ajustada à mão (já há 3 suas: apague uma para "
                         "guardar esta).")
            elif minha is not None:
                texto = "sua · o que mudar abaixo fica gravado nela."
            else:
                texto = (qualidade.texto_do_nivel("video", {
                    "equilibrado": "padrao"}.get(atual, atual)).lower() +
                    " fixa: mudar abaixo cria uma ajustada à mão.")
            E.Texto(f, texto, cor=E.APAGADO, tamanho=E.ROTULO,
                    largura=E.px(560)).pack(side="top", fill="x",
                                            pady=(E.px(6), E.px(0)))

        colunas = tk.Frame(f, bg=E.FUNDO)
        colunas.pack(side="top", fill="both", expand=True,
                     pady=(E.px(10), E.px(0)))
        esq = tk.Frame(colunas, bg=E.FUNDO)
        dir_ = tk.Frame(colunas, bg=E.FUNDO)
        esq.place(relx=0, rely=0, relwidth=0.5, relheight=1.0, width=-E.px(8))
        dir_.place(relx=0.5, rely=0, relwidth=0.5, relheight=1.0,
                   x=E.px(8), width=-E.px(8))
        video, audio = q.get("video") or {}, q.get("audio") or {}
        E.Rotulo(esq, "imagem").pack(side="top", fill="x",
                                     pady=(E.px(0), E.px(6)))
        for ajuste in qualidade.AJUSTES_VIDEO:
            campo = ajuste["campo"]
            self._fila(esq, NOME_CURTO.get(("video", campo), campo),
                       self._opcoes_curtas(ajuste), video.get(campo),
                       lambda v, c=campo: self._escolheu_qualidade("video", c, v))
        E.Rotulo(dir_, "som").pack(side="top", fill="x",
                                   pady=(E.px(0), E.px(6)))
        for ajuste in qualidade.AJUSTES_AUDIO:
            campo = ajuste["campo"]
            if campo == "origem":
                continue
            s = self._fila(dir_, NOME_CURTO.get(("audio", campo), campo),
                           self._opcoes_curtas(ajuste), audio.get(campo),
                           lambda v, c=campo: self._escolheu_qualidade(
                               "audio", c, v))
            if campo == "bitrate" and audio.get("codec") in qualidade.SEM_TAXA:
                s.habilitar(False)
        E.Texto(dir_, "vale para espelhar, extensão e apps. um app pode ter a "
                      "sua em apps › personalizados.", cor=E.APAGADO,
                tamanho=E.ROTULO, largura=E.px(250)).pack(
            side="top", fill="x", pady=(E.px(8), E.px(0)))

    def _qualidade_mudou(self, ok: bool, o_que: str) -> None:
        self.programa.anotar("qualidade: %s%s" % (o_que,
                                                  "" if ok else " (NAO GRAVOU)"))
        self._conferir_gravacao(ok)
        for nome in ("jogo", "extensao"):
            self.programa.mudou_a_qualidade(nome)
        # A qualidade de OPCOES tambem e a dos apps (r123).
        self._agendar_reabrir(self.programa.apps_abertos())
        self._montar_conteudo()

    def _escolheu_predef(self, ident: str) -> None:
        self._renomeando = None
        self._qualidade_mudou(self._config.escolher_predef(ident),
                              "predefinicao %s" % ident)

    def _escolheu_qualidade(self, secao: str, campo: str, valor) -> None:
        self._qualidade_mudou(self._config.definir_qualidade(secao, campo,
                                                             valor),
                              "%s.%s = %s" % (secao, campo, valor))

    def _nova_predef(self) -> None:
        ident = self._config.criar_predef()
        self._renomeando = ident          # ja abre a caixa do nome
        self._qualidade_mudou(ident is not None, "nova predefinicao %s" % ident)

    def _renomear_predef(self, ident) -> None:
        self._renomeando = ident
        self._montar_conteudo()

    def _gravar_nome_predef(self, ident: str, nome: str) -> None:
        self._renomeando = None
        self._qualidade_mudou(self._config.renomear_predef(ident, nome),
                              "predefinicao %s = %r" % (ident, nome))

    def _apagar_predef(self, ident: str) -> None:
        self._renomeando = None
        self._qualidade_mudou(self._config.apagar_predef(ident),
                              "apagou a predefinicao %s" % ident)

    def _virar_opcao(self, nome: str, valor: bool) -> None:
        self._conferir_gravacao(self._config.definir_opcao(nome, valor))
        self.programa.anotar("opcao %s: %s" % (nome, "ligada" if valor
                                               else "desligada"))

    def _ler_o_windows(self) -> None:
        """Pergunta ao Agendador fora da thread da tela."""
        def trabalho():
            try:
                ativo = inicio_windows.ativo()
                rapido = inicio_windows.rapido()
            except Exception as erro:            # (r149) nao cala
                self._windows_falhou("ler", erro)
                return
            self._da_outra_thread.put(
                lambda: self._windows_mudou(ativo, rapido))
        threading.Thread(target=trabalho, daemon=True, name="windows").start()

    def _windows_falhou(self, o_que: str, erro) -> None:
        """(r149) Da thread "windows": anota o erro e devolve a chave ao
        estado que o Agendador disser (ou deixa como esta, se nem ler da)."""
        log.exception("iniciar com o Windows (%s)", o_que)
        try:
            ativo, rapido = inicio_windows.ativo(), inicio_windows.rapido()
        except Exception:
            ativo = rapido = None
        self._da_outra_thread.put(lambda: (
            self.programa.anotar("iniciar com o Windows: ERRO ao %s (%s)"
                                 % (o_que, erro)),
            ativo is not None and self._windows_mudou(ativo, rapido)))

    def _windows_mudou(self, ativo: bool, rapido=None) -> None:
        antes = (getattr(self, "_windows_ligado", None),
                 getattr(self, "_rapido_ligado", None))
        self._windows_ligado = bool(ativo)
        if rapido is not None:
            self._rapido_ligado = bool(rapido)
        # A sub-chave trava/destrava com a de cima: remonta a tela de opcoes
        # se ela esta a vista e algo mudou.
        if antes != (self._windows_ligado, getattr(self, "_rapido_ligado",
                                                   None)):
            self._acertar_sub_chaves()      # (r180) no lugar, sem piscar

    def _virar_rapido(self, quer: bool) -> None:
        """NUMA THREAD: pode esperar a confirmacao de administrador."""
        def trabalho():
            try:
                inicio_windows.definir_rapido(bool(quer))
                ativo = inicio_windows.ativo()
                rapido = inicio_windows.rapido()
            except Exception as erro:            # (r149) nao cala
                self._windows_falhou("mudar o iniciar mais rapido", erro)
                return
            self._da_outra_thread.put(lambda: (
                self._windows_mudou(ativo, rapido),
                self.programa.anotar("iniciar mais rapido: %s (com o Windows: "
                                     "%s)" % ("ligado" if rapido else
                                              "desligado",
                                              "sim" if ativo else "nao"))))
        threading.Thread(target=trabalho, daemon=True, name="windows").start()

    def _virar_windows(self) -> None:
        """
        NUMA THREAD: criar a tarefa pode pedir a confirmacao de administrador.
        A chave so fica como o Agendador responder -- nunca mente que ligou.
        """
        def trabalho():
            try:
                quer = not inicio_windows.ativo()
                inicio_windows.definir(quer, com_admin=True)
                real = inicio_windows.ativo()
                rapido = inicio_windows.rapido()
            except Exception as erro:            # (r149) nao cala
                self._windows_falhou("mudar o iniciar com o Windows", erro)
                return
            self._da_outra_thread.put(lambda: (
                self._windows_mudou(real, rapido),
                self.programa.anotar("iniciar com o Windows: %s"
                                     % ("ligado" if real else "desligado"))))
        threading.Thread(target=trabalho, daemon=True, name="windows").start()

    def _baixar(self) -> None:
        """
        (r166) INSTALAR NUM BOTAO (pedido dele, 25/set/2026): baixa o scrcpy
        mais novo, confere e instala em `scrcpy\\` ao lado do programa,
        pedindo o administrador (ver `atualizar.py`). O andamento aparece no
        lugar do texto da pasta.
        """
        if getattr(self, "_instalando", False):
            return
        self._instalando = True
        self.programa.anotar("instalar scrcpy: pedido pela janela")

        def mostrar(texto, cor=None):
            self._instalar_texto = (texto, cor or E.TEXTO_2) if texto else None
            s = self._ui.get("status_pasta")
            if s is not None and s.winfo_exists():
                s.configure(text=texto, fg=cor or E.TEXTO_2)

        def avisar(texto):
            self._da_outra_thread.put(lambda t=texto: mostrar(t))

        def fim(ok, texto):
            self._instalando = False
            self._instalar_texto = None
            if ok:
                self._montar_conteudo()
                mostrar("✓  " + texto, E.VERDE)
                self._instalar_texto = None
            else:
                mostrar("✗  " + texto, E.ERRO)
                self._instalar_texto = None

        def trabalho():
            try:
                ok, texto = self.programa.instalar_scrcpy(avisar)
            except Exception as erro:
                log.exception("instalar scrcpy")
                ok, texto = False, "algo deu errado: %s" % erro
            self._da_outra_thread.put(lambda: fim(ok, texto))

        mostrar("começando…")
        threading.Thread(target=trabalho, daemon=True,
                         name="instalar-scrcpy").start()

    NOMES_DAS_PAGINAS = (("jogo", "espelhar"), ("extensao", "extensão"),
                         ("apps", "apps"), ("celular", "status"),
                         ("parear", "parear"), ("opcoes", "opções"))

    def _escolha_inicial(self, pai) -> None:
        """(r168) Caixa de escolha: clique (ou Enter/espaco) abre a lista.
        (r180) Travar e trocar o texto acontecem no lugar."""
        caixa = tk.Label(pai, anchor="w", bg=E.FUNDO_FUNDO,
                         font=E.fonte(E.PEQUENA), padx=E.px(8), pady=E.px(5),
                         highlightthickness=1, highlightbackground=E.LINHA,
                         highlightcolor=E.ACENTO)
        caixa.pack(side="top", fill="x", pady=(E.px(2), E.px(0)))
        self._ui["escolha_inicial"] = caixa

        def abrir(_e=None):
            if not self._config.opcao("pagina_inicial_ligada"):
                return "break"
            m = tk.Menu(self, tearoff=0, bg=E.FUNDO_FUNDO, fg=E.TEXTO,
                        activebackground=E.ACENTO, activeforeground=E.FUNDO,
                        bd=0, font=E.fonte(E.PEQUENA))
            for valor, rotulo in self.NOMES_DAS_PAGINAS:
                m.add_command(label=rotulo,
                              command=lambda v=valor: self._escolheu_inicial(v))
            try:
                m.tk_popup(caixa.winfo_rootx(),
                           caixa.winfo_rooty() + caixa.winfo_height())
            finally:
                m.grab_release()
            return "break"

        caixa.bind("<Button-1>", abrir)
        caixa.bind("<Return>", abrir)
        caixa.bind("<space>", abrir)
        self._pintar_escolha_inicial()

    def _pintar_escolha_inicial(self) -> None:
        caixa = self._ui.get("escolha_inicial")
        if caixa is None or not caixa.winfo_exists():
            return
        ligada = self._config.opcao("pagina_inicial_ligada")
        atual = self._config.opcoes.get("pagina_inicial", "jogo")
        nome = dict(self.NOMES_DAS_PAGINAS).get(atual, "espelhar")
        caixa.configure(text="%s  ▾" % nome,
                        fg=E.TEXTO if ligada else E.APAGADO,
                        takefocus=1 if ligada else 0,
                        cursor="hand2" if ligada else "arrow")

    def _acertar_sub_chaves(self) -> None:
        """(r180) As sub-chaves travam/destravam no lugar."""
        c = self._ui.get("chave_aviso_atalho")
        if c is not None and c.winfo_exists():
            notif = self._config.opcao("notificacoes")
            c.travar(not notif)
            c.definir(notif and self._config.opcao("aviso_atalho"))
        w = self._ui.get("windows")
        if w is not None and w.winfo_exists():
            w.definir(bool(self._windows_ligado))
        r = self._ui.get("chave_rapido")
        if r is not None and r.winfo_exists():
            r.travar(not self._windows_ligado)
            r.definir(bool(self._windows_ligado)
                      and bool(getattr(self, "_rapido_ligado", False)))

    def _escolheu_inicial(self, valor: str) -> None:
        self._config.opcoes["pagina_inicial"] = valor
        self._conferir_gravacao(self._config.gravar())
        self.programa.anotar("pagina inicial: %s" % valor)
        self._pintar_escolha_inicial()

    def _escolheu_prazo(self, valor) -> None:
        self._config.opcoes["procurar_atualizacao"] = valor
        self._conferir_gravacao(self._config.gravar())
        self.programa.anotar("atualizacao: prazo %s" % valor)

    def _procurar_agora(self) -> None:
        """(r167) Procura ja (a pergunta, se houver, e a caixa do Windows)."""
        if getattr(self, "_procurando", False):
            return
        self._procurando = True

        def mostrar(texto):
            self._procura_texto = texto
            r = self._ui.get("procura")
            if r is not None and r.winfo_exists():
                r.configure(text=texto)

        pasta_antes = self._config.scrcpy

        def fim(texto):
            self._procurando = False
            if self._config.scrcpy != pasta_antes:
                # Instalou/atualizou: a pasta mudou, a tela e refeita.
                self._procura_texto = texto
                self._montar_conteudo()
                self._procura_texto = None
            else:
                mostrar(texto)             # (r180) no lugar, sem piscar
                self._procura_texto = None

        def trabalho():
            try:
                texto = self.programa.procurar_atualizacao(manual=True)
            except Exception as erro:
                log.exception("procurar atualizacao")
                texto = "algo deu errado: %s" % erro
            self._da_outra_thread.put(lambda: fim(texto))

        mostrar("procurando…")
        threading.Thread(target=trabalho, daemon=True,
                         name="procurar").start()

    def _escolher_pasta(self) -> None:
        from tkinter import filedialog
        pasta = filedialog.askdirectory(
            parent=self, title="Pasta onde você extraiu o scrcpy",
            initialdir=self._config.scrcpy or None, mustexist=True)
        if not pasta:
            return
        pasta = conexao.achar_pasta_dentro(pasta)
        ok, texto = conexao.conferir_pasta(pasta)
        self.programa.anotar("pasta escolhida: %s -- %s" % (pasta, texto))
        if ok:
            self._config.scrcpy = str(pasta)
            self._conferir_gravacao(self._config.gravar())
            self._montar_conteudo()
            return
        s = self._ui.get("status_pasta")
        if s is not None:
            s.configure(text="✗  " + texto.lower(), fg=E.ERRO)

    # -- atalhos ----------------------------------------------------------------

    def _tela_opcoes_atalhos(self, area) -> None:
        """
        TODOS OS ATALHOS NUM LUGAR SO (23/set/2026): antes havia um "atalhos"
        em APPS e outro aqui, com coisas diferentes. Agora: MODOS (os de
        sempre) e APPS (abrir cada app), com rolagem.
        """
        f = self._uma(area)
        if self.motor is None or not self.motor.disponivel:
            E.Rotulo(f, "atalhos").pack(side="top", fill="x", pady=(E.px(0), E.px(6)))
            E.Texto(f, "atalhos de teclado só funcionam no windows.",
                    cor=E.APAGADO).pack(side="top", fill="x")
            return
        if self._gravando is not None:
            self._montar_gravador(f)
            return
        if getattr(self, "_atalhos_modo", "lista") == "seletor":
            self._montar_seletor(f)
            return
        recusadas = self.motor.falhas()
        lista = [(a, t) for a, t in atalhos_mod.em_ordem(self._config)
                 if not a.startswith(atalhos_mod.APP)]
        if recusadas:
            aviso = ("em vermelho: o windows não aceitou (outro programa já "
                     "usa). clique na linha e grave outra.", E.ERRO)
        else:
            aviso = ("valem em qualquer programa, com a janela fechada. "
                     "clique numa linha para gravar as teclas.", E.APAGADO)
        E.Texto(f, aviso[0], cor=aviso[1], tamanho=E.ROTULO,
                largura=E.px(560)).pack(side="bottom", fill="x",
                                        pady=(E.px(6), E.px(0)))
        caixa = tk.Frame(f, bg=E.FUNDO)
        caixa.pack(side="top", fill="both", expand=True)
        rol = _Rolagem(caixa)
        self._ui["rolagem_atalhos"] = rol
        d = rol.dentro
        topo = tk.Frame(d, bg=E.FUNDO)
        topo.pack(side="top", fill="x", pady=(E.px(0), E.px(6)))
        E.Rotulo(topo, "modos").pack(side="left")
        if atalhos_mod.livres(self._config):
            E.Botao(topo, "+ adicionar atalho", self._abrir_seletor,
                    tipo="discreto").pack(side="right")
        if not lista:
            E.Texto(d, "nenhum atalho ainda.", cor=E.APAGADO).pack(
                side="top", fill="x")
        for acao, teclas in lista:
            self._linha_de_atalho(d, acao, teclas, acao in recusadas)
        E.Rotulo(d, "apps").pack(side="top", fill="x",
                                 pady=(E.px(12), E.px(6)))
        if self._apps is None and not self._apps_carregando:
            self._carregar_apps()
        apps = sorted(self._apps or [], key=lambda a: (a[2], a[0].lower()))
        def linha(app):
            nome, pacote, _sis = app
            acao = atalhos_mod.APP + pacote
            atalhos_mod.NOMES_DE_APP.setdefault(pacote, nome)
            self._linha_de_atalho_livre(d, acao, (pacote, nome),
                                        acao in recusadas)

        # Em lotes: com ~100 apps a aba abria atrasada (23/set/2026).
        self._em_lotes(rol.canvas, apps, linha, primeiro=12)
        if not apps:
            E.Texto(d, "lendo os apps do celular…" if self._apps_carregando
                    else "os apps aparecem aqui quando a lista do celular "
                         "chegar.", cor=E.APAGADO).pack(side="top", fill="x")

    def _linha_de_atalho(self, pai, acao: str, teclas: str,
                         recusado: bool) -> None:
        linha = tk.Frame(pai, bg=E.FUNDO, highlightthickness=1,
                         highlightbackground=E.ERRO if recusado else E.LINHA,
                         cursor="hand2", takefocus=1, highlightcolor=E.ACENTO)
        linha.pack(side="top", fill="x", pady=(E.px(0), E.px(5)))
        nome = tk.Label(linha, text=atalhos_mod.rotulo(acao).upper(),
                        bg=E.FUNDO, fg=E.TEXTO, font=E.fonte(E.PEQUENA),
                        anchor="w", cursor="hand2")
        nome.pack(side="left", padx=(E.px(10), E.px(0)), pady=E.px(7))
        tirar = tk.Label(linha, text="×", bg=E.FUNDO, fg=E.APAGADO,
                         font=E.fonte(E.CORPO), cursor="hand2", padx=E.px(8))
        tirar.pack(side="right")
        tirar.bind("<Enter>", lambda _e: tirar.configure(fg=E.ERRO))
        tirar.bind("<Leave>", lambda _e: tirar.configure(fg=E.APAGADO))
        tirar.bind("<Button-1>", lambda _e, a=acao: (self._tirar_atalho(a),
                                                     "break")[1])
        caixa = tk.Frame(linha, bg=E.FUNDO)
        caixa.pack(side="right", padx=(E.px(0), E.px(4)))
        partes = [p.strip() for p in teclas.split("+") if p.strip()] \
            if teclas else []
        if not partes:
            tk.Label(caixa, text="sem teclas", bg=E.FUNDO, fg=E.APAGADO,
                     font=E.fonte(E.ROTULO)).pack(side="left")
        for i, p in enumerate(partes):
            if i:
                tk.Label(caixa, text="+", bg=E.FUNDO, fg=E.APAGADO,
                         font=E.fonte(E.ROTULO)).pack(side="left", padx=E.px(2))
            tk.Label(caixa, text=p.upper(), bg=E.FUNDO,
                     fg=E.ERRO if recusado else E.TEXTO,
                     font=E.fonte(E.ROTULO + 1), padx=E.px(5), pady=1,
                     highlightthickness=1,
                     highlightbackground=E.ERRO if recusado
                     else E.LINHA_FORTE).pack(side="left")

        def regravar(_e=None, a=acao):
            self._comecar_gravacao(a)
            return "break"

        for peca in (linha, nome, caixa, *caixa.winfo_children()):
            peca.bind("<Button-1>", regravar)
        linha.bind("<Return>", regravar)
        linha.bind("<space>", regravar)
        linha.bind("<Delete>", lambda _e, a=acao: (self._tirar_atalho(a),
                                                   "break")[1])

    def _abrir_seletor(self) -> None:
        self._atalhos_modo = "seletor"
        self._montar_conteudo()

    def _montar_seletor(self, pai) -> None:
        E.Rotulo(pai, "adicionar atalho para").pack(side="top", fill="x",
                                                    pady=(E.px(0), E.px(8)))
        for acao in atalhos_mod.livres(self._config):
            E.Botao(pai, atalhos_mod.rotulo(acao),
                    lambda a=acao: self._criar_atalho(a),
                    tipo="contorno").pack(side="top", fill="x", pady=(E.px(0), E.px(5)))
        E.Botao(pai, "cancelar", self._fechar_seletor, tipo="discreto").pack(
            side="top", anchor="w", pady=(E.px(6), E.px(0)))

    def _fechar_seletor(self) -> None:
        self._atalhos_modo = "lista"
        self._montar_conteudo()

    def _montar_gravador(self, pai) -> None:
        E.Rotulo(pai, "gravando o atalho de").pack(side="top", fill="x",
                                                   pady=(E.px(0), E.px(4)))
        tk.Label(pai, text=atalhos_mod.rotulo(self._gravando or "").upper(),
                 bg=E.FUNDO, fg=E.TEXTO, font=E.fonte(E.CORPO, "bold"),
                 anchor="w").pack(side="top", fill="x", pady=(E.px(0), E.px(10)))
        caixa = tk.Frame(pai, bg=E.FUNDO_FUNDO, height=E.px(50),
                         highlightthickness=1, highlightbackground=E.ACENTO)
        caixa.pack(side="top", fill="x")
        caixa.pack_propagate(False)
        self._ui["alvo_caixa"] = caixa
        teclas = tk.Label(caixa, text="", bg=E.FUNDO_FUNDO,
                          font=E.fonte(E.MEDIDA))
        teclas.pack(expand=True)
        self._ui["alvo_teclas"] = teclas
        recado = E.Texto(pai, "", largura=E.px(480))
        recado.pack(side="top", fill="x", pady=(E.px(8), E.px(0)))
        self._ui["alvo_recado"] = recado
        E.Botao(pai, "cancelar", self._cancelar_gravacao,
                tipo="discreto").pack(side="top", anchor="w", pady=(E.px(10), E.px(0)))
        self._pintar_gravador()

    def _aplicar_atalhos(self) -> None:
        if self.motor is None or not self.motor.disponivel:
            return
        self.motor.aplicar(dict(atalhos_mod.em_ordem(self._config)))

    def _atualizar_teclas_da_lista(self) -> None:
        """Os numeros da lista da esquerda seguem os atalhos gravados."""
        for chave, acao in (("jogo", "alternar_jogo"),
                            ("extensao", "alternar_extensao")):
            it = self._itens.get(chave)
            if it is not None:
                try:
                    it.definir(tecla=self._tecla_do(acao))
                except tk.TclError:
                    pass

    def _criar_atalho(self, acao: str) -> None:
        self._conferir_gravacao(self._config.definir_atalho(acao, ""))
        self._atalhos_modo = "lista"
        self._comecar_gravacao(acao)

    def _tirar_atalho(self, acao: str) -> None:
        self._conferir_gravacao(self._config.remover_atalho(acao))
        self.programa.anotar("atalho removido: %s" % acao)
        self._aplicar_atalhos()
        self._atualizar_teclas_da_lista()
        self._montar_conteudo()

    def _comecar_gravacao(self, acao: str) -> None:
        """Os atalhos globais saem do ar enquanto grava (o Windows engoliria)."""
        if self.motor is not None and self.motor.disponivel:
            self.motor.aplicar({})
        self._gravando = acao
        self._segurando = {}
        self._combinacao = self._tecla_final = self._recado = ""
        self._valida = False
        self.focus_set()
        self._montar_conteudo()

    def _cancelar_gravacao(self, sem_tela: bool = False) -> None:
        acao = self._gravando
        if acao is None:
            return
        if not self._config.atalhos.get(acao):
            self._config.remover_atalho(acao)
        self._gravando = None
        self._segurando = {}
        self._aplicar_atalhos()
        if not sem_tela:
            self._montar_conteudo()

    def _tecla_desceu(self, evento):
        if self._gravando is None:
            return None
        nome = evento.keysym
        if nome == "Escape":
            return None
        if evento.keycode in self._segurando:
            return "break"
        self._segurando[evento.keycode] = atalhos_mod.nome_de_tecla(nome)
        if atalhos_mod.e_modificador(nome):
            self._combinacao = atalhos_mod.escrever(self._pressionados())
            self._recado = ""
            self._valida = False
        else:
            self._congelar(nome)
        self._pintar_gravador()
        return "break"

    def _tecla_subiu(self, evento):
        if self._gravando is None or evento.keysym == "Escape":
            return None
        self._segurando.pop(evento.keycode, None)
        if self._segurando:
            if not self._tecla_final:
                self._combinacao = atalhos_mod.escrever(self._pressionados())
            self._pintar_gravador()
            return "break"
        self._terminou_o_gesto()
        return "break"

    def _perdeu_foco(self, _e=None) -> None:
        if self._gravando is not None and self._segurando:
            self._segurando = {}
            self._tecla_final = ""
            self._combinacao = ""
            self._pintar_gravador()

    def _pressionados(self) -> set[str]:
        presos = set()
        seguradas = set(self._segurando.values())
        for tk_nome, bonito in atalhos_mod.MODIFICADORES.items():
            if bonito in seguradas:
                presos.add(tk_nome)
        return presos

    def _congelar(self, keysym: str) -> None:
        mods = self._pressionados()
        self._tecla_final = keysym
        self._combinacao = atalhos_mod.escrever(mods, keysym)
        self._recado = atalhos_mod.porque_nao(mods, keysym)
        if not self._recado:
            dono = atalhos_mod.quem_usa(self._config, self._combinacao,
                                        self._gravando or "")
            if dono:
                self._recado = "Já é o atalho de: %s." % atalhos_mod.rotulo(
                    dono)
        self._valida = not self._recado

    def _terminou_o_gesto(self) -> None:
        combinacao, valida, motivo = (self._combinacao, self._valida,
                                      self._recado)
        self._segurando = {}
        self._tecla_final = ""
        self._combinacao = ""
        if not valida or not combinacao:
            self._valida = False
            self._recado = motivo
            self._pintar_gravador()
            return
        acao = self._gravando
        self._conferir_gravacao(self._config.definir_atalho(acao, combinacao))
        self.programa.anotar("atalho de %s: %s" % (acao, combinacao))
        self._gravando = None
        self._recado = ""
        self._valida = False
        self._aplicar_atalhos()
        self._atualizar_teclas_da_lista()
        self._montar_conteudo()

    def _pintar_gravador(self) -> None:
        teclas = self._ui.get("alvo_teclas")
        if teclas is None or not teclas.winfo_exists():
            return
        texto = self._combinacao.replace("+", " + ").upper()
        errado = bool(self._recado)
        if texto:
            teclas.configure(text=texto, fg=E.ERRO if errado else E.TEXTO,
                             font=E.fonte(E.MEDIDA))
        else:
            teclas.configure(text="PRESSIONE AS TECLAS", fg=E.APAGADO,
                             font=E.fonte(E.PEQUENA))
        self._ui["alvo_caixa"].configure(
            highlightbackground=E.ERRO if errado else E.ACENTO)
        self._ui["alvo_recado"].configure(
            text=(self._recado or "solte as teclas para gravar · esc cancela"
                  ).lower(),
            fg=E.ERRO if errado else E.APAGADO)

    def _conferir_recusas(self) -> None:
        if self.motor is None or not self.motor.disponivel:
            return
        agora = self.motor.falhas()
        if agora == self._recusas_conhecidas:
            return
        self._recusas_conhecidas = agora
        if agora:
            self.programa.anotar("atalhos recusados pelo Windows: %s"
                                 % ", ".join(sorted(agora)))
        if (self._visivel and self._item == "opcoes"
                and self._aba["opcoes"] == "atalhos"
                and self._gravando is None
                and getattr(self, "_atalhos_modo", "lista") == "lista"):
            self._montar_conteudo()

    # ==========================================================================
    # Mudancas de ajuste
    # ==========================================================================

    def _gravou(self, nome: str, o_que: str) -> None:
        ok = self._config.gravar()
        self.programa.anotar("ajuste '%s': %s%s"
                             % (nome, o_que, "" if ok else " (NAO GRAVOU)"))
        self._conferir_gravacao(ok)
        self.programa.mudou_a_qualidade(nome)

    def _conferir_gravacao(self, ok: bool) -> None:
        """Nao gravou: avisa UMA vez por sessao."""
        if ok or self._ja_avisou_gravacao:
            return
        self._ja_avisou_gravacao = True
        if self._config.ilegivel:
            texto = ("O config.json está com defeito, então nada que você "
                     "mudar aqui será gravado.\n\nOs ajustes valem até fechar "
                     "o programa.")
        else:
            texto = ("Não consegui gravar o config.json.\n\nOs ajustes valem "
                     "até fechar o programa. Confira se a pasta do scrcpy-f "
                     "não está só para leitura.")
        sistema.avisar(texto)

    def _perfil_mudou_fora(self, nome: str) -> None:
        """Um atalho mudou o perfil: remonta a tela se ela mostra esse perfil."""
        if self._visivel and self._item == nome and not self._grande \
                and self._gravando is None:
            self._montar_conteudo()

    def _escolheu_conteudo(self, conteudo: str) -> None:
        perfil = self._perfil_jogo()
        perfil["conteudo"] = conteudo
        self._gravou("jogo", "conteudo = %s" % conteudo)
        self._montar_conteudo()

    def _escolheu_ajuste(self, nome: str, secao: str, campo: str,
                         valor) -> None:
        perfil = self._config.perfil(nome)
        qualidade.escrever(perfil, secao, campo, valor)
        self._gravou(nome, "%s.%s = %s" % (secao, campo, valor))
        if campo == "codec":
            self._montar_conteudo()       # o kb/s acende ou apaga

    def _virar_campo(self, nome: str, secao: str, campo: str, valor,
                     remontar: bool = False) -> None:
        perfil = self._config.perfil(nome)
        perfil.setdefault(secao, {})[campo] = bool(valor)
        self._gravou(nome, "%s.%s = %s" % (secao, campo, valor))
        if remontar:
            self._montar_conteudo()

    def _botao_principal(self, nome: str) -> None:
        situacao = self.programa.situacao(nome)
        if situacao == "parado":
            self.programa.ligar(nome)
        elif situacao == "rodando" and nome in self.programa.pendentes:
            self.programa.religar(nome)
        elif situacao == "rodando":
            self.programa.desligar(nome)
        self._repintar()

    # ==========================================================================
    # Estado vindo do programa
    # ==========================================================================

    def _estado_mudou(self) -> None:
        self._repintar()

    def _textos_do_modo(self, nome: str):
        """(grande, explicacao, cor da explicacao, botao, tipo, ligado)."""
        p = self.programa
        situacao = p.situacao(nome)
        pendente = nome in p.pendentes and situacao == "rodando"
        if nome == "jogo":
            conteudo = conteudo_do(self._perfil_jogo())
            parado_txt, no_ar_txt = SUB_PARADO[conteudo], SUB_NO_AR[conteudo]
        else:
            parado_txt = "o mouse passa do pc para o celular pela borda."
            no_ar_txt = {"fora": "encoste o mouse na borda do celular.",
                         "dentro": "no celular. empurre a borda ou tab 2x."
                         }.get(p.borda_estado, "")
        cor = E.TEXTO_2
        if situacao == "parado":
            return ("parado", parado_txt, cor, "ligar", "acao", True)
        if situacao == "ligando":
            return ("ligando", "procurando o celular…", cor, "ligando…",
                    "acao", False)
        grande = "no ar"
        texto = no_ar_txt
        if nome == "extensao":
            if p.borda_estado == "dentro":
                grande = "no celular"
            cal = self._texto_da_calibracao()
            if cal:
                grande, texto, cor = cal
        if p.aplicando(nome):
            texto, cor = "aplicando o ajuste…", E.TEXTO_2
        elif pendente:
            return (grande, "religue para aplicar o ajuste.", E.ALERTA,
                    "religar", "acao", True)
        return (grande, texto, cor, "desligar", "contorno", True)

    def _texto_da_calibracao(self):
        estado = self.programa.borda_calibracao
        if estado == "aguardando":
            return ("calibrando", "não mexa o mouse um instante…", E.ALERTA)
        if estado == "falhou":
            return ("no ar", "não calibrou. pare o mouse um instante.",
                    E.ALERTA)
        if estado == "pronta":
            falta = 3.0 - (time.monotonic() - self.programa.borda_calibrada_em)
            if falta > 0:
                marcado = getattr(self, "_marca_do_calibrado", None)
                if marcado is not None:
                    try:
                        self.after_cancel(marcado)
                    except Exception:
                        pass
                self._marca_do_calibrado = self.after(
                    int(falta * 1000) + 50, self._repintar)
                return ("calibrado", "pronto: o mouse já pode passar.",
                        E.VERDE)
        return None

    def _repintar(self) -> None:
        """Poe lista, estado e botao em dia com o programa, sem remontar."""
        p = self.programa
        # (r163) A CONEXAO QUE A JANELA MOSTRA vem do programa (que agora
        # vigia em tempo real), nao do ultimo "procurar": caiu, o quadrado
        # do parear apaga e o texto diz; voltou, diz tambem (teste dele,
        # 25/set/2026: seguia "pronto: ... em uso" com o celular fora).
        cel = getattr(p, "celular", None) or {}
        conectado = bool(cel.get("serial"))
        antes = getattr(self, "_conectado_visto", None)
        if conectado != antes:
            self._conectado_visto = conectado
            if not conectado:
                self._celular_ok = False
                if antes:
                    self._pintar_status(
                        "✗  celular desconectado. ligue a depuração sem fio "
                        "(ou o cabo) e procure de novo.", E.ERRO)
            else:
                self._celular_ok = True
                if antes is False:
                    self._pintar_status("✓  conectado: %s."
                                        % (cel.get("modelo") or "celular")
                                        .lower(), E.VERDE)
        sdk = (self._sdk(), cel.get("id"))
        if sdk != getattr(self, "_sdk_montado", None):
            self._sdk_montado = sdk
            self.after_idle(self._montar_conteudo)
        try:
            for chave, it in self._itens.items():
                if not it.winfo_exists():
                    continue
                if chave in ("jogo", "extensao"):
                    it.definir(selecionado=(chave == self._item),
                               vivo=p.ativo(chave) or p.ocupado(chave))
                elif chave == "parear":
                    ok = self._celular_ok or any(
                        p.ativo(n) for n in ("jogo", "extensao", "audio"))
                    it.definir(selecionado=(chave == self._item), ok=ok)
                elif chave == "apps":
                    it.definir(selecionado=(chave == self._item),
                               vivo=bool(p.apps_abertos()))
                else:
                    it.definir(selecionado=(chave == self._item))
        except tk.TclError:
            pass
        self._conferir_status()
        self._conferir_cache()
        if self._item == "apps":
            self._pintar_lista_apps()

        if self._item in ("jogo", "extensao") and not self._grande:
            estado = self._ui.get("estado")
            if estado is not None and estado.winfo_exists():
                grande, texto, cor, botao, tipo, ligado = \
                    self._textos_do_modo(self._item)
                pintura = (self._item, grande, texto, cor, botao, tipo, ligado)
                if pintura != getattr(self, "_pintado", None):
                    self._pintado = pintura
                    estado.configure(text=grande)
                    self._ui["sub"].configure(text=texto, fg=cor)
                    acao = self._ui.get("acao")
                    if acao is not None:
                        acao.definir(botao, tipo, ligado)

        self._pintar_info_celular()

        icone = p.estado_do_icone()
        if icone != self._estado_do_icone:
            self._estado_do_icone = icone
            try:
                moldura.pintar_icone(self, icone)
            except Exception:
                pass

    def _nome_do_celular(self) -> str:
        """O modelo lido ("sm-s901e") ou "celular" sem celular lido."""
        info = getattr(self.programa, "celular", None) or {}
        return str(info.get("modelo") or "")[:20].lower() or "celular"

    def _pintar_info_celular(self) -> None:
        """(r119) A aba do STATUS tem o nome do celular: chegou/trocou o
        celular com o STATUS aberto -> refaz so as abas."""
        if self._item != "celular" or self._grande:
            return
        if self._nome_do_celular() != getattr(self, "_aba_celular_rotulo",
                                              None):
            self._montar_abas()

    def _atualizar_previa(self) -> None:
        """A marca de previa na tela: so com a extensao (basico/personalizar)."""
        mostrar = (self._visivel and self._item == "extensao" and
                   (self._grande or self._aba["extensao"] in
                    ("basico", "personalizar")))
        self.programa.previa_da_borda(mostrar)

    # ==========================================================================
    # O relogio
    # ==========================================================================

    def _passo_do_relogio(self) -> int:
        if self._visivel or self._trabalhando:
            return PASSO_MS
        p = self.programa
        if (p.ligando or p.trocando or p.sessoes
                or getattr(p, "_trocar_em", None)):
            return PASSO_MS
        return PASSO_PARADO_MS

    def _girar(self) -> None:
        # (r165) CADA PARTE NO SEU TRY: antes um erro que se repetisse no
        # passo do programa pulava todo giro os atalhos, o chamado e os
        # recados das threads -- o programa ficava surdo.
        self._parte_do_giro(self.programa.passo)
        self._parte_do_giro(self._giro_chamado)
        self._parte_do_giro(self._giro_atalhos)
        # (r120) Medidor do status ligado pela previa (ao conectar) com a
        # janela escondida: so desligava quando algo repintava a janela,
        # e o celular seguia sendo lido sem ninguem olhando.
        if getattr(self.programa, "_status_procs", None):
            self._parte_do_giro(self._conferir_status)
        for _vez in range(200):          # teto: nunca prende o relogio
            try:
                funcao = self._da_outra_thread.get_nowait()
            except queue.Empty:
                break
            self._parte_do_giro(funcao)
        if self.programa._sair:
            self._encerrar()
            return
        self.after(self._passo_do_relogio(), self._girar)

    def _parte_do_giro(self, fazer) -> None:
        try:
            fazer()
        except Exception:
            log.exception("falha no giro da janela")
            resumo = traceback.format_exc().strip().splitlines()[-1]
            if resumo not in self._erros_do_relogio:
                self._erros_do_relogio.add(resumo)
                self.programa.anotar("ERRO no giro da janela: %s" % resumo)

    def _giro_chamado(self) -> None:
        if sistema.houve_chamado():
            # (r159) O chamado pode trazer um pedido: o atalho de um app
            # abre SO o app, sem mostrar esta janela.
            pedido = sistema.ler_pedido().split("\t")
            if pedido[0] == "app" and len(pedido) >= 2:
                self.programa.abrir_pelo_atalho(
                    pedido[1], pedido[2] if len(pedido) > 2 else "")
            else:
                self.mostrar()

    def _giro_atalhos(self) -> None:
        if self.motor is None or not self.motor.disponivel:
            return
        for acao in self.motor.pedidos():
            pedido = PEDIDO_DO_ATALHO.get(acao)
            if pedido is None and acao.startswith(atalhos_mod.APP):
                pedido = ("app", acao[len(atalhos_mod.APP):])
            if pedido:
                self.programa.anotar("atalho: %s" % acao)
                self.programa.pedidos.put(pedido)
        self._conferir_recusas()

    # ==========================================================================
    # Barra: X, minimizar, arrastar
    # ==========================================================================

    def _x_apertou(self, _e=None) -> None:
        self._cancelar_x()
        self._x_apertado_id = self.after(SEGURAR_X_MS, self._x_segurou)
        self._animar("dica", SEGURAR_X_MS, self._encher_letras)

    def _pintar_dica(self, texto: str, cores=None, negrito: bool = False,
                     brilho: str = "", forca=None) -> None:
        """
        O texto alinhado a DIREITA, uma cor por letra (`cores`), ou todo
        cinza. A letra e monoespacada: cada uma tem seu lugar fixo.

        BRILHO (pedido dele): atras de cada letra acesa vai um halo da cor
        `brilho`, com a forca da letra (`forca`, 0 a 1) -- copias da letra
        deslocadas em volta, mais apagadas quanto mais longe.

        LEVE: os itens do canvas nascem UMA vez por texto; cada quadro so
        troca cores (por etiqueta, um comando por letra). Recriar tudo a
        cada 10 ms eram ~240 textos novos por quadro.
        """
        c = self._dica_x
        chave = (texto, negrito)
        if chave != getattr(self, "_dica_montada", None):
            self._dica_montada = chave
            self._dica_cores = {}
            c.delete("all")
            if texto:
                fonte = self._fonte_negrito if negrito else self._fonte_dica
                y = E.ALTURA_BARRA // 2
                direita = int(c.cget("width")) - E.px(5)
                x0 = direita - self._largura_letra * len(texto)
                for raio, _peso in HALO:
                    for i, letra in enumerate(texto):
                        if letra == " ":
                            continue
                        x = x0 + i * self._largura_letra
                        for dx, dy in _VOLTA[raio]:
                            c.create_text(x + dx, y + dy, text=letra,
                                          anchor="w", font=fonte,
                                          fill=E.FUNDO, state="hidden",
                                          tags=("h%d_%d" % (raio, i),))
                for i, letra in enumerate(texto):
                    c.create_text(x0 + i * self._largura_letra, y, text=letra,
                                  anchor="w", font=fonte, fill=E.APAGADO,
                                  tags=("l%d" % i,))
        if not texto:
            return
        feitas = self._dica_cores
        for raio, peso in HALO:
            for i, letra in enumerate(texto):
                if letra == " ":
                    continue
                f = (forca[i] * peso) if (brilho and forca) else 0.0
                etiqueta = "h%d_%d" % (raio, i)
                novo = _misturar(E.FUNDO, brilho, f) if f > 0.02 else None
                if feitas.get(etiqueta, "?") != novo:
                    feitas[etiqueta] = novo
                    if novo is None:
                        c.itemconfigure(etiqueta, state="hidden")
                    else:
                        c.itemconfigure(etiqueta, fill=novo, state="normal")
        for i in range(len(texto)):
            cor = cores[i] if cores else E.APAGADO
            etiqueta = "l%d" % i
            if feitas.get(etiqueta) != cor:
                feitas[etiqueta] = cor
                c.itemconfigure(etiqueta, fill=cor)

    def _encher_letras(self, t: float) -> None:
        """
        O laranja entra da primeira a ultima letra com a borda MACIA: a letra
        da vez vai clareando aos poucos, e nao pula de cinza para laranja.
        """
        n = len(DICA_X)
        borda = 2.0                             # letras na transicao
        frente = t * (n + borda)
        cores, forca = [], []
        for i in range(n):
            k = min(1.0, max(0.0, (frente - i) / borda))
            cores.append(_misturar(E.APAGADO, E.ACENTO, k))
            forca.append(k)
        self._pintar_dica(DICA_X, cores, brilho=E.ACENTO, forca=forca)

    def _cancelar_x(self) -> None:
        self._parar_animacao("dica")
        if self._x_apertado_id is not None:
            try:
                self.after_cancel(self._x_apertado_id)
            except Exception:
                pass
            self._x_apertado_id = None

    def _x_segurou(self) -> None:
        """
        Segurou ate o fim: "segure para sair" se apaga, "saindo…" acende em
        vermelho e fica um tempo para dar para ler; so entao o programa fecha.
        """
        self._x_apertado_id = "feito"
        saindo = "saindo…"

        def a_cada(t):
            if t < 0.45:
                k = self._entrada(t / 0.45)
                cor = _misturar(E.ACENTO, E.FUNDO, k)
                self._pintar_dica(DICA_X, [cor] * len(DICA_X),
                                  brilho=E.ACENTO,
                                  forca=[1.0 - k] * len(DICA_X))
            else:
                k = self._saida((t - 0.45) / 0.55)
                cor = _misturar(E.FUNDO, VERMELHO_SAINDO, k)
                self._pintar_dica(saindo, [cor] * len(saindo), negrito=True,
                                  brilho=VERMELHO_SAINDO,
                                  forca=[k] * len(saindo))

        def sair():
            # A janela some NA HORA; o resto da despedida (derrubar as
            # sessoes) acontece com ela ja fora da tela -- antes ela ficava
            # esperando o proximo giro do relogio e parecia demorar.
            self._sumir_ja()
            self.sair_do_programa()

        self._animar("dica", MS_TROCA_DICA, a_cada,
                     lambda: self.after(MS_SAINDO, sair))

    def _sumir_ja(self) -> None:
        try:
            self.withdraw()
            self.update_idletasks()
        except Exception:
            pass

    def _x_soltou(self, _e=None) -> None:
        if self._x_apertado_id == "feito":
            return
        self._cancelar_x()
        self._pintar_dica("", None)
        self.esconder()

    def minimizar(self) -> None:
        if self._gravando is not None:
            self._cancelar_gravacao()
        self._origem = "barra"
        moldura.minimizar(self)

    def _arrastou(self) -> None:
        self._pos = (self.winfo_x(), self.winfo_y())

    def _esc(self, _evento=None):
        """Esc desfaz UM nivel por vez; so no ultimo esconde a janela."""
        if self._gravando is not None:
            self._cancelar_gravacao()
        elif self._grande:
            self._fechar_grande()
        elif (self._item == "opcoes" and
              getattr(self, "_atalhos_modo", "lista") == "seletor"):
            self._fechar_seletor()
        else:
            self.esconder()
        return "break"

    # ==========================================================================
    # Mostrar e esconder
    # ==========================================================================

    def _tamanho(self) -> tuple[int, int]:
        if self._grande:
            return self._tamanho_grande()
        return E.LARGURA, E.ALTURA_BARRA + 1 + E.ALTURA_CORPO

    def _cancelar_animacao(self) -> None:
        self._parar_animacao("mostrar")

    def _alfa(self, valor: float) -> None:
        try:
            self.attributes("-alpha", max(0.0, min(1.0, valor)))
        except Exception:
            pass

    def alternar_pelo_atalho(self) -> None:
        """
        Atalho da janela: aberta E na frente -> volta para onde estava
        (bandeja ou barra de tarefas). Escondida, minimizada ou atras de
        outra janela -> vem para a frente.
        """
        if self._visivel and not self._escondendo:
            minimizada, na_frente = moldura.situacao(self)
            if not minimizada and na_frente:
                if self._origem == "barra":
                    self.minimizar()
                else:
                    self.esconder()
                return
        self.mostrar()

    def mostrar(self) -> None:
        """Traz a janela, subindo uns pixels perto da bandeja."""
        if not self._visivel or self._escondendo:
            self._origem = "bandeja"
        elif moldura.situacao(self)[0]:
            self._origem = "barra"
        if self._visivel and self._escondendo:
            self._cancelar_animacao()
            self._escondendo = False
            self._alfa(1.0)
            if self._pos:
                self.geometry("+%d+%d" % self._pos)
            self.deiconify()
            self._vir_para_frente()
            return
        if self._visivel:
            self.deiconify()
            self._vir_para_frente()
            return

        self._cancelar_animacao()
        self._visivel = True
        self._mostrou_em = time.monotonic()
        self._pintado = None
        l, a = self._tamanho()
        if self._pos is None:
            self._pos = moldura.canto_da_bandeja(self, l, a, E.px(12))
        x, y = self._dentro_da_tela(self._pos[0], self._pos[1], l, a)
        self._pos = (x, y)
        animar = moldura.animacoes_ligadas()
        self._alfa(0.0 if animar else 1.0)
        self.geometry("%dx%d+%d+%d" % (l, a, x, y + (SALTO_PX if animar
                                                     else 0)))
        self.deiconify()
        self._vir_para_frente()
        self._repintar()
        self._atualizar_previa()
        item = self._itens.get(self._item)
        if item is not None and not self._grande:
            self.after(30, lambda: item.winfo_exists() and item.focus_set())
        if self._falta_arrumar_a_barra:
            self._falta_arrumar_a_barra = False
            self.after(10, lambda: moldura.fixar_barra_de_tarefas(self))
        for espera in (60, 200, 500, 900, 1500, 2500):
            self.after(espera, self._conferir_aberta)
        if not animar:
            return

        def a_cada(t):
            k = self._saida(t)
            self._alfa(k)
            self.geometry("+%d+%d" % (x, y + round(SALTO_PX * (1 - k))))

        self._animar("mostrar", MS_MOSTRAR, a_cada)

    def _conferir_aberta(self) -> None:
        if not self._visivel or self._escondendo:
            return
        # (r169) PAGINA INICIAL EM APPS: a tela pesada montando junto com o
        # esconde-e-mostra de `fixar_barra_de_tarefas` deixava a janela
        # MINIMIZADA sem ninguem pedir (so o botao na barra). Nos primeiros
        # segundos depois de abrir, minimizada sem ele ter pedido = volta.
        try:
            minimizada = moldura.situacao(self)[0]
        except Exception:
            minimizada = False
        if minimizada and self._origem != "barra" and \
                time.monotonic() - getattr(self, "_mostrou_em", 0) < 3:
            self.deiconify()
            self._vir_para_frente()
            if not getattr(self, "_anotou_minimizada", False):
                self._anotou_minimizada = True
                self.programa.anotar("janela: abriu MINIMIZADA sozinha; "
                                     "restaurada")
        try:
            if moldura.garantir_visivel(self) and not self._anotou_escondida:
                self._anotou_escondida = True
                self.programa.anotar("janela: estava ESCONDIDA pelo Windows; "
                                     "mostrada de novo")
            estava, conseguiu = moldura.trazer_para_frente(self)
        except Exception:
            return
        if estava != "ok":
            if conseguiu:
                self.focus_force()
            if not self._anotou_a_frente:
                self._anotou_a_frente = True
                self.programa.anotar("janela: abriu %s; %s" % (
                    estava, "trazida para a frente" if conseguiu
                    else "o Windows NAO deixou vir para a frente"))

    def _vir_para_frente(self) -> None:
        self.lift()
        try:
            self.attributes("-topmost", True)
            self.after(60, lambda: self.attributes("-topmost", False))
        except Exception:
            pass
        self.focus_force()

    def esconder(self) -> None:
        """Some voltando para a bandeja. O programa continua rodando."""
        if not self._visivel or self._escondendo:
            return
        if self._gravando is not None:
            self._cancelar_gravacao()
        if self.programa.bandeja is None or \
                not getattr(self.programa.bandeja, "disponivel", False):
            self.minimizar()
            return
        if self._gravando is not None:
            self._cancelar_gravacao()
        self._cancelar_animacao()
        if not moldura.animacoes_ligadas():
            self._sumir()
            return
        self._escondendo = True
        x, y = self.winfo_x(), self.winfo_y()

        def a_cada(t):
            k = self._entrada(t)
            self._alfa(1.0 - k)
            self.geometry("+%d+%d" % (x, y + round(SALTO_PX * k)))

        def fim():
            self._escondendo = False
            self._sumir()
            self.geometry("+%d+%d" % (x, y))

        self._animar("mostrar", MS_ESCONDER, a_cada, fim)

    def _sumir(self) -> None:
        self._origem = "bandeja"
        self._visivel = False
        self._atualizar_previa()
        self.withdraw()
        self._alfa(1.0)
        if self._grande:
            self._fechar_grande(animar=False)

    # ==========================================================================
    # Saida
    # ==========================================================================

    def sair_do_programa(self) -> None:
        """Segurar o X: o programa inteiro fecha, sessoes junto."""
        self.programa.anotar("pedido: sair (segurou o X)")
        self.programa.encerrar()

    def _encerrar(self) -> None:
        try:
            self.withdraw()
        except Exception:
            pass
        self._parar_trabalho.set()
        try:
            self.programa.desligar_tudo()
        except Exception:
            log.exception("falha ao desligar as sessoes")
        try:
            if self.motor is not None:
                self.motor.encerrar()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


def _misturar(a: str, b: str, k: float) -> str:
    """Cor entre `a` (k=0) e `b` (k=1), em "#RRGGBB"."""
    k = min(1.0, max(0.0, k))
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02X%02X%02X" % tuple(round(x + (y - x) * k)
                                   for x, y in zip(ca, cb))


def _volta(raio: int) -> list[tuple[int, int]]:
    """Os pontos em volta da letra onde as copias do brilho vao."""
    if raio <= 0:
        return []
    pontos = [(raio, 0), (-raio, 0), (0, raio), (0, -raio)]
    d = max(1, round(raio * 0.7))
    pontos += [(d, d), (-d, d), (d, -d), (-d, -d)]
    return pontos


_VOLTA = {r: _volta(r) for r, _p in HALO}


def _encurtar(texto: str, n: int) -> str:
    """Corta com reticencias para caber embaixo do icone."""
    return texto if len(texto) <= n else texto[:n - 1] + "…"


class _Rolagem:
    """
    Area com rolagem vertical no estilo da casa (pedido dele, 23/set/2026:
    "a lista de apps tem que ter a scrollbar"): um canvas com a lista dentro
    e, ao lado, uma barra fina -- trilho de 1 px e o cursor laranja, que so
    aparece quando ha mais do que cabe. Arrastar o cursor ou clicar no
    trilho rola; a roda do mouse chega pela `Janela._roda_global`.
    """

    def __init__(self, pai) -> None:
        self.canvas = tk.Canvas(pai, bg=E.FUNDO, highlightthickness=0, bd=0,
                                yscrollincrement=E.px(24))
        self.barra = tk.Canvas(pai, width=E.px(6), bg=E.FUNDO,
                               highlightthickness=0, bd=0, cursor="hand2")
        self.barra.pack(side="right", fill="y", padx=(E.px(4), E.px(0)))
        self.canvas.pack(side="left", fill="both", expand=True)
        self.dentro = tk.Frame(self.canvas, bg=E.FUNDO)
        self._item = self.canvas.create_window(0, 0, window=self.dentro,
                                               anchor="nw")
        self._pos = (0.0, 1.0)
        self._arraste = None
        self.dentro.bind("<Configure>", lambda _e: self._medir())
        self.canvas.bind("<Configure>", self.largura)
        self.canvas.configure(yscrollcommand=self._rolou)
        self.barra.bind("<Configure>", lambda _e: self._pintar())
        self.barra.bind("<Button-1>", self._clicou)
        self.barra.bind("<B1-Motion>", self._arrastou)

    def largura(self, evento) -> None:
        self.canvas.itemconfigure(self._item, width=evento.width)

    def _medir(self) -> None:
        caixa = self.canvas.bbox("all") or (0, 0, 0, 0)
        self.canvas.configure(scrollregion=caixa)

    def _rolou(self, primeiro, ultimo) -> None:
        self._pos = (float(primeiro), float(ultimo))
        self._pintar()

    def _cabe_tudo(self) -> bool:
        return self._pos[1] - self._pos[0] >= 0.999

    def _pintar(self) -> None:
        b = self.barra
        b.delete("all")
        if self._cabe_tudo():
            return
        altura, larg = b.winfo_height(), b.winfo_width()
        b.create_rectangle(larg // 2, 0, larg // 2 + 1, altura,
                           fill=E.LINHA, width=0)
        topo = int(self._pos[0] * altura)
        base = max(topo + E.px(16), int(self._pos[1] * altura))
        b.create_rectangle(0, topo, larg, base, fill=E.ACENTO, width=0)

    def _clicou(self, evento) -> None:
        altura = max(1, self.barra.winfo_height())
        fracao = evento.y / altura
        p0, p1 = self._pos
        if p0 <= fracao <= p1:
            self._arraste = (evento.y, p0)
        else:
            self._arraste = None
            self.canvas.yview_moveto(max(0.0, fracao - (p1 - p0) / 2))

    def _arrastou(self, evento) -> None:
        if self._arraste is None:
            return
        y0, p0 = self._arraste
        altura = max(1, self.barra.winfo_height())
        self.canvas.yview_moveto(max(0.0, p0 + (evento.y - y0) / altura))

    def roda(self, evento):
        if not self._cabe_tudo():
            passos = -int(evento.delta / 120) or (-1 if evento.delta > 0
                                                  else 1)
            self.canvas.yview_scroll(passos, "units")
        return "break"

    def limpar(self, manter: bool = False) -> None:
        """Esvazia a lista. `manter`: volta ao mesmo ponto da rolagem depois
        de remontar (abrir um app nao joga a lista para o topo)."""
        ponto = self._pos[0]
        for filho in self.dentro.winfo_children():
            filho.destroy()
        if manter:
            self.canvas.after_idle(lambda: self.canvas.yview_moveto(ponto))
        else:
            self.canvas.yview_moveto(0)


def _gb(n: float) -> str:
    """Bytes em GB, com virgula: 59177504768 -> "55,1 GB"."""
    return ("%.1f GB" % (n / 1024 ** 3)).replace(".", ",")


def _mb(n: float) -> str:
    """Bytes em MB (ou GB, a partir de 1 GB)."""
    if n >= 1024 ** 3:
        return _gb(n)
    return "%d MB" % round(n / 1024 ** 2)
