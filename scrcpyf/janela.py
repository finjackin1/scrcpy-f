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
               formatos, moldura, monitores as mon, qualidade, sistema)
from . import estudio as E
from . import movimento as mov
from . import filtro_animado as FA
from .programa import APP, COPIA, DEX, conteudo_do
from .notificacoes import botoes_de_tela as nt_botoes, codigo_de as nt_codigo
from . import visual_notif as VN

log = logging.getLogger(__name__)

PASSO_MS = 100
PASSO_PARADO_MS = 250
SEGURAR_X_MS = 1000
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
MS_DISPENSA = 200        # (03/out) cartao saindo de lado (SwipeHelper)
# (07/out) Botoes da barra: o som (clique troca pc/celular, segurar 1 s =
# os dois) e a conexao (clique troca cabo/sem fio, segurar 2 s =
# desconectar tudo). Os textos so vao para o log.
SEGURAR_SOM_MS = 1000
SEGURAR_CON_MS = 2000
TEXTO_SOM = {"pc": "som: no pc", "celular": "som: no celular",
             "ambos": "som: nos dois"}
TEXTO_CON = {"cabo": "conexão: cabo", "sem_fio": "conexão: sem fio",
             "": "sem celular", "pausada": "desconectado"}
SALTO_PX = E.px(10)
# A janela crescendo para o mapa grande (e voltando).
ORDEM_DOS_ITENS = ["jogo", "extensao", "apps", "celular", "notif", "parear",
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
    "mini_player": "mini_player",
}

# REORGANIZACAO DE 23/set/2026 (pedido dele: nomes sem duvida, abas em
# ordem alfabetica -- menos a PRIMEIRA de cada item, que e a tela que abre
# ao entrar nele). As
# CHAVES continuam as de antes (config e codigo); so o que aparece mudou.
ABAS = {
    "jogo": [("basico", "espelhar")],
    "extensao": [("basico", "básico"), ("personalizar", "posição e marca"),
                 ("avancado", "som e controles")],
    "apps": [("lista", "apps"), ("aparencia", "ajustes"),
             ("personalizados", "personalizados")],
    "celular": [("status", "celular")],
    # (01/out) As notificacoes do celular: como no celular, o historico de
    # 24 h (como o do Samsung) e as chaves.
    "notif": [("lista", "notificações"), ("ajustes", "ajustes"),
              ("historico", "histórico"), ("player", "player")],
    # (r193) Duas abas pela frequencia de uso (pedido dele, 30/set/2026: o
    # parear estava "desconexo"): o dia a dia e o celular novo.
    "parear": [("conexao", "conexão"), ("adicionar", "adicionar")],
    "opcoes": [("geral", "geral"), ("rodape", "rodapé"),
               ("atalhos", "atalhos"), ("qualidade", "qualidade")],
}

# O que depende da versao do Android (documentacao do scrcpy): som no
# pc = Android 11 (API 30); tocar no pc E no celular = 13 (API 33); app em
# janela propria (tela virtual) = 10 (API 29). Sem celular lido, nada trava.
APPS_RECENTES = 8
# APPS > ajustes que mudam a janela de um app aberto (os outros so mudam a
# lista): reabrem os apps abertos (r123).
AJUSTES_DA_JANELA_DO_APP = ("onde", "formato", "modo", "itens", "res_pc",
                            "forma", "melhor_auto", "escala")
# Ajustes do app que NAO mexem na janela aberta (nao reabrem) -- r134.
# (08/out) "tela_cheia" reabre pelo proprio caminho (entra/sai na hora)
AJUSTES_SEM_REABRIR = ("ao_fechar", "tela_cheia", "rodinha_arrasto")
# (09/out, pedido dele: so a porcentagem) o tamanho nos apps (formatos.TAMANHOS)
OPCOES_ESCALA = [("menor", "90%"), ("normal", "100%"), ("maior", "115%"),
                 ("bem_maior", "130%")]
# Ao fechar a janela de um app (r134).
AO_FECHAR = [("fechar", "fechar o app"), ("deixar", "deixar aberto")]
# Os grupos do editor do app personalizado, na ordem (07/out).
GRUPOS_DO_EDITOR = ("janela", "video", "audio", "outros")
# Telas que ficam guardadas (escondidas) ao sair e voltam prontas (r115/116).
TELAS_GUARDADAS = ("_tela_apps_lista", "_tela_opcoes_qualidade",
                   "_tela_opcoes_atalhos", "_tela_notif_ajustes",
                   "_tela_notif_lista", "_tela_notif_historico")
# (08/out, pedido dele: "diminuir ao maximo o tempo de carregamento") As
# telas que eram refeitas a cada visita (100-200 ms cada, medido) tambem
# ficam guardadas; a `_assinatura` delas e a GERAL (`_assinatura_geral`):
# o config inteiro + o estado do celular/conexao/janela que elas leem ao
# montar. Mudou algo = monta de novo. De fora: PAREAR (monta com a procura
# e o status dela). O STATUS volta com os numeros zerados para o relogio
# dele pintar de novo (`_conferir_status`, chamado pelo `_repintar`).
TELAS_GUARDADAS_GERAL = ("_tela_jogo_basico", "_tela_extensao_basico",
                         "_tela_extensao_personalizar",
                         "_tela_extensao_avancado", "_tela_apps_aparencia",
                         "_tela_apps_personalizados", "_tela_opcoes_geral",
                         "_tela_opcoes_rodape", "_tela_celular_status",
                         "_tela_notif_player")
TELAS_GUARDADAS = TELAS_GUARDADAS + TELAS_GUARDADAS_GERAL

PRECISA = {"som": (30, "11"), "pc_cel": (33, "13"), "apps": (29, "10")}

CONTEUDOS = [("ambos", "imagem+som"), ("som", "só som"),
             ("imagem", "só imagem")]

# Nomes curtos para as fileiras do avancado (cabem na coluna de 78 px).
NOME_CURTO = {
    ("video", "codec"): "codec", ("video", "bitrate"): "mb/s",
    ("video", "fps_max"): "quadros", ("video", "resolucao_max"): "resolução",
    ("video", "resolucao"): "resolução",
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
                     "celular": "status", "notif": "lista",
                     "parear": "conexao", "opcoes": "geral"}
        self._metodo = "cabo"           # (r193) ADICIONAR: "cabo" | "codigo"
        self._prontos_vistos = None     # (r193) outros celulares ao vivo
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
        self._ui: dict = {}
        self._notif_abertas: set = set()   # (02/out) cartoes abertos
        # (03/out) Responder pelo PC: o cartao com a caixa aberta, o que ja
        # foi digitado em cada um (o cartao e refeito quando chega mensagem
        # nova; o texto nao se perde) e o recado embaixo da caixa.
        self._respondendo: str = ""
        self._rascunhos: dict = {}
        self._recado_resposta: dict = {}
        # (03/out) tiradas aqui (x/arraste), antes do celular confirmar; e os
        # botoes do app esperando a resposta do celular ("marcar como lida …")
        self._notif_dispensadas: dict = {}
        self._acao_pendente: set = set()
        self._notif_tempo_grupo: dict = {}   # app -> hora que ordena o grupo
        self._notif_tempo_item: dict = {}    # chave -> hora que a ordena
        self._fotos_notif: dict = {}
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
        # (07/out, padrao do botao direito) toda caixa de texto tem o menu
        # da casa: recortar, copiar, colar, selecionar tudo (o Tk nao tem)
        self.bind_class("Entry", "<Button-3>", self._menu_texto)
        # (07/out) quando foi o ultimo clique/tecla dele (ver efeito em
        # `_montar_conteudo`)
        for ev in ("<ButtonRelease-1>", "<KeyPress>"):
            self.bind_all(ev, lambda _e: setattr(
                self, "_ultimo_toque", time.monotonic()), add="+")
        self._menu_app = None

        programa.ouvintes.append(self._estado_mudou)
        programa.ao_mostrar = self.mostrar
        programa.ao_alternar_janela = self.alternar_pelo_atalho
        programa.ao_mini_player = self.alternar_mini_player
        programa.ao_menu_bandeja = self._menu_bandeja
        # (07/out) avisos e perguntas do programa na caixa da casa
        sistema.CAIXA = lambda msg, tit, botoes, resp: \
            self._da_outra_thread.put(
                lambda: self._caixa_da_casa(msg, tit, botoes, resp))
        # janela fechada (saindo): de volta a caixa do Windows
        self.bind("<Destroy>", lambda e: e.widget is self and setattr(
            sistema, "CAIXA", None), add="+")
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
            # (07/out) fora da thread da tela: pergunta ao Agendador
            threading.Thread(target=inicio_windows.arrumar, daemon=True,
                             name="windows-arrumar").start()
            self._ler_o_windows()
        # O celular conecta sozinho ao abrir (pedido dele, 23/set/2026): nada
        # de entrar no PAREAR so para ver o quadradinho verde.
        self.after(1200, self._conectar_ao_abrir)
        self.bind_all("<MouseWheel>", self._roda_global, add="+")
        # (03/out) Ctrl+F vai para a busca da tela (apps, ajustes das notif.)
        self.bind_all("<Control-f>", self._ir_para_busca, add="+")
        self.bind_all("<Control-F>", self._ir_para_busca, add="+")
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

        # (07/out, pedido dele: "padronizar a separacao entre os icones e o
        # espaco clicavel") OS 4 BOTOES DA BARRA -- fechar, minimizar, som,
        # conexao -- sao CELULAS IGUAIS (ver "botoes da barra"): a altura
        # inteira da barra, a mesma largura, o icone do mesmo tamanho no meio
        # e o mesmo realce. Encostadas, sem vao entre elas (como os do
        # Windows 11): o clique nunca cai num buraco entre dois botoes.
        self._botoes_barra = {}
        # (07/out, pedido dele) a esquerda do minimizar: OPCOES e, a esquerda
        # dele, PAREAR -- sairam da lista da esquerda e ficaram no lugar dos
        # indicadores de som e conexao (que foram para o rodape da lista).
        # O clique abre a tela com a animacao SAINDO DO BOTAO.
        for tipo in ("fechar", "minimizar", "opcoes", "parear"):
            b = self._botao_barra(barra, tipo)
            b.pack(side="right", fill="y")
            if tipo == "minimizar":
                b.bind("<Button-1>", lambda _e, b=b: (
                    self._barra_apertou(b), self.minimizar()))
            elif tipo == "fechar":
                b.bind("<ButtonPress-1>",
                       lambda _e, b=b: self._barra_apertou(b))
                b.bind("<ButtonRelease-1>",
                       lambda _e, b=b: self._barra_soltou(b))
            else:
                b.bind("<Button-1>", lambda _e, b=b: (
                    self._barra_apertou(b), self._abrir_pela_barra(b)))
        # (07/out, pedido dele) o "segure para sair" escrito saiu: segurar
        # enche o proprio botao de cor (fechar).

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

        # (07/out, pedido dele) os indicadores bem no CANTO da janela (fora
        # da margem da lista), alinhados
        # (08/out, pedido dele) a largura toda: icones a esquerda, a barrinha
        # da verificacao dos apps a direita
        rodape = tk.Frame(lista, bg=E.FUNDO)
        rodape.pack(side="bottom", fill="x", padx=E.px(6),
                    pady=(E.px(0), E.px(5)))
        dentro = tk.Frame(lista, bg=E.FUNDO)
        dentro.pack(fill="both", expand=True, padx=E.PADDING,
                    pady=(E.PADDING, E.px(2)))
        E.Rotulo(dentro, "modos").pack(side="top", fill="x", pady=(E.px(0), E.px(8)))
        self._itens = {}
        # (03/out, pedido dele) Os sete itens IGUAIS: mesma caixa (opcoes
        # tambem), sem o vao antes do PAREAR e sem a linha antes de OPCOES;
        # a sobra de altura se divide por igual entre eles (`expand`).
        # (r119) O nome verde + bateria embaixo do PAREAR saiu: o nome do
        # celular e o titulo da aba do STATUS.
        # (07/out, pedido dele) PAREAR e OPCOES foram para a barra de cima;
        # no lugar deles, o RODAPE com os indicadores de conexao e de som,
        # lado a lado (`_montar_rodape`).
        # (08/out, pedido dele) sem a tecla do atalho no botao
        for chave, rotulo, marca in (
                ("jogo", "espelhar", ""),
                ("extensao", "extensão", ""),
                ("apps", "apps", ""),
                ("celular", "status", ""),
                ("notif", "notificações", "")):
            it = E.Item(dentro, rotulo, lambda c=chave: self._escolher_item(c),
                        tecla="", marca=marca)
            it.pack(side="top", fill="x", expand=True,
                    pady=(E.px(0), E.px(5)))
            self._itens[chave] = it
        self._montar_rodape(rodape)
        self._travar_itens()
        self._caber_lista(lista, dentro)

        # Teclado: setas andam pela lista (Enter/Espaco escolhem).
        for chave, item in self._itens.items():
            item.bind("<Up>", lambda _e, c=chave: self._focar_item(c, -1))
            item.bind("<Down>", lambda _e, c=chave: self._focar_item(c, +1))

        self._montar_abas()
        self._montar_conteudo()
        self._pre_geracao = getattr(self, "_pre_geracao", 0) + 1
        geracao = self._pre_geracao
        self.after(1500, lambda: self._pre_montar(geracao))

    def _caber_lista(self, lista, dentro) -> None:
        """
        (03/out, teste do amigo: "opcoes" cortado embaixo) A altura e a
        largura da lista eram fixas e so cabiam com a letra e a escala da
        maquina dele (sobravam 2 px). Com outra escala do Windows, tela menor
        ou sem a Cascadia Mono (Windows 10 cai na Consolas), o rodape saia da
        janela. Agora a lista mede o que precisa (com "F12" no atalho, o mais
        largo) e a janela cresce o que faltar. Uma vez por execucao.
        """
        if getattr(self, "_lista_medida", False):
            return
        self._lista_medida = True
        it = self._itens["jogo"]
        antes = it._tecla.cget("text")
        try:
            it.definir(tecla="F12")
            dentro.update_idletasks()
            alt, larg = dentro.winfo_reqheight(), dentro.winfo_reqwidth()
        finally:
            it.definir(tecla=antes)
        falta_a = alt + 2 * E.PADDING + E.px(4) - E.ALTURA_CORPO
        falta_l = larg + 2 * E.PADDING - E.LARGURA_LISTA
        self.programa.anotar("lista da esquerda: precisa %dx%d, tem %dx%d "
                             "(escala %.2f, dpi %.2f, letra %s)" % (
                                 larg + 2 * E.PADDING,
                                 alt + 2 * E.PADDING + E.px(4),
                                 E.LARGURA_LISTA, E.ALTURA_CORPO,
                                 E.ESCALA, E.DPI, E.familia()))
        if falta_a > 0:
            E.ALTURA_CORPO += falta_a
            E.ALTURA_GRANDE_CORPO += falta_a
        if falta_l > 0:
            E.LARGURA_LISTA += falta_l
            E.LARGURA += falta_l
            E.LARGURA_GRANDE += falta_l
            lista.configure(width=E.LARGURA_LISTA)
        if (falta_a > 0 or falta_l > 0) and not getattr(self, "_grande", False):
            self.geometry("%dx%d" % self._tamanho())

    def _ele_esta_usando(self) -> bool:
        """(07/out, pedido dele: "a engine nao pode afetar a interface") A
        janela esta a vista e ele mexeu no mouse/teclado ha menos de 1,5 s
        com ela na frente ou o mouse em cima: trabalho pesado de fundo no
        Tk (montar telas escondidas) espera, senao ele sente a travada."""
        if not self._visivel:
            return False
        try:
            import ctypes
            from ctypes import wintypes

            class _LII(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT),
                            ("dwTime", wintypes.DWORD)]
            u, k = ctypes.windll.user32, ctypes.windll.kernel32
            lii = _LII(ctypes.sizeof(_LII), 0)
            if not u.GetLastInputInfo(ctypes.byref(lii)):
                return False
            parado = (k.GetTickCount() - lii.dwTime) & 0xFFFFFFFF
            if parado >= 1500:
                return False
            x, y = self.winfo_pointerxy()
            em_cima = self.winfo_containing(x, y) is not None
            # (sem moldura.situacao: ela faz update_idletasks, o peso que
            # se quer evitar)
            return em_cima or u.GetForegroundWindow() == int(
                self.wm_frame(), 16)
        except Exception:
            return False

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
        precisa_apps = tela in ("_tela_apps_lista", "_tela_opcoes_atalhos",
                                "_tela_notif_ajustes")
        ocupado = (self._grande or getattr(self, "_veu", None) is not None
                   or getattr(self, "_lotes_de", None) or FA.animando()
                   or self._gravando is not None
                   or (precisa_apps and (self._apps_carregando
                                         or not self._apps)))
        if ocupado:
            self.after(1000, lambda: self._pre_montar(geracao, tentativa + 1))
            return
        if self._ele_esta_usando():
            # sem gastar tentativa: so espera ele parar
            self.after(700, lambda: self._pre_montar(geracao, tentativa))
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
        # (07/out) so os itens que estao na lista (parear e opcoes na barra)
        ordem = [c for c in ORDEM_DOS_ITENS if c in self._itens]
        if de not in ordem:
            return "break"
        destino = ordem[(ordem.index(de) + passo) % len(ordem)]
        item = self._itens.get(destino)
        if item is not None:
            item.focus_set()
        return "break"

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
        visiveis = self._abas_visiveis()
        self._abas_montadas = (self._item, tuple(visiveis))
        chaves = [c for c, _r, _t in visiveis]
        for chave, rotulo, travada in visiveis:
            if (self._item, chave) == ("celular", "status"):
                rotulo = self._aba_celular_rotulo = self._nome_do_celular()
            a = E.Aba(self._abas_frame, rotulo,
                      lambda c=chave: self._escolher_aba(c))
            a._chave = chave
            a.pack(side="left", fill="y", padx=(E.px(0), E.px(16)))
            a.definir(chave == self._aba[self._item])
            if travada:
                # (r185) Sem o scrcpy: apagada, sem foco nem clique.
                a.configure(fg=E.LINHA_FORTE, cursor="arrow", takefocus=0)
            if chave == self._aba[self._item]:
                self._sublinhar(a)
            # Teclado: setas trocam de aba.
            k = chaves.index(chave)
            a.bind("<Left>", lambda _e, k=k: self._aba_vizinha(k - 1))
            a.bind("<Right>", lambda _e, k=k: self._aba_vizinha(k + 1))
            self._abas_w.append(a)

    def _marcar_aba_no_lugar(self, aba: str) -> bool:
        """Troca a aba escolhida sem refazer a barra. False = as abas a vista
        nao sao as deste item (ai quem chama remonta)."""
        if self._grande or getattr(self, "_abas_montadas", None) != (
                self._item, tuple(self._abas_visiveis())):
            return False
        abas = [a for a in self._abas_w if getattr(a, "_chave", None)]
        alvo = next((a for a in abas if a._chave == aba), None)
        if alvo is None:
            return False
        try:
            # (07/out, gravado: a cor trocava NA HORA e o sublinhado so andava
            # depois da montagem da tela -- a "piscada") As cores esmaecem
            # JUNTO com o sublinhado, no mesmo movimento.
            livres = [a for a in abas if str(a.cget("fg")) != E.LINHA_FORTE]
            # cliques seguidos: a troca anterior termina na hora
            pendente = getattr(self, "_cores_abas", None)
            if pendente is not None:
                pendente(1.0)
            saindo = [a for a in livres if a._sel and a is not alvo]

            def cores(k):
                for a in saindo:
                    a.configure(fg=VN.misturar(E.APAGADO, E.TEXTO, k))
                if not alvo._sel:
                    alvo.configure(fg=VN.misturar(E.TEXTO, E.APAGADO, k))
                if k >= 1.0:
                    if getattr(self, "_cores_abas", None) is cores:
                        self._cores_abas = None
                    for a in livres:
                        if a.winfo_exists():
                            a.definir(a is alvo)
            self._cores_abas = cores
            velho = getattr(self, "_risco", None)
            if velho is not None:
                mov.parar(velho, "deslizar")     # o novo o tira ao andar
            self._sublinhar(alvo, cores)
        except tk.TclError:
            return False
        return True

    def _abas_visiveis(self) -> list:
        """
        (r185, pedidos dele) As abas do item agora: [(chave, rotulo,
        travada)]. PERSONALIZADOS so aparece com algum app personalizado
        (ou com um sendo editado). Sem o scrcpy, em OPCOES so "geral"
        abre: atalhos e qualidade ficam travadas.
        """
        saida = []
        sem_scrcpy = not self._config.instalacao_ok
        for chave, rotulo in ABAS[self._item]:
            if (self._item, chave) == ("apps", "personalizados") and not (
                    self._config.personalizados()
                    or getattr(self, "_app_configurado", None)):
                continue
            travada = sem_scrcpy and self._item == "opcoes" and \
                chave != "geral"
            saida.append((chave, rotulo, travada))
        return saida

    def _acertar_abas(self) -> None:
        """(r185) A aba escolhida sumiu ou travou -> a primeira; e se a
        barra de abas montada nao bate com a de agora, remonta."""
        visiveis = self._abas_visiveis()
        livres = [c for c, _r, t in visiveis if not t]
        if livres and self._aba.get(self._item) not in livres:
            self._aba[self._item] = livres[0]
        if getattr(self, "_abas_montadas", None) != (self._item,
                                                    tuple(visiveis)) \
                and not self._grande:
            self._montar_abas()

    def _aba_vizinha(self, k: int):
        chaves = [c for c, _r, _t in self._abas_visiveis()]
        if 0 <= k < len(chaves):
            self._escolher_aba(chaves[k])
        return "break"

    def _focar_aba_escolhida(self) -> None:
        chaves = [c for c, _r, _t in self._abas_visiveis()]
        try:
            k = chaves.index(self._aba[self._item])
            self._abas_w[k].focus_set()
        except (ValueError, IndexError, tk.TclError):
            pass

    RISCO_L = E.px(28)

    def _sublinhar(self, aba: tk.Label, cores=None) -> None:
        """O sublinhado laranja da aba escolhida, grudado embaixo dela.
        (07/out, padrao de animacao) Trocando de aba no mesmo item, ele
        DESLIZA da aba anterior ate a nova (como as abas do Android)."""
        # (07/out, pedido dele) o sublinhado tem SEMPRE o mesmo tamanho,
        # centrado na aba, qualquer que seja o tamanho do nome dela; so
        # desliza de uma para a outra.
        larg = self.RISCO_L
        # (07/out) o sublinhado velho FICA ate o novo comecar a andar (depois
        # da montagem da tela): sem ele, a barra ficava sem sublinhado
        anterior = getattr(self, "_risco", None)
        risco = tk.Frame(self._abas_frame, bg=E.ACENTO, height=E.px(2))
        de = getattr(self, "_risco_de", None)
        self._risco_de = None
        self._risco = risco

        def tirar_anterior():
            try:
                if anterior is not None and anterior is not risco and \
                        anterior.winfo_exists():
                    mov.parar(anterior, "deslizar")
                    anterior.destroy()
            except tk.TclError:
                pass

        def grudar():
            tirar_anterior()
            try:
                risco.place(in_=aba, relx=0.5, rely=1.0, y=-E.px(2),
                            relwidth=0, x=-(larg // 2), width=larg)
                if cores is not None:
                    cores(1.0)
            except tk.TclError:
                pass

        def pos(_e=None):
            if de is None or not self._visivel:
                grudar()
                return
            try:
                aba.update_idletasks()
                c1 = aba.winfo_x() + aba.winfo_width() / 2.0
                # a mesma altura do parado ("in_=aba" conta de DENTRO da aba:
                # sem a borda e sem o anel de foco dela)
                dentro = int(float(aba.cget("highlightthickness") or 0)) + \
                    int(float(aba.cget("bd") or 0))
                y = aba.winfo_y() + aba.winfo_height() - E.px(2) - dentro
            except tk.TclError:
                return
            c0 = de

            def a_cada(k):
                tirar_anterior()
                risco.place(in_=self._abas_frame,
                            x=round(c0 + (c1 - c0) * k - larg / 2.0),
                            y=y, width=larg, relx=0, relwidth=0, rely=0)
                if cores is not None:
                    cores(min(1.0, max(0.0, k)))

            def terminou():
                # (07/out, gravado) sem re-colocar "in_=aba": la a conta e de
                # dentro da borda da aba e o sublinhado pulava 1 px no fim
                tirar_anterior()
                if cores is not None:
                    cores(1.0)
            mov.animar(risco, "deslizar", mov.MS_POPUP_ENTRA + 60, a_cada,
                       fim=terminou)
        aba.after_idle(pos)

    def _guardar_risco(self) -> None:
        """Antes de remontar as abas: onde o sublinhado estava."""
        r = getattr(self, "_risco", None)
        try:
            if r is not None and r.winfo_exists() and r.winfo_ismapped():
                self._risco_de = r.winfo_x() + r.winfo_width() / 2.0
        except tk.TclError:
            self._risco_de = None

    def _esvaziar_caixas(self) -> None:
        """Trocou de tela: o que foi digitado nas caixas nao fica (pedido
        dele, 23/set/2026)."""
        self._apps_busca = ""
        self._busca_escolha = ""
        self._renomeando = None

    def _voltar_ao_inicio(self) -> None:
        """(09/out, pedido dele) Clicou no item (ou no botao da barra) em que
        ja esta, numa aba que nao e a primeira: volta para a tela inicial
        dele (a 1a aba). O editor de um app aberto em personalizados fecha
        junto (a proxima visita la comeca na lista)."""
        if self._grande:
            return
        livres = [c for c, _r, t in self._abas_visiveis() if not t]
        if not livres or self._aba.get(self._item) == livres[0]:
            return
        if self._item == "apps":
            self._app_configurado = None
            self._escolhendo_app = False
        self._escolher_aba(livres[0])

    def _escolher_item(self, item: str, origem=None) -> None:
        if item == self._item:
            self._voltar_ao_inicio()
            return
        if item != "opcoes" and not self._config.instalacao_ok:
            return                          # (r180) travado sem o scrcpy
        self._esvaziar_caixas()
        self._cancelar_gravacao(sem_tela=True)
        self._atalhos_modo = "lista"
        self._item = item
        self._pintar_barra()            # o botao da barra (opcoes/parear)
        # (07/out) as abas entram juntas; o veu cobre ANTES de refazer
        self._revelar_abas(origem)
        self._montar_abas()
        # ANIMACAO (pedido dele, 23/set/2026): os modos ficam na esquerda,
        # entao a tela nova sai da borda ESQUERDA para a direita. (07/out)
        # Pelos botoes da barra, ela NASCE DO BOTAO (`origem`).
        self._montar_conteudo(deslizar=("botao", origem) if origem
                              else ("x", -1))
        # O anel de foco acompanha o item escolhido (clique ou teclado).
        novo = self._itens.get(item)
        if novo is not None:
            novo.focus_set()

    def _escolher_aba(self, aba: str) -> None:
        if aba == self._aba[self._item]:
            return
        if any(c == aba and t for c, _r, t in self._abas_visiveis()):
            return                          # (r185) travada sem o scrcpy
        self._esvaziar_caixas()
        self._cancelar_gravacao(sem_tela=True)
        # A aba com o foco e destruida ao remontar: o foco volta para a nova.
        foco_nas_abas = self.focus_get() in self._abas_w
        self._aba[self._item] = aba
        self._guardar_risco()            # (07/out) o sublinhado desliza
        # (07/out, relato dele: "o texto da barra da uma piscada") Mesmo item:
        # as abas FICAM -- so muda a escolhida e o sublinhado anda. Refazer
        # todas apagava os nomes por um instante.
        if not self._marcar_aba_no_lugar(aba):
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
        self.abrir_em("parear", "conexao")
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
        # (07/out) PAREAR foi para a barra: trava igual
        b = (getattr(self, "_botoes_barra", None) or {}).get("parear")
        if b is not None and getattr(b, "_travado", False) != travar:
            b._travado = travar
            self._pintar_barra()

    def _montar_conteudo(self, deslizar=None) -> None:
        """
        Monta a tela do item/aba. `deslizar` = ("x" ou "y", +1/-1): a tela
        nova entra deslizando (troca de aba = de lado, troca de item = de
        cima/baixo). Remontar por causa de um ajuste NAO desliza: seria a
        tela pulando a cada clique.
        """
        self._cancelar_deslize()
        self._dica_cancelar()           # (01/out) o quadro de uso nao fica
        self._dica_esconder()
        self._travar_itens()
        self._acertar_abas()
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
        # (07/out, pedido dele: "a troca entre as configuracoes tem que ter a
        # animacao da aba") Remontar a MESMA tela por um ajuste que ele
        # acabou de fazer (clique/tecla ha menos de 0,6 s) revela a tela nova
        # como a troca de aba. Remontagem que o programa faz sozinho, nao.
        efeito = deslizar
        # (08/out, relato dele: "ao trocar as configuracoes personalizadas a
        # interface bugava e redesenhava") remontar por um AJUSTE de valor
        # (`_remontar_quieto`) nao anima: so a navegacao (outro app, voltar)
        quieto = self.__dict__.pop("_sem_efeito", False)
        if deslizar is None and tela == atual and not quieto and \
                self._ele_acabou_de_agir():
            efeito = ("y", -1)
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
        if guardada is not None and deslizar and \
                guardada[2] != self._assinatura(tela):
            # (09/out) so mudou um valor: poe em dia no lugar, sem refazer
            nova = self._em_dia_no_lugar(tela, guardada[1], guardada[2])
            if nova is not None:
                g[tela] = guardada = (guardada[0], guardada[1], nova)
        reusar = guardada is not None and bool(deslizar) and \
            not (tela == "_tela_apps_lista" and self._falta("apps")) and \
            guardada[2] == self._assinatura(tela)
        if guardada is not None and not reusar:
            guardada[0].destroy()           # remontagem de verdade
            del g[tela]
        velhas = [f for f in self._area.winfo_children()
                  if all(f is not v[0] for v in g.values())]
        # (03/out, teste dele) Remontar por um ajuste (a MESMA tela) volta
        # com a rolagem onde estava; antes cada clique levava ao topo.
        rolagens = {}
        if not deslizar and tela == atual:
            for k, v in self._ui.items():
                if isinstance(v, _Rolagem):
                    try:
                        rolagens[k] = v.canvas.yview()[0]
                    except tk.TclError:
                        pass
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
        if efeito and self._visivel and moldura.animacoes_ligadas():
            veu = self._cobrir_area()
            self._veu = veu
        try:
            if reusar:
                if tela == "_tela_apps_lista":
                    # Largura de agora antes de conferir (a grade depende).
                    palco.update_idletasks()
                    self._pintar_lista_apps()  # so o que mudou enquanto fora
                elif tela.startswith("_tela_notif_"):
                    # (01/out) A busca nao fica entre visitas (como as outras
                    # caixas); o resto so muda no lugar.
                    b = self._ui.get("busca_notif")
                    if b is not None and b.get():
                        b.delete(0, "end")
                    self._busca_notif = ""
                    self._pintar_notif()
                    self._horas_notif()
                elif tela == "_tela_celular_status":
                    self._status_pintado = None     # (08/out) pinta tudo
            else:
                getattr(self, tela)(palco)
            if tela == "_tela_notif_ajustes":
                self.programa.notif.reler_bloqueados()
            elif tela == "_tela_notif_lista":
                self.programa.notif.ler_nao_perturbe()     # (02/out)
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
        # (07/out, medido) vale tambem com o veu: sem travar, cada peca se
        # pinta uma a uma embaixo dele e a troca fica ~50% mais lenta.
        self._congelar_area(True)
        try:
            try:
                palco.update_idletasks()
                for k, pos in rolagens.items():
                    rol = self._ui.get(k)
                    if isinstance(rol, _Rolagem) and pos > 0:
                        rol._medir()
                        rol.canvas.yview_moveto(pos)
                palco.lift()
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
            self._congelar_area(False, (palco,))
        self.after(700, self._conferir_textos)
        if veu is not None:
            self._revelar(veu, *efeito)

    def _em_dia_no_lugar(self, tela: str, ui: dict, velha):
        """(09/out, pedido dele: as abas tambem pre-desenhadas) Uma tela
        guardada cujas funcoes vivas cobrem TUDO o que ela le do config
        (`_vivas_completas`) e em que so o config mudou (o 1o item da
        assinatura): as vivas a poem em dia, sem destruir e refazer.
        Devolve a assinatura nova, ou None (refaz como antes)."""
        if not ui.get("_vivas_completas"):
            return None
        nova = self._assinatura(tela)
        if not (isinstance(velha, tuple) and isinstance(nova, tuple)) or \
                len(velha) != len(nova) or velha[1:] != nova[1:]:
            return None
        salvo = self._ui
        self._ui = ui
        try:
            self._atualizar_vivas()
        finally:
            self._ui = salvo
        return nova

    def _remontar_quieto(self) -> None:
        """(08/out) Remonta a tela a vista depois de um ajuste de VALOR (o
        "voltar ao geral" que aparece, etc.): montada por baixo e trocada de
        uma vez, sem a animacao de troca de aba e na mesma rolagem."""
        if getattr(self, "_quieto_id", None):
            try:
                self.after_cancel(self._quieto_id)
            except Exception:
                pass
        self._quieto_id = None
        self._sem_efeito = True
        self._montar_conteudo()

    def _remontar_quieto_depois(self, ms: int = 260) -> None:
        """Igual, depois da troca animada do cartao; cliques seguidos juntam
        numa remontagem so."""
        if getattr(self, "_quieto_id", None):
            try:
                self.after_cancel(self._quieto_id)
            except Exception:
                pass
        self._quieto_id = self.after(ms, self._remontar_quieto)

    def _ele_acabou_de_agir(self) -> bool:
        """O remonte vem de um clique/tecla dele? O botao do mouse (ou
        Enter/espaco) esta apertado AGORA -- os cliques agem no apertar --
        ou ele soltou ha menos de 0,35 s (remonte via after_idle). O
        bind_all sozinho nao serve: quase todo clique da casa devolve
        "break" e ele nunca ouviria."""
        try:
            import ctypes
            u = ctypes.windll.user32
            if any(u.GetAsyncKeyState(v) & 0x8000 for v in (0x01, 0x0D, 0x20)):
                return True
        except Exception:
            pass
        return time.monotonic() - getattr(self, "_ultimo_toque", 0.0) < 0.35

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
        if getattr(self, "_veu", None) is not None or FA.animando() or \
                getattr(self, "_lotes_de", None) or self._ele_esta_usando():
            if tentativa < 100:
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
                nova = self._em_dia_no_lugar(tela, ui, assin)
                if nova is not None:
                    g[tela] = (palco, ui, nova)
                    continue
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
                # (r197b) + a conexao mostrada: sem ela, a tela guardada
                # voltava na conexao antiga depois da troca (teste dele).
                ap = self._config.apps
                return ((repr(self._config.qualidade), ap.get("modo"),
                         ap.get("escala")),
                        getattr(self, "_renomeando", None),
                        self._conexao_da_qualidade())
            if tela == "_tela_opcoes_atalhos":
                m = self.motor
                return (repr(list(atalhos_mod.em_ordem(self._config))),
                        repr(self._gravando),
                        getattr(self, "_atalhos_modo", "lista"),
                        repr(m.falhas()) if m is not None and m.disponivel
                        else None,
                        tuple(a[1] for a in (self._apps or [])),
                        self._icones_versao, self._apps_carregando)
            if tela in TELAS_GUARDADAS_GERAL:
                return self._assinatura_geral(tela)
        except Exception:
            return object()
        return None

    def _assinatura_geral(self, tela: str) -> tuple:
        """(08/out) Tudo o que as telas de TELAS_GUARDADAS_GERAL leem ao
        montar: o config inteiro, o celular (versao do Android = o que falta),
        a conexao, o que esta no ar, os monitores (extensao) e o estado da
        janela que muda o desenho (mapa grande, app sendo editado...). O que
        so muda VALORES (estado, bateria) o `_repintar` ja poe em dia."""
        import json
        c, p = self._config, self.programa
        cel = p.celular or {}
        estado = (
            json.dumps({"s": c.scrcpy, "ip": c.ip_reserva, "pf": c.perfis,
                        "at": c.atalhos, "op": c.opcoes, "ap": c.apps,
                        "q": c.qualidade}, sort_keys=True, default=repr),
            c.instalacao_ok, cel.get("serial"), cel.get("sdk"),
            cel.get("android"), p.conexao_de(), p.conexao_preferida(),
            tuple(sorted(p.sessoes)), tuple(sorted(p.ligando)),
            self._grande, getattr(self, "_windows_ligado", None),
            getattr(self, "_app_configurado", None),
            getattr(self, "_escolhendo_app", None),
            getattr(self, "_grupo_editor", None),
            len(self._apps or ()), self._icones_versao, self._apps_carregando,
            len(self.programa.sinais_dos_apps()),
            len(self.programa.interface_dos_apps()))
        if tela.startswith("_tela_extensao"):
            estado += (repr(self._monitores()),)
        return estado

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

    # (07/out, pedido dele: "padronizar a animacao") As curvas sao as do
    # Android, as mesmas da lista de notificacoes (movimento.py).
    @staticmethod
    def _saida(t: float) -> float:
        """Rapida no comeco, pousando devagar (entradas): LINEAR_OUT_SLOW_IN."""
        return mov.ENTRADA(t)

    @staticmethod
    def _entrada(t: float) -> float:
        """Devagar no comeco, acelerando (saidas): FAST_OUT_LINEAR_IN."""
        return mov.SAIDA(t)

    @staticmethod
    def _meio(t: float) -> float:
        """Devagar nas duas pontas (mudanca de tamanho): FAST_OUT_SLOW_IN."""
        return mov.PADRAO(t)

    def _cancelar_deslize(self) -> None:
        self._parar_animacao("deslize")
        veu = getattr(self, "_veu", None)
        self._veu = None
        if veu is not None:
            mov.parar(veu, "deslize")
            self._descobrir_area(veu)

    # (07/out, relato dele: "a animacao das opcoes das abas ainda ta
    # bugada"; medido quadro a quadro) O veu era um Frame DENTRO da janela:
    # a tela nova ficava escondida atras dele sem pintar, e cada faixa que
    # ele descobria tinha de se pintar na hora -- textos primeiro, chaves,
    # linhas e bordas depois: a tela surgia aos pedacos. Agora o veu e uma
    # janelinha SEPARADA por cima (sem borda, sem foco, sem barra de
    # tarefas): embaixo dela a tela nova se pinta inteira de uma vez (o
    # Windows compoe as janelas) e so o veu encolhe.

    def _cobrir_area(self):
        a = self._area
        caixa = (a.winfo_rootx(), a.winfo_rooty(), a.winfo_width(),
                 a.winfo_height())
        return self._cobrir(a, "_veu_janela", caixa,
                            foto=self._foto_da_tela(*caixa))

    # (07/out, gravado com clique de verdade: no clique a tela de baixo
    # SUMIA de uma vez -- o veu da cor do fundo -- e voltava de cima para
    # baixo: o "apagao" rente a barra parecia uma piscada) Agora o veu
    # mostra uma FOTO da tela de antes: a nova e montada embaixo e a velha
    # dissolve (troca de aba/opcao) ou recua (troca de item). Nunca aparece
    # o fundo vazio.

    def _foto_da_tela(self, x: int, y: int, larg: int, alt: int):
        """O que a janela mostra AGORA no retangulo (coordenadas da tela),
        pronto para o Tk; None se nao der."""
        if not moldura.NO_WINDOWS or larg < 2 or alt < 2:
            return None
        try:
            import ctypes
            from ctypes import wintypes
            from PIL import Image, ImageTk
            u, g = ctypes.windll.user32, ctypes.windll.gdi32
            # (07/out, gravado) copia da TELA, o que ele esta vendo: o
            # PrintWindow desenhava tambem as telas guardadas escondidas
            # atras da atual (a foto saia com OUTRA tela). Fora da area da
            # tela (monitor) nao da para copiar: sem foto.
            esq = u.GetSystemMetrics(76)             # SM_XVIRTUALSCREEN
            topo = u.GetSystemMetrics(77)
            larg_v = u.GetSystemMetrics(78)
            alt_v = u.GetSystemMetrics(79)
            if x < esq or y < topo or x + larg > esq + larg_v or \
                    y + alt > topo + alt_v:
                return None
            L, A = larg, alt
            dc = u.GetDC(0)
            mdc = g.CreateCompatibleDC(dc)
            bmp = g.CreateCompatibleBitmap(dc, L, A)
            g.SelectObject(mdc, bmp)
            g.BitBlt(mdc, 0, 0, L, A, dc, x, y, 0x00CC0020)   # SRCCOPY
            h = 0

            class _BMI(ctypes.Structure):
                _fields_ = [("biSize", wintypes.DWORD),
                            ("biWidth", wintypes.LONG),
                            ("biHeight", wintypes.LONG),
                            ("biPlanes", wintypes.WORD),
                            ("biBitCount", wintypes.WORD),
                            ("biCompression", wintypes.DWORD),
                            ("biSizeImage", wintypes.DWORD),
                            ("x", wintypes.LONG), ("y", wintypes.LONG),
                            ("a", wintypes.DWORD), ("b", wintypes.DWORD)]
            bi = _BMI(ctypes.sizeof(_BMI), L, -A, 1, 32, 0, 0, 0, 0, 0, 0)
            buf = ctypes.create_string_buffer(L * A * 4)
            g.GetDIBits(mdc, bmp, 0, A, buf, ctypes.byref(bi), 0)
            g.DeleteObject(bmp)
            g.DeleteDC(mdc)
            u.ReleaseDC(h, dc)
            img = Image.frombuffer("RGB", (L, A), buf, "raw", "BGRX", 0, 1)
            foto = ImageTk.PhotoImage(img, master=self)
            # os pixels crus: o veu e pintado com eles NA HORA (o Tk so
            # repinta a foto depois da montagem; ate la o veu mostrava a
            # foto da troca ANTERIOR)
            foto._cru = (buf, L, A)
            return foto
        except Exception:
            log.exception("foto da tela")
            return None

    def _cobrir(self, alvo, guarda: str, caixa=None, furos=(), foto=None):
        """Mostra o veu (uma janelinha so por `guarda`, reaproveitada)
        cobrindo `alvo` (ou a `caixa` (x, y, largura, altura) da tela);
        `foto` = o que estava ali (senao, a cor do fundo). None se nao der
        (ai a troca e sem animacao)."""
        try:
            v = getattr(self, guarda, None)
            if v is None or not v.winfo_exists():
                v = tk.Toplevel(self, bg=E.FUNDO, bd=0, highlightthickness=0)
                v.withdraw()
                v.overrideredirect(True)
                v.transient(self)
                v._foto_lbl = tk.Label(v, bd=0, highlightthickness=0,
                                       bg=E.FUNDO, padx=0, pady=0,
                                       anchor="nw")
                setattr(self, guarda, v)
            v._foto = foto
            if foto is not None:
                v._foto_lbl.configure(image=foto)
                v._foto_lbl.place(x=0, y=0, relwidth=1.0, relheight=1.0)
            else:
                v._foto_lbl.place_forget()
            # (07/out, gravado: UM quadro com a tela errada logo apos o
            # clique -- a "piscada" dele) Ao reaparecer, o Windows mostrava
            # por um quadro o ultimo conteudo do veu (a foto da troca
            # anterior). Agora ele aparece INVISIVEL, e pintado com a foto
            # certa e so entao fica visivel.
            try:
                v.attributes("-alpha", 0.0)
            except tk.TclError:
                pass
            # (sem update_idletasks aqui: o do veu, abaixo, ja serve; cada um
            # paga TODA a pintura pendente da janela)
            if caixa is not None:
                x, y, larg, alt = caixa
            else:
                x, y = alvo.winfo_rootx(), alvo.winfo_rooty()
                larg, alt = alvo.winfo_width(), alvo.winfo_height()
            if larg < 2 or alt < 2:
                return None
            v._caixa = (x, y, larg, alt)
            v.geometry("%dx%d+%d+%d" % (larg, alt, x, y))
            # o recorte inteiro (dentro do contorno da janela, com os furos)
            # ANTES de aparecer: o da ultima animacao era um fio
            self._recortar_veu(v, x, y, x + larg, y + alt, furos)
            self._veu_na_hora(v, x, y, larg, alt, foto=foto)
            v.deiconify()
            v.lift(self)
            v.update_idletasks()
            self._veu_na_hora(v, x, y, larg, alt, foto=foto, mover=False)
            try:
                if moldura.NO_WINDOWS:
                    import ctypes
                    ctypes.windll.dwmapi.DwmFlush()  # a pintura chegou a tela
                v.attributes("-alpha", 1.0)
            except Exception:
                pass
            return v
        except tk.TclError:
            return None

    def _descobrir_area(self, veu) -> None:
        try:
            veu.withdraw()
        except tk.TclError:
            pass

    # (07/out, relato dele: "a animacao ta comendo a barra em cima") O veu e
    # outra janela: por cima, ele cobria a BORDA de 1 px que o Windows desenha
    # em volta da janela (e o canto redondo). Agora o veu fica PARADO no
    # tamanho da faixa e o que anda e o RECORTE dele (SetWindowRgn): so a
    # parte ainda coberta, sempre dentro do contorno da janela (1 px de borda
    # e o canto redondo) e com FUROS onde ficam os botoes da barra -- eles
    # continuam a vista, "por cima" do veu.

    def _veu_na_hora(self, veu, x: int, y: int, larg: int, alt: int,
                     foto=None, mover: bool = True) -> None:
        """(07/out, medido) O Tk aplica o tamanho de uma janelinha alguns
        quadros depois e so pinta a parte nova na folga: o veu nascia do
        tamanho velho e com um pedaco preto. Aqui o Windows poe no lugar e o
        fundo e pintado JA."""
        if not moldura.NO_WINDOWS:
            return
        try:
            import ctypes
            from ctypes import wintypes
            u, g = ctypes.windll.user32, ctypes.windll.gdi32
            hv = u.GetParent(veu.winfo_id()) or veu.winfo_id()
            # SWP_NOZORDER | SWP_NOACTIVATE
            if mover:
                u.SetWindowPos(hv, 0, int(x), int(y), int(larg), int(alt),
                               0x0004 | 0x0010)
            cru = getattr(foto, "_cru", None) if foto is not None else None
            if cru is not None:
                buf, L, A = cru

                class _BMI(ctypes.Structure):
                    _fields_ = [("biSize", wintypes.DWORD),
                                ("biWidth", wintypes.LONG),
                                ("biHeight", wintypes.LONG),
                                ("biPlanes", wintypes.WORD),
                                ("biBitCount", wintypes.WORD),
                                ("biCompression", wintypes.DWORD),
                                ("biSizeImage", wintypes.DWORD),
                                ("x", wintypes.LONG), ("y", wintypes.LONG),
                                ("a", wintypes.DWORD), ("b", wintypes.DWORD)]
                bi = _BMI(ctypes.sizeof(_BMI), L, -A, 1, 32, 0, 0, 0, 0, 0,
                          0)
                # na janelinha DA FOTO (ela cobre o veu todo; pintar o veu
                # de fora era cortado por ela)
                alvo = veu._foto_lbl.winfo_id()
                dc = u.GetDC(alvo)
                g.SetDIBitsToDevice(dc, 0, 0, L, A, 0, 0, 0, A, buf,
                                    ctypes.byref(bi), 0)
                u.ReleaseDC(alvo, dc)
                return
            if foto is not None:
                return
            cor = E.FUNDO.lstrip("#")
            ref = int(cor[4:6], 16) << 16 | int(cor[2:4], 16) << 8 | \
                int(cor[0:2], 16)
            pincel = g.CreateSolidBrush(ref)
            dc = u.GetDC(hv)
            r = wintypes.RECT(0, 0, int(larg), int(alt))
            u.FillRect(dc, ctypes.byref(r), pincel)
            u.ReleaseDC(hv, dc)
            g.DeleteObject(pincel)
        except Exception:
            log.exception("veu na hora")

    def _recortar_veu(self, veu, x0: float, y0: float, x1: float, y1: float,
                      furos=(), circulo=None) -> None:
        """Mostra do veu so o retangulo (x0, y0)-(x1, y1) (coordenadas da
        tela), menos os `furos` [(x, y, larg, alt)] e o `circulo` (cx, cy,
        raio) -- a tela nova nascendo de um botao --, dentro da janela."""
        if not moldura.NO_WINDOWS:
            return
        try:
            import ctypes
            from ctypes import wintypes
            u, g = ctypes.windll.user32, ctypes.windll.gdi32
            hv = u.GetParent(veu.winfo_id()) or veu.winfo_id()
            vx, vy = veu._caixa[0], veu._caixa[1]
            r = g.CreateRectRgn(int(round(x0 - vx)), int(round(y0 - vy)),
                                int(round(x1 - vx)), int(round(y1 - vy)))
            jw = wintypes.RECT()
            u.GetWindowRect(int(self.wm_frame(), 16), ctypes.byref(jw))
            d = 2 * E.px(8)              # o canto redondo do Windows 11
            # (07/out, gravado) 1 px de borda dos QUATRO lados: a direita e
            # embaixo contavam 1 a mais e o veu cobria a borda
            forma = g.CreateRoundRectRgn(jw.left + 1 - vx, jw.top + 1 - vy,
                                         jw.right - 1 - vx, jw.bottom - 1 - vy,
                                         d, d)
            g.CombineRgn(r, r, forma, 1)             # RGN_AND
            g.DeleteObject(forma)
            for fx, fy, fl, fa in furos:
                f = g.CreateRectRgn(fx - vx, fy - vy, fx - vx + fl,
                                    fy - vy + fa)
                g.CombineRgn(r, r, f, 4)             # RGN_DIFF
                g.DeleteObject(f)
            if circulo is not None and circulo[2] > 0.5:
                cx, cy, rr = circulo
                f = g.CreateEllipticRgn(int(cx - rr - vx), int(cy - rr - vy),
                                        int(cx + rr - vx), int(cy + rr - vy))
                g.CombineRgn(r, r, f, 4)             # RGN_DIFF
                g.DeleteObject(f)
            u.SetWindowRgn(hv, r, True)              # o Windows fica com r
        except Exception:
            log.exception("recorte do veu")

    def _raio_ate_o_fim(self, origem) -> float:
        """Raio que, saindo de `origem`, cobre a janela inteira (os dois
        veus -- abas e tela -- terminam juntos)."""
        x0, y0 = self.winfo_rootx(), self.winfo_rooty()
        x1, y1 = x0 + self.winfo_width(), y0 + self.winfo_height()
        ox, oy = origem
        return max(((cx - ox) ** 2 + (cy - oy) ** 2) ** 0.5
                   for cx in (x0, x1) for cy in (y0, y1)) + 2

    def _revelar_abas(self, origem=None) -> None:
        """(07/out, pedido dele) Trocou de item: as abas de cima entram com a
        MESMA animacao da tela (o veu recua da esquerda), so na faixa das
        abas -- o nome do programa e os botoes da direita ficam parados.
        `origem` = (x, y) do botao da barra: aí elas nascem dele."""
        if not self._visivel or not moldura.animacoes_ligadas():
            return
        # (07/out) janelinha por cima, como o veu da area (ver `_cobrir`):
        # o Frame deixava restos das abas velhas ate a faixa se repintar
        velho = getattr(self, "_veu_abas", None)
        if velho is not None:
            mov.parar(velho, "deslize")
        # (07/out, relato dele: "da um tranco no meio") O veu era medido nas
        # abas VELHAS (antes de remontar): indo de 1 aba para 3, ele cobria
        # so a largura de 1 e as outras surgiam de uma vez no meio do
        # deslize. Agora cobre a faixa INTEIRA: do comeco das abas ate o fim
        # da barra (pedido dele), com furos nos botoes da direita.
        f = self._abas_frame
        try:
            x = f.winfo_rootx()
            fim_x = self.winfo_rootx() + self.winfo_width()
            caixa = (x, f.winfo_rooty(), max(f.winfo_width(), fim_x - x),
                     f.winfo_height())
            furos = [(b.winfo_rootx(), b.winfo_rooty(), b.winfo_width(),
                      b.winfo_height()) for b in
                     (getattr(self, "_botoes_barra", None) or {}).values()
                     if b.winfo_ismapped()]
        except tk.TclError:
            caixa, furos = None, []
        # (07/out) com a FOTO das abas velhas: elas recuam e as novas
        # aparecem (sem a faixa vazia no meio)
        foto = self._foto_da_tela(*caixa) if caixa else None
        veu = self._cobrir(f, "_veu_abas_janela", caixa, furos, foto=foto)
        if veu is None:
            return
        self._veu_abas = veu
        x0, y0, larg, alt = veu._caixa
        raio = self._raio_ate_o_fim(origem) if origem else 0

        def a_cada(p):
            if origem:
                self._recortar_veu(veu, x0, y0, x0 + larg, y0 + alt, furos,
                                   circulo=(origem[0], origem[1], raio * p))
                return
            self._recortar_veu(veu, x0 + larg * p, y0, x0 + larg, y0 + alt,
                               furos)

        def fim():
            if getattr(self, "_veu_abas", None) is veu:
                self._veu_abas = None
            self._descobrir_area(veu)
        # o relogio comeca no 1o quadro livre: montar a tela nova segura o
        # Tk e, contando dali, o veu ja nascia no fim
        if origem:                       # no mesmo ritmo do da tela
            mov.animar(veu, "deslize", MS_DESLIZE + 60, a_cada, fim,
                       curva=mov.PADRAO)
        else:
            mov.animar(veu, "deslize", MS_DESLIZE, a_cada, fim,
                       curva=mov.ENTRADA)

    def _revelar(self, veu: tk.Frame, eixo: str, sinal: int) -> None:
        """
        O veu recua da borda ate sumir, pousando devagar: sinal -1 = a tela
        aparece a partir da esquerda (eixo x) ou de cima (eixo y); +1 = da
        direita / de baixo. A tela embaixo nao se mexe.
        """
        x0, y0, larg, alt = veu._caixa

        dissolver = eixo == "y" and getattr(veu, "_foto", None) is not None
        if eixo == "botao":
            # (07/out, pedido dele) a tela nova NASCE DO BOTAO da barra: um
            # circulo cresce dali, abrindo a tela por cima da velha
            origem = sinal
            raio = self._raio_ate_o_fim(origem)

            def no_botao(p):
                self._recortar_veu(veu, x0, y0, x0 + larg, y0 + alt,
                                   circulo=(origem[0], origem[1], raio * p))

            def fim_botao():
                if getattr(self, "_veu", None) is veu:
                    self._veu = None
                self._descobrir_area(veu)
            mov.animar(veu, "deslize", MS_DESLIZE + 60, no_botao, fim_botao,
                       curva=mov.PADRAO)
            return

        def a_cada(p):
            if dissolver:
                # (07/out) troca de aba/opcao: a foto da tela velha DISSOLVE
                # na nova (nada de fundo vazio no meio)
                try:
                    veu.attributes("-alpha", max(0.0, 1.0 - p))
                except tk.TclError:
                    pass
                return
            # o veu fica parado; o recorte anda (ver `_recortar_veu`)
            if eixo == "x":
                a, b = (x0 + larg * p, x0 + larg) if sinal < 0 else \
                    (x0, x0 + larg * (1.0 - p))
                self._recortar_veu(veu, a, y0, b, y0 + alt)
            else:
                a, b = (y0 + alt * p, y0 + alt) if sinal < 0 else \
                    (y0, y0 + alt * (1.0 - p))
                self._recortar_veu(veu, x0, a, x0 + larg, b)

        def fim():
            if getattr(self, "_veu", None) is veu:
                self._veu = None
            self._descobrir_area(veu)

        # (07/out, relato dele: "a animacao das configuracoes esta bugada")
        # Medido quadro a quadro: o relogio contava da chamada, e o Tk
        # passava ~150 ms pintando a tela nova -- o veu ja nascia quase no
        # fim e as pecas (chaves, textos) surgiam aos pedacos. Agora o veu
        # cobre tudo ate o 1o quadro livre (a tela ja pintada embaixo) e so
        # entao anda.
        mov.animar(veu, "deslize", MS_DESLIZE, a_cada, fim, curva=mov.ENTRADA)

    def _duas(self, pai) -> tuple[tk.Frame, tk.Frame]:
        # (08/out, padrao da qualidade) sem a linha no meio: as colunas sao
        # separadas pelos paineis e pelo vao entre eles
        caixa = tk.Frame(pai, bg=E.FUNDO)
        caixa.pack(fill="both", expand=True)
        esq = tk.Frame(caixa, bg=E.FUNDO)
        esq.place(relx=0, rely=0, relwidth=0.5, relheight=1.0)
        dir_ = tk.Frame(caixa, bg=E.FUNDO)
        dir_.place(relx=0.5, rely=0, relwidth=0.5, relheight=1.0)
        meio = E.px(4)
        a = tk.Frame(esq, bg=E.FUNDO)
        a.pack(fill="both", expand=True, padx=(E.PADDING, meio),
               pady=E.PADDING)
        b = tk.Frame(dir_, bg=E.FUNDO)
        b.pack(fill="both", expand=True, padx=(meio, E.PADDING),
               pady=E.PADDING)
        return a, b

    def _seg(self, pai, titulo: str = "", info: str = "",
             expand: bool = False) -> tk.Frame:
        """(08/out, pedido dele: o padrao da qualidade no app todo) Um
        SEGMENTO: o painel sutil (E.painel) com o titulo em cima (semibold)
        e o i opcional. Devolve o CORPO, onde vai o conteudo; o `_topo`
        dele (a linha do titulo) aceita coisas a direita. O 1o da coluna
        nao tem vao em cima."""
        primeiro = not any(c.winfo_manager() for c in pai.winfo_children())
        p = E.painel(pai, side="top", fill="both" if expand else "x",
                     expand=expand,
                     pady=(0 if primeiro else E.px(8), 0))
        corpo = tk.Frame(p, bg=E.FUNDO)
        corpo.pack(fill="both", expand=True, padx=E.px(12),
                   pady=(E.px(7), E.px(9)))
        corpo._painel = p
        if titulo:
            topo = tk.Frame(corpo, bg=E.FUNDO)
            topo.pack(side="top", fill="x", pady=(0, E.px(5)))
            tk.Label(topo, text=titulo, bg=E.FUNDO, fg=E.TEXTO,
                     font=E.fonte(E.CORPO, "bold"), anchor="w").pack(
                side="left")
            if info:
                self._so_info(topo, info).pack(side="left",
                                               padx=(E.px(4), 0))
            corpo._topo = topo
        return corpo

    def _uma(self, pai) -> tk.Frame:
        f = tk.Frame(pai, bg=E.FUNDO)
        f.pack(fill="both", expand=True, padx=E.PADDING, pady=E.PADDING)
        return f

    # -- pecas reaproveitadas --------------------------------------------------

    def _estado(self, pai, chave: str) -> None:
        """O bloco "texto grande. / explicacao" dos modos. (08/out) sem o
        rotulo "estado": o painel ja separa e o "parado." se explica."""
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
            tk.Label(c, text=rotulo, bg=E.FUNDO, fg=E.APAGADO,
                     font=E.fonte(E.ROTULO - 1), anchor="w").pack(
                side="top", fill="x", padx=E.px(6), pady=(E.px(0), E.px(5)))
            self._ui["medidas"].append(v)

    def _caixa(self, pai, texto: str = "", ao_mudar=None,
               ipady: int = 4, fundo: str | None = None,
               borda: str | None = None) -> tk.Entry:
        """
        CAIXA DE TEXTO DA CASA (pedido dele, 23/set/2026): com um x no fim que
        apaga tudo. Quem chama empacota `campo.master` (a moldura).
        (03/out) `fundo`/`borda`: a que FLUTUA (busca dos apps) usa a
        superficie clara, como os menus.
        """
        fundo = fundo or E.FUNDO_FUNDO
        borda = borda or E.LINHA_FORTE
        moldura = tk.Frame(pai, bg=fundo, highlightthickness=1,
                           highlightbackground=borda)
        campo = tk.Entry(moldura, font=E.fonte(E.CORPO), bg=fundo,
                         fg=E.TEXTO, insertbackground=E.TEXTO, relief="flat",
                         highlightthickness=0, bd=0)
        campo.pack(side="left", fill="x", expand=True, ipady=E.px(ipady),
                   padx=(E.px(6), E.px(0)))
        def limpar(_e=None):
            campo.delete(0, "end")
            if ao_mudar is not None:
                ao_mudar()
            return "break"

        # (07/out) o x e o icone da casa e, como na barra de busca, so
        # aparece com texto na caixa
        x = self._x_de_tirar(moldura, fundo, limpar)
        x.configure(takefocus=0)

        def acertar_x(*_a):
            try:
                if campo.get() and not x.winfo_manager():
                    x.pack(side="right", padx=(E.px(2), E.px(5)),
                           before=campo)
                elif not campo.get() and x.winfo_manager():
                    x.pack_forget()
            except tk.TclError:
                pass
        # qualquer mudanca (digitar, colar, o programa preencher) acerta o x
        var = tk.StringVar(master=campo)
        campo.configure(textvariable=var)
        var.trace_add("write", acertar_x)
        campo._var = var
        campo.bind("<FocusIn>", lambda _e: (moldura.configure(
            highlightbackground=E.FOCO), E.cantos(moldura)), add="+")
        campo.bind("<FocusOut>", lambda _e: (moldura.configure(
            highlightbackground=borda), E.cantos(moldura)), add="+")
        E.cantos(moldura)                # (03/out) canto arredondado
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
        tk.Label(textos, text=titulo, bg=E.FUNDO, fg=E.TEXTO,
                 font=E.fonte(E.PEQUENA), anchor="w").pack(side="top", fill="x")
        if explicacao:
            tk.Label(textos, text=explicacao, bg=E.FUNDO, fg=E.APAGADO,
                     font=E.fonte(E.ROTULO), anchor="w", justify="left",
                     wraplength=E.px(170)).pack(side="top", fill="x")
        c = E.Chave(linha, ligado, ao_virar, travada=travada)
        c.pack(side="right")
        # (08/out) os textos quebram na largura que SOBRA ao lado da chave
        # (fixo em 190 px, a chave passava da borda numa coluna estreita)
        def quebrar(e, textos=textos, c=c):
            larg = max(E.px(80), e.width - c.winfo_reqwidth() - E.px(12))
            for w in textos.winfo_children():
                try:
                    if int(float(w.cget("wraplength"))) != larg:
                        w.configure(wraplength=larg)
                except tk.TclError:
                    pass
        linha.bind("<Configure>", quebrar, add="+")
        if borda:
            tk.Frame(pai, bg=E.LINHA, height=1).pack(side="top", fill="x")
        return c

    def _fila(self, pai, nome: str, opcoes, valor, ao_escolher,
              espaco: int = 6, nome_larg: int = 11) -> E.Segmentado:
        # (08/out, padrao da qualidade) o nome EM CIMA e os chips na largura
        # toda (ao lado, os chips de 4 opcoes ficavam espremidos); a largura
        # do nome (nome_larg) nao conta mais
        linha = tk.Frame(pai, bg=E.FUNDO)
        linha.pack(side="top", fill="x", pady=(E.px(0), E.px(max(espaco, 6))))
        tk.Label(linha, text=nome, bg=E.FUNDO, fg=E.TEXTO_2,
                 font=E.fonte(E.PEQUENA), anchor="w").pack(
            side="top", fill="x", pady=(0, E.px(3)))
        s = E.Segmentado(linha, opcoes, valor, ao_escolher)
        s.pack(side="top", fill="x")
        return s

    # ==========================================================================
    # ESPELHAR
    # ==========================================================================

    def _perfil_jogo(self) -> dict:
        return self._config.perfil("jogo")

    def _tela_jogo_basico(self, area) -> None:
        esq, dir_ = self._duas(area)
        col_esq = esq
        perfil = self._perfil_jogo()
        conteudo = conteudo_do(perfil)

        # (08/out, padrao da qualidade) cada bloco num segmento
        s_est = self._seg(esq)
        self._estado(s_est, "jogo")
        acao = E.Botao(s_est, "ligar", lambda: self._botao_principal("jogo"),
                       tipo="acao")
        acao.pack(side="top", fill="x", pady=(E.px(12), E.px(0)))
        self._ui["acao"] = acao
        # (08/out, pedido dele) a esquerda: estado e JANELA; a direita: o
        # que vem do celular (com a imagem) e, embaixo, onde o som toca
        col_dir = dir_
        s_jan = self._seg(esq, "janela")
        s_cont = self._seg(col_dir, "o que vem do celular")
        if self._falta("som") and conteudo != "imagem":
            perfil["conteudo"] = conteudo = "imagem"
            self._gravou("jogo", "conteudo = imagem (Android sem som no pc)")
        seg = E.Segmentado(s_cont, CONTEUDOS, conteudo,
                           self._escolheu_conteudo)
        seg.pack(side="top", fill="x")
        if self._falta("som"):
            seg.habilitar(False)
            E.Texto(s_cont, "som no pc precisa do android %s ou mais novo."
                    % self._falta("som"), cor=E.APAGADO, tamanho=E.ROTULO,
                    largura=E.px(220)).pack(side="top", fill="x",
                                            pady=(E.px(4), E.px(0)))

        dir_ = s_som = self._seg(col_dir, "onde o som toca")
        opcoes = [o for o in qualidade.ONDE if o[0] != "celular"]
        if self._falta("pc_cel"):
            opcoes = [o for o in opcoes if o[0] != "ambos"]
        onde = qualidade.onde_do_perfil(dict(perfil, audio=dict(
            perfil.get("audio") or {}, ligado=True)))
        s_onde = E.Segmentado(dir_, opcoes, onde, self._escolheu_onde_jogo)
        s_onde.pack(side="top", fill="x")
        if conteudo == "imagem" or self._falta("som"):
            s_onde.habilitar(False)
        sessao = perfil.get("sessao") or {}
        dir_ = s_jan
        ch_cima = self._chave(
            dir_, "por cima das outras janelas",
            bool((perfil.get("janela") or {}).get("sempre_no_topo"))
            and conteudo != "som",
            lambda v: self.programa.fixar_espelhamento(v, avisar=False),
            travada=(conteudo == "som"))
        explica_apagar = ("não vale no só som: você está jogando nele",
                          "o celular fica de tela preta enquanto espelha")
        ch_apagar = self._chave(
            dir_, "apagar a tela do celular",
            bool(sessao.get("apagar_tela")) and conteudo != "som",
            lambda v: self._virar_campo("jogo", "sessao", "apagar_tela", v),
            explicacao=explica_apagar[0 if conteudo == "som" else 1],
            travada=(conteudo == "som"), borda=False)
        # As medidas (resolucao/quadros/mb/s) sairam: a fileira de
        # qualidade diz o mesmo e nao cabia tudo (23/set/2026).
        # (08/out, relato dele: os botoes da imagem cortados embaixo) a
        # qualidade DENTRO dos paineis do assunto: a da imagem no "o que vem
        # do celular", a do som no "onde o som toca" (um painel a menos)
        img = self._chips_do_modo(s_cont, "jogo", "nivel")
        if conteudo == "som":
            img.habilitar(False)
        chips = self._chips_som_do_modo(s_som, "jogo")
        if conteudo == "imagem" or self._falta("som"):
            chips.habilitar(False)

        def viva():
            # (08/out) trocar o "o que vem do celular" acende/apaga NO LUGAR
            p = self._perfil_jogo()
            c = conteudo_do(p)
            seg.definir(c)
            s_onde.definir(qualidade.onde_do_perfil(dict(p, audio=dict(
                p.get("audio") or {}, ligado=True))))
            sem_som = c == "imagem" or bool(self._falta("som"))
            s_onde.habilitar(not sem_som)
            chips.habilitar(not sem_som)
            img.habilitar(c != "som")
            so_som = c == "som"
            ch_cima.travar(so_som)
            ch_cima.definir(bool((p.get("janela") or {}).get(
                "sempre_no_topo")) and not so_som)
            ch_apagar.travar(so_som)
            ch_apagar.definir(bool((p.get("sessao") or {}).get(
                "apagar_tela")) and not so_som)
            textos = ch_apagar.master.winfo_children()[0].winfo_children()
            if len(textos) > 1:
                textos[1].configure(text=explica_apagar[0 if so_som else 1])
        self._viva(viva)
        self._ui["_vivas_completas"] = True

    def _fileira_predef(self, pai, nome: str, som: bool = True,
                        imagem: bool = True) -> None:
        """
        (08/out, rework) A QUALIDADE DESTE MODO: os mesmos cartoes de OPCOES
        > qualidade, compactos -- imagem (540/720/1080) e som (normal/alto).
        Marcado = o que vale (o do modo, senao o geral); escolher o mesmo do
        geral nao guarda (segue o geral).
        """
        perfil = self._config.perfil(nome)
        q = self._config.qualidade
        proprio = bool(qualidade.nivel_valido(perfil.get("nivel")) or
                       qualidade.som_valido(perfil.get("som")))
        # (08/out) um segmento proprio; o link/aviso na linha do titulo
        pai = self._seg(pai, "qualidade" if (som and imagem) else
                        "qualidade da imagem" if imagem else
                        "qualidade do som")
        topo = pai._topo
        marca = self._marca_geral(
            topo, proprio, "voltar ao geral",
            lambda: self._qualidade_do_modo(nome, None, None),
            "a geral (opções)")
        marca.pack(side="right")
        # (08/out) em CHIPS (a coluna do modo e estreita e baixa): a imagem
        # pela resolucao e o som com a medida
        s_img = s_som = None
        if imagem:
            s_img = E.Segmentado(
                pai, [(c, "%dp" % p) for c, _r, p in qualidade.NIVEIS],
                qualidade.nivel_de(perfil, q),
                lambda v: self._qualidade_do_modo(nome, "nivel", v))
            s_img.pack(side="top", fill="x")
        if som:
            s_som = E.Segmentado(
                pai, [(c, "%s · %s kb/s" % (n, t.rstrip("K")))
                      for c, n, t in qualidade.SONS],
                qualidade.som_de(perfil, q),
                lambda v: self._qualidade_do_modo(nome, "som", v))
            s_som.pack(side="top", fill="x",
                       pady=(E.px(6) if imagem else 0, 0))

        def viva():
            p, qq = self._config.perfil(nome), self._config.qualidade
            marca.mostrar(bool(qualidade.nivel_valido(p.get("nivel")) or
                               qualidade.som_valido(p.get("som"))))
            if s_img is not None:
                s_img.definir(qualidade.nivel_de(p, qq))
            if s_som is not None:
                s_som.definir(qualidade.som_de(p, qq))
        self._viva(viva)

    # (08/out, pedido dele: "a interface pre-desenhada, que escuta a funcao")
    # Um ajuste de VALOR nao remonta mais a tela: o controle ja mudou no
    # clique (E.ouvir desfaz se a funcao falhar) e o que depende dele (o
    # "voltar ao geral", a legenda, outros chips) muda NO LUGAR, pelas
    # funcoes "vivas" que cada tela registra.
    def _viva(self, fn) -> None:
        self._ui.setdefault("_vivas", []).append(fn)

    def _atualizar_vivas(self) -> bool:
        """Poe a tela a vista em dia sem remontar. False = ela nao tem
        funcoes vivas (quem chamou remonta, como antes)."""
        vivas = self._ui.get("_vivas")
        if not vivas:
            return False
        for fn in vivas:
            try:
                fn()
            except tk.TclError:
                pass
            except Exception:
                log.exception("falha pondo a tela em dia no lugar")
        return True

    def _marca_geral(self, pai, proprio: bool, voltar: str, ao_voltar,
                     geral: str, **pack_link) -> tk.Frame:
        """O "voltar ao geral" (link) ou o "a geral" (apagado), os dois ja
        desenhados; `mostrar(proprio)` troca no lugar."""
        bg = pai.cget("bg")
        f = tk.Frame(pai, bg=bg)
        lk = self._link(f, voltar, ao_voltar)
        lk.configure(font=E.fonte(E.ROTULO), bg=bg, highlightbackground=bg)
        rot = tk.Label(f, text=geral, bg=bg, fg=E.APAGADO,
                       font=E.fonte(E.ROTULO)) if geral else None
        pack_link = pack_link or {"side": "right"}

        def mostrar(sim: bool) -> None:
            if sim == getattr(f, "_sim", None):
                return
            f._sim = sim
            if sim:
                if rot is not None:
                    rot.pack_forget()
                lk.pack(**pack_link)
            else:
                lk.pack_forget()
                if rot is not None:
                    rot.pack(**pack_link)
        f.mostrar = mostrar
        mostrar(bool(proprio))
        return f

    def _sub(self, pai, texto: str, primeiro: bool = False) -> tk.Frame:
        """(08/out, pedido dele: juntar funcoes por segmento) Um SUBTITULO
        dentro de um painel (o nome de uma parte dele), como o "qualidade
        da imagem" do espelhar. Devolve a linha (aceita coisas a direita)."""
        linha = tk.Frame(pai, bg=E.FUNDO)
        linha.pack(side="top", fill="x",
                   pady=(0 if primeiro else E.px(10), E.px(3)))
        tk.Label(linha, text=texto, bg=E.FUNDO, fg=E.TEXTO_2,
                 font=E.fonte(E.PEQUENA), anchor="w").pack(side="left")
        return linha

    def _chips_som_do_modo(self, pai, nome: str) -> E.Segmentado:
        """(08/out) A qualidade do SOM do modo, num painel que ja existe (o
        do som): o nome em cima e os chips; igual a geral nao guarda."""
        return self._chips_do_modo(pai, nome, "som")

    def _chips_do_modo(self, pai, nome: str, campo: str) -> E.Segmentado:
        """(08/out) A qualidade (campo "nivel" = imagem, "som") de um modo
        DENTRO de um painel que ja existe: o nome a esquerda, "a geral" ou
        "voltar ao geral" a direita, e os chips embaixo."""
        perfil = self._config.perfil(nome)
        q = self._config.qualidade
        imagem = campo == "nivel"
        linha = tk.Frame(pai, bg=E.FUNDO)
        linha.pack(side="top", fill="x", pady=(E.px(8), E.px(3)))
        tk.Label(linha, text="qualidade da imagem" if imagem else
                 "qualidade do som", bg=E.FUNDO, fg=E.TEXTO_2,
                 font=E.fonte(E.PEQUENA), anchor="w").pack(side="left")
        valido = qualidade.nivel_valido if imagem else qualidade.som_valido
        de = qualidade.nivel_de if imagem else qualidade.som_de
        marca = self._marca_geral(
            linha, valido(perfil.get(campo)), "voltar ao geral",
            lambda: self._qualidade_do_modo(nome, campo, None), "a geral")
        marca.pack(side="right")
        if imagem:
            opcoes = [(c, "%dp" % p) for c, _r, p in qualidade.NIVEIS]
            valor = qualidade.nivel_de(perfil, q)
        else:
            opcoes = [(c, "%s · %s kb/s" % (n, t.rstrip("K")))
                      for c, n, t in qualidade.SONS]
            valor = qualidade.som_de(perfil, q)
        s = E.Segmentado(pai, opcoes, valor,
                         lambda v: self._qualidade_do_modo(nome, campo, v))
        s.pack(side="top", fill="x")

        def viva():
            p = self._config.perfil(nome)
            marca.mostrar(bool(valido(p.get(campo))))
            s.definir(de(p, self._config.qualidade))
        self._viva(viva)
        return s

    def _qualidade_do_modo(self, nome: str, campo, valor) -> None:
        """campo None = volta ao geral (tira nivel e som do modo)."""
        perfil = self._config.perfil(nome)
        q = self._config.qualidade
        if campo is None:
            perfil.pop("nivel", None)
            perfil.pop("som", None)
        else:
            geral = qualidade.nivel_geral(q) if campo == "nivel" else \
                qualidade.som_geral(q)
            if valor is None or valor == geral:   # None = voltar ao geral
                perfil.pop(campo, None)
            else:
                perfil[campo] = valor
        self._gravou(nome, "%s = %s" % (campo or "qualidade",
                                        valor or "geral"))
        # (08/out) o "voltar ao geral" aparece/some NO LUGAR
        if not self._atualizar_vivas():
            self._remontar_quieto_depois()

    def _con_da_fileira(self, nome: str) -> str:
        # (03/out, pedido dele) A conexao so se escolhe em PAREAR: a
        # qualidade mostrada e editada e sempre a da conexao EM USO (a que a
        # proxima partida usa), e muda junto quando ela muda.
        return self.programa.conexao_de()

    def _marca_conexao(self, pai) -> tk.Frame:
        """(03/out) No lugar do antigo seletor sem fio|cabo: "sem fio ·
        trocar em parear" (o link leva ao PAREAR)."""
        con = self.programa.conexao_de()
        f = tk.Frame(pai, bg=E.FUNDO)
        tk.Label(f, text={"cabo": "cabo", "sem_fio": "sem fio"}.get(con, con),
                 bg=E.FUNDO, fg=E.TEXTO_2, font=E.fonte(E.ROTULO)).pack(
            side="left")
        tk.Label(f, text="  ·  ", bg=E.FUNDO, fg=E.APAGADO,
                 font=E.fonte(E.ROTULO)).pack(side="left")
        lk = self._link(f, "trocar em parear",
                        lambda: self._escolher_item("parear"))
        lk.configure(font=E.fonte(E.ROTULO))
        lk.pack(side="left")
        return f

    def _seguir_a_conexao(self) -> None:
        """(r197) PEDIDO DELE (30/set/2026): "ao trocar o modo de conexao a
        predefinicao de qualidade tem que seguir". Mudou a conexao em uso
        (ou a preferida, sem celular): as fileiras sem fio|cabo das telas de
        qualidade voltam para ela, e a tela a vista remonta."""
        con = self.programa.conexao_de()
        if con == getattr(self, "_con_seguida", None):
            return
        primeira = getattr(self, "_con_seguida", None) is None
        self._con_seguida = con
        if primeira:
            return
        # (r198) A tela de qualidade GUARDADA (escondida para voltar rapido)
        # ainda mostra a conexao antiga: descartada, a proxima visita monta
        # de novo. Nao depende so da `_assinatura` (r197b, nao confirmado).
        guardada = self._guardadas.pop("_tela_opcoes_qualidade", None)
        if guardada is not None:
            try:
                guardada[0].destroy()
            except tk.TclError:
                pass
            self._pre_geracao = getattr(self, "_pre_geracao", 0) + 1
            geracao = self._pre_geracao
            self.after(300, lambda: self._pre_montar(geracao))
        self.programa.anotar("qualidade: seguiu a conexao -> %s%s" % (
            con, " (tela guardada descartada)" if guardada else ""))
        aba = self._aba.get(self._item)
        if self._grande:        # o mapa grande da extensao aberto: fica
            return
        if (self._item in ("jogo", "extensao") or
                (self._item, aba) in (("opcoes", "qualidade"),
                                      ("apps", "personalizados"))):
            self.after_idle(self._montar_conteudo)

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
        if not self._atualizar_vivas():
            self._remontar_quieto_depois()

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
        col_esq, col_dir = self._duas(area)
        esq = self._seg(col_esq)
        self._estado(esq, "extensao")
        lista = self._monitores()
        b = self._borda_resolvida(lista)
        valores = self._valores_da_borda(lista, b)
        self._medidas(esq, list(zip(valores, ("monitor", "lado", "altura"))))
        acao = E.Botao(esq, "ligar", lambda: self._botao_principal("extensao"),
                       tipo="acao")
        acao.pack(side="top", fill="x", pady=(E.px(12), E.px(0)))
        self._ui["acao"] = acao

        dir_ = self._seg(col_dir, "onde o celular fica")
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
        E.cantos(mapa)                   # (03/out) canto arredondado
        mapa.bind("<Configure>", lambda _e: self._desenhar_mapa_pequeno())
        E.Texto(dir_, "clique numa das quatro vagas. posição exata e "
                      "tamanho: aba posição e marca.", cor=E.APAGADO,
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
            t.withdraw()
            t.overrideredirect(True)
            # (07/out, padrao) janelinha por cima de tudo = SUPERFICIE, borda
            # e curva do Windows 11 (era a moldura quadrada laranja do Tk
            # dentro do canto redondo); aparece e some esmaecendo
            moldura.arredondar_ao_mostrar(t, borda=E.SUPERFICIE_BORDA)
            try:
                t.attributes("-topmost", True)
            except tk.TclError:
                pass
            t.configure(bg=E.SUPERFICIE)
            tk.Label(t, text=str(k + 1), bg=E.SUPERFICIE, fg=E.ACENTO,
                     font=E.fonte(90, "bold")).pack(padx=E.px(40), pady=(E.px(4), E.px(0)))
            tk.Label(t, text="TELA %d" % (k + 1), bg=E.SUPERFICIE,
                     fg=E.TEXTO_2,
                     font=E.fonte(E.CORPO)).pack(pady=(E.px(0), E.px(14)))
            t.update_idletasks()
            l, a = t.winfo_reqwidth(), t.winfo_reqheight()
            t.geometry("+%d+%d" % (m["x"] + (m["l"] - l) // 2,
                                   m["y"] + (m["a"] - a) // 2))
            if mov.ligadas():
                t.attributes("-alpha", 0.0)
            t.deiconify()
            mov.entrar(t)
            t.after(2000, lambda t=t: mov.sair(t, t.destroy))

    def _tela_extensao_avancado(self, area) -> None:
        col_esq, col_dir = self._duas(area)
        perfil = self._perfil_ext()
        esq = self._seg(col_esq, "onde o som toca")
        E.Segmentado(esq, self._opcoes_de_onde(),
                     qualidade.onde_do_perfil(perfil),
                     lambda v: self._escolheu_onde("extensao", v)).pack(
            side="top", fill="x")
        E.Texto(esq, "celular: o som fica nele. pc: vem para o pc junto "
                     "com o mouse.", cor=E.APAGADO, tamanho=E.ROTULO,
                largura=E.px(230)).pack(side="top", fill="x",
                                        pady=(E.px(6), E.px(0)))
        # (08/out, rework) a extensao nao traz imagem: so o som -- (08/out,
        # pedido dele: juntar por assunto) dentro do painel do som
        self._chips_do_modo(esq, "extensao", "som")
        if self._falta("som"):
            self._cortina(col_esq.master, "som", "som do celular no pc")

        controle = perfil.get("controle") or {}
        dir_ = self._seg(col_dir, "controles")
        self._chave(dir_, "controle de videogame",
                    bool(controle.get("joystick", True)),
                    lambda v: self._virar_campo("extensao", "controle",
                                                "joystick", v),
                    explicacao="o controle do pc vira controle do celular",
                    borda=False)
        # (03/out) A chave travada "teclado e mouse" virou dica: nao se
        # desliga, entao nao e escolha.
        # (07/out, pedido dele) as dicas com as TECLAS desenhadas, como na
        # aba atalhos (era um texto corrido que quebrava no meio)
        # (08/out) no mesmo painel dos controles
        self._sub(dir_, "dicas")
        for nome, pecas in (
                ("volume", ["ctrl", "+", "alt", "+", "=", "−", "0"]),
                ("voltar", ["tab", "tab", "ou a borda"]),
                ("acentos", ["teclado físico › scrcpy"]),
                ("mouse", ["vai junto com o teclado"])):
            linha = tk.Frame(dir_, bg=E.FUNDO)
            linha.pack(side="top", fill="x", pady=(E.px(0), E.px(5)))
            tk.Label(linha, text=nome, bg=E.FUNDO, fg=E.TEXTO_2,
                     font=E.fonte(E.ROTULO), width=9, anchor="w").pack(
                side="left")
            for p in pecas:
                if p == "+":
                    tk.Label(linha, text="+", bg=E.FUNDO, fg=E.APAGADO,
                             font=E.fonte(E.ROTULO)).pack(side="left",
                                                          padx=E.px(2))
                elif len(p) <= 4:
                    self._teclinha(linha, p).pack(side="left",
                                                  padx=(0, E.px(3)))
                else:
                    tk.Label(linha, text=p, bg=E.FUNDO, fg=E.APAGADO,
                             font=E.fonte(E.ROTULO)).pack(side="left",
                                                          padx=(E.px(2), 0))

    def _info(self, pai, curto: str, detalhe: str,
              largura: int = 230) -> tk.Frame:
        """(07/out, pedido dele: menos texto na tela) UMA linha curta e um
        ⓘ; o resto aparece na dica da casa com o mouse em cima do ⓘ.
        `detalhe` = titulo e linhas separados por \\n."""
        f = tk.Frame(pai, bg=pai.cget("bg"))
        E.Texto(f, curto, cor=E.APAGADO, tamanho=E.ROTULO,
                largura=E.px(largura - 18), bg=pai.cget("bg")).pack(
            side="left", fill="x", expand=True, anchor="n")
        i = tk.Label(f, text="ⓘ", bg=pai.cget("bg"), fg=E.APAGADO,
                     font=E.fonte(E.PEQUENA), cursor="question_arrow",
                     padx=E.px(2), pady=0)
        i.pack(side="right", anchor="n")
        i._tipo = "info"
        i._sobre = False

        def entrou(_e=None):
            i._sobre = True
            i.configure(fg=E.TEXTO)
            self.after(350, lambda: i._sobre and self._mostrar_dica_barra(
                i, detalhe))

        def saiu(_e=None):
            i._sobre = False
            try:
                i.configure(fg=E.APAGADO)
            except tk.TclError:
                pass
            self._esconder_dica_barra()
        i.bind("<Enter>", entrou)
        i.bind("<Leave>", saiu)
        return f

    def _teclinha(self, pai, texto: str, fundo: str = E.FUNDO) -> tk.Label:
        """(07/out) Uma tecla desenhada (a "teclinha" da aba atalhos)."""
        t = tk.Label(pai, text=texto.upper(), bg=E.CAMADA_2, fg=E.TEXTO,
                     font=E.fonte(E.ROTULO), padx=E.px(4), pady=0,
                     highlightthickness=1, highlightbackground=E.BORDA_2)
        E.cantos(t, raio=E.px(4))
        return t

    def _tela_extensao_personalizar(self, area) -> None:
        col_esq, col_dir = self._duas(area)
        lista = self._monitores()
        b = self._borda_resolvida(lista)
        borda_toda = self._borda()

        esq = self._seg(col_esq, "posição do celular", expand=True)
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
        E.cantos(mapa)                   # (03/out) canto arredondado

        dir_ = self._seg(col_dir, "marca na borda", expand=True)
        tk.Label(dir_, text="cor", bg=E.FUNDO, fg=E.TEXTO_2,
                 font=E.fonte(E.PEQUENA), anchor="w").pack(side="top",
                                                          fill="x")
        cores = tk.Frame(dir_, bg=E.FUNDO)
        cores.pack(side="top", fill="x", pady=(E.px(3), E.px(8)))
        atual = str(borda_toda.get("cor") or "#FF5A1F").upper()
        for cor in E.CORES_DA_MARCA:
            # (03/out) amostra arredondada e lisa; (07/out) o anel de
            # "escolhida" vem na propria imagem
            q = self._amostra(cores, cor, E.FUNDO, cor.upper() == atual)
            q.pack(side="left", padx=(E.px(0), E.px(2)))
            q.bind("<Button-1>", lambda _e, cc=cor: self._escolheu_cor(cc))
            self._ui.setdefault("cores", []).append((cor.upper(), q))
        mais = tk.Label(cores, text="+", bg=E.FUNDO, fg=E.TEXTO_2,
                        font=E.fonte(E.CORPO), cursor="hand2", width=2,
                        highlightthickness=1, highlightbackground=E.LINHA_FORTE)
        mais.pack(side="left")
        E.cantos(mais, raio=E.px(5))
        mais.bind("<Button-1>", lambda _e: self._escolher_outra_cor())
        self._ui["cor_mais"] = mais
        if atual not in [c.upper() for c in E.CORES_DA_MARCA]:
            q = self._amostra(cores, atual, E.FUNDO, True)
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
        tk.Label(linha, text=nome, bg=E.FUNDO, fg=E.TEXTO_2,
                 font=E.fonte(E.PEQUENA), anchor="w").pack(side="left")
        v = tk.Label(linha, text=valor, bg=E.FUNDO, fg=E.TEXTO,
                     font=E.fonte(E.PEQUENA))
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
                self._marcar_amostra(q, c == cor.upper())
        else:
            self._remontar_quieto()       # cor escolhida a mao: novo quadrado

    def _amostra(self, pai, cor: str, fundo: str, escolhida: bool,
                 lado: int | None = None) -> tk.Label:
        """Uma amostra de cor clicavel (imagem lisa; o anel claro = a
        escolhida)."""
        q = tk.Label(pai, bd=0, highlightthickness=0, bg=fundo,
                     cursor="hand2")
        q._amostra = (lado or E.px(24), cor, fundo)
        self._marcar_amostra(q, escolhida)

        def recamada(nova):              # (08/out) dentro de um painel
            q._amostra = (q._amostra[0], q._amostra[1], nova)
            self._marcar_amostra(q, q._escolhida)
        q._recamada = recamada
        return q

    def _marcar_amostra(self, q, escolhida: bool) -> None:
        q._escolhida = escolhida
        lado, cor, fundo = q._amostra
        q.configure(image=E.imagem_amostra(lado, cor, fundo,
                                           E.TEXTO if escolhida else None))

    # (07/out, padrao) SELETOR DE COR DA CASA: era o dialogo do Windows
    # (outra cara, outra lingua, sem as cores do programa). Agora uma
    # janelinha na SUPERFICIE, como os menus: uma paleta, o codigo #RRGGBB
    # e a amostra ao vivo; a marca na tela ja mostra a cor enquanto escolhe.
    PALETA_DE_CORES = (
        "#FF5A1F", "#FF8A3D", "#FFB020", "#E8C15A", "#FFE066", "#C6E377",
        "#57C27A", "#2FD07A", "#1FB5A6", "#2FC6E0", "#3D8BFF", "#5B6CFF",
        "#8A5CFF", "#B48CFF", "#E05CFF", "#FF3D8B", "#FF5A5A", "#C7392B",
        "#E9E6DF", "#BDB9B0", "#9A978F", "#6F6D68", "#3A3A42", "#FFFFFF")

    def _escolher_outra_cor(self) -> None:
        atual = str(self._borda().get("cor") or "#FF5A1F").upper()
        if self._menu_alternar(self._ui.get("cor_mais")):
            return                       # clicar no "+" de novo fecha
        menu, corpo = self._novo_menu()
        menu._fora = False
        menu._dono = self._ui.get("cor_mais")
        escolha = [atual]
        lado = E.px(18)
        grade = tk.Frame(corpo, bg=E.SUPERFICIE)
        grade.pack(side="top", padx=E.px(6), pady=(E.px(6), E.px(4)))
        amostras = []

        def pintar_amostras():
            for cor, q in amostras:
                self._marcar_amostra(q, cor == escolha[0])

        def provar(cor, de_fora=False):
            cor = cor.upper()
            escolha[0] = cor
            amostra.configure(image=E.imagem_redonda(
                E.px(28), cor, E.SUPERFICIE, E.px(6)))
            if not de_fora and campo.get().upper() != cor:
                campo.delete(0, "end")
                campo.insert(0, cor)
            pintar_amostras()
            # a marca na borda ja mostra a cor (sem gravar)
            b = self._borda()
            faixa = getattr(self.programa, "faixa", None)
            if faixa is not None:
                try:
                    faixa.definir_estilo(
                        cor=cor,
                        transparencia=float(b.get("transparencia", 0.45)),
                        espessura=int(b.get("espessura", 3)),
                        brilhar=bool(b.get("brilhar", True)))
                except Exception:
                    log.exception("previa da cor")

        for i, cor in enumerate(self.PALETA_DE_CORES):
            q = self._amostra(grade, cor, E.SUPERFICIE, False, lado=lado + 4)
            q.grid(row=i // 6, column=i % 6, padx=E.px(1), pady=E.px(1))
            q.bind("<Button-1>", lambda _e, c=cor: provar(c))
            amostras.append((cor.upper(), q))
        linha = tk.Frame(corpo, bg=E.SUPERFICIE)
        linha.pack(side="top", fill="x", padx=E.px(8), pady=(E.px(4), E.px(6)))
        amostra = tk.Label(linha, bg=E.SUPERFICIE, bd=0)
        amostra.pack(side="left")
        campo = self._caixa(linha, atual, ipady=2)
        campo.configure(width=8)
        campo.master.pack(side="left", fill="x", expand=True,
                          padx=(E.px(8), 0))

        def digitou(_e=None):
            texto = campo.get().strip().upper()
            if not texto.startswith("#"):
                texto = "#" + texto
            import re
            if re.fullmatch(r"#[0-9A-F]{6}", texto):
                provar(texto, de_fora=True)
        campo.bind("<KeyRelease>", digitou, add="+")

        def usar(_e=None):
            cor = escolha[0]
            self._fechar_menu_app()
            self._escolheu_cor(cor)
            return "break"

        def cancelar(_e=None):
            self._fechar_menu_app()
            return "break"
        campo.bind("<Return>", usar)
        fim = tk.Frame(corpo, bg=E.SUPERFICIE)
        fim.pack(side="top", fill="x", padx=E.px(8), pady=(0, E.px(6)))
        E.Botao(fim, "usar", usar, tipo="acao").pack(side="right")
        E.Botao(fim, "cancelar", cancelar, tipo="discreto",
                bg=E.SUPERFICIE).pack(side="right", padx=(0, E.px(6)))
        menu.bind("<Escape>", cancelar)
        provar(atual)
        mais = self._ui.get("cor_mais")
        import types
        try:
            onde = types.SimpleNamespace(
                x_root=mais.winfo_rootx(),
                y_root=mais.winfo_rooty() + mais.winfo_height())
        except (AttributeError, tk.TclError):
            x, y = self.winfo_pointerxy()
            onde = types.SimpleNamespace(x_root=x, y_root=y)
        self._encher_menu(menu, corpo, onde, [])
        menu.bind("<Escape>", cancelar)
        # fechar clicando fora tambem desfaz a previa
        # fechou (usar, cancelar ou clique fora): a marca volta a cor
        # gravada -- que ja e a nova, se usou
        menu.bind("<Destroy>", lambda e: e.widget is menu and self.after_idle(
            self.programa.aplicar_estilo_da_faixa))

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
        E.cantos(palco)                  # (07/out) canto arredondado
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
        # (03/out/2026, pedido dele) A AREA INTEIRA da aba e dos icones: a
        # lista vai ate as linhas que limitam a aba (em cima, embaixo e dos
        # lados; sem a margem das outras telas). A busca e o atualizar
        # flutuam SOLTOS no alto (sem faixa por tras) e o aviso flutua
        # embaixo, POR CIMA da grade: os icones rolam por tras deles (e a
        # barra de rolagem tambem fica por cima). O Tk nao tem vidro: o que
        # flutua e opaco.
        caixa = tk.Frame(area, bg=E.FUNDO)
        caixa.pack(side="top", fill="both", expand=True)
        m = E.PADDING
        # (03/out, pedido dele) a busca do tamanho da barra "no celular
        # agora" das notificacoes (30), com o mesmo espaco ate a lista
        alto_busca = E.px(30)
        rolagem = _Rolagem(caixa, sobreposta=True,
                           margem_topo=m + alto_busca + E.px(8),
                           margem_base=E.px(36), margem_lados=m)
        busca = self._barra_de_busca(
            caixa, getattr(self, "_apps_busca", ""),
            "buscar",
            self._buscou_app, ao_enter=self._abrir_primeiro_app,
            atualizar=lambda: self._carregar_apps(forcar=True),
            altura=alto_busca)
        busca.master.place(x=m, y=m, relwidth=1.0, width=-2 * m,
                           height=alto_busca)
        busca.master.lift()
        E.cantos(busca.master)          # os cantinhos voltam por cima dela
        self._ui["busca_apps"] = busca
        # O aviso ("atualizando a lista...") e um balao embaixo, no meio;
        # some sozinho quando o trabalho acaba (`_pintar_aviso_apps`).
        # (07/out, gravado na partida: nascia quadrado com uma faixa escura)
        # camada que flutua (SUPERFICIE, como o snackbar), recortado redondo
        # pelo Windows -- sem borda, que o recorte cortaria nos cantos
        # (07/out, relato dele: "muda de formato") LARGURA FIXA, a do texto
        # mais longo: trocar "atualizando a lista" por "buscando os icones"
        # mudava o tamanho e o recorte redondo chegava um quadro depois
        aviso = tk.Label(caixa, text="", bg=E.SUPERFICIE, fg=E.TEXTO,
                         font=E.fonte(E.ROTULO), padx=E.px(14), pady=E.px(6),
                         highlightthickness=0, anchor="center",
                         width=len("buscando os ícones no celular…") + 1)
        E.recorte_redondo(aviso, raio=E.px(9))
        self._ui["aviso_apps"] = aviso
        # A grade muda o numero de colunas quando a largura aparece.
        rolagem.canvas.bind("<Configure>",
                            lambda _e: self._pintar_lista_apps(), add="+")
        self._ui["rolagem_apps"] = rolagem
        # (09/out) a grade com `place` e o filtro animado (filtro_animado)
        self._ui["arranjo_apps"] = FA.Arranjo(rolagem.dentro, rolagem.canvas,
                                              E.FUNDO)
        self._apps_pintado = None
        self._pintar_lista_apps()
        # A busca NAO pega o foco sozinha (pedido dele, 23/set/2026).
        if not any(a[1] != DEX for a in (self._apps or [])) and \
                not self._apps_carregando:
            self._carregar_apps()

    # -- ICONES DE LINHA e BARRA DE BUSCA (03/out/2026, pedido dele) ---------
    # Padrao dos sistemas de icones (Material): grade de 24 unidades, desenho
    # numa AREA UTIL de 20 (2 de folga em volta), traco de 2 unidades com
    # pontas redondas, feitos 4x maiores e reduzidos (lisos). Todos com a
    # mesma espessura, para conversarem entre si.

    _ICONES_LINHA: dict = {}

    def _icone_linha(self, nome: str, lado: int, cor: str, fundo: str,
                     bolha: str | None = None):
        """"atualizar" | "lupa" | "x" em `lado` px. `bolha` = um circulo de
        fundo (o realce do botao com o mouse em cima)."""
        chave = (nome, lado, cor, fundo, bolha)
        if chave in self._ICONES_LINHA:
            return self._ICONES_LINHA[chave]
        import math
        from PIL import Image, ImageDraw, ImageTk
        k = 4
        L = lado * k
        u = L / 24.0                          # uma unidade da grade
        g = max(k, int(round(2 * u)))         # o traco: 2 unidades
        img = Image.new("RGB", (L, L), fundo)
        d = ImageDraw.Draw(img)
        if bolha:
            d.ellipse((0, 0, L - 1, L - 1), fill=bolha)

        def ponta(x, y):                      # tampa redonda do traco
            d.ellipse((x - g / 2, y - g / 2, x + g / 2, y + g / 2), fill=cor)

        if nome == "atualizar":
            # arco de 300 graus (circulo da area util, r = 7) com a abertura
            # no canto de cima a direita; a seta na ponta, no sentido do giro
            c, r = 12 * u, 7 * u
            ini_, fim_ = 330, 330 + 300        # graus (0 = 3h, sentido horario)
            h = 3.8 * u                               # tamanho da seta
            # (03/out, relato dele: "pixels no fim da seta") o arco PARA
            # antes da ponta e termina ESCONDIDO dentro do triangulo: a ponta
            # reta do traco nao aparece mais. O PIL desenha o traco do arco
            # para DENTRO da caixa: a caixa cresce meio traco, para o traco
            # ficar CENTRADO no raio (onde estao a bolinha e a seta).
            recuo = math.degrees(0.25 * h / r)
            m_ = g / 2.0
            d.arc((c - r - m_, c - r - m_, c + r + m_, c + r + m_), ini_,
                  fim_ - recuo, fill=cor, width=g)
            a0 = math.radians(ini_)
            ponta(c + r * math.cos(a0), c + r * math.sin(a0))
            a = math.radians(fim_)
            px_, py_ = c + r * math.cos(a), c + r * math.sin(a)
            tx, ty = -math.sin(a), math.cos(a)        # tangente (o giro)
            nx, ny = math.cos(a), math.sin(a)         # para fora
            d.polygon([(px_ + tx * h * 0.95, py_ + ty * h * 0.95),
                       (px_ - tx * h * 0.35 + nx * h * 0.85,
                        py_ - ty * h * 0.35 + ny * h * 0.85),
                       (px_ - tx * h * 0.35 - nx * h * 0.85,
                        py_ - ty * h * 0.35 - ny * h * 0.85)], fill=cor)
        elif nome == "lupa":
            # mesmo tamanho de desenho do atualizar (14 unidades, 5 a 19);
            # o traco da lente CENTRADO no raio (o PIL desenha para dentro)
            c, r = 10.5 * u, 5.5 * u
            m_ = g / 2.0
            d.ellipse((c - r - m_, c - r - m_, c + r + m_, c + r + m_),
                      outline=cor, width=g)
            x0 = y0 = c + r * 0.72                    # cabo a 45 graus
            x1 = y1 = 19 * u
            d.line((x0, y0, x1, y1), fill=cor, width=g)
            ponta(x1, y1)
        elif nome == "x":
            a0, a1 = 7 * u, 17 * u           # um pouco menor que a lupa
            for p, q in (((a0, a0), (a1, a1)), ((a1, a0), (a0, a1))):
                d.line(p + q, fill=cor, width=g)
                ponta(*p)
                ponta(*q)
        filtro = getattr(Image, "Resampling", Image).BOX
        foto = ImageTk.PhotoImage(img.resize((lado, lado), filtro), master=self)
        self._ICONES_LINHA[chave] = foto
        return foto

    def _botao_icone(self, pai, nome: str, lado: int, fundo: str, acao,
                     cor: str | None = None) -> tk.Label:
        """Um botao que e SO o icone: realce = bolha discreta atras dele e o
        icone clareia; teclado: Tab chega, Enter/Espaco aciona."""
        cor = cor or E.TEXTO_2
        b = tk.Label(pai, bd=0, highlightthickness=0, bg=fundo,
                     cursor="hand2", takefocus=1,
                     image=self._icone_linha(nome, lado, cor, fundo))
        estado = {"sobre": False, "foco": False}

        def pintar(**mudou):
            estado.update(mudou)
            ativo = estado["sobre"] or estado["foco"]
            b.configure(image=self._icone_linha(
                nome, lado, E.TEXTO if ativo else cor, fundo,
                bolha=E.SUPERFICIE_SOBRE if ativo else None))

        def agir(_e=None):
            acao()
            return "break"
        for ev in ("<Button-1>", "<Return>", "<space>"):
            b.bind(ev, agir)
        b.bind("<Enter>", lambda _e: pintar(sobre=True))
        b.bind("<Leave>", lambda _e: pintar(sobre=False))
        b.bind("<FocusIn>", lambda _e: pintar(foco=True))
        b.bind("<FocusOut>", lambda _e: pintar(foco=False))
        return b

    def _barra_de_busca(self, pai, texto: str, dica: str, ao_mudar,
                        ao_enter=None, atualizar=None, chave_ui: str = "",
                        altura: int = 0) -> tk.Entry:
        """
        A BARRA DE BUSCA da casa (03/out/2026, pedido dele: "coisas que
        normalmente tem em barras de pesquisa"), na camada 2 (flutua):
          lupa | texto de dica (some ao digitar) | contador | x | atualizar
        - o x so aparece com texto; Esc limpa (e, vazia, solta o foco);
        - `atualizar` = acao do botao (seta em circulo) ao lado do x, depois
          de um separador fino;
        - o contador ("3 de 87") e posto por quem filtra: `_contar_busca`.
        Quem chama posiciona `campo.master` (a moldura).
        """
        fundo, borda = E.CAMADA_2, E.BORDA_2
        # (03/out, relato dele: "estranha, nao parece natural") Os tres
        # icones no MESMO tamanho de quadro (o desenho de cada um pesa igual:
        # lupa, x e atualizar), a letra da casa no tamanho das linhas
        # (PEQUENA, nao a de titulo) e as folgas iguais dos dois lados.
        lado_ic = E.px(20)
        moldura = tk.Frame(pai, bg=fundo, highlightthickness=1,
                           highlightbackground=borda, height=altura or E.px(30))
        moldura.pack_propagate(False)
        lupa = tk.Label(moldura, bg=fundo, bd=0,
                        image=self._icone_linha("lupa", lado_ic, E.TEXTO_2,
                                                fundo))
        lupa.pack(side="left", padx=(E.px(6), E.px(2)))
        if atualizar is not None:
            self._botao_icone(moldura, "atualizar", lado_ic, fundo,
                              atualizar).pack(side="right",
                                              padx=(E.px(2), E.px(6)))
            tk.Frame(moldura, bg=borda, width=1).pack(
                side="right", fill="y", pady=E.px(8), padx=(E.px(4), 0))
        limpar = self._botao_icone(moldura, "x", lado_ic, fundo,
                                   lambda: None)
        conta = tk.Label(moldura, text="", bg=fundo, fg=E.APAGADO,
                         font=E.fonte(E.ROTULO))
        # (03/out, relato dele: "nao fica piscando") o cursor de texto mais
        # visivel; a dica comeca DEPOIS dele (antes ela o cobria)
        campo = tk.Entry(moldura, font=E.fonte(E.PEQUENA), bg=fundo,
                         fg=E.TEXTO, insertbackground=E.TEXTO, relief="flat",
                         highlightthickness=0, bd=0,
                         insertwidth=max(2, E.px(1.5)), insertontime=600,
                         insertofftime=450)
        campo.pack(side="left", fill="both", expand=True)
        aviso = tk.Label(moldura, text=dica, bg=fundo, fg=E.APAGADO,
                         font=E.fonte(E.PEQUENA), anchor="w", cursor="xterm",
                         padx=0, bd=0)
        # (03/out, relato dele: "nenhuma barra funciona") o clique na dica
        # (que fica por cima da caixa vazia) e na lupa leva o foco para a
        # caixa e PARA ali ("break"): senao o clique geral da janela
        # ("clicou fora da caixa") tirava o foco de volta na mesma hora.
        def focar(_e=None):
            campo.focus_set()
            campo.icursor("end")
            return "break"
        aviso.bind("<Button-1>", focar)
        lupa.bind("<Button-1>", focar)
        campo._dica = aviso
        campo._conta = conta

        def acertar():
            tem = bool(campo.get())
            if tem and not limpar.winfo_manager():
                limpar.pack(side="right", padx=(0, E.px(2)))
            elif not tem and limpar.winfo_manager():
                limpar.pack_forget()
            if tem:
                aviso.place_forget()
            else:
                # a dica comeca onde o texto digitado comeca (sem "pular"
                # ao digitar) e logo depois do cursor, que fica a vista
                folga = max(2, E.px(1.5)) + 1
                aviso.place(in_=campo, x=folga, relx=0, rely=0.5, anchor="w",
                            relwidth=1.0, width=-folga)
            if not tem and conta.winfo_manager():
                conta.pack_forget()

        def mudou(_e=None):
            acertar()
            ao_mudar()

        def esvaziar(_e=None):
            if campo.get():
                campo.delete(0, "end")
                mudou()
            else:
                self.focus_set()
            return "break"

        limpar.bind("<Button-1>", esvaziar)
        limpar.bind("<Return>", esvaziar)
        campo.bind("<KeyRelease>", mudou, add="+")
        campo.bind("<Escape>", esvaziar)
        if ao_enter is not None:
            campo.bind("<Return>", lambda _e: ao_enter())
        campo.bind("<FocusIn>", lambda _e: (moldura.configure(
            highlightbackground=E.FOCO), E.cantos(moldura)), add="+")
        campo.bind("<FocusOut>", lambda _e: (moldura.configure(
            highlightbackground=borda), E.cantos(moldura)), add="+")
        if texto:
            campo.insert(0, texto)
        campo._acertar = acertar
        moldura.after_idle(acertar)
        E.cantos(moldura)
        if chave_ui:
            self._ui[chave_ui] = campo
        return campo

    def _ir_para_busca(self, _e=None):
        for chave in ("busca_apps", "busca_notif", "busca_atalhos"):
            campo = self._ui.get(chave)
            try:
                if campo is not None and campo.winfo_ismapped():
                    campo.focus_set()
                    campo.select_range(0, "end")
                    return "break"
            except tk.TclError:
                pass
        return None

    def _contar_busca(self, campo, achados: int, total: int) -> None:
        """O contador da barra: "3 de 87" so enquanto filtra."""
        try:
            conta = campo._conta
            if campo.get().strip():
                texto = "%d de %d" % (achados, total)
                if conta.cget("text") != texto:
                    conta.configure(text=texto)
                if not conta.winfo_manager():
                    conta.pack(side="right", padx=(E.px(6), E.px(4)))
            elif conta.winfo_manager():
                conta.pack_forget()
        except (AttributeError, tk.TclError):
            pass

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
        # (03/out) so pelo NOME que aparece: o pacote ("com.google...")
        # trazia resultados que nao pareciam ter nada a ver
        itens = [a for a in self._apps if not termo or termo in a[0].lower()]
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

    def _limpar_busca_apps(self, pintar: bool = True) -> None:
        """(09/out, pedido dele) Agiu num resultado da busca (abriu, fechou,
        fixou, personalizou...): a busca se apaga e a lista volta inteira.
        `pintar=False` (acao do menu): a lista so se refaz DEPOIS da acao e
        so se ainda estiver a vista -- se a acao trocou de tela (ex.: o
        personalizar), refazer a grade agora brigava com a animacao da troca
        (relato dele); a volta a lista ja a poe em dia (reaproveitar)."""
        b = self._ui.get("busca_apps")
        if not (getattr(self, "_apps_busca", "") or
                (b is not None and b.winfo_exists() and b.get())):
            return
        self._apps_busca = ""
        if getattr(self, "_busca_id", None):
            try:
                self.after_cancel(self._busca_id)
            except Exception:
                pass
            self._busca_id = None
        try:
            if b is not None and b.winfo_exists():
                b.delete(0, "end")
                b._acertar()
                if self.focus_get() is b:
                    self.focus_set()
        except (tk.TclError, KeyError, AttributeError):
            pass
        if pintar:
            self._pintar_lista_apps()
            return
        ui = self._ui

        def depois():
            if self._ui is ui and \
                    getattr(self, "_tela_atual", "") == "_tela_apps_lista" \
                    and getattr(self, "_veu", None) is None:
                self._pintar_lista_apps()
        self.after_idle(depois)

    def _clicou_app(self, pacote: str, nome: str) -> None:
        """Clique: aberto vem para a frente; fechado abre."""
        self._limpar_busca_apps()
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
        self._grupo_editor = GRUPOS_DO_EDITOR[0]   # (07/out) no primeiro
        self._escolhendo_app = False
        if self._aba.get("apps") == "personalizados":
            self._montar_conteudo()
        else:
            self._escolher_aba("personalizados")

    # -- menu do botao direito num app (23/set/2026) ------------------------

    def _novo_menu(self):
        """(07/out) O MENU DA CASA, um so para todo botao direito e lista de
        escolha: janelinha na SUPERFICIE (camada 3), sem moldura do Tk, a
        borda fina e a curva do Windows 11; nasce escondida (aparece pronta,
        no lugar, esmaecendo -- `_encher_menu`). Devolve (menu, corpo)."""
        self._fechar_menu_app()
        try:
            volta = self.focus_get()
        except (tk.TclError, KeyError):
            volta = None
        menu = tk.Toplevel(self)
        menu._volta_foco = volta         # fechou: o foco volta para quem abriu
        menu.withdraw()
        menu.overrideredirect(True)
        # (03/out, pedido dele: "quadradoes feios") a borda e a curva sao do
        # Windows 11 (sem a moldura quadrada do Tk)
        moldura.arredondar_ao_mostrar(menu, borda=E.SUPERFICIE_BORDA)
        menu.attributes("-topmost", True)
        menu.configure(bg=E.SUPERFICIE)
        corpo = tk.Frame(menu, bg=E.SUPERFICIE)
        corpo.pack(padx=E.px(5), pady=E.px(5))
        return menu, corpo

    def _menu_do_app(self, evento, pacote: str, nome: str) -> None:
        fixado = pacote in self._config.fixados()
        menu, corpo = self._novo_menu()
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
        # (08/out, pedido dele) com ajuste proprio: tirar pelo botao direito
        tirar = [("remover ajuste personalizado",
                  lambda: self._limpar_personalizado(pacote))] \
            if pacote in self._config.personalizados() else []
        opcoes = cheia + [
                  ("configurações personalizadas",
                   lambda: self._configurar_app(pacote, nome))] + tirar + [
                  # (r159) I2 da v1.0: atalho com o nome e o icone do app.
                  ("criar atalho na área de trabalho",
                   lambda: self._criar_atalho_desktop(pacote, nome)),
                  None,
                  # (03/out) liga/desliga = linha com chave
                  ("fixado na lista", fixado,
                   lambda v: self._fixar_app(pacote, v))]
        if pacote != DEX:
            # (01/out) Atalho para a chave do app em NOTIFICACOES > ajustes.
            opcoes.append(("notificações no pc",
                           self._config.notif_do_app(pacote),
                           lambda v: self._virar_notif_app(pacote, v)))
        # (09/out, pedido dele) qualquer acao do menu num resultado da busca
        # apaga a busca (antes da acao: a lista a vista e a dos apps)
        def limpando(o):
            if o is None:
                return o
            if len(o) == 2 and callable(o[1]):
                return (o[0], lambda a=o[1]: (
                    self._limpar_busca_apps(pintar=False), a())[1])
            if len(o) == 3 and isinstance(o[1], bool) and callable(o[2]):
                return (o[0], o[1], lambda v, a=o[2]: (
                    self._limpar_busca_apps(pintar=False), a(v))[1])
            return o
        opcoes = [limpando(o) for o in opcoes]
        self._encher_menu(menu, corpo, evento, opcoes)

    def _encher_menu(self, menu, corpo, evento, opcoes,
                     largura_min: int = 0) -> None:
        """Itens do menu da casa (botao direito e listas de escolha). Cada:
          None                          um risco separando grupos
          (texto, acao)                 um comando
          (texto, acao, True)           (07/out) a escolha atual de uma
                                        lista (marcada, como no Android)
          (texto, [(valor, acao), ...]) (03/out, pedido dele) UM comando com
                                        valores: uma linha so, os valores
                                        em botoezinhos ao lado
          (texto, ligado, acao(novo))   liga/desliga: a linha com uma chave
        """
        itens = []                       # (07/out) setas + Enter (teclado)
        for opcao in opcoes:
            if opcao is None:
                tk.Frame(corpo, bg=E.SUPERFICIE_SOBRE, height=1).pack(
                    side="top", fill="x", pady=E.px(4), padx=E.px(6))
                continue
            marcado = len(opcao) == 3 and callable(opcao[1]) and \
                opcao[2] is True
            if not marcado and (len(opcao) == 3 or isinstance(opcao[1], list)):
                self._linha_de_menu(corpo, opcao)
                continue
            texto, acao = opcao[0], opcao[1]
            fundo = E.SUPERFICIE
            # a escolha atual: letra forte e ja realcada ao abrir
            item = tk.Label(corpo, text=texto,
                            bg=E.SUPERFICIE_SOBRE if marcado else fundo,
                            fg=E.TEXTO, font=E.fonte(E.PEQUENA, "bold")
                            if marcado else E.fonte(E.PEQUENA), anchor="w",
                            cursor="hand2", padx=E.px(10), pady=E.px(5))
            item._marcado = marcado
            item.pack(side="top", fill="x")
            # (03/out) o realce e uma pilula discreta (sem laranja)
            # (07/out, varredura: o Tk chegou a chamar o <Leave> sem o evento
            # com o menu sumindo) o evento e opcional
            item.bind("<Enter>", lambda _e=None, w=item: (w.configure(
                bg=E.SUPERFICIE_SOBRE), E.cantos(w, raio=E.px(5))))
            item.bind("<Leave>", lambda _e=None, w=item, f=fundo: (
                w.winfo_exists() and (w.configure(bg=f),
                                      E.cantos(w, raio=E.px(5)))))
            E.cantos(item, raio=E.px(5))
            item.bind("<Button-1>", lambda _e=None, w=item, a=acao:
                      self._no_menu(w, a))
            item._fundo = fundo
            itens.append((item, acao))
        if largura_min:
            tk.Frame(corpo, bg=E.SUPERFICIE, width=largura_min - E.px(10),
                     height=0).pack(side="top")
        menu.geometry("+%d+%d" % self._lugar_do_menu(
            menu, evento.x_root, evento.y_root))
        menu.bind("<Escape>", lambda _e: self._fechar_menu_app())
        sel = [next((i for i, (w, _a) in enumerate(itens) if w._marcado),
                    -1)]

        def andar(passo):
            if not itens:
                return "break"
            if 0 <= sel[0] < len(itens):
                w = itens[sel[0]][0]
                w.configure(bg=w._fundo)
                E.cantos(w, raio=E.px(5))
            sel[0] = (sel[0] + passo) % len(itens)
            w = itens[sel[0]][0]
            w.configure(bg=E.SUPERFICIE_SOBRE)
            E.cantos(w, raio=E.px(5))
            return "break"

        def escolher(_e=None):
            if 0 <= sel[0] < len(itens):
                w, a = itens[sel[0]]
                return self._no_menu(w, a)
            return "break"
        menu.bind("<Down>", lambda _e: andar(+1))
        menu.bind("<Up>", lambda _e: andar(-1))
        menu.bind("<Return>", escolher)
        menu.bind("<space>", escolher)
        self._menu_app = menu
        # (07/out) aparece pronto, no lugar, esmaecendo e descendo um pouco
        if mov.ligadas():
            menu.attributes("-alpha", 0.0)
        menu.deiconify()
        mov.entrar(menu)
        self._dica_cancelar()
        self._dica_esconder()
        # (03/out, teste dele: "nao somem quando clico fora") o vigia e o
        # teclado (o Esc so chega com o foco no menu)
        menu._apertado = True            # o botao que abriu ainda esta descendo
        menu.after(120, lambda: menu.winfo_exists() and menu.focus_force())
        menu.after(80, lambda: self._vigiar_menu(menu))

    def _lugar_do_menu(self, menu, x: int, y: int) -> tuple[int, int]:
        """(03/out, pedido dele) O menu cabe na tela do mouse: passando da
        borda de BAIXO (barra de tarefas fora) abre para CIMA do ponteiro;
        passando da direita, para a esquerda."""
        menu.update_idletasks()
        larg, alt = menu.winfo_reqwidth(), menu.winfo_reqheight()
        folga = E.px(2)
        if getattr(menu, "_alinhar", None) == "direita":
            x -= larg + 2 * folga        # a borda direita no ponto pedido
        try:
            ax, ay, al, aa = moldura.area_util(self, (x, y))
        except Exception:
            ax, ay = 0, 0
            al, aa = self.winfo_screenwidth(), self.winfo_screenheight()
        nx = x + folga if x + folga + larg <= ax + al else x - folga - larg
        ny = y + folga if y + folga + alt <= ay + aa else y - folga - alt
        # tela pequena demais para os dois lados: encosta na borda
        nx = max(ax, min(nx, ax + al - larg))
        ny = max(ay, min(ny, ay + aa - alt))
        return nx, ny

    def _vigiar_menu(self, menu) -> None:
        """Enquanto o menu esta aberto (de 80 em 80 ms): clique em QUALQUER
        lugar fora dele (outro programa, area de trabalho), outra janela na
        frente ou a janela do programa sumindo -> fecha."""
        if menu is not getattr(self, "_menu_app", None):
            return
        try:
            if not menu.winfo_exists():
                return
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            apertado = any(u.GetAsyncKeyState(b) & 0x8000 for b in (1, 2, 4))
            # (07/out) o menu do aviso do canto / mini vive sem a janela
            fechar = not self._visivel and not getattr(menu, "_fora", False)
            if apertado and not menu._apertado:
                p = wintypes.POINT()
                u.GetCursorPos(ctypes.byref(p))
                x0, y0 = menu.winfo_rootx(), menu.winfo_rooty()
                dentro = (x0 <= p.x < x0 + menu.winfo_width() and
                          y0 <= p.y < y0 + menu.winfo_height())
                fechar = fechar or not dentro
            menu._apertado = apertado
            # outra janela veio para a frente (Alt+Tab, clique em outro
            # programa): so conta se a da frente MUDOU desde que abriu
            frente = u.GetForegroundWindow()
            if not hasattr(menu, "_frente_ao_abrir"):
                menu._frente_ao_abrir = frente
            nossas = {int(self.wm_frame(), 16), int(menu.wm_frame(), 16),
                      menu._frente_ao_abrir}
            if frente and frente not in nossas:
                fechar = True
        except Exception:
            return
        if fechar:
            self._fechar_menu_app()
            return
        menu.after(80, lambda: self._vigiar_menu(menu))

    def _linha_de_menu(self, corpo, opcao) -> None:
        """Linha de menu com valores (botoezinhos) ou com uma chave."""
        linha = tk.Frame(corpo, bg=E.SUPERFICIE)
        linha.pack(side="top", fill="x", pady=E.px(1))
        tk.Label(linha, text=opcao[0], bg=E.SUPERFICIE, fg=E.TEXTO,
                 font=E.fonte(E.PEQUENA), anchor="w", padx=E.px(10),
                 pady=E.px(5)).pack(side="left")
        if len(opcao) == 3:
            _t, ligado, acao = opcao
            # (07/out) vale na hora; o menu some depois de a chave deslizar
            menu = linha.winfo_toplevel()

            def virar(v, a=acao):
                a(v)
                self.after(mov.MS_CONTROLE + 80, lambda: (
                    menu is getattr(self, "_menu_app", None) and
                    self._fechar_menu_app()))
            ch = E.Chave(linha, bool(ligado), virar, bg=E.SUPERFICIE)
            ch.pack(side="right", padx=(E.px(16), E.px(8)))
            return
        valores = tk.Frame(linha, bg=E.SUPERFICIE)
        valores.pack(side="right", padx=(E.px(16), E.px(6)))
        for valor in opcao[1]:
            rotulo, acao = valor[0], valor[1]
            # (07/out) (rotulo, acao, True) = o valor atual, ja aceso
            atual = len(valor) > 2 and bool(valor[2])
            bg0, fg0 = ((E.SUPERFICIE_SOBRE, E.TEXTO) if atual
                        else (E.SUPERFICIE, E.TEXTO_2))
            v = tk.Label(valores, text=rotulo, bg=bg0, fg=fg0,
                         font=E.fonte(E.ROTULO), cursor="hand2",
                         highlightthickness=1,
                         highlightbackground=E.FOCO if atual
                         else E.SUPERFICIE_BORDA,
                         padx=E.px(7), pady=E.px(2))
            v.pack(side="left", padx=(E.px(4), 0))
            v.bind("<Enter>", lambda _e, w=v: (w.configure(
                bg=E.SUPERFICIE_SOBRE, fg=E.TEXTO), E.cantos(w, raio=E.px(4))))
            v.bind("<Leave>", lambda _e, w=v, b=bg0, f=fg0: (w.configure(
                bg=b, fg=f), E.cantos(w, raio=E.px(4))))
            v.bind("<Button-1>", lambda _e, w=v, a=acao: self._no_menu(w, a))
            E.cantos(v, raio=E.px(4))

    # Nomes curtos das telas do Android no menu da notificacao (viram os
    # botoezinhos de "no celular").
    TELAS_CURTAS = {"desativar notificações": "desativar",
                    "configurações": "ajustes",
                    "configurações do app": "do app",
                    "informações do app": "info"}

    def _menu_notif(self, evento, app: str, chave: str,
                    fora: bool = False) -> None:
        """
        (01/out, pedido dele) BOTAO DIREITO NUMA NOTIFICACAO = o que o
        Android mostra ao segurar ela: desativar notificacoes e
        configuracoes (as telas das Configuracoes do Android, do app e da
        categoria), configuracoes do app (a tela propria dos apps do
        sistema), informacoes do app -- cada uma abre na janela certa do PC.
        """
        from . import notificacoes as nt
        n = next((x for x in self.programa.notif.todas() if x.chave == chave),
                 None)
        if n is None:
            return
        p = self.programa
        opcoes = []
        if n.alvo is not None or self._app_abre(app):
            opcoes.append(("abrir", lambda: self._abrir_notif(app, chave)))
        # (02/out) abrir/fechar o cartao, copiar o texto e ADIAR (como o
        # "adiar" do Android: some e volta, avisando, depois do tempo).
        if self._tem_mais_notif(n, self._largura_texto_notif()):
            opcoes.append(("fechar" if chave in self._notif_abertas
                           else "expandir",
                           lambda: self._virar_notif_aberta(chave)))
        opcoes.append(("copiar texto", lambda: self._copiar_texto(
            n.texto_para_copiar())))
        if n.limpavel and not n.fixa:
            # (03/out) um comando, tres valores: uma linha so
            opcoes.append(("adiar", [
                ("%d min" % mi if mi < 60 else "%d h" % (mi // 60),
                 lambda mi=mi: p.notif.adiar(chave, mi))
                for mi in p.notif.ADIAR_MIN]))
        if n.limpavel:
            opcoes.append(("remover", lambda: self._remover_notif([chave])))
        opcoes.append(None)
        telas = [(self.TELAS_CURTAS.get(rotulo, rotulo),
                  lambda j=janela, a=args: p.abrir_tela(j, a))
                 for rotulo, janela, args in nt.telas_da_notificacao(
                     n, p.notif.prefs.get(n.pacote, ""))]
        if telas:
            opcoes.append(("no celular", telas))
        opcoes.append(("notificações no pc", self._config.notif_do_app(app),
                       lambda v: self._virar_notif_app(app, v)))
        menu, corpo = self._novo_menu()
        menu._fora = fora                # aberto do aviso: a janela pode
        self._encher_menu(menu, corpo, evento, opcoes)   # estar escondida

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

    def _menu_alternar(self, dono) -> bool:
        """(07/out, pedido dele) Clicar de novo em quem abriu o menu FECHA.
        True = era o caso (o menu dele estava aberto, ou acabou de fechar
        por este mesmo clique -- o vigia pode chegar antes). Quem abre
        chama isto primeiro e, com True, nao abre de novo."""
        if dono is None:
            return False
        menu = getattr(self, "_menu_app", None)
        if menu is not None and getattr(menu, "_dono", None) is dono:
            self._fechar_menu_app()
            return True
        quem, quando = getattr(self, "_menu_fechado", (None, 0.0))
        return quem is dono and time.monotonic() - quando < 0.3

    def _fechar_menu_app(self) -> None:
        menu, self._menu_app = getattr(self, "_menu_app", None), None
        if menu is not None:
            self._menu_fechado = (getattr(menu, "_dono", None),
                                  time.monotonic())
            # (07/out) some esmaecendo; sem o foco nem cliques enquanto isso
            try:
                menu.unbind("<Escape>")
                volta = getattr(menu, "_volta_foco", None)
                if volta is not None and volta.winfo_exists() and \
                        self.focus_get() is not None and \
                        str(self.focus_get()).startswith(str(menu)):
                    volta.focus_set()
                mov.sair(menu, menu.destroy)
            except (tk.TclError, KeyError):
                pass

    def _no_menu(self, w, acao, *args) -> str:
        """Clique num item do menu: fecha e age -- uma vez so (o menu que
        esta sumindo nao aceita outro clique)."""
        try:
            if getattr(w.winfo_toplevel(), "_saindo", False):
                return "break"
        except tk.TclError:
            return "break"
        self._fechar_menu_app()
        acao(*args)
        return "break"

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
            # (07/out, travadas medidas na abertura) So os icones que MUDARAM
            # no disco: antes cada chegada (inclusive a do cache, com nada
            # novo) refazia a grade inteira e as telas guardadas (~0,8 s +
            # ~1,5 s com o Tk parado).
            marcas = self.__dict__.setdefault("_fotos_marca", {})
            pasta = self.programa.pasta_de_icones()
            mudaram = {pac for pac, m in marcas.items()
                       if self._marca_do_icone(pasta / (pac + ".png")) != m}
            if not mudaram:
                self._pintar_lista_apps()
                return
            # Esquece as imagens montadas desses (inclusive os "nao tem") e
            # redesenha. (02/out, revisao) As velhas ficam vivas ate a
            # proxima chegada: soltas, o Python apagava a imagem de quem nao
            # e redesenhado (aviso no canto, escolher app, personalizados).
            self._fotos_velhas = {k: v for k, v in self._fotos.items()
                                  if k[0] in mudaram}
            self._fotos = {k: v for k, v in self._fotos.items()
                           if k[0] not in mudaram}
            for pac in mudaram:
                marcas.pop(pac, None)
            self._icones_mudaram = mudaram
            self._icones_versao += 1
            self._agendar_renovar()
            # (01/out, teste dele: "os icones aparecem e depois somem")
            # Limpar as fotos apaga a imagem de quem ja estava na tela: a
            # aba de notificacoes a vista redesenha os icones na hora.
            if self._item == "notif":
                self._pintar_notif()
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
            # (cabe na largura fixa do balao)
            texto, cor = _encurtar("✗  " + self._apps_erro, 30), E.ERRO
        else:
            texto, cor = "", E.APAGADO
        # (07/out, gravado na abertura com APPS: o balao apagava o texto
        # ANTES de descer e virava uma bolinha vazia, com um quadradinho no
        # meio) Sumindo, o texto fica ate ele sair; so troca para mostrar.
        if texto and aviso.cget("text") != texto:
            # (o recorte redondo acompanha o tamanho sozinho)
            aviso.configure(text=texto, fg=E.TEXTO if cor == E.APAGADO
                            else cor)
        # (07/out, pedido dele: aparecia "2x" na partida) Como o indicador de
        # progresso do Android: so aparece se o trabalho passar de MEIO
        # SEGUNDO (o rapido nao pisca um balao na tela); erro, na hora.
        if not texto:
            aviso._quer_desde = None
        elif getattr(aviso, "_quer_desde", None) is None:
            aviso._quer_desde = time.monotonic()
        if texto and (not aviso.winfo_manager() or
                      getattr(aviso, "_sumindo", False)):
            falta = 0.5 - (time.monotonic() - aviso._quer_desde)
            if cor == E.ERRO or falta <= 0:
                self._balao(aviso, True)
            elif not getattr(aviso, "_espera_id", None):
                def depois(a=aviso):
                    a._espera_id = None
                    if a.winfo_exists():
                        self._pintar_aviso_apps()
                aviso._espera_id = self.after(int(falta * 1000) + 10, depois)
        elif not texto and aviso.winfo_manager() and \
                not getattr(aviso, "_sumindo", False):
            self._balao(aviso, False)
        if texto and cor == E.ERRO:
            if getattr(self, "_aviso_apps_id", None):
                self.after_cancel(self._aviso_apps_id)
            self._aviso_apps_id = self.after(
                8000, lambda: aviso.winfo_exists() and
                self._balao(aviso, False))

    def _balao(self, aviso, mostrar: bool) -> None:
        """(07/out, padrao de animacao) O balao de baixo SOBE do rodape ao
        aparecer (como o snackbar do Android) e desce ao sumir."""
        fora, dentro = E.px(36), -E.px(4)
        aviso._sumindo = not mostrar
        if mostrar:
            if not aviso.winfo_manager():
                aviso.place(relx=0.5, rely=1.0, y=fora, anchor="s")
            aviso.lift()
            # o recorte JA no tamanho certo antes de subir (escondido la
            # embaixo): nunca aparece quadrado
            aviso.update_idletasks()
            E.recorte_redondo(aviso, raio=E.px(9))
        try:
            de = int(float(aviso.place_info().get("y", dentro)))
        except (tk.TclError, ValueError):
            de = fora if mostrar else dentro
        alvo = dentro if mostrar else fora

        def repintar_onde_estava():
            # (07/out, gravado: descendo, o balao deixava um RASTRO -- a
            # lista embaixo nao se repintava na faixa que ele descobria)
            if not moldura.NO_WINDOWS:
                return
            try:
                import ctypes
                from ctypes import wintypes
                pai = aviso.master
                r = wintypes.RECT(aviso.winfo_x() - 2, aviso.winfo_y() - 2,
                                  aviso.winfo_x() + aviso.winfo_width() + 2,
                                  aviso.winfo_y() + aviso.winfo_height() + 2)
                # INVALIDATE | ERASE | ALLCHILDREN | UPDATENOW
                ctypes.windll.user32.RedrawWindow(
                    pai.winfo_id(), ctypes.byref(r), None,
                    0x1 | 0x4 | 0x80 | 0x100)
            except Exception:
                pass

        def a_cada(k):
            if not mostrar:
                repintar_onde_estava()
            aviso.place_configure(y=round(de + (alvo - de) * k))

        def fim():
            if not mostrar:
                repintar_onde_estava()
                aviso._sumindo = False
                aviso.place_forget()
        mov.animar(aviso, "balao", mov.MS_POPUP_ENTRA if mostrar
                   else mov.MS_POPUP_SAI, a_cada, fim,
                   curva=mov.ENTRADA if mostrar else mov.SAIDA)

    # -- CARTAO DE LINHA (07/out, pedido dele: "padronizar camadas e bordas")
    # Toda linha clicavel de lista e um cartao da CAMADA 1 (sobre o fundo),
    # de canto redondo, com a borda que clareia com o mouse em cima -- o
    # mesmo das notificacoes. `borda` = cor de estado (laranja = aberto,
    # vermelho = erro), que o mouse nao muda.

    def _cartao(self, pai, borda: str | None = None, foco: bool = False,
                fundo: str | None = None) -> tk.Frame:
        linha = tk.Frame(pai, bg=fundo or E.CAMADA_1, highlightthickness=1,
                         highlightbackground=borda or E.BORDA_1,
                         highlightcolor=E.FOCO, cursor="hand2",
                         takefocus=1 if foco else 0)
        linha._borda = borda or E.BORDA_1
        linha._sobre = None if borda else E.BORDA_1_SOBRE
        E.cantos(linha)
        return linha

    def _pintar_cartao(self, linha, sobre: bool = False) -> None:
        """`_borda` = a cor parada; `_sobre` = a do mouse (None = nao muda)."""
        try:
            cor = getattr(linha, "_borda", E.BORDA_1)
            if sobre and getattr(linha, "_sobre", None):
                cor = linha._sobre
            if linha.cget("highlightbackground") != cor or \
                    getattr(linha, "_cantos", None) is None:
                linha.configure(highlightbackground=cor)
                E.cantos(linha)
        except tk.TclError:
            pass

    def _cartao_vivo(self, linha, pecas) -> None:
        """Mouse em cima de qualquer peca = o cartao acende; so apaga quando
        o ponteiro sai do cartao inteiro (passar do nome para o icone nao
        pisca)."""
        def saiu(_e=None):
            try:
                x, y = self.winfo_pointerxy()
                alvo = self.winfo_containing(x, y)
                if alvo is not None and str(alvo).startswith(str(linha)):
                    return
            except (tk.TclError, KeyError):
                pass
            self._pintar_cartao(linha, False)
        for p in pecas:
            p.bind("<Enter>", lambda _e: self._pintar_cartao(linha, True),
                   add="+")
            p.bind("<Leave>", saiu, add="+")

    def _realce_pilula(self, linha, pecas, fundo: str = E.FUNDO,
                       realce: str = E.CAMADA_1) -> None:
        """(07/out) Linha de lista simples (sem borda): com o mouse, o fundo
        vira uma pilula da camada de cima, como os itens do menu."""
        def pintar(cor):
            for p in pecas:
                try:
                    p.configure(bg=cor)
                except tk.TclError:
                    pass
            E.cantos(linha, raio=E.px(5))

        def saiu(_e=None):
            try:
                x, y = self.winfo_pointerxy()
                alvo = self.winfo_containing(x, y)
                if alvo is not None and str(alvo).startswith(str(linha)):
                    return
            except (tk.TclError, KeyError):
                pass
            pintar(fundo)
        for p in pecas:
            p.bind("<Enter>", lambda _e: pintar(realce), add="+")
            p.bind("<Leave>", saiu, add="+")

    def _x_de_tirar(self, pai, fundo: str, acao) -> tk.Label:
        """(07/out) O "x" de tirar/fechar e o icone de linha da casa (o
        mesmo da barra de busca), nao a letra ×."""
        return self._botao_icone(pai, "x", E.px(18), fundo, acao,
                                 cor=E.APAGADO)

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

        # (07/out) o realce do mouse e o do cartao da casa: borda clara, de
        # canto redondo (era uma moldura quadrada)
        def entrar(_e=None):
            if borda is not None and not aberto:
                self._pintar_cartao(borda, True)

        def sair(_e=None):
            if borda is None or aberto:
                return
            try:
                x, y = self.winfo_pointerxy()
                alvo = self.winfo_containing(x, y)
                if alvo is not None and str(alvo).startswith(str(borda)):
                    return
            except (tk.TclError, KeyError):
                pass
            self._pintar_cartao(borda, False)

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
        marcas = self.__dict__.setdefault("_fotos_marca", {})
        if pacote not in marcas:
            marcas[pacote] = self._marca_do_icone(arquivo)
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

    @staticmethod
    def _marca_do_icone(arquivo):
        """(hora, tamanho) do arquivo do icone, ou None se nao existe."""
        try:
            s = arquivo.stat()
            return (s.st_mtime_ns, s.st_size)
        except OSError:
            return None

    def _icone_app(self, pai, pacote: str, nome: str, lado: int,
                   fundo: str | None = None) -> tk.Canvas:
        """
        O icone de verdade; sem ele -- ou com os icones desligados em APPS >
        aparencia (pedido dele, 23/set/2026) -- a inicial num quadrado de
        canto redondo (07/out). `fundo` = a camada onde ele esta.
        """
        fundo = fundo or E.FUNDO
        c = tk.Canvas(pai, width=lado, height=lado, bg=fundo,
                      highlightthickness=0, bd=0)
        foto = None if self._config.apps.get("sem_icones") else \
            self._foto(pacote, lado)
        if foto is not None:
            c.create_image(lado // 2, lado // 2, image=foto)
            return c
        cor = CORES_DE_APP[sum(map(ord, pacote)) % len(CORES_DE_APP)]
        quadro = E.imagem_redonda(lado, cor, fundo, max(2, lado // 5))
        if quadro is not None:
            c._quadro = quadro
            c.create_image(0, 0, anchor="nw", image=quadro)
        else:
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
        # (03/out) a barra de busca: o total na dica e o "3 de 87" filtrando
        busca = self._ui.get("busca_apps")
        if busca is not None and busca.winfo_exists():
            total = len([a for a in (self._apps or []) if a[1] != DEX])
            dica = "buscar"
            if busca._dica.cget("text") != dica:
                busca._dica.configure(text=dica)
            self._contar_busca(busca, len([a for a in itens if a[1] != DEX]),
                               total)
        abertos = frozenset(p.apps_abertos())
        subindo = frozenset(a[1] for a in itens if p.app_subindo(a[1]))
        visual = geral.get("visual", "grade")
        colunas, medidas = self._grade_dos_apps(rol, self._medidas_dos_apps())
        # FIXADOS · RECENTES · TODOS (pedido dele, 23/set/2026), como a tela
        # inicial do celular: fixados na ordem em que ele fixou; recentes =
        # os ultimos abertos, sem repetir fixado; todos = a gaveta inteira.
        fixados = tuple(self._config.fixados())
        recentes = tuple(x for x in self._config.recentes()
                         if x not in fixados)[:APPS_RECENTES]
        # (07/out, gravado na abertura com APPS: a lista sumia e voltava duas
        # vezes) "lendo"/erro so mudam o que se ve com a lista VAZIA; com
        # apps na tela, quem fala e o balao -- nao refaz a grade.
        com_apps = bool(self._apps)
        base = (self._apps is None,
                None if com_apps else self._apps_carregando,
                None if com_apps else self._apps_erro,
                tuple(a[1] for a in itens), visual, medidas, colunas,
                self._icones_versao, fixados, recentes)
        estado = (abertos, subindo)
        antes = self._apps_pintado
        if antes == (base, estado):
            return
        arr = self._ui.get("arranjo_apps")
        if arr is None:
            return
        sem_lotes = str(rol.canvas) not in getattr(self, "_lotes_de", ())
        meta = self._ui.setdefault("meta_apps", {})   # chave -> (nome, ctx)
        # (02/out, revisao) SO OS ICONES CHEGARAM: cada bloco e refeito no
        # lugar, sem esvaziar a grade (antes ela sumia e voltava em lotes e
        # a rolagem pulava para o topo).
        if antes is not None and meta and sem_lotes and \
                antes[1] == estado and antes[0][7] != base[7] and \
                antes[0][:7] == base[:7] and antes[0][8:] == base[8:]:
            self._apps_pintado = (base, estado)
            mudaram = getattr(self, "_icones_mudaram", None)
            for chave in list(meta):
                if mudaram is None or chave[1] in mudaram:
                    self._refazer_bloco(chave, abertos, subindo)
            return
        # (na "lista" um app aberto e uma linha mais alta: abrir/fechar
        # refaz o layout, com as de baixo andando -- o caminho do filtro)
        if antes is not None and antes[0] == base and meta and sem_lotes \
                and (visual != "lista" or antes[1][0] == abertos):
            mudou = (antes[1][0] ^ abertos) | (antes[1][1] ^ subindo)
            self._apps_pintado = (base, estado)
            for chave in list(meta):
                if chave[1] in mudou:
                    self._refazer_bloco(chave, abertos, subindo)
            return
        # (09/out, pedido dele: "a lista pisca atualizando") so a BUSCA (ou
        # fixados/recentes) mudou e a grade esta inteira: o FILTRO ANIMADO
        # -- o que sai esmaece, o resto anda ate o lugar novo. Mudou a busca
        # = a lista volta ao topo (como a gaveta do Android).
        filtrar = (antes is not None and sem_lotes and meta and
                   antes[0][:3] == base[:3] and antes[0][4:8] == base[4:8])
        busca_mudou = antes is None or antes[0][3] != base[3]
        self._apps_pintado = (base, estado)
        ctx = (visual, colunas, medidas)
        if not filtrar:
            arr.esvaziar()
            meta.clear()
            for filho in rol.dentro.winfo_children():   # o que nao e dele
                filho.destroy()
        layout, nomes = self._layout_apps(rol, itens, fixados, recentes,
                                          ctx)

        def criar(chave):
            if chave[0] == "_msg":
                return E.Texto(rol.dentro, chave[1], cor=chave[2],
                               largura=E.px(420))
            if chave[0] == "_h":
                return E.Rotulo(rol.dentro, chave[1])
            nome = nomes[chave]
            meta[chave] = (nome, ctx)
            return self._montar_bloco(rol.dentro, nome, chave[1], abertos,
                                      subindo, ctx)

        for chave in [c for c in meta if c not in nomes]:
            meta.pop(chave, None)
        for chave, nome in nomes.items():     # (reaproveitados nao passam
            meta[chave] = (nome, ctx)         # pelo criar)
        # mudou a busca = a lista volta ao topo (por baixo da copia, junto)
        adiadas = arr.aplicar(layout, criar, animar=bool(filtrar),
                              adiar=True,
                              topo=busca_mudou and antes is not None)
        # abriu/fechou junto com a busca: os que ficaram sao postos em dia
        if filtrar:
            mudou = (antes[1][0] ^ abertos) | (antes[1][1] ^ subindo)
            for chave in list(meta):
                if chave[1] in mudou and arr.tem(chave):
                    self._refazer_bloco(chave, abertos, subindo)
        if adiadas:
            # o que entra fora da vista chega em lotes, sem travar
            def fazer(chave):
                arr.criar_adiado(chave, criar)
            self._em_lotes(rol.canvas, adiadas, fazer, primeiro=0)

    def _layout_apps(self, rol, itens, fixados, recentes, ctx):
        """(09/out) As posicoes da grade (ou lista) de APPS para o
        `Arranjo`: [(chave, x, y, larg, alt)] e {chave: nome}. Chaves:
        (grupo, pacote) nos blocos, ("_h", grupo) nos titulos, ("_msg",
        texto, cor) no aviso de lista vazia."""
        visual, colunas, medidas = ctx
        if not self._apps or not itens:
            if not self._apps:
                if self._apps_carregando:
                    texto, cor = "lendo os apps do celular…", E.APAGADO
                elif self._apps_erro:
                    texto, cor = "✗  " + self._apps_erro, E.ERRO
                else:
                    texto, cor = ("nenhum app lido ainda. clique em "
                                  "atualizar.", E.APAGADO)
            else:
                texto, cor = "nenhum app com esse nome.", E.APAGADO
            return [(("_msg", texto, cor), 0, 0, None, None)], {}
        por_pacote = {a[1]: a for a in itens}
        grupos = [("fixados", [por_pacote[x] for x in fixados
                               if x in por_pacote]),
                  ("recentes", [por_pacote[x] for x in recentes
                                if x in por_pacote]),
                  ("todos os apps", itens)]
        cheios = [(titulo, lista) for titulo, lista in grupos if lista]
        lado, altura = medidas[0], medidas[1]
        largura = self._largura_dos_apps(rol)
        x0 = max(0, (largura - colunas * lado) // 2)
        alt_titulo = self._altura_titulo_apps()
        alt_linha = self._altura_linha_apps(rol, medidas) \
            if visual == "lista" else (0, 0)
        abertos = frozenset(self.programa.apps_abertos())
        layout, nomes = [], {}
        y = 0
        for i, (titulo, lista) in enumerate(cheios):
            if len(cheios) > 1:
                y += 0 if i == 0 else E.px(10)
                layout.append((("_h", titulo), 0, y, None, alt_titulo))
                y += alt_titulo + E.px(4)
            for k, (nome, pacote, _sis) in enumerate(lista):
                chave = (titulo, pacote)
                nomes[chave] = nome
                if visual == "lista":
                    a = alt_linha[1 if pacote in abertos else 0]
                    layout.append((chave, 0, y, None, a))
                    y += a + E.px(3)
                else:
                    layout.append((chave, x0 + (k % colunas) * lado,
                                   y + (k // colunas) * (altura + E.px(2)),
                                   lado, altura))
            if visual != "lista":
                fileiras = (len(lista) + colunas - 1) // colunas
                y += fileiras * (altura + E.px(2))
        return layout, nomes

    def _altura_titulo_apps(self) -> int:
        alt = getattr(self, "_alt_titulo_apps", 0)
        if not alt:
            r = E.Rotulo(self, "x")
            r.update_idletasks()
            alt = self._alt_titulo_apps = r.winfo_reqheight()
            r.destroy()
        return alt

    def _altura_linha_apps(self, rol, medidas) -> tuple:
        """A linha da lista (visual "lista"): (altura comum, altura de um
        app aberto, com o "fechar"), medidas uma vez."""
        cache = self.__dict__.setdefault("_alt_linhas_apps", {})
        if medidas not in cache:
            alts = []
            for aberto in (False, True):
                w = self._linha_de_app(rol.dentro, "x", "x.medida", aberto,
                                       False, medidas)
                w.update_idletasks()
                alts.append(w.winfo_reqheight())
                FA.destruir(w)
            cache[medidas] = (alts[0], max(alts))
        return cache[medidas]

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
        # (03/out) o bloco MINIMO acompanha o icone de verdade (antes a
        # folga fixa de 40 deixava quase o mesmo numero de colunas); a
        # sobra da largura se divide entre eles (`_grade_dos_apps`).
        lado = icone + max(E.px(24), int(icone * 0.9))
        altura = icone + E.px(36)
        return (lado, altura, icone, na_lista, com)

    def _largura_dos_apps(self, rol) -> int:
        largura = rol.largura_util()
        if largura < E.px(60):
            largura = self._area.winfo_width() - 2 * E.PADDING - E.px(14)
        if largura < E.px(60):
            largura = E.LARGURA - E.LARGURA_LISTA - E.px(50)
        return largura

    def _colunas_de_apps(self, rol, lado: int) -> int:
        return max(1, self._largura_dos_apps(rol) // lado)

    def _grade_dos_apps(self, rol, medidas: tuple) -> tuple:
        """
        (03/out, relato dele: o tamanho mudava os icones mas eles ficavam
        no mesmo lugar, e sobrava uma faixa a direita) As colunas saem do
        tamanho escolhido (o bloco MINIMO) e o bloco se ESTICA para a grade
        ocupar a largura inteira: icone maior = menos colunas, mais
        espacadas; menor = mais colunas. Devolve (colunas, medidas com a
        largura de verdade do bloco).
        """
        largura = self._largura_dos_apps(rol)
        colunas = max(1, largura // medidas[0])
        lado = max(medidas[0], largura // colunas)
        return colunas, (lado,) + tuple(medidas[1:])

    def _montar_bloco(self, pai, nome, pacote, abertos, subindo, ctx):
        """Um app da lista (sem posicao: o `Arranjo` o poe no lugar)."""
        visual, _colunas, medidas = ctx
        if visual == "lista":
            return self._linha_de_app(pai, nome, pacote, pacote in abertos,
                                      pacote in subindo, medidas)
        return self._bloco_de_app(pai, nome, pacote, pacote in abertos,
                                  pacote in subindo, medidas)

    def _refazer_bloco(self, chave, abertos, subindo) -> None:
        """Refaz UM bloco no mesmo lugar (abriu/fechou o app)."""
        arr = self._ui.get("arranjo_apps")
        info = (self._ui.get("meta_apps") or {}).get(chave)
        if arr is None or info is None or not arr.tem(chave):
            return
        nome, ctx = info
        try:
            novo = self._montar_bloco(arr.pai, nome, chave[1], abertos,
                                      subindo, ctx)
        except tk.TclError:
            return
        arr.trocar(chave, novo)

    def _em_lotes(self, dono, trabalhos, fazer, primeiro: int = 28,
                  lote: int = 10, ao_fim=None) -> None:
        # (07/out, varredura) lote de 10 (era 24): cada um para o Tk ~50 ms
        # e nao ~150 -- o clique e o mouse por cima respondem no meio
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
            # (07/out, varredura) com o veu andando, o lote espera: montar
            # no meio da animacao fazia os quadros dela pularem
            if getattr(self, "_veu", None) is not None or \
                    getattr(self, "_veu_abas", None) is not None or \
                    FA.animando():
                self.after(40, proximo)
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
                # (07/out, medido) 15 ms e nao 1: com um relogio sempre
                # vencido o Tk nunca chega a vez das tarefas de folga, e a
                # medida de TODOS os lotes ficava para o fim (~1 s parado).
                self.after(15, proximo)
            else:
                pendentes.discard(chave)
                if ao_fim is not None:
                    ao_fim()

        if resto:
            self.after(15, proximo)
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
        # (07/out) o realce e a borda de canto redondo (os cantinhos so
        # nascem no 1o realce: parado, a borda e da cor do fundo)
        bloco._borda = E.ACENTO if aberto else E.FUNDO
        bloco._sobre = None if aberto else E.SOBRE_BORDA
        if aberto:
            E.cantos(bloco)
        pecas = [bloco]
        texto = "abrindo…" if subindo else nome
        cor = E.ACENTO if aberto else E.TEXTO_2
        if com:
            icone = self._icone_app(bloco, pacote, nome, icone_px)
            icone.configure(cursor="hand2")
            icone.pack(side="top", pady=(E.px(7), E.px(3)))
            pecas.append(icone)
            # (08/out, pedido dele: mais letras no nome) cortado pela LARGURA
            # de verdade (a letra nao e mais mono: contar pelo "M" deixava 6
            # letras); usa o bloco todo, quase de borda a borda
            rotulo_txt = self._uma_linha(texto, E.fonte(E.ROTULO),
                                         lado - E.px(4))
            # (09/out, check-interface: 4 nomes cortados 2-3 px) sem a folga
            # interna do Label (padx/bd), que somava ao texto ja medido
            rotulo = tk.Label(bloco, text=rotulo_txt, bg=E.FUNDO,
                              fg=cor, font=E.fonte(E.ROTULO), cursor="hand2",
                              padx=0, bd=0)
            rotulo.pack(side="top")
        else:
            rotulo = tk.Label(bloco, text=texto, bg=E.FUNDO, fg=cor,
                              font=E.fonte(E.ROTULO), cursor="hand2",
                              wraplength=lado - E.px(8), justify="center")
            rotulo.pack(expand=True)
        pecas.append(rotulo)
        self._ligar_cliques(pecas, pacote, nome, bloco, aberto)
        if aberto:
            # (08/out, pedido dele: "um quadrado da cor de fundo ao redor" --
            # o botao encostava no icone e cortava o canto dele) O x mora no
            # CANTO LIVRE do bloco, do tamanho que cabe ao lado do icone (nunca
            # encosta nele), desenhado ja sobre a cor do fundo: vermelho com um
            # brilho leve em volta, sem clarear o traco.
            livre = (lado - (icone_px if com else 0)) // 2 - E.px(2)
            caixa = max(E.px(12), min(E.px(20), livre))
            fechar = self._x_vermelho(bloco, caixa,
                                      lambda: self._fechar_app(pacote))
            # (08/out, relato: "bolinha preta na perna de cima" -- o
            # cantinho redondo da borda e uma peca POR CIMA do bloco e
            # cortava o brilho da ponta do x) o x comeca logo ABAIXO dele
            fechar.place(relx=1.0, x=-E.px(1), y=E.RAIO, anchor="ne")
        return bloco

    _X_FOTOS: dict = {}

    def _foto_x_vermelho(self, caixa: int, fundo: str):
        """O x de fechar numa imagem `caixa` x `caixa` ja sobre `fundo`
        (sem transparencia: nada de quadrado de outra cor): traco vermelho de
        ponta redonda e um brilho vermelho LEVE em volta."""
        chave = (caixa, fundo)
        if chave in self._X_FOTOS:
            return self._X_FOTOS[chave]
        from PIL import Image, ImageDraw, ImageFilter, ImageTk
        k = 4
        n = caixa * k
        folga = caixa * 0.20                     # espaco do brilho
        a, b = folga * k, (caixa - folga) * k
        traco = max(2.0, caixa * 0.15) * k

        mascara = Image.new("L", (n, n), 0)
        d = ImageDraw.Draw(mascara)
        for p, q in (((a, a), (b, b)), ((b, a), (a, b))):
            d.line([p, q], fill=255, width=int(round(traco)))
            for cx, cy in (p, q):
                r = traco / 2.0
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
        brilho = mascara.filter(ImageFilter.GaussianBlur(folga * k * 0.45))
        img = Image.new("RGB", (n, n), fundo)
        tinta = Image.new("RGB", (n, n), E.ERRO)
        img.paste(tinta, (0, 0), brilho.point(lambda v: int(v * 0.35)))
        img.paste(tinta, (0, 0), mascara)
        img = img.resize((caixa, caixa), Image.BOX)
        foto = ImageTk.PhotoImage(img, master=self)
        self._X_FOTOS[chave] = foto
        return foto

    def _x_vermelho(self, pai, caixa: int, acao) -> tk.Label:
        b = tk.Label(pai, bd=0, highlightthickness=0, bg=E.FUNDO,
                     cursor="hand2", takefocus=1,
                     image=self._foto_x_vermelho(caixa, E.FUNDO))
        for ev in ("<Button-1>", "<Return>", "<space>"):
            b.bind(ev, lambda _e: (acao(), "break")[1])
        return b

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
        linha = self._cartao(pai, borda=E.ACENTO if aberto else None)
        # (09/out) sem pack: o `Arranjo` poe a linha no lugar (place)
        pecas = [linha]
        if com:
            icone = self._icone_app(linha, pacote, nome, icone_px,
                                    fundo=E.CAMADA_1)
            icone.configure(cursor="hand2")
            icone.pack(side="left", padx=E.px(6), pady=E.px(3))
            pecas.append(icone)
        if aberto:
            E.Botao(linha, "fechar", lambda: self._fechar_app(pacote),
                    tipo="contorno", bg=E.CAMADA_1).pack(
                side="right", padx=E.px(4), pady=E.px(2))
        # (08/out) o melhor modo reconheceu como jogo: marca discreta
        from . import melhor_modo
        if pacote != DEX and self.programa.melhor_auto() and \
                melhor_modo.tipo_do_app(pacote.split(COPIA)[0],
                                        self.programa.sinais_dos_apps().get(
                                            pacote.split(COPIA)[0]))[0] == \
                melhor_modo.JOGO:
            marca = tk.Label(linha, text="JOGO", bg=E.CAMADA_1, fg=E.APAGADO,
                             font=E.fonte(E.ROTULO), cursor="hand2")
            marca.pack(side="right", padx=E.px(8))
            pecas.append(marca)
        rotulo = tk.Label(linha, text=("abrindo…  " if subindo else "")
                          + nome[:40], bg=E.CAMADA_1,
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
        if getattr(self, "_menu_app", None) is not None:
            self._fechar_menu_app()      # (03/out) rolar fecha o menu aberto
        try:
            alvo = self.winfo_containing(evento.x_root, evento.y_root)
        except Exception:
            return None
        if alvo is None:
            return None
        for chave in ("rolagem_apps", "rolagem_atalhos", "rolagem_escolha",
                      "rolagem_editor", "rolagem_pers", "rolagem_geral",
                      "rolagem_notif", "rolagem_qualidade"):
            rol = self._ui.get(chave)
            if rol is not None and rol.canvas.winfo_exists() and \
                    str(alvo).startswith(str(rol.canvas)):
                return rol.roda(evento)
        return None

    # -- APPS > aparencia ------------------------------------------------------

    # (07/out, rework pedido dele: "so as configuracoes que fazem sentido em
    # cada menu, por importancia") A esquerda o que muda a JANELA do app
    # (o modo, o mais importante); a direita o comportamento (som, fechar) e,
    # por ultimo, o visual da lista.
    def _tela_apps_aparencia(self, area) -> None:
        # (08/out, rework) O modo, a resolucao e o som da janela foram para
        # OPCOES > qualidade (e para o personalizado de cada app); aqui fica
        # o comportamento: onde o som toca e ao fechar (esq.) e a lista (dir.)
        col_esq, col_dir = self._duas(area)
        geral = self._config.apps
        # (08/out, pedido dele: juntar por assunto) a JANELA DOS APPS num
        # painel so: onde o som toca e o que acontece ao fechar
        esq = self._seg(col_esq, "janela dos apps")
        caixa_som = tk.Frame(esq, bg=E.FUNDO)
        caixa_som.pack(side="top", fill="x")
        caixa_som._painel = caixa_som
        self._sub(caixa_som, "onde o som toca", primeiro=True)
        E.Segmentado(caixa_som, self._opcoes_de_onde(),
                     geral.get("onde", "celular"),
                     lambda v: self._virar_apps(
                         "onde", "" if v == "celular" else v)).pack(
            side="top", fill="x")
        E.Texto(caixa_som, "o som é o do celular inteiro: o android não "
                           "separa por app.",
                cor=E.APAGADO, tamanho=E.ROTULO, largura=E.px(230)).pack(
            side="top", fill="x", pady=(E.px(4), E.px(0)))
        if self._falta("som"):
            self._cortina(caixa_som._painel, "som", "som do celular no pc",
                          curta=True)
        # AO FECHAR A JANELA (24/set/2026): fecha o app no celular (como
        # tirar dos recentes; as notificacoes continuam) ou deixa aberto.
        self._sub(esq, "ao fechar a janela")
        E.Segmentado(esq, AO_FECHAR, geral.get("ao_fechar", "fechar"),
                     lambda v: self._virar_apps(
                         "ao_fechar", "" if v == "fechar" else v)).pack(
            side="top", fill="x")
        # A LISTA (so visual): duas fileiras; "sem" icone virou opcao do
        # tamanho (era uma chave a parte).
        dir_ = self._seg(col_dir, "lista de apps")
        self._fila(dir_, "mostrar", [("grade", "grade"), ("lista", "lista")],
                   geral.get("visual", "grade"),
                   lambda v: self._virar_apps("visual", v),
                   espaco=4, nome_larg=8)
        icones = "sem" if geral.get("sem_icones") else \
            geral.get("tamanho", "m")
        self._fila(dir_, "ícones", [("sem", "sem"), ("p", "pequeno"),
                                    ("m", "médio"), ("g", "grande")], icones,
                   self._escolheu_icones, espaco=0, nome_larg=8)
        # o que vale para tudo: a nota no pe da coluna, fora dos paineis
        E.Texto(col_dir, "imagem, som e o modo pc / tablet de todos os apps: "
                         "opções › qualidade. de um app só: personalizados.",
                cor=E.APAGADO, tamanho=E.ROTULO, largura=E.px(250)).pack(
            side="top", fill="x", pady=(E.px(10), E.px(0)))

    def _escolheu_icones(self, v: str) -> None:
        if v == "sem":
            self._virar_apps("sem_icones", True)
            return
        if self._config.apps.get("sem_icones"):
            self._config.apps.pop("sem_icones", None)
        self._virar_apps("tamanho", "" if v == "m" else v)

    # (08/out, pedido dele) O VERIFICADOR: "tipo um botao de procurar
    # atualizacoes, clica e espera ele verificar". Le de cada app a tabela
    # de telas (analise_app.py) -- nada e baixado, nao precisa de admin.
    # (08/out, pedido dele) AUTOMATICA: comeca sozinha ao conectar (o que
    # falta) e fica guardada. Na tela, so a legenda viva da linha "janela
    # dos apps" e o link "verificar de novo" (le tudo outra vez).
    def _bloco_analise(self, esq, texto) -> None:
        link = self._link(esq, "verificar de novo", self._clicou_analise)
        link.configure(font=E.fonte_ui(E.ROTULO), bg=esq.cget("bg"),
                       highlightbackground=esq.cget("bg"))
        E.cantos(link, raio=E.px(4))
        link.pack(side="top", anchor="w", pady=(E.px(4), 0))
        self._ui["analise"] = (texto, link)
        self._pintar_analise()

    def _clicou_analise(self) -> None:
        p = self.programa
        estado = p.analise_estado
        if estado is not None and not estado.get("fim"):
            p.cancelar_analise()
        elif not p.analisar_apps():
            self._ui_analise_recado = "conecte o celular e espere a lista " \
                                      "de apps."
        self._pintar_analise()

    def _pintar_analise(self) -> None:
        par = self._ui.get("analise")
        if not par or not par[0].winfo_exists():
            return
        texto, botao = par
        p = self.programa
        estado = p.analise_estado
        dados = {k: v for k, v in p.interface_dos_apps().items()
                 if not k.startswith("_")}
        rodando = estado is not None and not estado.get("fim")
        if rodando:
            t = "verificando os apps: %d de %d." % (
                min(estado["feitos"] + 1, max(1, estado["total"])),
                max(1, estado["total"]))
            cor = E.TEXTO_2
        elif getattr(self, "_ui_analise_recado", ""):
            t, cor = self._ui_analise_recado, E.ALERTA
            self._ui_analise_recado = ""
        elif dados:
            from . import analise_app
            n = sum(1 for v in dados.values()
                    if v.get("resultado") == analise_app.TABLET)
            t = "%d de %d apps têm tela de tablet." % (n, len(dados))
            cor = E.APAGADO
        else:
            t, cor = "verifica sozinho ao conectar o celular.", E.APAGADO
        if texto.cget("text") != t or texto.cget("fg") != cor:
            texto.configure(text=t, fg=cor)
        rotulo = "cancelar" if rodando else "verificar de novo"
        if botao.cget("text") != rotulo:
            botao.configure(text=rotulo)
        if rodando or (estado is not None and estado.get("fim") and
                       not getattr(self, "_analise_vista", False)):
            if estado is not None and estado.get("fim"):
                # acabou: as telas guardadas que mostram o modo se refazem
                self._analise_vista = True
                self._agendar_renovar()
            else:
                self._analise_vista = False
            self.after(400, self._pintar_analise)

    def _linha_orientacao(self, pai, pacote) -> None:
        """O que o programa ja reconheceu (deitado) e o "reconhecer de
        novo" (o modo pc decide sozinho; isto so esquece o que viu)."""
        orient = self._config.apps.get("orientacao") or {}
        if pacote:
            sabido = orient.get(pacote)
            if not sabido:
                return
            texto = "reconhecido: abre %s" % (
                "deitado" if sabido == "deitado" else "em pé")
        else:
            deitados = [p for p, v in orient.items() if v == "deitado"]
            if not deitados:
                return
            texto = "deitados: %d app%s" % (len(deitados),
                                            "s" if len(deitados) > 1 else "")
        linha = tk.Frame(pai, bg=E.FUNDO)
        linha.pack(side="top", fill="x", pady=(E.px(8), E.px(0)))
        tk.Label(linha, text=texto, bg=E.FUNDO, fg=E.TEXTO_2,
                 font=E.fonte(E.ROTULO)).pack(side="left")
        tk.Label(linha, text="  ·  ", bg=E.FUNDO, fg=E.APAGADO,
                 font=E.fonte(E.ROTULO)).pack(side="left")
        lk = self._link(linha, "reconhecer de novo",
                        lambda: self._esquecer_orientacao(pacote))
        lk.configure(font=E.fonte(E.ROTULO))
        lk.pack(side="left")

    def _esquecer_orientacao(self, pacote) -> None:
        orient = self._config.apps.get("orientacao") or {}
        tirar = [pacote] if pacote else list(orient)
        for p in tirar:
            orient.pop(p, None)
        if not orient:
            self._config.apps.pop("orientacao", None)
        self._conferir_gravacao(self._config.gravar())
        self.programa.anotar("orientacao esquecida: %s" % (pacote or "todos"))
        self._agendar_reabrir({p for p in tirar
                               if p in self.programa.apps_abertos()})
        self._remontar_quieto()


    def _linha_de_atalho_livre(self, pai, acao: str, app, recusado: bool):
        """Uma acao que pode ganhar atalho: nome, as teclas (ou "clique para
        definir") e um x para tirar. Clique na linha = gravar."""
        teclas = self._config.atalhos.get(acao, "")
        erro = recusado and bool(teclas)
        linha = self._cartao(pai, borda=E.ERRO if erro else None)
        # (09/out) sem pack: o `Arranjo` dos atalhos a poe no lugar
        pecas = [linha]
        if app is not None:
            icone = self._icone_app(linha, app[0], app[1], E.px(16),
                                    fundo=E.CAMADA_1)
            icone.configure(cursor="hand2")
            icone.pack(side="left", padx=(E.px(8), E.px(0)))
            pecas.append(icone)
        rotulo = tk.Label(linha, text=atalhos_mod.rotulo(acao),
                          bg=E.CAMADA_1, fg=E.TEXTO, font=E.fonte(E.PEQUENA),
                          anchor="w", cursor="hand2")
        rotulo.pack(side="left", padx=(E.px(8), E.px(0)), pady=E.px(6))
        pecas.append(rotulo)
        if teclas:
            self._x_de_tirar(linha, E.CAMADA_1,
                             lambda: self._tirar_atalho(acao)).pack(
                side="right", padx=(E.px(2), E.px(6)))
        teclas_rot = tk.Label(
            linha, text=teclas.replace("+", " + ").upper() if teclas
            else "clique para definir", bg=E.CAMADA_1,
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
        self._cartao_vivo(linha, pecas)
        return linha

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
            tk.Label(cabeca, text="escolha o app", bg=E.FUNDO, fg=E.TEXTO,
                     font=E.fonte(E.CORPO, "bold"), anchor="w").pack(
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
            linha = self._cartao(rol.dentro)
            linha.pack(side="top", fill="x", pady=(E.px(0), E.px(3)))
            ic = self._icone_app(linha, pacote, nome, E.px(20),
                                 fundo=E.CAMADA_1)
            ic.configure(cursor="hand2")
            ic.pack(side="left", padx=E.px(6), pady=E.px(4))
            rot = tk.Label(linha, text=nome[:40], bg=E.CAMADA_1,
                           fg=E.TEXTO, font=E.fonte(E.PEQUENA), anchor="w",
                           cursor="hand2")
            rot.pack(side="left", fill="x", expand=True)
            # (08/out, pedido dele) o x da linha tira o ajuste deste app
            self._x_de_tirar(linha, E.CAMADA_1,
                             lambda p=pacote: self._limpar_personalizado(p)
                             ).pack(side="right", padx=(E.px(2), E.px(6)))
            resumo = tk.Label(linha, text=self._resumo_do_app(conf),
                              bg=E.CAMADA_1, fg=E.TEXTO_2,
                              font=E.fonte(E.ROTULO), cursor="hand2")
            resumo.pack(side="right", padx=(E.px(8), E.px(2)))
            for peca in (linha, ic, rot, resumo):
                peca.bind("<Button-1>", lambda _e, p=pacote, n=nome: (
                    self._editar_personalizado(p, n)))
                # (07/out) o botao direito tambem tem o menu do app
                peca.bind("<Button-3>", lambda e, p=pacote, n=nome: (
                    self._clique_em_qualquer_lugar(e),
                    self._menu_do_app(e, p, n), "break")[2])
            self._cartao_vivo(linha, (linha, ic, rot, resumo))

    def _resumo_do_app(self, conf: dict) -> str:
        """O que o app tem de proprio, em poucas palavras."""
        partes = []
        # (08/out, rework) so o que existe agora: nivel, som, modo
        if qualidade.nivel_valido(conf.get("nivel")):
            partes.append("%dp" % qualidade.P_DO_NIVEL[conf["nivel"]])
        if qualidade.som_valido(conf.get("som")):
            partes.append("som " + conf["som"])
        if conf.get("modo"):
            partes.append({"pc": "pc / tablet"}.get(conf["modo"],
                                                   conf["modo"]))
        if conf.get("escala"):
            partes.append("tamanho " + dict(OPCOES_ESCALA).get(
                conf["escala"], ""))
        if conf.get("onde"):
            partes.append("toca: " + dict(qualidade.ONDE).get(conf["onde"], ""))
        if conf.get("ao_fechar"):
            partes.append(dict(AO_FECHAR).get(conf["ao_fechar"], ""))
        if conf.get("teclado_celular") is True:
            partes.append("teclado")
        if conf.get("rodinha_arrasto") is True:
            partes.append("rodinha")
        if conf.get("tela_cheia"):
            partes.append("tela cheia")
        return " · ".join(partes)

    def _editar_personalizado(self, pacote: str, nome: str) -> None:
        self._app_configurado = (pacote, nome)
        # (07/out, pedido dele) abre no PRIMEIRO grupo; a rolagem passa de um
        # para o outro (ver `_rolou_na_borda`)
        self._grupo_editor = GRUPOS_DO_EDITOR[0]
        self._escolhendo_app = False
        self._montar_conteudo()

    def _voltar_personalizados(self) -> None:
        self._app_configurado = None
        self._escolhendo_app = False
        # (r185) Sem nenhum personalizado a aba some: volta para a lista.
        # (09/out, pedido dele: "so um teleporte de volta") voltar ANIMA:
        # com a aba personalizados, a mesma troca de entrar no editor; sem
        # ela, a troca de aba ao contrario (o sublinhado volta para "apps")
        if self._item == "apps" and not self._config.personalizados() and \
                self._aba.get("apps") == "personalizados":
            self._escolher_aba("lista")
            return
        self._montar_conteudo(deslizar=("y", -1))

    def _limpar_personalizado(self, pacote: str) -> None:
        self._conferir_gravacao(self._config.limpar_app(pacote))
        self.programa.anotar("app %s: tudo volta ao padrao" % pacote)
        self._agendar_reabrir({pacote})
        if self._item == "apps" and \
                self._aba.get("apps") == "personalizados":
            self._voltar_personalizados()
        else:
            # (09/out) pelo botao direito na lista: nao refaz a tela a vista;
            # a aba personalizados se poe em dia escondida
            self._app_configurado = None
            self._escolhendo_app = False
            self._agendar_renovar()
            if self._item == "apps" and not self._marcar_aba_no_lugar(
                    self._aba.get("apps")):
                self._montar_abas()     # a aba personalizados pode sumir

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
        b_padrao = E.Botao(cabeca, "voltar ao padrão",
                           lambda: self._limpar_personalizado(pacote),
                           tipo="discreto")
        rot_nome = tk.Label(cabeca, text=nome, bg=E.FUNDO, fg=E.TEXTO,
                            font=E.fonte(E.CORPO, "bold"), anchor="w")
        rot_nome.pack(side="left", fill="x", expand=True,
                      padx=(E.px(8), E.px(4)))

        def padrao():
            # (08/out) ja desenhado; aparece/some no lugar
            if pacote in self._config.personalizados():
                if not b_padrao.winfo_ismapped():
                    b_padrao.pack(side="right", before=rot_nome)
            else:
                b_padrao.pack_forget()
        padrao()
        self._viva(padrao)
        caixa = tk.Frame(pai, bg=E.FUNDO)
        caixa.pack(side="top", fill="both", expand=True)
        rol = _Rolagem(caixa)
        self._ui["rolagem_editor"] = rol
        corpo = rol.dentro
        deste = self._config.app(pacote)
        geral = self._config.apps
        q = self._config.qualidade
        # (08/out, REWORK pedido dele) os MESMOS cartoes de OPCOES >
        # qualidade, so deste app: IMAGEM, SOM, MODO; marcado = o que vale
        # (o dele, senao o geral / o indicado). Escolher igual ao que valeria
        # sem escolha nao guarda.
        rec = self.programa.melhor_do_app(pacote) or {}
        efetivo = self.programa.config_efetiva(pacote)
        self._linha_da_analise(corpo, pacote, rec)

        # (08/out, pedido dele: o padrao da qualidade no app todo) as MESMAS
        # linhas de OPCOES > qualidade: nome + legenda a esquerda (a legenda
        # diz se segue o geral; com ajuste proprio, o link de voltar), os
        # cartoes a direita
        # (08/out, pedido dele: pre-desenhada) a legenda e o link de voltar
        # trocam NO LUGAR (funcao viva); escolher nao remonta mais
        def secao(titulo, campos, voltar, legenda):
            _l, esq_, leg, d = self._linha_qualidade(corpo, titulo, legenda)
            if campos:
                marca = self._marca_geral(
                    esq_, False, voltar,
                    lambda: self._app_volta(pacote, campos), "",
                    side="top", anchor="w", pady=(E.px(4), 0))
                marca.pack(side="top", fill="x")

                def mostrar():
                    d_ = self._config.app(pacote)
                    sim = any(d_.get(c) not in (None, "") for c in campos)
                    leg.configure(text="ajuste só deste app." if sim
                                  else legenda)
                    marca.mostrar(sim)
                mostrar()
                self._viva(mostrar)
            return d

        d = secao("imagem", ("nivel",), "voltar ao geral", "segue o geral.")
        e_img = E.Escolha(d, self._opcoes_nivel(),
                          qualidade.nivel_de(deste, q),
                          lambda v: self._nivel_do_app(pacote, "nivel", v))
        e_img.pack(side="top", fill="x")
        caixa_som = secao("som", ("som",), "voltar ao geral",
                          "segue o geral.")
        e_som = E.Escolha(caixa_som, self._opcoes_som(),
                          qualidade.som_de(deste, q),
                          lambda v: self._nivel_do_app(pacote, "som", v))
        e_som.pack(side="top", fill="x")
        d = secao("janela", ("modo",), "voltar ao automático",
                  "automático: o indicado.")
        indicado = (rec.get("janela") or {}).get("modo", "celular")
        sw = (rec.get("janela") or {}).get("sw_dp")
        e_modo = E.Escolha(d, self._opcoes_modo(
                               bool(rec.get("pc")), indicado,
                               ("largura %d dp" % sw) if sw else ""),
                           efetivo.get("modo") or "celular",
                           lambda v: self._modo_do_app(pacote, v),
                           ao_travada=lambda _v: self._pc_travado_no_app(
                               pacote))
        e_modo.pack(side="top", fill="x")
        # (09/out, pedido dele: "as vezes um funciona melhor num tamanho
        # diferente") o tamanho nos apps, so deste
        d = secao("tamanho", ("escala",), "voltar ao geral",
                  "segue o geral.")
        e_tam = E.Segmentado(
            d, OPCOES_ESCALA,
            deste.get("escala") or geral.get("escala") or "normal",
            lambda v: self._escala_do_app(pacote, v))
        e_tam.pack(side="top", fill="x")

        # -- OUTROS: onde o som toca, ao fechar, teclado
        def onde_fechar():
            d_, g_ = self._config.app(pacote), self._config.apps
            return (d_.get("onde") or g_.get("onde") or "celular",
                    d_.get("ao_fechar") or g_.get("ao_fechar") or "fechar")
        onde, fechar = onde_fechar()
        d = secao("onde o som toca", (), "", "o som do celular inteiro.")
        e_onde = E.Segmentado(d, self._opcoes_de_onde(), onde,
                              lambda v: self._mudou_no_app(pacote, "onde", v))
        e_onde.pack(side="top", fill="x")
        d = secao("ao fechar", (), "", "a janela deste app.")
        e_fechar = E.Segmentado(
            d, AO_FECHAR, fechar,
            lambda v: self._mudou_no_app(pacote, "ao_fechar", v))
        e_fechar.pack(side="top", fill="x")
        g_outros = self._seg(corpo)
        g_outros._painel.pack_configure(pady=(E.px(6), 0))
        # (08/out, pedido dele) SEMPRE EM TELA CHEIA: a janela deste app
        # abre ocupando o monitor (aberta agora: entra/sai na hora)
        ch_cheia = self._chave(g_outros, "sempre em tela cheia",
                               bool(deste.get("tela_cheia")),
                               lambda v: self._tela_cheia_do_app(pacote, v),
                               explicacao="a janela deste app abre ocupando "
                                          "a tela inteira do monitor.",
                               borda=False)
        # (08/out, pedido dele) CORRECOES DESTE APP num segmento proprio:
        # desligadas de fabrica, menos onde ja se sabe que precisa (o
        # Instagram). (r148) o teclado do celular na janela; (08/out) a
        # rodinha como arrasto.
        g_fix = self._seg(corpo, "correções deste app",
                          info="correções\nservem para apps que não se dão "
                               "bem com mouse e teclado de pc\nde fábrica "
                               "desligadas, menos no instagram, que precisa "
                               "das duas")
        g_fix._painel.pack_configure(pady=(E.px(6), 0))
        p = self.programa
        ch_rod = self._chave(
            g_fix, "rodinha como arrasto",
            p.fix_do_app(pacote, "rodinha_arrasto"),
            lambda v: self._virar_fix(pacote, "rodinha_arrasto", v),
            explicacao="a rodinha do mouse vira um arrasto com o dedo. "
                       "ligue se rolar mexe em duas coisas ao mesmo "
                       "tempo (ex.: comentários e feed no instagram).")
        ch_tec = self._chave(
            g_fix, "mostrar o teclado do celular",
            p.fix_do_app(pacote, "teclado_celular"),
            lambda v: self._virar_fix(pacote, "teclado_celular", v),
            explicacao="ligue só se o app não mostra a caixa de texto "
                       "sem o teclado na tela (ex.: repostar no "
                       "instagram). o teclado do pc continua "
                       "digitando normal.",
            borda=False)

        def valores():
            # (08-09/out) a tela guardada se poe em dia NO LUGAR
            d_, qq, g_ = (self._config.app(pacote), self._config.qualidade,
                          self._config.apps)
            e_img.definir(qualidade.nivel_de(d_, qq))
            e_som.definir(qualidade.som_de(d_, qq))
            e_modo.definir(p.config_efetiva(pacote).get("modo")
                           or "celular")
            e_tam.definir(d_.get("escala") or g_.get("escala") or "normal")
            o, f_ = onde_fechar()
            e_onde.definir(o)
            e_fechar.definir(f_)
            ch_cheia.definir(bool(d_.get("tela_cheia")))
            ch_rod.definir(p.fix_do_app(pacote, "rodinha_arrasto"))
            ch_tec.definir(p.fix_do_app(pacote, "teclado_celular"))
        self._viva(valores)
        self._ui["_vivas_completas"] = True
        E.Texto(corpo, "o que você escolher aqui vale só para este app, e já "
                       "vale na janela aberta.",
                cor=E.APAGADO, tamanho=E.ROTULO, largura=E.px(480)).pack(
            side="top", fill="x", pady=(E.px(10), E.px(0)))
        if self._falta("som"):
            self._cortina(caixa_som, "som", "som do celular no pc", curta=True)
        self._ui["grupos_editor"] = {}      # (08/out) sem grupos: uma coluna

    def _linha_da_analise(self, pai, pacote: str, rec: dict) -> None:
        """(08/out, rework) O que a VERIFICACAO diz do app, numa linha: e o
        que libera (ou nao) o modo pc / tablet."""
        from . import analise_app, melhor_modo
        analise = self.programa.interface_dos_apps().get(
            pacote.split(COPIA)[0])
        tipo = rec.get("tipo")
        if tipo == melhor_modo.JOGO:
            texto, cor = ("jogo: modo pc indicado (16:9 deitado, como o "
                          "monitor)."), E.VERDE
        elif not analise:
            texto, cor = None, None
        elif analise.get("resultado") == analise_app.TABLET:
            texto, cor = "✓ " + analise_app.texto(analise) + ".", E.VERDE
        else:
            texto, cor = None, None
        if texto:
            tk.Label(pai, text=texto, bg=E.FUNDO, fg=cor,
                     font=E.fonte(E.ROTULO), anchor="w").pack(
                side="top", fill="x")
            return
        if not analise:
            self._info(pai, "ainda não verificado: só o modo celular.",
                       "verificação\nautomática: ao conectar, o programa lê "
                       "de cada app se ele tem tela de tablet. com tablet, o "
                       "modo pc / tablet é liberado e passa a ser o "
                       "indicado.", largura=460).pack(
                side="top", fill="x")
        else:
            self._info(pai, analise_app.texto(analise) + ": só o modo "
                       "celular.",
                       "sem configuração de tablet\n"
                       "este app não traz telas próprias para tablet "
                       "(ou desenha a tela sozinho): abre no formato de "
                       "celular, com a densidade da resolução escolhida.",
                       largura=460).pack(side="top", fill="x")

    def _virar_fix(self, pacote: str, chave: str, ligada: bool) -> None:
        """Igual a de fabrica = nada guardado; diferente = True / "nao"."""
        fabrica = self.programa.fix_de_fabrica(pacote, chave)
        valor = "" if bool(ligada) == fabrica else (True if ligada else "nao")
        self._virar_app(pacote, chave, valor)

    def _tela_cheia_do_app(self, pacote: str, ligada: bool) -> None:
        self._virar_app(pacote, "tela_cheia", True if ligada else "")
        if pacote in self.programa.apps_abertos():
            self.programa.reabrir_app(pacote, tela_cheia=bool(ligada))

    def _nivel_do_app(self, pacote: str, campo: str, valor: str) -> None:
        q = self._config.qualidade
        geral = qualidade.nivel_geral(q) if campo == "nivel" else \
            qualidade.som_geral(q)
        self._virar_app(pacote, campo, "" if valor == geral else valor)
        if not self._atualizar_vivas():    # o "voltar ao geral"
            self._remontar_quieto_depois()

    def _escala_do_app(self, pacote: str, valor: str) -> None:
        """Igual ao geral = segue o geral (nao guarda)."""
        geral = self._config.apps.get("escala") or "normal"
        self._virar_app(pacote, "escala", "" if valor == geral else valor)
        self._atualizar_vivas()

    def _modo_do_app(self, pacote: str, modo: str) -> None:
        from . import melhor_modo
        sem_escolha = melhor_modo.mesclar(
            dict(self._config.app(pacote), modo=""),
            self.programa.melhor_do_app(pacote),
            self._config.apps.get("modo") or "pc")["modo"]
        self._virar_app(pacote, "modo", "" if modo == sem_escolha else modo)
        if not self._atualizar_vivas():
            self._remontar_quieto_depois()

    def _app_volta(self, pacote: str, campos) -> None:
        for c in campos:
            self._config.definir_app(pacote, c, "")
        self._virar_app(pacote, campos[0], "")
        if not self._atualizar_vivas():
            self._remontar_quieto()

    def _pc_travado_no_app(self, pacote: str) -> None:
        if not self.programa.verificacao_feita():
            self._escolher_aba_qualidade()

    def _escolher_aba_qualidade(self) -> None:
        """Leva a OPCOES > qualidade (onde fica o "verificar")."""
        self._aba["opcoes"] = "qualidade"
        self._escolher_item("opcoes")

    # (r189) GRUPOS DO EDITOR DO APP: um cabecalho clicavel (mouse, Enter,
    # espaco) e o corpo embaixo; so um aberto por vez, trocado NO LUGAR
    # (sem remontar a tela = sem piscar). Clicar no aberto recolhe.
    def _grupo_do_editor(self, pai, chave: str, titulo: str) -> tk.Frame:
        cab = tk.Frame(pai, bg=E.FUNDO)
        cab.pack(side="top", fill="x", pady=(E.px(2), E.px(0)))
        topo = tk.Frame(cab, bg=E.FUNDO, cursor="hand2")
        topo.pack(side="top", fill="x")
        rot = tk.Label(topo, text="", bg=E.FUNDO, fg=E.TEXTO,
                       font=E.fonte(E.PEQUENA), anchor="w", cursor="hand2",
                       takefocus=1, highlightthickness=1,
                       highlightbackground=E.FUNDO, highlightcolor=E.FOCO,
                       padx=E.px(2), pady=E.px(6))
        rot.pack(side="left")
        # (07/out) o que vale no grupo, a direita (sem precisar abrir)
        resumo = tk.Label(topo, text="", bg=E.FUNDO, fg=E.TEXTO_2,
                          font=E.fonte(E.ROTULO), anchor="e", cursor="hand2")
        resumo.pack(side="right", padx=(E.px(8), E.px(4)))
        self._ui.setdefault("resumos_editor", {})[chave] = resumo
        tk.Frame(cab, bg=E.LINHA, height=1).pack(side="top", fill="x")
        E.cantos(rot)                    # (07/out) o foco em canto redondo
        for w in (topo, resumo):
            w.bind("<Button-1>", lambda _e, k=chave:
                   self._abrir_grupo_editor(k))
        for ev in ("<Button-1>", "<Return>", "<space>"):
            rot.bind(ev, lambda _e, k=chave: self._abrir_grupo_editor(k))
        # (07/out, padrao de animacao) o corpo mora numa "janela" que abre e
        # fecha a altura (360 ms, como o cartao que expande no Android).
        # (07/out, "o desenho quebrava ao trocar") O corpo vai por PLACE, no
        # tamanho dele: a janela so CORTA. Com pack, a altura menor espremia
        # as fileiras de dentro a cada quadro (o Tk refazia tudo encolhido).
        clip = tk.Frame(pai, bg=E.FUNDO, height=1)
        clip.pack_propagate(False)
        corpo = tk.Frame(clip, bg=E.FUNDO)
        corpo.place(x=0, y=0, relwidth=1.0)
        clip._andando = False

        def seguir(_e=None):
            # aberto e parado: acompanha o conteudo (fileira que muda etc.)
            if not clip._andando and clip.winfo_manager():
                clip.configure(height=self._altura_do_grupo(corpo))
        corpo.bind("<Configure>", seguir, add="+")
        self._ui["grupos_editor"][chave] = (cab, rot, titulo, corpo, clip)
        return corpo

    @staticmethod
    def _altura_do_grupo(corpo) -> int:
        return corpo.winfo_reqheight() + E.px(8)

    def _abrir_grupo_editor(self, chave: str):
        """Clique no cabecalho: abre este (fechando o aberto) ou recolhe."""
        aberto = getattr(self, "_grupo_editor", None)
        self._trocar_grupo(None if aberto == chave else chave, "topo")
        return "break"

    def _pintar_grupos_editor(self, animar: bool = False) -> None:
        """No estado de agora, sem animar (a tela acabou de nascer)."""
        aberto = getattr(self, "_grupo_editor", None)
        self._grupo_andando = False
        for chave, (cab, _rot, _t, corpo, clip) in \
                (self._ui.get("grupos_editor") or {}).items():
            try:
                self._titulo_do_grupo(chave, aberto)
                clip._andando = False
                if chave == aberto:
                    clip.configure(height=self._altura_do_grupo(corpo))
                    clip.pack(side="top", fill="x", after=cab)
                else:
                    clip.pack_forget()
            except tk.TclError:
                pass
        rol = self._ui.get("rolagem_editor")
        if rol is not None:
            rol.na_borda = self._rolou_na_borda
            # a rolagem em pixel (a roda continua andando 24 por vez): com
            # degraus de 24 px a troca de grupo pulava de degrau em degrau
            # e o Tk arredondava o fim para o degrau
            rol.canvas.configure(yscrollincrement=1)
            rol.passo_px = E.px(24)

    def _titulo_do_grupo(self, chave: str, aberto) -> None:
        _cab, rot, titulo, _c, _clip = self._ui["grupos_editor"][chave]
        rot.configure(text="%s  %s" % ("▾" if chave == aberto else "▸",
                                       titulo),
                      fg=E.TEXTO if chave == aberto else E.TEXTO_2)

    # (07/out, pedido dele) A RODA PASSA DE UM GRUPO PARA O OUTRO: chegou ao
    # fim do aberto e rolou mais para baixo = ele fecha e o proximo abre (com
    # o cabecalho no topo); no comeco e rolou para cima = abre o anterior,
    # ja mostrando o fim dele. Durante a troca a roda nao empilha trocas.
    def _rolou_na_borda(self, direcao: int):
        if getattr(self, "_grupo_andando", False) or \
                time.monotonic() - getattr(self, "_grupo_trocou", 0.0) < 0.25:
            return "break"
        ordem = GRUPOS_DO_EDITOR
        atual = getattr(self, "_grupo_editor", None)
        i = ordem.index(atual) if atual in ordem else \
            (-1 if direcao > 0 else len(ordem))
        j = i + direcao
        if 0 <= j < len(ordem):
            self._trocar_grupo(ordem[j], "topo" if direcao > 0 else "fim")
        return "break"

    def _trocar_grupo(self, novo, rolar: str = "topo") -> None:
        """Fecha o aberto e abre `novo` (None = so fecha).
        (07/out, gravado quadro a quadro no programa de verdade) A altura
        animada movia dezenas de pecas por quadro e o Windows mostrava
        estados pela metade (fileiras repetidas, fantasmas). Agora e o VEU da
        casa: a foto da lista cobre, a troca acontece inteira por baixo (ja
        rolada no lugar certo) e a foto dissolve."""
        velho = getattr(self, "_grupo_editor", None)
        if novo == velho or getattr(self, "_grupo_andando", False):
            return
        rol = self._ui.get("rolagem_editor")
        self._grupo_editor = novo
        veu = None
        if rol is not None and mov.ligadas():
            try:
                cv = rol.canvas
                if cv.winfo_viewable():
                    caixa = (cv.winfo_rootx(), cv.winfo_rooty(),
                             cv.winfo_width(), cv.winfo_height())
                    foto = self._foto_da_tela(*caixa)
                    if foto is not None:
                        veu = self._cobrir(cv, "_veu_grupo", caixa, foto=foto)
            except tk.TclError:
                veu = None
        self._pintar_grupos_editor()
        if rol is not None:
            try:
                self._rolar_ate_grupo(rol, novo, rolar)
            except tk.TclError:
                pass
        if veu is None:
            self._grupo_trocou = time.monotonic()
            return
        self._grupo_andando = True

        def a_cada(p):
            try:
                veu.attributes("-alpha", max(0.0, 1.0 - p))
            except tk.TclError:
                pass

        def fim():
            self._grupo_andando = False
            self._grupo_trocou = time.monotonic()
            self._descobrir_area(veu)
        mov.animar(veu, "grupo", MS_DESLIZE, a_cada, fim, curva=mov.ENTRADA)

    def _rolar_ate_grupo(self, rol, chave, rolar: str) -> None:
        """Descendo ("topo"): o cabecalho do grupo no alto da lista; subindo
        ("fim"): o fim do grupo embaixo."""
        cv = rol.canvas
        rol.dentro.update_idletasks()
        grupos = self._ui.get("grupos_editor") or {}
        total = rol.dentro.winfo_reqheight()
        base = rol.margem_base
        cv.configure(scrollregion=(0, 0, cv.winfo_width(), total + base))
        if chave not in grupos:
            return
        cab, _r, _t, corpo, _clip = grupos[chave]
        vista = max(1, cv.winfo_height())
        y = cab.winfo_y()
        if rolar == "fim":
            y += cab.winfo_height() + self._altura_do_grupo(corpo) - vista
        y = max(0, min(y, total + base - vista))
        cv.yview_moveto(y / max(1.0, total + base))

    def _opcoes_curtas(self, ajuste) -> list:
        return [(v, ROTULO_CURTO.get(str(v), ROTULO_CURTO.get(r, r.lower())))
                for v, r in ajuste["opcoes"]]

    def _mudou_no_app(self, pacote: str, campo: str, valor) -> None:
        eh_predef = campo in qualidade.CHAVES_PREDEF.values()     # (r196)
        if eh_predef:
            # Escolher a predefinicao poe as fileiras todas nela.
            self._config.definir_app(pacote, "video_fino", "")
            self._config.definir_app(pacote, "audio_fino", "")
        # (07/out) Igual ao de todos os apps = segue o de todos (nao guarda).
        de_todos = {"onde": self._config.apps.get("onde") or "celular",
                    "ao_fechar": self._config.apps.get("ao_fechar")
                    or "fechar"}
        if campo in de_todos and valor == de_todos[campo]:
            valor = ""
        if campo == "formato":
            res = self._config.app(pacote).get("resolucao")
            if res and res not in formatos.possiveis(valor or "",
                                                     self.programa.celular):
                self._config.definir_app(pacote, "resolucao", "")
        self._virar_app(pacote, campo, valor or "")
        if eh_predef or campo == "formato":
            self._remontar_quieto_depois()

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
        # (07/out, camadas) o aviso flutua por cima do que esta travado:
        # camada 2, de canto redondo (era a caixa afundada, quadrada)
        caixa = tk.Frame(cortina, bg=E.CAMADA_2, highlightthickness=1,
                         highlightbackground=E.BORDA_2)
        caixa.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(caixa, text=titulo + " · indisponível",
                 bg=E.CAMADA_2, fg=E.TEXTO,
                 font=E.fonte(E.PEQUENA, "bold")).pack(
            side="top", padx=E.px(14), pady=(E.px(8 if curta else 12),
                                             E.px(3)))
        tk.Label(caixa, text="não funciona no android %s.\nprecisa do "
                 "android %s ou mais novo." % (versao, PRECISA[recurso][1]),
                 bg=E.CAMADA_2, fg=E.TEXTO_2, font=E.fonte(E.ROTULO),
                 justify="center", wraplength=E.px(260)).pack(
            side="top", padx=E.px(14), pady=(E.px(0),
                                             E.px(8 if curta else 12)))
        E.cantos(caixa, raio=E.px(8))
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

        feito = [None]
        espera = [None]
        # (09/out, pedido dele) o filtro animado (filtro_animado), como a
        # grade de apps; as linhas que a busca tira ficam guardadas
        arr = FA.Arranjo(rol.dentro, rol.canvas, E.FUNDO)
        arr.guardar = True
        nomes = {}

        def criar(chave):
            if chave[0] == "_msg":
                return E.Texto(rol.dentro, chave[1], cor=E.APAGADO)
            pacote = chave[1]
            nome = nomes[pacote]
            linha = tk.Frame(rol.dentro, bg=E.FUNDO, cursor="hand2")
            pecas = [linha]
            ic = self._icone_app(linha, pacote, nome, E.px(16))
            ic.pack(side="left", padx=(E.px(6), E.px(6)), pady=E.px(3))
            pecas.append(ic)
            rot = tk.Label(linha, text=nome, bg=E.FUNDO, fg=E.TEXTO_2,
                           font=E.fonte(E.PEQUENA), anchor="w",
                           cursor="hand2")
            rot.pack(side="left", fill="x", expand=True)
            pecas.append(rot)
            for peca in pecas:
                peca.bind("<Button-1>", lambda _e, pk=pacote, n=nome:
                          escolher(pk, n))
            self._realce_pilula(linha, pecas)
            return linha

        def pintar(_e=None):
            self._busca_escolha = busca.get()
            termo = self._busca_escolha.strip().lower()
            # (02/out, revisao) Seta, Tab, Shift e repeticao do mesmo termo
            # nao refazem as 80 linhas (nem jogam a lista para o topo).
            agora = (termo, id(self._apps), self._apps_carregando)
            if agora == feito[0]:
                return
            antes, feito[0] = feito[0], agora
            mesma_lista = antes is not None and antes[1:] == agora[1:]
            if not mesma_lista:
                arr.esvaziar()
            apps = sorted((a for a in (self._apps or [])
                           if not termo or termo in a[0].lower()),
                          key=lambda a: (a[2], a[0].lower()))
            if not self._apps:
                chaves = [("_msg", "lendo os apps do celular…"
                           if self._apps_carregando else "nenhum app lido.")]
            else:
                for nome, pacote, _sis in apps:
                    nomes[pacote] = nome
                chaves = [("a", pacote) for _n, pacote, _s in apps[:80]] or \
                    [("_msg", "nenhum app com esse nome.")]
            layout = FA.empilhar(arr, chaves, criar, E.px(2))
            adiadas = arr.aplicar(layout, criar, animar=mesma_lista,
                                  topo=True, adiar=True)
            if adiadas:
                self._em_lotes(rol.canvas, adiadas,
                               lambda c: arr.criar_adiado(c, criar),
                               primeiro=0)

        def depois(_e=None):
            # 120 ms depois da ultima tecla, como a busca da grade de apps.
            if espera[0]:
                self.after_cancel(espera[0])
            espera[0] = self.after(
                120, lambda: rol.canvas.winfo_exists() and pintar())

        busca.bind("<KeyRelease>", depois)
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
        # (02/out, revisao) Uma conferencia por tela por execucao: na grade
        # de apps eram milhares de perguntas ao Tk a cada remontagem.
        conferidas = self.__dict__.setdefault("_telas_conferidas", set())
        if tela in conferidas or not self._na_tela():
            return                  # (escondida: nada mapeado para medir)
        conferidas.add(tela)
        limite = self.winfo_rootx() + self.winfo_width()
        # (limpeza 01/out) As telas guardadas ficam ATRAS da atual, mapeadas:
        # conferi-las acusava corte com o nome da aba errada no relatorio.
        escondidas = {str(v[0]) for v in self._guardadas.values()}

        def olhar(w):
            for f in w.winfo_children():
                try:
                    if not f.winfo_ismapped() or str(f) in escondidas:
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
        # (r196) A predefinicao de UMA conexao so reabre a janela que esta
        # nela (a do cabo nao mexe numa janela sem fio).
        con = next((c for c, k in qualidade.CHAVES_PREDEF.items()
                    if k == campo), None)
        if campo not in AJUSTES_SEM_REABRIR and (
                con is None or self.programa.na_conexao(APP + pacote, con)):
            self._agendar_reabrir({pacote})
        # Virou (ou deixou de ser) personalizado: o "voltar tudo ao padrao"
        # aparece/some no editor.
        if antes != (pacote in self._config.personalizados()) and \
                self._aba.get("apps") == "personalizados" and \
                not self._atualizar_vivas():
            self._remontar_quieto_depois()

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
        col_esq, col_dir = self._duas(area)
        ui = {}
        # (08/out, pedido dele: juntar por assunto) bateria e uso num painel
        esq = self._seg(col_esq, "bateria e uso", expand=True)
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
        dir_ = self._seg(col_dir, "o que mais pesa agora", expand=True)
        tabela = tk.Frame(dir_, bg=E.FUNDO)
        tabela.pack(side="top", fill="x")
        tabela.grid_columnconfigure(0, weight=1)
        # Largura fixa para CPU e RAM: numero mudando de tamanho nao
        # empurra as colunas (sem tremer a cada 0,75 s).
        tabela.grid_columnconfigure(1, minsize=E.px(38))
        tabela.grid_columnconfigure(2, minsize=E.px(44))
        for col, titulo in enumerate(("app", "cpu", "ram")):
            tk.Label(tabela, text=titulo, bg=E.FUNDO, fg=E.APAGADO,
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
        tk.Label(linha, text=nome, bg=E.FUNDO, fg=E.TEXTO_2,
                 font=E.fonte(E.PEQUENA)).pack(side="left")
        valor = tk.Label(linha, text="—", bg=E.FUNDO, fg=E.TEXTO,
                         font=E.fonte(E.PEQUENA))
        valor.pack(side="right")
        # (07/out, padrao) barra de pontas redondas (como a do deslizador e a
        # do player) que anda ate o valor novo, em vez de pular
        alto = E.px(4)
        barra = tk.Canvas(pai, height=alto, bg=E.FUNDO,
                          highlightthickness=0, bd=0)
        barra.pack(side="top", fill="x", pady=(E.px(0), E.px(4)))
        meio = alto / 2.0
        trilho = barra.create_line(meio, meio, meio, meio, fill=E.LINHA,
                                   width=alto, capstyle="round")
        cheio = barra.create_line(meio, meio, meio, meio, fill=E.ACENTO,
                                  width=alto, capstyle="round",
                                  state="hidden")
        m = {"valor": valor, "barra": barra, "cheio": cheio,
             "trilho": trilho, "fracao": 0.0, "mostrado": 0.0}
        barra.bind("<Configure>", lambda _e: self._encher(m, animar=False))
        return m

    def _encher(self, m: dict, animar: bool = True) -> None:
        barra, fracao = m["barra"], max(0.0, min(1.0, m["fracao"]))
        cor = E.ERRO if fracao >= 0.9 else (E.ALERTA if fracao >= 0.75
                                            else E.ACENTO)
        alto = E.px(4)
        meio = alto / 2.0

        def por(f):
            try:
                larg = barra.winfo_width()
                barra.coords(m["trilho"], meio, meio, max(meio, larg - meio),
                             meio)
                fim = meio + (larg - alto) * f
                barra.coords(m["cheio"], meio, meio, fim, meio)
                barra.itemconfigure(m["cheio"], fill=cor,
                                    state="normal" if f > 0.004 else "hidden")
                m["mostrado"] = f
            except tk.TclError:
                pass
        de = m.get("mostrado", 0.0)
        if not animar or abs(fracao - de) < 0.002:
            mov.parar(barra, "encher")
            por(fracao)
            return
        mov.animar(barra, "encher", mov.MS_PADRAO,
                   lambda k: por(de + (fracao - de) * k))

    def _conferir_status(self) -> None:
        """
        Do relogio (100 ms): com a tela "status" a vista, mantem os medidores
        do celular ligados e troca os numeros que mudaram; fora dela, desliga
        os medidores -- o celular so e consultado enquanto se olha.
        """
        ui = self._ui.get("status")
        a_vista = (self._item == "celular" and self._na_tela()
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
                por(rot_nome, _encurtar(nomes.get(bruto) or
                                        _nome_de_processo(bruto), 22))
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
            por(ui["aviso"], "ao vivo", E.APAGADO)

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
            dica = self._dica
            try:
                mov.sair(dica, dica.destroy)       # (07/out) some esmaecendo
            except Exception:
                pass
            self._dica = None
            self._dica_de = None

    def _dica_mostrar(self, pacote: str, nome: str, dono) -> None:
        self._dica_id = None
        if not self._mouse_sobre(dono):
            return                      # trocou de tela antes dos 600 ms
        self._dica_esconder()
        dica = tk.Toplevel(self)
        dica.withdraw()
        dica.overrideredirect(True)
        # (07/out, camadas) a dica flutua por cima de tudo: SUPERFICIE (3),
        # como os menus; a borda e a curva sao do Windows 11
        moldura.arredondar_ao_mostrar(dica, borda=E.SUPERFICIE_BORDA)
        dica.attributes("-topmost", True)
        dica.configure(bg=E.SUPERFICIE)
        corpo = tk.Frame(dica, bg=E.SUPERFICIE)
        corpo.pack(padx=E.px(3), pady=E.px(3))
        tk.Label(corpo, text=nome, bg=E.SUPERFICIE, fg=E.TEXTO,
                 font=E.fonte(E.PEQUENA), anchor="w").pack(
            side="top", fill="x", padx=E.px(8), pady=(E.px(5), E.px(1)))
        texto = tk.Label(corpo, text="lendo o uso…", bg=E.SUPERFICIE,
                         fg=E.TEXTO_2, font=E.fonte(E.ROTULO), anchor="w",
                         justify="left")
        texto.pack(side="top", fill="x", padx=E.px(8), pady=(E.px(0),
                                                             E.px(6)))
        x, y = self.winfo_pointerxy()
        dica.geometry("+%d+%d" % self._lugar_do_menu(
            dica, x + E.px(12), y + E.px(14)))
        if mov.ligadas():
            dica.attributes("-alpha", 0.0)
        dica.deiconify()
        mov.entrar(dica)
        self._dica = dica
        self._dica_de = pacote
        self._dica_dono = dono

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

    def _na_tela(self) -> bool:
        """(02/out, revisao) Aberta E nao minimizada: minimizada, `_visivel`
        segue True e o status (0,25 s no celular) e a barra do player
        continuavam trabalhando para ninguem."""
        return self._visivel and not moldura.situacao(self)[0]

    def _mouse_sobre(self, dono) -> bool:
        """O mouse esta em cima de `dono`, a vista, com a janela aberta?"""
        try:
            if not dono.winfo_exists() or not dono.winfo_viewable() or \
                    not self._visivel or self.state() == "iconic":
                return False
            x, y = self.winfo_pointerxy()
            alvo = self.winfo_containing(x, y)
            return alvo is not None and str(alvo).startswith(str(dono))
        except Exception:
            return False

    def _conferir_dica(self) -> None:
        """(01/out, relato dele: o quadro de uso ficava na tela ao trocar de
        aba ou minimizar -- o "saiu" do mouse nunca chegava) No relogio: o
        mouse saiu do app por qualquer caminho -> o quadro some."""
        if self._dica is None:
            return
        if not self._mouse_sobre(getattr(self, "_dica_dono", None)):
            self._dica_cancelar()
            self._dica_esconder()

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
        # (02/out) Chave propria: "status" e o dict da tela STATUS, e o
        # configure num dict derrubava o _repintar com a aba STATUS aberta.
        self._ui["status_parear"] = s

    def _pintar_status(self, texto: str, cor: str = E.TEXTO_2) -> None:
        self._status_parear = (texto, cor)
        s = self._ui.get("status_parear")
        if s is not None:
            try:
                s.configure(text=texto, fg=cor)
            except tk.TclError:
                pass

    # (r193) PAREAR EM DUAS ABAS (pedido dele, 30/set/2026: "desconexa").
    # CONEXAO = o dia a dia: o celular em uso, a conexao preferida e os
    # outros celulares, que aparecem sozinhos (a lista refaz quando o adb
    # ve alguem entrar ou sair -- `_conferir_outros`). ADICIONAR = celular
    # novo, uma vez: com cabo (so para ligar o sem fio) ou com codigo.

    def _link(self, pai, texto: str, acao) -> tk.Label:
        """Texto pequeno clicavel, com foco pelo Tab (teclado-e-foco)."""
        rot = tk.Label(pai, text=texto, bg=E.FUNDO, fg=E.TEXTO_2,
                       font=E.fonte(E.PEQUENA), anchor="w", cursor="hand2",
                       takefocus=1, highlightthickness=1,
                       highlightbackground=E.FUNDO, highlightcolor=E.FOCO)
        rot.bind("<Button-1>", lambda _e: acao())
        rot.bind("<Return>", lambda _e: acao())
        rot.bind("<space>", lambda _e: acao())
        rot.bind("<Enter>", lambda _e: rot.configure(fg=E.TEXTO))
        rot.bind("<Leave>", lambda _e: rot.configure(fg=E.TEXTO_2))
        E.cantos(rot, raio=E.px(4))      # (07/out) o foco em canto redondo
        return rot

    def _tela_parear_conexao(self, area) -> None:
        if self._sem_pasta(area):
            return
        if not self._trabalhando and \
                getattr(self, "_status_de", "") != "conexao":
            self._status_parear = ("", E.TEXTO_2)
        self._status_de = "conexao"
        col_esq, col_dir = self._duas(area)
        esq = self._seg(col_esq, "celular em uso")
        nome = tk.Label(esq, text="", bg=E.FUNDO,
                        font=E.fonte(E.CORPO, "bold"), anchor="w")
        nome.pack(side="top", fill="x")
        detalhe = E.Texto(esq, "", cor=E.TEXTO_2, largura=E.px(230))
        detalhe.pack(side="top", fill="x", pady=(E.px(2), E.px(0)))
        self._ui["cel_nome"] = nome
        self._ui["cel_detalhe"] = detalhe
        # (08/out, pedido dele) DESPAREAR com duas opcoes, no menu da casa
        # logo abaixo do botao (`_abrir_desparear`); aparece com celular em
        # uso ou com um endereco guardado
        b = E.Botao(esq, "desparear ▾", self._abrir_desparear,
                    tipo="contorno")
        self._ui["botao_desparear"] = b
        # (08/out, pedido dele: juntar por assunto) no mesmo painel
        self._sub(esq, "conexão preferida")
        self._seletor_de_conexao(esq)

        # (07/out, pedido dele) "procurar de novo" no titulo da lista (estava
        # solto no pe da coluna, longe do que ele atualiza)
        dir_ = self._seg(col_dir, "outros celulares", expand=True)
        topo = dir_._topo
        lk = self._link(topo, "procurar de novo", self._procurar)
        lk.configure(font=E.fonte(E.ROTULO))
        lk.pack(side="right")
        lista = tk.Frame(dir_, bg=E.FUNDO)
        lista.pack(side="top", fill="x")
        self._ui["lista_parear"] = lista
        self._status(dir_)
        self._pintar_celular_em_uso()
        self._mostrar_achados()
        self.after(150, self._talvez_procurar)

    def _abrir_desparear(self) -> None:
        b = self._ui.get("botao_desparear")
        if b is None or not b.winfo_exists():
            return

        class _Onde:
            x_root = b.winfo_rootx()
            y_root = b.winfo_rooty() + b.winfo_height()
        opcoes = []
        if (self.programa.celular or {}).get("serial"):
            opcoes.append(("só desconectar (continua pareado)",
                           lambda: self._desparear(False)))
        opcoes.append(("desconectar e desparear",
                       lambda: self._desparear(True)))
        menu, corpo = self._novo_menu()
        menu._dono = b
        self._encher_menu(menu, corpo, _Onde, opcoes)

    def _desparear(self, esquecer: bool) -> None:
        self.programa.desconectar_tudo(desparear=esquecer)
        self._pintar_status(
            "despareado. para usar de novo, pareie pelo cabo ou pelo código "
            "em adicionar." if esquecer else
            "desconectado. continua pareado: use conectar ao lado ou o botão "
            "da conexão no rodapé.", E.TEXTO_2)
        self._repintar()

    def _pintar_desparear(self) -> None:
        b = self._ui.get("botao_desparear")
        if b is None or not b.winfo_exists():
            return
        mostrar = bool((self.programa.celular or {}).get("serial")
                       or self._config.ip_reserva)
        if mostrar and not b.winfo_manager():
            b.pack(side="top", anchor="w", pady=(E.px(10), 0),
                   after=self._ui["cel_detalhe"])
        elif not mostrar and b.winfo_manager():
            b.pack_forget()

    def _pintar_celular_em_uso(self) -> None:
        nome = self._ui.get("cel_nome")
        if nome is None or not nome.winfo_exists():
            return
        self._pintar_desparear()
        cel = self.programa.celular or {}
        if cel.get("serial"):
            partes = []
            # (07/out, pedido dele) numa linha so ("android 16" quebrava)
            if cel.get("bateria") is not None:
                partes.append("%s%%" % cel["bateria"] + (
                    " carregando" if cel.get("carregando") else ""))
            if cel.get("temperatura") is not None:
                partes.append("%d °C" % round(cel["temperatura"]))
            if cel.get("android"):
                partes.append("android %s" % cel["android"])
            pintura = ((cel.get("modelo") or "celular"), E.VERDE,
                       " · ".join(partes), False)
        else:
            # (01/out) O botao "adicionar celular" saiu: quem esta por perto
            # aparece na lista ao lado, com "conectar".
            pintura = ("nenhum celular", E.APAGADO,
                       "ligue no celular a depuração sem fio (ou a usb, com "
                       "o cabo): ele aparece ao lado para conectar.", True)
        if pintura == getattr(self, "_cel_pintado", None) and \
                nome.cget("text"):
            return
        self._cel_pintado = pintura
        texto, cor, det, _sem = pintura
        nome.configure(text=texto, fg=cor)
        self._ui["cel_detalhe"].configure(text=det)

    def _conferir_outros(self) -> None:
        """(r193) OUTROS CELULARES AO VIVO: o adb viu alguem entrar ou sair
        com a aba CONEXAO aberta -> procura de novo (em segundo plano)."""
        prontos = frozenset(getattr(self.programa, "_prontos", None) or ())
        if prontos == self._prontos_vistos:
            return
        primeira = self._prontos_vistos is None
        self._prontos_vistos = prontos
        if (not primeira and self._visivel and self._item == "parear"
                and self._aba["parear"] == "conexao"
                and not self._trabalhando and self._pasta_ok()):
            self._procurar()

    def _tela_parear_adicionar(self, area) -> None:
        if self._sem_pasta(area):
            return
        if not self._trabalhando and \
                getattr(self, "_status_de", "") != "adicionar":
            self._status_parear = ("", E.TEXTO_2)   # o da outra aba nao vem
        self._status_de = "adicionar"
        col_esq, col_dir = self._duas(area)
        esq = self._seg(col_esq, "como")
        dir_ = self._seg(col_dir, "com cabo" if self._metodo == "cabo"
                         else "com código", expand=True)
        E.Segmentado(esq, [("cabo", "com cabo"), ("codigo", "com código")],
                     self._metodo, self._escolheu_metodo).pack(
            side="top", fill="x")
        if self._metodo == "cabo":
            # (r194) O texto do r193 dizia que o cabo "so serve para ligar o
            # sem fio" -- errado desde o seletor do r192 (o cabo pode ser a
            # propria conexao, em CONEXAO › conexao preferida).
            # (07/out, pedido dele) uma linha + o resto no ⓘ
            curto = "o cabo autoriza o celular e já deixa o sem fio pronto."
            detalhe = ("pelo cabo\n"
                       "o pc autoriza o celular e já prepara o sem fio\n"
                       "(os dois no mesmo wi-fi)\n"
                       "depois, em conexão, escolha cabo ou sem fio\n"
                       "preferindo o cabo, funciona mesmo sem wi-fi")
        else:
            curto = "sem cabo, android 11 ou mais novo."
            detalhe = ("com código\n"
                       "no celular: opções do desenvolvedor ›\n"
                       "depuração sem fio › parear o dispositivo\n"
                       "com código de pareamento\n"
                       "o endereço aparece sozinho; digite o código")
        self._info(esq, curto, detalhe).pack(side="top", fill="x",
                                             pady=(E.px(12), E.px(0)))
        if self._metodo == "cabo":
            self._acao_cabo(dir_)
        else:
            self._acao_codigo(dir_)

    def _recamada(self, w) -> None:
        """(08/out) Conteudo refeito dentro de um painel: repinta na cor dele
        (o que nasce na cor do fundo)."""
        p = w
        while p is not None and not getattr(p, "_camada", None):
            p = getattr(p, "master", None)
        if p is not None:
            E.camada(p, p._camada)

    def _escolheu_metodo(self, valor: str) -> None:
        self._metodo = valor
        self._montar_conteudo()

    # (r192) SELETOR DE CONEXAO (pedido dele, 30/set/2026): sem fio ou cabo,
    # trocado sem parar o adb. A regra fica no programa; aqui so a escolha e
    # a linha que diz qual esta em uso agora.
    CONEXOES = [("sem_fio", "sem fio"), ("cabo", "cabo")]

    def _seletor_de_conexao(self, pai) -> None:
        # (08/out) o titulo e o painel vem de quem chama (`_seg`)
        seg = E.Segmentado(pai, self.CONEXOES,
                           self.programa.conexao_preferida(),
                           self._escolheu_conexao)
        seg.pack(side="top", fill="x")
        linha = E.Texto(pai, "", cor=E.APAGADO, largura=E.px(230))
        linha.pack(side="top", fill="x", pady=(E.px(6), E.px(0)))
        self._ui["linha_conexao"] = linha
        # (07/out, pedido dele: "1 clique e pode tirar o cabo") com o cabo
        # ligado e sem o sem fio de pe, um botao abre o sem fio na hora
        b = E.Botao(pai, "abrir sem fio pelo cabo", self._abrir_sem_fio_ja,
                    tipo="contorno")
        self._ui["botao_sem_fio"] = b
        self._pintar_conexao()

    def _abrir_sem_fio_ja(self) -> None:
        if not self.programa.abrir_sem_fio_agora():
            self._pintar_status("ligue o celular no pc pelo cabo.", E.ALERTA)
        self._pintar_conexao()

    def _escolheu_conexao(self, valor: str) -> None:
        self.programa.definir_conexao(valor)
        self._pintar_conexao()

    def _texto_da_conexao(self) -> tuple[str, str]:
        p = self.programa
        quer, usa = p.conexao_preferida(), p.conexao_em_uso()
        de_pe = p.conexoes_de_pe()
        nome = {"cabo": "cabo", "sem_fio": "sem fio"}
        # (07/out) o cabo abrindo o sem fio (sozinho ou pelo botao) manda
        estado, texto = p.estado_sem_fio()
        if estado:
            return texto, {"abrindo": E.TEXTO_2, "pronto": E.VERDE,
                           "falhou": E.ALERTA}[estado]
        if not usa:
            return "nenhum celular em uso.", E.APAGADO
        if usa == quer:
            texto = "em uso: %s." % nome[usa]
            if p.sessoes:
                texto += " o que abrir agora usa esta conexão."
            return texto, E.TEXTO_2
        if quer not in de_pe:
            falta = ("cabo não está ligado" if quer == "cabo"
                     else "sem fio não está conectado")
            return ("em uso: %s — %s." % (nome[usa], falta)), E.APAGADO
        return "trocando para %s…" % nome[quer], E.TEXTO_2

    def _pintar_conexao(self) -> None:
        linha = self._ui.get("linha_conexao")
        if linha is None or not linha.winfo_exists():
            return
        texto, cor = self._texto_da_conexao()
        if linha.cget("text") != texto or linha.cget("fg") != cor:
            linha.configure(text=texto, fg=cor)
        b = self._ui.get("botao_sem_fio")
        if b is not None and b.winfo_exists():
            p = self.programa
            estado = p.estado_sem_fio()[0]
            de_pe = p.conexoes_de_pe()
            mostrar = "cabo" in de_pe and estado != "pronto" and (
                "sem_fio" not in de_pe or estado == "falhou")
            if mostrar and not b.winfo_manager():
                b.pack(side="top", anchor="w", pady=(E.px(8), 0))
            elif not mostrar and b.winfo_manager():
                b.pack_forget()
            if b._ligado != (estado != "abrindo"):
                b.definir(ligado=estado != "abrindo")

    def _e_o_em_uso(self, achado) -> bool:
        cel = self.programa.celular or {}
        if achado.estado != conexao.PRONTO:
            return False        # (01/out) mesmo modelo nao e o mesmo aparelho
        return bool(cel.get("serial")) and (
            achado.serial == cel.get("serial") or
            (bool(cel.get("modelo")) and achado.modelo == cel.get("modelo")))

    def _mostrar_achados(self) -> None:
        lista = self._ui.get("lista_parear")
        if lista is None or not lista.winfo_exists():
            return
        for f in lista.winfo_children():
            f.destroy()
        # (08/out) o que nascer aqui na cor do fundo fica na cor do painel
        self.after_idle(lambda: lista.winfo_exists() and self._recamada(lista))
        if self._achados is None:
            E.Texto(lista, "procurando…" if self._trabalhando else
                    "nada procurado ainda.", cor=E.APAGADO).pack(
                side="top", fill="x")
            return
        # (r193) O celular em uso fica na coluna da esquerda, nao aqui.
        outros = [a for a in self._achados if not self._e_o_em_uso(a)]
        if not outros:
            E.Texto(lista, "nenhum outro celular por perto."
                    if self.programa.celular else
                    "nenhum celular por perto.",
                    cor=E.APAGADO, largura=E.px(230)).pack(side="top",
                                                           fill="x")
            return
        for achado in outros[:4]:
            linha = self._cartao(lista)          # (07/out) cartao da casa
            linha.configure(cursor="arrow")
            linha.pack(side="top", fill="x", pady=(E.px(0), E.px(5)))
            # (01/out) Nao conectado ainda: "conectar" leva ao jeito certo
            # (cabo = o fluxo do cabo; sem fio nunca pareado = o codigo).
            pronto = achado.estado == conexao.PRONTO
            E.Botao(linha, "usar" if pronto else "conectar",
                    lambda a=achado: self._usar(a),
                    tipo="contorno" if self.programa.celular else "acao",
                    bg=E.CAMADA_1).pack(side="right", padx=E.px(4),
                                        pady=E.px(4))
            textos = tk.Frame(linha, bg=E.CAMADA_1)
            textos.pack(side="left", fill="x", expand=True, padx=E.px(8), pady=E.px(4))
            tk.Label(textos, text=achado.modelo, bg=E.CAMADA_1,
                     fg=E.TEXTO, font=E.fonte(E.PEQUENA), anchor="w").pack(
                side="top", fill="x")
            if achado.estado == conexao.PERMITIR:
                sub = "cabo · falta permitir"
            elif achado.estado == conexao.PAREAR:
                sub = "sem fio · falta parear"
            elif achado.sem_fio:
                sub = "sem fio" + (" · %s" % achado.endereco
                                   if achado.endereco else "")
            else:
                sub = "pelo cabo"
            tk.Label(textos, text=sub, bg=E.CAMADA_1,
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
        if (self._item == "parear" and self._aba["parear"] == "conexao"
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
        # (r193) A lista FICA: o celular que estava em uso passa a aparecer
        # nela (o filtro de `_mostrar_achados` tira so o novo em uso).
        # (r193) "usar" num celular da lista = ESTE celular (antes o programa
        # procurava de novo e, com dois, podia ficar com o outro).
        if achado.estado == conexao.PERMITIR:
            self._conectar_cabo()       # espera o "Permitir" e segue
            return
        if achado.estado == conexao.PAREAR:
            self._ir_parear(achado.endereco)
            return
        self._usando = achado.serial
        if not achado.sem_fio:
            if self.programa.conexao_preferida() == "cabo":
                # (r192) Preferindo o cabo: usa ele como esta.
                self._terminou(conexao.Resultado(
                    True, "pronto: %s em uso, pelo cabo." % achado.modelo,
                    modelo=achado.modelo))
                return
            # So no cabo: o mesmo caminho de ADICIONAR › com cabo, que abre
            # a conexao sem fio (o serial muda: quem decide e o programa).
            self._usando = ""
            self._conectar_cabo()
            return
        self._terminou(conexao.Resultado(
            True, "pronto: %s em uso, sem fio%s." % (
                achado.modelo, (" (%s)" % achado.endereco)
                if achado.endereco else ""),
            modelo=achado.modelo, endereco=achado.endereco))

    def _acao_cabo(self, dir_) -> None:
        """ADICIONAR › com cabo: os passos e o botao (coluna da direita)."""
        for n, passo in enumerate((
                "no celular, ative a depuração usb (opções do "
                "desenvolvedor).",
                "ligue o celular no pc pelo cabo.",
                "clique em conectar e aceite o aviso no celular.")):
            linha = tk.Frame(dir_, bg=E.FUNDO)
            linha.pack(side="top", fill="x", pady=(E.px(0), E.px(6)))
            tk.Label(linha, text="%d" % (n + 1), bg=E.FUNDO, fg=E.ACENTO,
                     font=E.fonte(E.PEQUENA, "bold"), width=2,
                     anchor="nw").pack(side="left", anchor="n")
            E.Texto(linha, passo, largura=E.px(200)).pack(side="left", fill="x")
        b = E.Botao(dir_, "conectar", self._conectar_cabo, tipo="acao")
        b.pack(side="top", fill="x", pady=(E.px(8), E.px(0)))
        b.definir(ligado=not self._trabalhando)
        self._ui["acao_parear"] = b
        self._status(dir_)

    def _conectar_cabo(self) -> None:
        self._trabalhar("cabo", conexao.conectar_pelo_cabo)

    def _acao_codigo(self, dir_) -> None:
        """ADICIONAR › com codigo: os campos e o botao (coluna da direita)."""
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
        self._endereco_auto = ""
        self._pedir_endereco()

    # (01/out) O ENDERECO SE PREENCHE SOZINHO: com a tela "parear com codigo"
    # aberta, o celular anuncia o endereco do parear na rede. Enquanto a tela
    # do codigo esta a vista, o programa pergunta ao adb a cada 1,5 s e poe
    # no campo (sem apagar o que a pessoa digitou); ela so digita o codigo.

    def _ir_parear(self, ip: str = "") -> None:
        """"conectar" num celular sem fio nunca pareado: vai direto ao codigo."""
        self._ip_parear = ip
        self._metodo = "codigo"
        self._escolher_aba("adicionar")

    def _na_tela_do_codigo(self) -> bool:
        return (self._item == "parear" and self._aba["parear"] == "adicionar"
                and self._metodo == "codigo")

    def _pedir_endereco(self) -> None:
        if getattr(self, "_perguntando_endereco", False):
            return
        if not self._na_tela_do_codigo() or not self._visivel:
            return
        adb = self._config.adb_exe
        ip = getattr(self, "_ip_parear", "")
        self._perguntando_endereco = True

        def perguntar():
            try:
                endereco = conexao.endereco_de_parear(adb, ip)
            except Exception:
                endereco = ""
            self._da_outra_thread.put(
                lambda e=endereco: self._chegou_endereco(e))

        threading.Thread(target=perguntar, daemon=True,
                         name="endereco-parear").start()

    def _chegou_endereco(self, endereco: str) -> None:
        self._perguntando_endereco = False
        if not self._na_tela_do_codigo():
            return
        campo = self._ui.get("campo_endereco")
        if endereco and campo is not None and campo.winfo_exists():
            atual = campo.get().strip()
            if atual in ("", self._endereco_auto) and atual != endereco:
                campo.delete(0, "end")
                campo.insert(0, endereco)
                self._endereco_auto = endereco
                codigo = self._ui.get("campo_codigo")
                if codigo is not None and not codigo.get().strip():
                    codigo.focus_set()
                self.programa.anotar("parear: endereco achado na rede (%s)"
                                     % endereco)
        self.after(1500, self._pedir_endereco)

    def _campo(self, pai, rotulo: str, dica: str) -> tk.Entry:
        linha = tk.Frame(pai, bg=E.FUNDO)
        linha.pack(side="top", fill="x", pady=(E.px(0), E.px(3)))
        tk.Label(linha, text=rotulo, bg=E.FUNDO, fg=E.TEXTO_2,
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
            self.programa.ler_celular_agora(
                getattr(self, "_usando", "") or
                getattr(resultado, "serial", ""))
            self._usando = ""
            if self._item == "parear" and self._aba["parear"] == "adicionar":
                # (r193) Adicionou: volta ao dia a dia, com ele em uso.
                self.after(1500, lambda: (
                    self._item == "parear" and
                    self._aba["parear"] == "adicionar" and
                    self._escolher_aba("conexao")))
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
            if len(self._achados) == 1 and \
                    self._achados[0].estado == conexao.PRONTO and (
                    self._achados[0].sem_fio or
                    self.programa.conexao_preferida() == "cabo") and \
                    not self.programa.celular and \
                    not self.programa.conexao_pausada:
                self._usar(self._achados[0])
                return
            if self.programa.celular or (
                    not self._achados and
                    "permitir" not in resultado.texto.lower()):
                # (r193) A lista basta: sem "achei N celulares" no status, e
                # sem "nenhum celular" (a coluna da esquerda ja diz). Fica
                # so o aviso de tocar em Permitir no celular.
                self._pintar_status("")
                self._mostrar_achados()
                self._repintar()
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
    # NOTIFICACOES (01/out/2026, pedido dele)
    # ==========================================================================
    # As do celular, como no celular (agrupadas por app, x remove la tambem),
    # o historico de 24 h (o Android nega o dele ao shell: e o que o programa
    # viu) e as chaves (a geral e o padrao; cada app, a excecao). O estado
    # vem de `programa.notif` (notificacoes.Central); a lista so e refeita
    # quando a "versao" dele muda.

    NOTIF_TEXTO_MAX = 180
    HIST_MAX = 150

    def _nome_notif(self, app: str) -> str:
        from . import notificacoes
        pacote, _, usuario = app.partition("@")
        for fonte in (self._apps, getattr(self.programa, "apps_do_celular",
                                          None)):
            for nome, p, _s in (fonte or []):
                if p == app:
                    return nome
        nome = (self._config.apps.get("nomes") or {}).get(pacote) or \
            notificacoes.nome_de_sistema(pacote) or pacote.split(".")[-1]
        return nome + (" (%s)" % usuario if usuario else "")

    def _app_abre(self, app: str) -> bool:
        """Da para abrir em janela (esta na lista de apps do celular)?"""
        lista = self._apps or getattr(self.programa, "apps_do_celular",
                                      None) or []
        return any(p == app for _n, p, _s in lista)

    def _quando_notif(self, ms) -> str:
        import datetime
        try:
            t = float(ms or 0) / 1000.0
        except (TypeError, ValueError):
            return ""
        if t <= 0:
            return ""
        passou = time.time() - t
        if passou < 60:
            return "agora"
        if passou < 3600:
            return "%d min" % (passou // 60)
        d = datetime.datetime.fromtimestamp(t)
        if d.date() == datetime.date.today():
            return d.strftime("%H:%M")
        return d.strftime("%d/%m %H:%M")

    def _lista_notif(self, pai, chave_ui: str = "rolagem_notif") -> _Rolagem:
        caixa = tk.Frame(pai, bg=E.FUNDO)
        caixa.pack(side="top", fill="both", expand=True)
        rol = _Rolagem(caixa)
        self._ui[chave_ui] = rol
        return rol

    def _lista_com_topo(self, area, titulo: str,
                        chave_ui: str = "rolagem_notif") -> tk.Frame:
        """
        (03/out/2026, pedido dele: "o mesmo efeito da aba apps") A lista
        ocupa a ABA INTEIRA (ate as linhas que a limitam) e o cabecalho --
        titulo e links -- vira uma barrinha arredondada FLUTUANDO no alto:
        os cartoes rolam por tras dela. Devolve a barrinha (os links vao
        nela, a direita).
        """
        caixa = tk.Frame(area, bg=E.FUNDO)
        caixa.pack(side="top", fill="both", expand=True)
        m, alto = E.PADDING, E.px(30)
        rol = _Rolagem(caixa, sobreposta=True,
                       margem_topo=m + alto + E.px(8), margem_base=m,
                       margem_lados=m)
        self._ui[chave_ui] = rol
        topo = tk.Frame(caixa, bg=E.CAMADA_2, highlightthickness=1,
                        highlightbackground=E.BORDA_2)
        topo.place(x=m, y=m, relwidth=1.0, width=-2 * m, height=alto)
        E.Rotulo(topo, titulo, bg=E.CAMADA_2).pack(
            side="left", padx=(E.px(10), 0))
        E.cantos(topo)
        return topo

    def _link_no_topo(self, topo, texto: str, acao) -> tk.Label:
        """(07/out, pedido dele) Os botoes da barrinha flutuante viraram
        PILULAS (as dos cartoes, One UI): fundo +8% de texto, +16% com o
        mouse -- eram texto solto."""
        base = E._mistura(E.TEXTO, E.CAMADA_2, 0.08)
        sobre = E._mistura(E.TEXTO, E.CAMADA_2, 0.16)
        lk = self._link(topo, texto, acao)
        lk.configure(bg=base, highlightbackground=E.CAMADA_2,
                     font=E.fonte(E.ROTULO), padx=E.px(9), pady=0)
        lk._fundos = (base, sobre)

        def pintar(dentro):
            try:
                lk.configure(bg=sobre if dentro else base,
                             fg=E.TEXTO if dentro else
                             getattr(lk, "_fg", E.TEXTO_2))
                E.cantos(lk, raio=E.px(9))
            except tk.TclError:
                pass
        lk.bind("<Enter>", lambda _e: pintar(True))
        lk.bind("<Leave>", lambda _e: pintar(False))
        E.cantos(lk, raio=E.px(9))
        return lk

    def _tela_notif_lista(self, area) -> None:
        self._ui["notif_tipo"] = "lista"
        topo = self._lista_com_topo(area, "no celular agora")
        # (02/out) O "nao perturbe" do celular, daqui (como o atalho da
        # barra do Android). Some enquanto nao se sabe o estado. Numa caixa
        # propria: o "limpar tudo" some e volta sem trocar de lugar com ele.
        caixa_zen = tk.Frame(topo, bg=E.CAMADA_2)
        caixa_zen.pack(side="right", padx=(0, E.px(4)))
        lim = self._link_no_topo(topo, "limpar tudo", self._limpar_notif)
        lim.pack(side="right")
        self._ui["notif_limpar"] = lim
        zen = self._link_no_topo(caixa_zen, "", self._virar_zen)
        self._ui["notif_zen"] = zen
        self.programa.notif.ler_nao_perturbe()
        self._ui["notif_pintada"] = None
        self._pintar_notif()

    def _acertar_zen(self) -> None:
        zen = self._ui.get("notif_zen")
        if zen is None or not zen.winfo_exists():
            return
        estado = self.programa.notif.zen
        if estado is None:
            if zen.winfo_manager():
                zen.pack_forget()
            return
        # (07/out) pilula: ligado = o texto em laranja (estado)
        texto = "não perturbe: ligado" if estado else "não perturbe"
        if zen.cget("text") != texto:
            zen._fg = E.ACENTO if estado else E.TEXTO_2
            zen.configure(text=texto, fg=zen._fg)
        if not zen.winfo_manager():
            zen.pack(side="right", padx=(E.px(6), 0))

    def _virar_zen(self) -> None:
        c = self.programa.notif
        if c.zen is None:
            return
        c.virar_nao_perturbe(not c.zen)

    def _tela_notif_historico(self, area) -> None:
        self._ui["notif_tipo"] = "historico"
        topo = self._lista_com_topo(area, "últimas 24 horas")
        self._link_no_topo(topo, "limpar histórico", self._limpar_hist).pack(
            side="right", padx=(0, E.px(10)))
        self._ui["notif_pintada"] = None
        self._pintar_notif()

    def _tela_notif_ajustes(self, area) -> None:
        self._ui["notif_tipo"] = "ajustes"
        col_esq, dir_ = self._duas(area)
        esq = self._seg(col_esq, "avisos no pc")
        self._ui["notif_geral"] = self._chave(
            esq, "todos os apps", self._config.opcao("notif_pc"),
            self._virar_notif_geral, borda=False,
            explicacao="liga ou desliga todos de uma vez")
        self._info(esq, "os apps ao lado são as exceções.",
                   "como funciona\n"
                   "ligada: todos avisam, menos os desligados ao lado\n"
                   "desligada: nenhum avisa, menos os ligados\n"
                   "nada disso muda o celular").pack(
            side="top", fill="x", pady=(E.px(4), 0))
        # (01/out) No Windows (central_windows). (08/out) no mesmo painel
        self._sub(esq, "no windows")
        self._chave(esq, "central do windows",
                    self._config.opcao("notif_windows"),
                    lambda v: self._virar_windows_notif("notif_windows", v),
                    explicacao="também na central de notificações",
                    borda=False)
        # (03/out, pedido dele: "o mesmo da aba apps") A lista POR APP vai
        # ate as linhas da coluna; a busca flutua por cima, na superficie.
        # (08/out, pedido dele) a lista NUM SEGMENTO, como o resto: o painel
        # ocupa o lugar da coluna; as linhas nascem ja na cor dele
        P = E.PAINEL
        painel = E.painel(dir_.master, P, fill="both", expand=True,
                          padx=(E.px(4), E.PADDING), pady=E.PADDING)
        dir_.pack_forget()
        m, alto = E.px(10), E.px(30)
        caixa = tk.Frame(painel, bg=P)
        caixa.pack(fill="both", expand=True)
        rol = _Rolagem(caixa, sobreposta=True, margem_topo=m + alto + E.px(8),
                       margem_base=m, margem_lados=m)
        for w in (rol.canvas, rol.barra, rol.dentro):
            w.configure(bg=P)
        self._ui["rolagem_notif"] = rol
        # (09/out) as linhas com `place` e o filtro animado; as que a busca
        # tira sao so escondidas (a chave de cada app continua viva)
        arr = FA.Arranjo(rol.dentro, rol.canvas, P)
        arr.guardar = True
        self._ui["arranjo_notif"] = arr
        busca = self._barra_de_busca(caixa, getattr(self, "_busca_notif", ""),
                                     "buscar", self._buscou_notif,
                                     altura=alto)
        busca.master.place(x=m, y=m, relwidth=1.0, width=-2 * m, height=alto)
        busca.master.lift()
        E.cantos(busca.master)
        self._ui["busca_notif"] = busca
        self._ui["notif_pintada"] = None
        self._pintar_notif()
        if self._apps is None and not self._apps_carregando:
            self._carregar_apps()

    def _tela_notif_player(self, area) -> None:
        """(03/out, pedido dele) A musica do celular fora da janela: nos
        controles de midia do Windows e no MINI PLAYER (o da bandeja)."""
        col_esq, col_dir = self._duas(area)
        # (08/out, pedido dele: juntar por assunto) a esquerda o MINI PLAYER
        # (tamanho, transparencia, abrir); a direita QUANDO ELE APARECE e o
        # player do windows
        esq = self._seg(col_esq, "mini player")
        self._fila(esq, "tamanho", self.MINI_TAMANHOS,
                   self._mini_ajuste("mini_tamanho", "m"),
                   lambda v: self._mini_mudou("mini_tamanho", v))
        transp = float(self._mini_ajuste("mini_transp", 0.0))
        self._rotulo_valor(esq, "transparência",
                           "%d%%" % round(transp * 100), "mini_transp")
        E.Deslizador(esq, transp / 0.7,
                     lambda v: self._mini_transp(v, False),
                     lambda v: self._mini_transp(v, True)).pack(
            side="top", fill="x", pady=(E.px(0), E.px(8)))
        E.Botao(esq, "abrir o mini player", self.alternar_mini_player,
                tipo="discreto").pack(side="top", fill="x")
        self._info(esq, "também pela bandeja e por atalho.",
                   "outros jeitos de abrir\n"
                   "o ícone ao lado do relógio (botão direito)\n"
                   "um atalho em opções › atalhos").pack(
            side="top", fill="x", pady=(E.px(6), 0))
        esq = self._seg(col_dir, "quando aparece")
        self._chave(esq, "abrir quando a música começar",
                    bool(self._mini_ajuste("mini_auto", False)),
                    lambda v: self._mini_mudou("mini_auto", bool(v)),
                    explicacao="aparece por alguns segundos e some")
        self._chave(esq, "ficar aberto",
                    bool(self._mini_ajuste("mini_fixo", False)),
                    lambda v: self._mini_mudou("mini_fixo", bool(v)),
                    explicacao="não some ao clicar fora; arraste para mudar "
                               "o lugar", borda=False)
        dir_ = esq
        self._sub(dir_, "no windows")
        self._chave(dir_, "player no windows",
                    self._config.opcao("player_windows"),
                    lambda v: self._virar_windows_notif("player_windows", v),
                    explicacao="a música nos controles de mídia do windows",
                    borda=False)

    def _buscou_notif(self) -> None:
        b = self._ui.get("busca_notif")
        self._busca_notif = b.get() if b is not None else ""
        if self._ui.get("arranjo_notif") is not None:
            # (09/out, relato dele: "a busca dos ajustes nao funciona") com
            # a lista rolada para baixo o resultado ficava FORA da vista (a
            # area parecia vazia): a busca volta ao topo, e anima
            if getattr(self, "_busca_notif_id", None):
                self.after_cancel(self._busca_notif_id)
            self._busca_notif_id = self.after(
                120, lambda: self._filtrar_notif(animar=True))
            return
        self._filtrar_notif()               # no lugar, sem remontar

    def _pintar_notif(self) -> None:
        # (09/out, achado no relato "a busca dos ajustes nao funciona") o
        # tipo vem da TELA (o `_ui`), nao da aba escolhida: montando os
        # ajustes escondidos (de antemao) com a aba "notificacoes" a vista,
        # a lista animada tomava o canvas dos ajustes e escondia as linhas
        aba = self._ui.get("notif_tipo") or self._aba.get("notif")
        rol = self._ui.get("rolagem_notif")
        if rol is None or not rol.canvas.winfo_exists():
            return
        try:
            if aba == "lista":
                self._pintar_notif_lista(rol)
            elif aba == "historico":
                self._pintar_notif_hist(rol)
            elif aba == "ajustes":
                self._pintar_notif_ajustes(rol)
        except tk.TclError:
            pass

    # LISTAS SEM PISCAR (01/out, "otimizacao geral da aba"): notificacoes e
    # historico nao sao mais refeitos a cada mudanca do celular (a
    # "carregando" do sistema muda a cada ~40 s) nem a cada minuto (a hora).
    # Cada cartao/linha nasce uma vez e fica guardado pela chave; numa
    # mudanca so entra o novo, sai o que saiu e a ordem e acertada com
    # pack/pack_forget. A hora ("2 min") troca no lugar (`_horas_notif`).

    def _largura_texto_notif(self) -> int:
        """Quebra de linha do texto: a largura da area menos margens, fixa
        (a do canvas ainda e 1 px quando a tela esta montando)."""
        return (E.LARGURA - E.LARGURA_LISTA - 2 * E.PADDING - E.px(10)
                - E.px(24))

    def _repor_notif(self, d, querido: list) -> None:
        """Deixa em `d` exatamente os widgets de `querido`, nessa ordem.
        (03/out, teste dele: "a aba redesenha toda vez") So MEXE no que saiu
        do lugar: tirar todos e repor escondia e mostrava a lista inteira
        (e a rolagem voltava ao topo) a cada cartao aberto ou refeito."""
        atual = d.pack_slaves()
        if atual == querido:
            return
        fica = set(querido)
        for w in atual:
            if w not in fica:
                w.pack_forget()
        atual = [w for w in atual if w in fica]
        for i, w in enumerate(querido):
            if i < len(atual) and atual[i] is w:
                continue
            jeito = dict(side="top", fill="x", pady=getattr(w, "_pady", 0))
            if i < len(atual):
                w.pack(before=atual[i], **jeito)
            else:
                w.pack(**jeito)
            if w in atual:
                atual.remove(w)
            atual.insert(i, w)

    def _sem_piscar(self, fazer) -> None:
        """Uma mudanca feita pelo clique dele aparece de uma vez so (a area
        nao e pintada pela metade enquanto os widgets mudam)."""
        palco = self._ui.get("_palco")
        self._congelar_area(True)
        try:
            fazer()
        finally:
            self._congelar_area(False, (palco,) if palco is not None else ())


    def _horas_notif(self) -> None:
        """Atualiza "agora"/"2 min"/"08:12": refaz so os blocos que tem hora
        (no canvas: sem piscar)."""
        lista = self._ui.get("notif_lista_anim")
        if lista is None:
            return
        # (03/out, revisao) so os que o texto da hora mudou ("1 min" ->
        # "2 min"); o historico tem ate 150 e eram todos a cada 20 s
        feitos = self._ui.setdefault("notif_horas_txt", {})
        for k, quando in list(self._ui.get("notif_horas", ())):
            texto = self._quando_notif(quando)
            if feitos.get(k) != texto:
                feitos[k] = texto
                lista.redesenhar(k)

    # LISTA NUM CANVAS SO (03/out/2026, teste dele: "a tela ainda pisca ao
    # redesenhar" + "animacoes suaves como no celular"). Cada cartao era um
    # Frame (uma janela do Windows): mexer num movia as de baixo e o Windows
    # repintava uma a uma. Agora o cartao e DESENHADO (`lista_animada`) e as
    # mudancas andam com os tempos do Android (docs/contexto/animacoes.md).

    def _lista_anim(self, rol):
        from .lista_animada import ListaAnimada
        lista = self._ui.get("notif_lista_anim")
        if lista is not None and lista.c is rol.canvas:
            return lista
        try:
            rol.canvas.itemconfigure(rol._item, state="hidden")
        except tk.TclError:
            pass
        lista = ListaAnimada(rol.canvas, E.FUNDO, rol.margem_topo,
                             rol.margem_lados, rol.margem_base)
        lista.animar = moldura.animacoes_ligadas()
        lista.ao_clicar = self._clicou_na_lista
        lista.ao_menu = self._menu_na_lista
        lista.ao_dispensar = self._dispensou_na_lista
        lista.arrastavel = self._arrastavel_na_lista
        lista.clicavel = self._clicavel_na_lista
        self._ui["notif_lista_anim"] = lista
        return lista

    def _definir_lista(self, lista, itens: list) -> None:
        """A primeira pintura da tela entra parada; as mudancas, andando."""
        lista.definir(itens, animar=bool(self._ui.get("notif_lista_pronta")))
        self._ui["notif_lista_pronta"] = True

    @staticmethod
    def _bloco_texto(texto: str, cor=None, fonte=None, topo: int = 0):
        def desenhar(p):
            _it, h = p.texto(p.x0, p.y + topo, texto,
                             fonte or E.fonte(E.PEQUENA), cor or E.APAGADO,
                             largura=p.largura)
            return h + topo
        return desenhar

    def _pintar_notif_lista(self, rol) -> None:
        c = self.programa.notif
        notifs = c.visiveis()
        cel = bool((self.programa.celular or {}).get("serial"))
        # (01/out) O PLAYER no topo, como no celular; o cartao de midia do
        # mesmo app (e o "MediaOngoingActivity" do Samsung) sai da lista.
        jogador = c.player() if cel else None
        if jogador is not None:
            notifs = [n for n in notifs if not (
                (n.modelo == "MediaStyle" and n.pacote == jogador["pacote"])
                or (n.pacote == "com.android.systemui"
                    and n.canal == "MediaOngoingActivity"))]
        # As que ele tirou aqui: fora ja, sem esperar o celular confirmar
        # (senao voltavam por um instante).
        agora = time.monotonic()
        fora = self._notif_dispensadas
        for k in [k for k, t in fora.items() if agora - t > 8.0]:
            del fora[k]
        notifs = [n for n in notifs if n.chave not in fora]
        tem = any(n.limpavel for n in notifs)
        capa = c.capa(jogador["pacote"]) if jogador is not None else None
        assin = (cel, tuple((n.chave, n.aparencia(), n.limpavel, n.quando)
                            for n in notifs), self._icones_versao,
                 frozenset(self._config.apps.get("notif") or {}),
                 self._config.opcao("notif_pc"), c.zen,
                 frozenset(self._notif_abertas), c.ouvinte_versao,
                 self._respondendo, tuple(sorted(
                     self._recado_resposta.items())),
                 tuple(sorted(self._acao_pendente)), frozenset(fora),
                 None if jogador is None else (
                     jogador["pacote"], jogador["estado"], jogador["titulo"],
                     jogador["artista"], jogador["dur"], jogador["acoes"],
                     len(capa or b"")))
        if assin == self._ui.get("notif_pintada"):
            return
        self._ui["notif_pintada"] = assin
        self._acertar_zen()
        # (01/out, teste dele) Sem nada que se possa tirar, o link some.
        lim = self._ui.get("notif_limpar")
        if lim is not None:
            if tem and not lim.winfo_manager():
                lim.pack(side="right")
            elif not tem and lim.winfo_manager():
                lim.pack_forget()
        cx = self._ui.get("notif_caixa")
        if cx is not None and cx[0] != self._respondendo:
            self._ui.pop("notif_caixa", None)
            try:
                cx[1].destroy()
            except tk.TclError:
                pass
        lista = self._lista_anim(rol)
        itens = []
        if jogador is not None:
            pl = self._acertar_player(rol.canvas, jogador)
            alto = E.px(self.PLAYER_ALTURA)
            itens.append(("player", lambda p, w=pl, a=alto: (
                p.janela(w, p.x0, p.y, largura=p.largura, altura=a), a)[1],
                ("player",), E.px(8)))
        msg = ""
        if not cel:
            msg = "nenhum celular conectado."
        elif not notifs and jogador is not None:
            pass                              # so o player: sem mensagem
        elif not notifs:
            ocultas = sum(1 for n in c.todas()
                          if not c.ligada(n.app) and not n.resumo)
            msg = "nenhuma notificação." + (
                "\n%d de apps desligados no pc (veja em ajustes)." % ocultas
                if ocultas else "")
        elif not tem:
            msg = "estas o celular não deixa dispensar: só o próprio app " \
                  "tira."
        if msg:
            itens.append(("msg", self._bloco_texto(msg), ("msg", msg),
                          E.px(6)))
        # (03/out, pedido dele) ORDEM POR HORA, ESTAVEL: a mais recente em
        # cima. O grupo (por app) fica na hora da sua mais nova e so SOBE
        # quando chega uma mais nova; tirar notificacoes nao reordena nada
        # (antes era o "rank" do celular, que muda a cada uma tirada e fazia
        # os cartoes trocarem de lugar). As silenciosas ficam embaixo, como
        # no Android.
        grupos: dict = {}
        for n in (notifs if cel else []):
            grupos.setdefault(n.app, []).append(n)
        tempo, item = self._notif_tempo_grupo, self._notif_tempo_item
        vivas = {n.chave for ns in grupos.values() for n in ns}
        for app in [a for a in tempo if a not in grupos]:
            del tempo[app]
        for k in [k for k in item if k not in vivas]:
            del item[k]
        for app, ns in grupos.items():
            for n in ns:
                # A fixa que se atualiza (download, "carregando") nao sobe
                # a cada atualizacao; mensagem nova numa conversa sobe.
                q = n.quando or 0
                if n.chave not in item or (not n.fixa and q > item[n.chave]):
                    item[n.chave] = q
            ns.sort(key=lambda n: -item[n.chave])
            mais_nova = item[ns[0].chave]
            if mais_nova > tempo.get(app, -1):
                tempo[app] = mais_nova
        grupos = dict(sorted(
            grupos.items(),
            key=lambda kv: (all(n.secao == 2 for n in kv[1]),
                            -tempo[kv[0]], kv[0])))
        horas, cronos, girando, dados = [], [], [], {}
        largura = self._largura_texto_notif()
        rotulo_posto = False
        for app, ns in grupos.items():
            if all(n.secao == 2 for n in ns) and not rotulo_posto:
                itens.append(("silenciosas", self._bloco_texto(
                    "SILENCIOSAS", E.APAGADO, E.fonte(E.ROTULO), E.px(6)),
                    ("sil",), E.px(2)))
                rotulo_posto = True
            nome = self._nome_notif(app)
            varias = sum(1 for n in ns if n.limpavel) > 1
            itens.append(("cab|" + app, lambda p, a=app, nm=nome, t=len(ns),
                          v=varias: self._desenhar_cabeca(p, a, nm, t, v),
                          (nome, len(ns), varias, self._icones_versao,
                           self._config.apps.get("sem_icones")), E.px(3)))
            for n in ns:
                k = "n|" + n.chave
                aberto = n.chave in self._notif_abertas
                mais = self._tem_mais_notif(n, largura)
                forma = self._forma_notif(n, aberto, mais)
                pend = tuple(sorted(i for ch, i in self._acao_pendente
                                    if ch == n.chave))
                itens.append((k, lambda p, a=app, nn=n:
                              self._desenhar_cartao(p, a, nn),
                              (n.aparencia(), forma, pend), E.px(5)))
                dados[k] = (app, n)
                if n.cronometro:
                    cronos.append(k)
                else:
                    horas.append((k, n.quando))
                if n.progresso is not None and n.progresso[2]:
                    girando.append(k)
        self._ui["notif_dados"] = dados
        self._ui["notif_horas"] = horas
        self._ui["notif_horas_txt"] = {k: self._quando_notif(q)
                                        for k, q in horas}
        self._ui["notif_cronos"] = cronos
        self._ui["notif_girando"] = girando
        # (02/out) Aberta que saiu do celular nao fica guardada para sempre.
        self._notif_abertas &= {x.chave for x in c.todas()}
        self._definir_lista(lista, itens)

    def _desenhar_icone(self, p, app: str, nome: str, x, y, lado: int,
                        anchor="nw") -> None:
        """O icone do app no canvas (ou a inicial num quadrado)."""
        foto = None if self._config.apps.get("sem_icones") else \
            self._foto(app, lado)
        if foto is not None:
            p.imagem(x, y, foto, anchor=anchor)
            return
        if anchor == "w":
            y -= lado / 2.0
        cor = CORES_DE_APP[sum(map(ord, app)) % len(CORES_DE_APP)]
        p.c.create_rectangle(x, y, x + lado - 1, y + lado - 1,
                             fill=p.cor(cor), width=0, tags=p.tags())
        p.c.create_text(x + lado / 2.0, y + lado / 2.0,
                        text=(nome[:1] or "?").upper(),
                        fill=p.cor("#FFFFFF"),
                        font=E.fonte(E.ROTULO, "bold"), tags=p.tags())

    def _desenhar_cabeca(self, p, app: str, nome: str, total: int,
                         varias: bool) -> int:
        lado = E.px(16)
        y = p.y + E.px(4)
        meio = y + lado / 2.0
        self._desenhar_icone(p, app, nome, p.x0, meio, lado, anchor="w")
        texto = ("%s  ·  %d" % (nome, total)) if total > 1 \
            else nome
        p.texto(p.x0 + lado + E.px(6), meio, texto, E.fonte(E.ROTULO),
                E.TEXTO_2, anchor="w")
        if varias:
            # (08/out, harmonizar) "limpar" na letra do cabecalho (no Android
            # o cabecalho inteiro e um tamanho so); era um ponto maior
            p.texto(p.x1 - E.px(2), meio, "limpar", E.fonte(E.ROTULO),
                    E.TEXTO if p.sobre == "limpar" else E.TEXTO_2,
                    anchor="e", extra=("s:limpar",))
        return lado + E.px(4)

    # -- o que o mouse faz na lista (03/out) -----------------------------------

    def _notif_da_lista(self, k: str):
        return (self._ui.get("notif_dados") or {}).get(k) or (None, None)

    def _clicavel_na_lista(self, k: str, sub) -> bool:
        if sub is not None:
            return True
        app, n = self._notif_da_lista(k)
        return n is not None and (n.alvo is not None or self._app_abre(app))

    def _arrastavel_na_lista(self, k: str) -> bool:
        _app, n = self._notif_da_lista(k)
        return n is not None and n.limpavel

    def _clicou_na_lista(self, k: str, sub, _evento) -> None:
        tipo, _, resto = k.partition("|")
        if tipo == "cab":
            if sub == "limpar":
                self._limpar_notif(resto)
            return
        app, n = self._notif_da_lista(k)
        if n is None:
            return
        chave = n.chave
        if sub == "x":
            self._dispensar_notif(chave)
            self._remover_notif([chave])
        elif sub == "seta":
            self._virar_notif_aberta(chave)
        elif sub == "cod":
            cod = nt_codigo(n)
            if cod:
                self._copiar_codigo(cod)
        elif sub == "enviar":
            self._mandar_resposta()
        elif sub and sub.startswith("a:"):
            i = int(sub[2:])
            o = self.programa.notif.ouvida(chave) or {}
            acoes = o.get("acoes") or []
            if i < len(acoes):
                if acoes[i][1]:
                    self._abrir_resposta(chave)
                else:
                    self._apertar_acao_notif(app, chave, i)
        elif sub and sub.startswith("b:"):
            i = int(sub[2:])
            botoes = nt_botoes(n)
            if i < len(botoes):
                self.programa.abrir_pela_notificacao(app, botoes[i][1])
        elif sub is None and (n.alvo is not None or self._app_abre(app)):
            self._abrir_notif(app, chave)

    def _menu_na_lista(self, k: str, evento) -> None:
        h = (self._ui.get("hist_dados") or {}).get(k)
        if h is not None:
            self._clique_em_qualquer_lugar(evento)
            self._menu_hist(evento, h)
            return
        app, n = self._notif_da_lista(k)
        if n is None:
            return
        # (01/out) o clique geral (bind_all no botao 3) fechava o menu logo
        # depois de abrir: faz o geral antes, como no menu dos apps.
        self._clique_em_qualquer_lugar(evento)
        self._menu_notif(evento, app, n.chave)

    def _caixa_da_casa(self, mensagem: str, titulo: str, botoes,
                       ao_responder=None) -> None:
        """(07/out, padrao) A CAIXA DE AVISO/PERGUNTA da casa (era a do
        Windows): janelinha na SUPERFICIE, no meio da tela onde a janela
        esta, de canto redondo, entra e sai esmaecendo. `botoes` = rotulos
        (o primeiro e o principal, Enter); Esc = o ultimo. ao_responder(r)."""
        j = tk.Toplevel(self)
        j.withdraw()
        j.overrideredirect(True)
        moldura.arredondar_ao_mostrar(j, borda=E.SUPERFICIE_BORDA)
        j.attributes("-topmost", True)
        j.configure(bg=E.SUPERFICIE)
        corpo = tk.Frame(j, bg=E.SUPERFICIE)
        corpo.pack(padx=E.px(18), pady=(E.px(14), E.px(14)))
        tk.Label(corpo, text=(titulo or "scrcpy-f").replace(" -- ", " · "),
                 bg=E.SUPERFICIE,
                 fg=E.APAGADO, font=E.fonte(E.ROTULO), anchor="w").pack(
            side="top", fill="x")
        tk.Label(corpo, text=mensagem, bg=E.SUPERFICIE, fg=E.TEXTO,
                 font=E.fonte(E.PEQUENA), anchor="w", justify="left",
                 wraplength=E.px(380)).pack(side="top", fill="x",
                                            pady=(E.px(6), E.px(14)))
        fila = tk.Frame(corpo, bg=E.SUPERFICIE)
        fila.pack(side="top", fill="x")
        feito = [False]

        def responder(r):
            if feito[0]:
                return
            feito[0] = True
            mov.sair(j, j.destroy)
            if ao_responder is not None:
                ao_responder(r)
        for i, rotulo in enumerate(botoes):     # o principal a direita
            principal = i == 0
            E.Botao(fila, rotulo, lambda r=rotulo: responder(r),
                    tipo="acao" if principal else "discreto",
                    bg=E.SUPERFICIE).pack(side="right",
                                          padx=(E.px(6), 0))
        j.bind("<Return>", lambda _e: responder(botoes[0]))
        j.bind("<Escape>", lambda _e: responder(botoes[-1]))
        j.protocol("WM_DELETE_WINDOW", lambda: responder(botoes[-1]))
        j.update_idletasks()
        l, a = j.winfo_reqwidth(), j.winfo_reqheight()
        try:
            if self._visivel:
                cx = self.winfo_rootx() + self.winfo_width() // 2
                cy = self.winfo_rooty() + self.winfo_height() // 2
            else:
                cx, cy = self.winfo_pointerxy()
            x0, y0, lu, au = moldura.area_util(self, (cx, cy))
            x, y = x0 + (lu - l) // 2, y0 + (au - a) // 2
        except Exception:
            x = (self.winfo_screenwidth() - l) // 2
            y = (self.winfo_screenheight() - a) // 2
        j.geometry("+%d+%d" % (x, y))
        if mov.ligadas():
            j.attributes("-alpha", 0.0)
        j.deiconify()
        mov.entrar(j)
        j.after(150, lambda: j.winfo_exists() and j.focus_force())
        self.programa.anotar("caixa: %s" % mensagem.splitlines()[0][:80])

    def _menu_bandeja(self, x: int, y: int) -> None:
        """(07/out, padrao do botao direito) O menu do icone ao lado do
        relogio, no visual da casa (era o menu do Windows)."""
        p = self.programa

        def rotulo(nome, parado, rodando):
            if p.ocupado(nome):
                return "procurando o celular…"
            return rodando if p.ativo(nome) else parado

        def pedir(nome):
            return lambda: p.pedidos.put(nome)
        opcoes = [("abrir a janela", pedir("mostrar")), None,
                  (rotulo("jogo", "espelhar a tela", "parar o espelhamento"),
                   pedir("jogo")),
                  (rotulo("extensao", "usar como extensão (borda)",
                          "parar a extensão"), pedir("extensao")),
                  ("mini player", pedir("mini_player")), None,
                  ("parear o celular…", pedir("configurar")),
                  ("sair", pedir("sair"))]
        import types
        menu, corpo = self._novo_menu()
        menu._fora = True
        self._encher_menu(menu, corpo, types.SimpleNamespace(
            x_root=x, y_root=y), opcoes)
        try:
            menu.focus_force()
        except tk.TclError:
            pass

    def _menu_texto(self, evento) -> str:
        """Botao direito numa caixa de texto (Entry)."""
        w = evento.widget
        self._clique_em_qualquer_lugar(evento)
        try:
            ligada = str(w.cget("state")) == "normal"
            w.focus_set()
            tem_sel = bool(w.selection_present())
        except tk.TclError:
            return "break"
        try:
            colar = bool(self.clipboard_get()) and ligada
        except tk.TclError:
            colar = False
        opcoes = []
        if tem_sel and ligada:
            opcoes.append(("recortar", lambda: w.event_generate("<<Cut>>")))
        if tem_sel:
            opcoes.append(("copiar", lambda: w.event_generate("<<Copy>>")))
        if colar:
            opcoes.append(("colar", lambda: w.event_generate("<<Paste>>")))
        if w.get():
            if opcoes:
                opcoes.append(None)
            opcoes.append(("selecionar tudo", lambda: (
                w.focus_set(), w.selection_range(0, "end"),
                w.icursor("end"))))
        if not opcoes:
            return "break"
        menu, corpo = self._novo_menu()
        menu._fora = True                # tambem na caixa do aviso do canto
        self._encher_menu(menu, corpo, evento, opcoes)
        return "break"

    def _menu_hist(self, evento, h: dict) -> None:
        """(07/out, padrao do botao direito) Uma linha do historico: abrir o
        app, copiar o texto e a chave de notificacoes do app."""
        app = str(h.get("app") or "")
        opcoes = []
        if app and self._app_abre(app):
            opcoes.append(("abrir o app", lambda: (
                self.programa.abrir_pela_notificacao(app))))
        texto = "\n".join(str(h.get(c) or "") for c in ("titulo", "texto")
                          if h.get(c))
        if texto:
            opcoes.append(("copiar texto", lambda: self._copiar_texto(texto)))
        if app:
            if opcoes:
                opcoes.append(None)
            opcoes.append(("notificações no pc", self._config.notif_do_app(app),
                           lambda v: self._virar_notif_app(app, v)))
        if not opcoes:
            return
        menu, corpo = self._novo_menu()
        self._encher_menu(menu, corpo, evento, opcoes)

    def _dispensou_na_lista(self, k: str) -> None:
        """Arrastou o cartao para o lado: some, como no celular."""
        _app, n = self._notif_da_lista(k)
        if n is None:
            return
        self._notif_dispensadas[n.chave] = time.monotonic()
        self.programa.anotar("notificacoes: arrastou para o lado")
        self._remover_notif([n.chave])
        self.after(MS_DISPENSA, self._pintar_notif)

    def _dispensar_notif(self, chave: str, atraso_ms: int = 0) -> None:
        """O x (e o limpar): o cartao sai de lado e o espaco fecha; o
        celular tira ao mesmo tempo."""
        lista = self._ui.get("notif_lista_anim")

        def fazer():
            self._notif_dispensadas[chave] = time.monotonic()
            if lista is not None:
                lista.dispensar("n|" + chave)
            # o grupo que ficou vazio sai (a cabeca), sem esperar o celular
            self.after(MS_DISPENSA, self._pintar_notif)
        if atraso_ms:
            self.after(atraso_ms, fazer)
        else:
            fazer()

    # -- o cartao, como no Android (02/out, pedido dele) ----------------------
    # RECOLHIDO: titulo e UMA linha de texto; a SETA (so quando ha mais o que
    # ver) abre o cartao: o texto inteiro, as linhas da caixa (InboxStyle),
    # a conversa com quem mandou cada mensagem (MessagingStyle), o resumo e
    # os botoes -- como no celular, os botoes so aparecem aberto. Barra de
    # progresso (download) e cronometro aparecem nos dois. A cor do app
    # (Notification.color) tinge a seta e os botoes; a "colorida" pinta o
    # cartao inteiro. Aberto/fechado fica guardado por notificacao.

    NOTIF_ABERTO_MAX = 1500      # caracteres no aberto (e-mail inteiro nao)
    NOTIF_LINHAS_MAX = 10        # linhas da caixa / mensagens no aberto

    @staticmethod
    def _medir(fonte, texto: str) -> int:
        try:
            return tkfont.nametofont(fonte).measure(texto)
        except (tk.TclError, TypeError):
            return len(texto) * E.px(6)

    def _uma_linha(self, texto: str, fonte, largura: int) -> str:
        """A primeira linha de `texto`, cortada com "…" no que cabe.
        (08/out, relato dele: palavras "bugadas") Medida no texto LIMPO (o
        que aparece) e cortada no fim de uma PALAVRA, como o "WordEllipsis"
        do Windows: so corta no meio quando a palavra sozinha nao cabe ou
        quando voltar ate o espaco jogaria fora mais de um terco da linha."""
        linha = E.texto_limpo(texto or "").strip().split("\n", 1)[0].strip()
        if self._medir(fonte, linha) <= largura:
            return linha
        baixo, alto = 0, len(linha)
        while baixo < alto:                  # busca o maior pedaco que cabe
            meio = (baixo + alto + 1) // 2
            if self._medir(fonte, linha[:meio].rstrip() + "…") <= largura:
                baixo = meio
            else:
                alto = meio - 1
        if 0 < baixo < len(linha) and not linha[baixo].isspace():
            espaco = linha.rfind(" ", 0, baixo)
            if espaco >= baixo * 2 // 3:
                baixo = espaco
        return linha[:baixo].rstrip(" ,;:·-–—") + "…"

    def _cores_notif(self, n) -> dict:
        if n.colorida and n.cor:
            c = VN.cores_colorida(n.cor)
            c["acento"] = "#FFFFFF"
            c["apagado"] = c["texto2"]
            return c
        # (03/out, pedido dele: as notificacoes "na frente" do fundo, nao
        # nele) o cartao e a SUPERFICIE clara, com borda, como os menus
        return {"fundo": E.CAMADA_1, "texto": E.TEXTO, "texto2": E.TEXTO_2,
                "linha": E.BORDA_1, "apagado": E.APAGADO,
                "acento": VN.cor_legivel(n.cor, E.CAMADA_1) or E.TEXTO_2}

    @staticmethod
    def _curto_notif(n) -> str:
        """A linha do recolhido: na conversa, a ultima mensagem (com quem
        mandou, se for grupo); senao o android.text."""
        if n.mensagens:
            quem, texto, _h = n.mensagens[-1]
            return ("%s: %s" % (quem, texto)) if quem and n.conversa \
                else texto
        return n.curto or n.texto or n.subtexto

    def _tem_mais_notif(self, n, largura: int) -> bool:
        """Ha o que ver aberto? (senao, sem seta)"""
        if nt_botoes(n) or n.linhas or len(n.mensagens) > 1 or \
                n.resumo_txt or n.imagem:
            return True
        o = self.programa.notif.ouvida(n.chave)
        if o and (o.get("acoes") or o.get("foto")):
            return True
        curto = self._curto_notif(n)
        cheio = n.texto or curto
        if cheio.strip() != curto.strip() or "\n" in cheio.strip():
            return True
        return self._medir(E.fonte(E.ROTULO), E.texto_limpo(curto)) > largura

    def _hora_notif(self, n) -> str:
        if n.cronometro:
            return self._cronometro(n.quando, n.regressivo)
        return self._quando_notif(n.quando)

    @staticmethod
    def _cronometro(quando, regressivo: bool) -> str:
        """O cronometro do Android (chamada, gravacao, timer): o tempo desde
        `quando` (ou ate ele, no regressivo)."""
        try:
            alvo = float(quando or 0) / 1000.0
        except (TypeError, ValueError):
            return ""
        s = int(alvo - time.time()) if regressivo else int(time.time() - alvo)
        s = max(0, s)
        return "%d:%02d" % (s // 60, s % 60) if s < 3600 else \
            "%d:%02d:%02d" % (s // 3600, s // 60 % 60, s % 60)

    def _desenhar_seta(self, p, cx, cy, giro: float, cor: str,
                       fundo: str, bolha: str | None = None) -> None:
        """A setinha de abrir/fechar: `giro` 0 = fechada (para baixo), 1 =
        aberta (para cima); no meio ela vira, como no Android. `bolha` =
        (07/out, One UI) o botao redondo em volta dela."""
        lado = E.px(22) if bolha else E.px(16)
        a, w = E.px(16) * 0.12, E.px(16) * 0.22
        lados = cy - a + 2 * a * giro
        ponta = cy + a - 2 * a * giro
        tg = p.tags("s:seta")
        # area de clique (a linha fina sozinha quase nao se acerta)
        p.c.create_rectangle(cx - lado / 2.0, cy - lado / 2.0,
                             cx + lado / 2.0, cy + lado / 2.0,
                             fill=p.cor(fundo), outline="", tags=tg)
        if bolha:
            p.c.create_oval(cx - lado / 2.0, cy - lado / 2.0,
                            cx + lado / 2.0, cy + lado / 2.0,
                            fill=p.cor(bolha), outline="", tags=tg)
        p.c.create_line(cx - w, lados, cx, ponta, cx + w, lados,
                        fill=p.cor(cor), width=max(1, E.px(1.4)),
                        capstyle="round", joinstyle="round", tags=tg)

    def _virar_notif_aberta(self, chave: str) -> None:
        abertas = self._notif_abertas
        abrindo = chave not in abertas
        if abrindo:
            abertas.add(chave)
        else:
            abertas.discard(chave)
        lista = self._ui.get("notif_lista_anim")
        if lista is not None:
            lista.animar_estado("n|" + chave, "giro",
                                0.0 if abrindo else 1.0,
                                1.0 if abrindo else 0.0)
        self._refazer_cartao(chave)

    def _forma_notif(self, n, aberto: bool, mais: bool) -> tuple:
        """O que muda a ESTRUTURA do cartao (mudou = refazer). O resto
        (titulo, a linha do recolhido, o progresso) troca no lugar."""
        o = self.programa.notif.ouvida(n.chave) or {}
        return (n.limpavel, tuple(r for r, _a in nt_botoes(n)), nt_codigo(n),
                aberto, mais, n.colorida, n.cor, n.progresso is not None,
                n.cronometro, n.aparencia() if aberto else None,
                tuple(o.get("acoes") or ()), hash(o.get("icone")),
                hash(o.get("foto")) if aberto else None,
                tuple(sorted((k, hash(v)) for k, v in
                             (o.get("rostos") or {}).items())) if aberto
                else None,
                aberto and self._respondendo == n.chave,
                self._recado_resposta.get(n.chave) if aberto else None,
                o.get("proprios"))

    def _desenhar_cartao(self, p, app: str, n) -> int:
        """O cartao no canvas (ver o comentario acima). Devolve a altura."""
        nome = self._nome_notif(app)
        aberto = n.chave in self._notif_abertas
        cores = self._cores_notif(n)
        bg = cores["fundo"]
        sobre = p.sobre
        abre = n.alvo is not None or self._app_abre(app)
        borda = E.BORDA_1_SOBRE if (sobre is not None and abre) \
            else cores["linha"]
        # (07/out, pedido dele: "usa a One UI mais recente como base") O
        # cartao como no Galaxy: margens folgadas, a FOTO de quem mandou
        # grande e redonda a esquerda (conversa), o titulo forte, o texto
        # apagado, a hora pequena; a seta num botao redondo; os botoes do
        # app em pilulas embaixo (o texto inteiro, sem "…").
        pad = E.px(14)
        x0, x1 = p.x0 + pad, p.x1 - pad
        o = self.programa.notif.ouvida(n.chave) or {}
        proprios = o.get("proprios") or ()
        y = p.y + E.px(12)
        alto1 = E.px(18)
        meio = y + alto1 / 2.0
        # (03/out) Pelo ouvinte: a foto de quem mandou (o "icone grande").
        lado_r = E.px(36)
        rosto = self._imagem_notif(o.get("icone"), lado_r, bg, redonda=True)
        if rosto is not None:
            p.imagem(x0, y, rosto)
            x0 += lado_r + E.px(12)
        largura = max(E.px(60), x1 - x0)
        xd = x1
        if n.limpavel:
            # (07/out) o x da casa (icone de linha, realce em bolha)
            lado_x = E.px(22)
            p.icone_x(xd - lado_x / 2.0, meio, lado_x,
                      E.TEXTO if sobre == "x" else cores["apagado"], bg,
                      bolha=E.SUPERFICIE_SOBRE if sobre == "x" else None,
                      extra=("s:x",))
            xd -= lado_x + E.px(4)
        if (len(proprios) > 2 if proprios else
                self._tem_mais_notif(n, self._largura_texto_notif())):
            self._desenhar_seta(p, xd - E.px(11), meio,
                                p.est.get("giro", 1.0 if aberto else 0.0),
                                cores["texto"], bg,
                                bolha=E.SUPERFICIE_SOBRE if sobre == "seta"
                                else VN.misturar(cores["texto"], bg, 0.10))
            xd -= E.px(22) + E.px(6)
        it, _h = p.texto(xd, meio, self._hora_notif(n),
                         E.fonte(E.ROTULO, "bold" if n.cronometro
                                 else "normal"),
                         cores["texto"] if n.cronometro else cores["apagado"],
                         anchor="e")
        caixa = p.c.bbox(it)
        xd = (caixa[0] if caixa else xd) - E.px(8)
        titulo = proprios[0] if proprios else (n.conversa or n.titulo or nome)
        fonte_t = E.fonte(E.PEQUENA, "bold")
        p.texto(x0, meio, self._uma_linha(titulo, fonte_t,
                                          max(E.px(20), xd - x0)),
                fonte_t, cores["texto"], anchor="w")
        y += alto1 + E.px(2)
        if proprios:
            # (07/out) layout proprio do app: os textos de dentro dele
            resto = [t for t in proprios[1:]]
            if not aberto:
                resto = resto[:1]
            for t in resto:
                _it, h = p.texto(x0, y, t if aberto else self._uma_linha(
                    t, E.fonte(E.ROTULO), largura), E.fonte(E.ROTULO),
                    cores["texto2"], largura=largura if aberto else None)
                y += h
        elif aberto:
            y = self._desenhar_corpo_aberto(p, n, cores, x0, largura, y, o)
        else:
            linha = self._uma_linha(self._curto_notif(n), E.fonte(E.ROTULO),
                                    largura)
            if linha:
                _it, h = p.texto(x0, y, linha, E.fonte(E.ROTULO),
                                 cores["texto2"])
                y += h
        if rosto is not None:
            y = max(y, p.y + E.px(12) + lado_r)
            x0 = p.x0 + pad          # pilulas e barra: a largura toda
            largura = max(E.px(60), x1 - x0)
        if n.progresso is not None:
            y += E.px(6)
            self._desenhar_progresso(
                p, x0, x1, y, n.progresso,
                cores["acento"] if n.cor else E.ACENTO,
                VN.misturar(cores["texto"], bg, 0.18))
            y += E.px(4)
        # (01/out) Os botoes que abrem uma tela (so aberto, como no
        # Android) e o "copiar codigo" (sempre: e o que se quer na hora).
        # (03/out) Com o ouvinte, os botoes sao os DO APP (ate 3, como no
        # Android): responder abre a caixa; o resto o celular faz.
        # (layout proprio: o "desfazer" ja aparece fechado, e o que se quer)
        acoes_app = (o.get("acoes") or [])[:3] if (aberto or proprios) \
            else []
        botoes = [] if acoes_app else (nt_botoes(n)[:3] if aberto else [])
        codigo = nt_codigo(n)
        links = []
        if codigo:
            links.append(("cod", "copiar código %s" % codigo, False))
        # (07/out, pedido dele) o rotulo INTEIRO, sem "…": apertado e
        # esperando o celular, a pilula so fica apagada
        for i, (rotulo, _t, _tela) in enumerate(acoes_app):
            links.append(("a:%d" % i, rotulo.strip().lower(),
                          (n.chave, i) in self._acao_pendente))
        for i, (rotulo, _alvo) in enumerate(botoes):
            links.append(("b:%d" % i, rotulo.strip().lower(), False))
        if links:
            y = self._desenhar_pilulas(p, links, x0, x1, y + E.px(8), cores,
                                       bg, sobre, bool(n.cor))
        if aberto and self._respondendo == n.chave:
            responder = next((i for i, a in enumerate(acoes_app) if a[1]),
                             None)
            if responder is not None:
                y += E.px(7)
                caixa_w = self._caixa_resposta(p.c, app, n.chave, responder)
                alto_c = max(E.px(24), caixa_w.winfo_reqheight())
                p.janela(caixa_w, x0, y, largura=largura - E.px(56),
                         altura=alto_c)
                p.texto(x1, y + alto_c / 2.0, "enviar", E.fonte(E.PEQUENA),
                        cores["texto"] if sobre == "enviar" else E.TEXTO_2,
                        anchor="e", extra=("s:enviar",))
                y += alto_c
        recado = self._recado_resposta.get(n.chave) if aberto else None
        if recado:
            y += E.px(4)
            _it, h = p.texto(x0, y, recado, E.fonte(E.ROTULO),
                             E.ERRO if recado.startswith("não foi")
                             else cores["apagado"], largura=largura)
            y += h
        y += E.px(12)
        alto = int(y - p.y)
        fim = p.y + (int(p.corte) if p.corte is not None else alto)
        if fim - p.y >= E.px(16):
            # (07/out) canto bem redondo, como os cartoes da One UI
            p.cartao(p.y, fim, bg, borda, raio=E.px(16),
                     extra=(p.tag + "f",))
            p.c.tag_lower(p.tag + "f")
        return alto

    def _desenhar_pilulas(self, p, links, x0, x1, y, cores: dict, bg: str,
                          sobre, colorida: bool) -> float:
        """(07/out, One UI) Os botoes do cartao em PILULAS: fundo um tom
        acima do cartao, o texto inteiro na cor do app; o mouse clareia; a
        apertada (esperando o celular) fica apagada. Nao cabe = outra
        fileira. Devolve o y de baixo."""
        fonte = E.fonte(E.PEQUENA, "bold")
        alto = E.px(28)
        folga = E.px(12)
        vao = E.px(6)
        xb = x0
        for sub, texto, esperando in links:
            larg = self._medir(fonte, texto) + 2 * folga
            if xb > x0 and xb + larg > x1:
                xb = x0
                y += alto + vao
            fundo = VN.misturar(cores["texto"], bg,
                                0.16 if sobre == sub else 0.08)
            cor = cores["apagado"] if esperando else (
                cores["texto"] if sobre == sub else
                (cores["acento"] if colorida else cores["texto"]))
            tg = p.tags("s:" + sub)
            r = alto / 2.0
            f = p.cor(fundo)
            # a pilula: dois circulos e o miolo (tudo clicavel)
            p.c.create_oval(xb, y, xb + alto, y + alto, fill=f, width=0,
                            tags=tg)
            p.c.create_oval(xb + larg - alto, y, xb + larg, y + alto, fill=f,
                            width=0, tags=tg)
            p.c.create_rectangle(xb + r, y, xb + larg - r, y + alto, fill=f,
                                 width=0, tags=tg)
            p.texto(xb + larg / 2.0, y + alto / 2.0, texto, fonte, cor,
                    anchor="center", extra=("s:" + sub,))
            xb += larg + vao
        return y + alto

    def _desenhar_corpo_aberto(self, p, n, cores: dict, x0: int,
                               largura: int, y, o: dict) -> float:
        """O miolo do cartao aberto. Devolve o y de baixo."""
        bg = cores["fundo"]
        fonte, forte = E.fonte(E.ROTULO), E.fonte(E.ROTULO, "bold")
        rostos = o.get("rostos") or {}

        def rotulo(texto, cor, f=fonte, topo=0, imagem=None):
            nonlocal y
            y += topo
            xt = x0
            if imagem is not None:
                p.imagem(x0, y, imagem)
                xt += E.px(14) + E.px(5)
            _it, h = p.texto(xt, y, texto, f, cor, largura=largura - (xt - x0))
            y += max(h, E.px(14) if imagem is not None else 0)

        if n.mensagens:
            # Como a conversa do Android: o nome de quem mandou em cima das
            # mensagens seguidas dele (com a foto, pelo ouvinte).
            antes = None
            mostradas = n.mensagens[-self.NOTIF_LINHAS_MAX:]
            if len(n.mensagens) > len(mostradas):
                rotulo("+%d anteriores" % (len(n.mensagens) - len(mostradas)),
                       cores["apagado"])
            # (07/out, One UI) conversa a dois: o nome ja e o titulo
            so_um = {q for q, _t, _h in mostradas if q} <= {
                n.conversa or n.titulo}
            for quem, texto, _h in mostradas:
                if quem and quem != antes and not so_um:
                    rotulo(quem, cores["texto"], forte,
                           E.px(4) if antes is not None else E.px(1),
                           self._imagem_notif(rostos.get(quem), E.px(14), bg,
                                              redonda=True))
                antes = quem
                rotulo(texto, cores["texto2"])
        elif n.linhas:
            for linha in n.linhas[:self.NOTIF_LINHAS_MAX]:
                rotulo(linha, cores["texto2"])
            if len(n.linhas) > self.NOTIF_LINHAS_MAX:
                rotulo("+%d" % (len(n.linhas) - self.NOTIF_LINHAS_MAX),
                       cores["apagado"])
        else:
            texto = (n.texto or n.curto or n.subtexto).strip()
            if len(texto) > self.NOTIF_ABERTO_MAX:
                texto = texto[:self.NOTIF_ABERTO_MAX - 1] + "…"
            if texto:
                rotulo(texto, cores["texto2"])
        if n.resumo_txt:
            rotulo(n.resumo_txt, cores["apagado"], topo=E.px(2))
        imagem = self._imagem_notif(o.get("foto"), E.px(160), bg,
                                    largura=largura)
        if imagem is not None:
            y += E.px(5)
            p.imagem(x0, y, imagem)
            y += imagem.height()
        elif n.imagem:
            rotulo("[imagem: veja no celular]", cores["apagado"], topo=E.px(2))
        return y

    def _desenhar_progresso(self, p, x0, x1, y, progresso, cor_feita: str,
                            cor_trilho: str) -> None:
        """A barra (download...). A indeterminada e um pedaco que corre (o
        giro da janela refaz o bloco)."""
        atual, maximo, indeterminado = progresso
        g = max(2, E.px(3))
        comp = max(1, x1 - x0 - 4)
        p.c.create_line(x0 + 2, y, x1 - 2, y, fill=p.cor(cor_trilho),
                        width=g, capstyle="round", tags=p.tags())
        if indeterminado:
            fase = (time.monotonic() * 0.7) % 1.4 - 0.3
            a, b = max(0.0, fase), min(1.0, fase + 0.3)
        else:
            a, b = 0.0, (min(1.0, atual / float(maximo)) if maximo else 0.0)
        if b > a:
            p.c.create_line(x0 + 2 + a * comp, y, x0 + 2 + b * comp, y,
                            fill=p.cor(cor_feita), width=g, capstyle="round",
                            tags=p.tags())

    # -- responder e botoes do app, pelo ouvinte (03/out, pedido dele) --------

    def _imagem_notif(self, dado: bytes | None, lado: int, fundo: str,
                      redonda: bool = False, largura: int = 0):
        """A foto do ouvinte pronta para o Tk (guardada: o cartao e refeito a
        toda hora). Redonda = o rosto de quem mandou, como no Android; senao
        cabe em `largura` x `lado`. None sem foto ou se nao abrir."""
        if not dado:
            return None
        chave = (hash(dado), lado, redonda, largura, fundo)
        if chave in self._fotos_notif:
            return self._fotos_notif[chave]
        foto = None
        try:
            import io
            from PIL import Image, ImageDraw, ImageOps, ImageTk
            filtro = getattr(Image, "Resampling", Image).LANCZOS
            img = Image.open(io.BytesIO(dado)).convert("RGBA")
            if redonda:
                img = ImageOps.fit(img, (lado * 3, lado * 3), filtro)
                mascara = Image.new("L", img.size, 0)
                ImageDraw.Draw(mascara).ellipse((0, 0) + img.size, fill=255)
                img.putalpha(mascara)
                img = img.resize((lado, lado), filtro)
            else:
                f = min(1.0, largura / float(img.width) if largura else 1.0,
                        lado / float(img.height))
                img = img.resize((max(1, int(img.width * f)),
                                  max(1, int(img.height * f))), filtro)
            base = Image.new("RGBA", img.size, fundo)
            base.alpha_composite(img)
            foto = ImageTk.PhotoImage(base.convert("RGB"), master=self)
        except Exception:
            log.exception("imagem da notificacao")
            foto = None
        if len(self._fotos_notif) > 300:
            self._fotos_notif.clear()
        self._fotos_notif[chave] = foto
        return foto

    def _refazer_cartao(self, chave: str) -> None:
        """O cartao e redesenhado no canvas (o que mudou anda; nada pisca)."""
        self._ui["notif_pintada"] = None
        self._pintar_notif()
        lista = self._ui.get("notif_lista_anim")
        if lista is not None:
            lista.redesenhar("n|" + chave)

    def _abrir_resposta(self, chave: str) -> None:
        """O botao "responder": abre (ou fecha) a caixa no cartao."""
        if self._respondendo == chave:
            self._respondendo = ""
        else:
            self._respondendo = chave
            self._notif_abertas.add(chave)
            self._recado_resposta.pop(chave, None)
        self._refazer_cartao(chave)

    def _caixa_resposta(self, canvas, app: str, chave: str,
                        indice: int) -> tk.Frame:
        """A caixa de texto do cartao (uma janela de verdade, no canvas).
        Nasce uma vez por resposta: refazer o cartao nao a recria."""
        cx = self._ui.get("notif_caixa")
        if cx is not None and cx[0] == chave and cx[1].winfo_exists():
            return cx[1]
        if cx is not None:
            try:
                cx[1].destroy()
            except tk.TclError:
                pass
        campo = self._caixa(canvas, self._rascunhos.get(chave, ""),
                            ao_mudar=lambda: self._rascunhos.pop(chave, None))
        moldura_c = campo.master
        # (07/out) em volta dela esta o cartao (camada 1), nao o canvas
        moldura_c._cor_fora = E.CAMADA_1
        E.cantos(moldura_c)
        self._ui["notif_caixa"] = (chave, moldura_c, campo, app, indice)

        def guardar(_e=None):
            self._rascunhos[chave] = campo.get()

        def mandar(_e=None):
            self._mandar_resposta()
            return "break"

        def fechar(_e=None):
            self._respondendo = ""
            self._refazer_cartao(chave)
            return "break"

        campo.bind("<KeyRelease>", guardar, add="+")
        campo.bind("<Return>", mandar)
        campo.bind("<Escape>", fechar)
        self.after_idle(lambda: campo.winfo_exists() and (
            campo.focus_set(), campo.icursor("end")))
        return moldura_c

    def _mandar_resposta(self) -> None:
        cx = self._ui.get("notif_caixa")
        if cx is None:
            return
        chave, _m, campo, app, indice = cx
        try:
            texto = campo.get()
        except tk.TclError:
            return
        self._rascunhos[chave] = texto       # falhou: o texto volta a caixa
        texto = texto.strip()
        if texto and self._recado_resposta.get(chave) != "enviando…":
            self._enviar_resposta(app, chave, indice, texto)

    def _enviar_resposta(self, app: str, chave: str, indice: int,
                         texto: str) -> None:
        self._recado_resposta[chave] = "enviando…"
        self._refazer_cartao(chave)

        def fim(ok, detalhe):
            def na_janela():
                if ok:
                    # Como no Android: a caixa fecha e o "enviado." some.
                    self._rascunhos.pop(chave, None)
                    self._respondendo = "" if self._respondendo == chave \
                        else self._respondendo
                    self._recado_resposta[chave] = "enviado."
                    self.after(4000, lambda: self._recado_resposta.get(
                        chave) == "enviado." and (
                        self._recado_resposta.pop(chave, None),
                        self._refazer_cartao(chave)))
                else:
                    self._recado_resposta[chave] = (
                        "não foi: %s. o texto continua na caixa."
                        % self.programa.notif.motivo_legivel(detalhe))
                self._refazer_cartao(chave)
            self._da_outra_thread.put(na_janela)

        self.programa.acao_notificacao(app, chave, indice, texto, fim)

    def _apertar_acao_notif(self, app: str, chave: str, indice: int) -> None:
        """Um botao do app sem texto (marcar como lida, curtir...)."""
        self._acao_pendente.add((chave, indice))
        self._refazer_cartao(chave)

        def fim(ok, detalhe):
            def na_janela():
                if not ok:
                    self._acao_pendente.discard((chave, indice))
                    self._recado_resposta[chave] = "não foi: %s." % \
                        self.programa.notif.motivo_legivel(detalhe)
                    self._refazer_cartao(chave)
                else:                        # tira o "…" do botao
                    self.after(1500, lambda: (
                        self._acao_pendente.discard((chave, indice)),
                        self._refazer_cartao(chave)))
            self._da_outra_thread.put(na_janela)

        self.programa.acao_notificacao(app, chave, indice, "", fim)

    # -- o player (01/out/2026, pedido dele) --------------------------------
    # Cartao no topo das notificacoes, como no celular: o app, a musica, a
    # barra (anda sozinha no PC; clicar/arrastar pula, se o app deixa) e
    # anterior / tocar-pausar / proxima. Vem do `Midia.java` no celular.

    ACAO_PAUSAR, ACAO_TOCAR, ACAO_ANTERIOR, ACAO_PROXIMA = 2, 4, 16, 32
    ACAO_PULAR, ACAO_TOCAR_PAUSAR = 256, 512

    @staticmethod
    def _mmss(ms) -> str:
        s = max(0, int(ms or 0)) // 1000
        return "%d:%02d" % (s // 60, s % 60) if s < 3600 else \
            "%d:%02d:%02d" % (s // 3600, s // 60 % 60, s % 60)

    # (02/out, pedido dele: "tematizado igual no Android, com a capa de
    # fundo") UM Canvas so: a capa cobrindo o cartao com o degrade da cor
    # dela (`visual_notif`), o app em cima, a musica, anterior / tocar
    # (botao redondo no tom claro da capa) / proxima, e a barra embaixo.
    # Teclado: com o foco no player, espaco toca/pausa e as setas pulam de
    # musica.

    PLAYER_ALTURA = 148

    def _acertar_player(self, d, m: dict):
        """Monta o cartao (1x) e poe em dia com a sessao `m`, no lugar."""
        pl = self._ui.get("player")
        if pl is None or not pl["frame"].winfo_exists():
            pl = self._montar_player(d)
            self._ui["player"] = pl
            # (07/out, pedido dele) botao direito = o menu da casa
            pl["frame"].bind("<Button-3>",
                             lambda e, p=pl: self._menu_player(e, p))
        pl["sessao"] = m
        pl["pula"] = bool(m["acoes"] & self.ACAO_PULAR) and m["dur"] > 0
        self._desenhar_player(pl)
        return pl["frame"]

    def _montar_player(self, d, ao_fechar=None) -> dict:
        # (03/out) sem a moldura quadrada: o cartao redondo esta na imagem
        c = tk.Canvas(d, height=E.px(self.PLAYER_ALTURA), bg=E.FUNDO,
                      highlightthickness=0, takefocus=1, bd=0)
        c._pady = (E.px(0), E.px(8))
        pl = {"frame": c, "arraste": None, "sessao": None, "pula": False,
              "desenho": None, "fundo_de": None, "foto": None,
              "tema_de": None, "tema": None, "barra_x": (0, 0, 0)}
        c.bind("<Configure>", lambda _e: self._desenhar_player(pl, True))
        for tag, acao in (("ant", "previous"), ("play", "play-pause"),
                          ("prox", "next")):
            c.tag_bind(tag, "<Button-1>",
                       lambda _e, a=acao: self._comando_player(a, pl))
            c.tag_bind(tag, "<Enter>", lambda _e, t=tag:
                       self._realce_player(pl, t, True))
            c.tag_bind(tag, "<Leave>", lambda _e, t=tag:
                       self._realce_player(pl, t, False))
        # (01/out, pedido dele) x = fechar o player, como arrastar no celular.
        c.tag_bind("fechar", "<Button-1>",
                   lambda _e: (ao_fechar or self._fechar_player)())
        c.tag_bind("fechar", "<Enter>", lambda _e: (
            c.itemconfigure("fechar_x", fill="#FFFFFF"),
            c.configure(cursor="hand2")))
        c.tag_bind("fechar", "<Leave>", lambda _e: (
            c.itemconfigure("fechar_x", fill=pl.get("x_cor", E.TEXTO_2)),
            c.configure(cursor="")))
        c.tag_bind("zona", "<Button-1>", lambda e: self._arrastar_player(e, pl))
        c.tag_bind("zona", "<B1-Motion>",
                   lambda e: self._arrastar_player(e, pl))
        c.tag_bind("zona", "<ButtonRelease-1>",
                   lambda e: self._soltar_player(e, pl))
        c.tag_bind("zona", "<Enter>", lambda _e: c.configure(
            cursor="hand2" if pl["pula"] else ""))
        c.tag_bind("zona", "<Leave>", lambda _e: c.configure(cursor=""))
        c.bind("<space>", lambda _e: self._comando_player("play-pause", pl))
        c.bind("<Return>", lambda _e: self._comando_player("play-pause", pl))
        c.bind("<Right>", lambda _e: self._comando_player("next", pl))
        c.bind("<Left>", lambda _e: self._comando_player("previous", pl))
        return pl

    def _realce_player(self, pl, tag: str, sobre: bool) -> None:
        """Mouse em cima de um botao: a versao "acesa" da imagem dele."""
        c = pl["frame"]
        try:
            c.configure(cursor="hand2" if sobre else "")
            imgs = (pl.get("icones") or {}).get(tag)
            if imgs:
                c.itemconfigure(tag + "_img", image=imgs[1 if sobre else 0])
        except tk.TclError:
            pass

    def _tema_player(self, pl, m) -> dict:
        capa = self.programa.notif.capa(m["pacote"])
        chave = (m["pacote"], len(capa or b""), hash(capa or b""))
        if pl["tema_de"] != chave:
            pl["tema_de"] = chave
            pl["capa"] = capa
            superficie = VN.misturar(E.TEXTO, E.FUNDO, 0.06)
            try:
                pl["tema"] = VN.tema_da_capa(capa, E.ACENTO, superficie)
            except Exception:
                log.exception("player: tema da capa")
                pl["capa"] = None
                pl["tema"] = VN.tema_da_capa(None, E.ACENTO, superficie)
        return pl["tema"]

    # (03/out, pedido dele: "botoes parecidos com o player da barra na One UI
    # nova") Capa pequena arredondada a esquerda com a musica ao lado, a
    # barra fina com bolinha, os tempos nas pontas e os controles no meio:
    # anterior/proxima so o icone; tocar/pausar num circulo claro. Os icones
    # sao desenhados em 4x (PIL) e reduzidos: bordas lisas e cantos
    # arredondados, como os do celular.

    def _icone_player(self, tipo: str, lado: int, cor: str,
                      circulo: str | None = None):
        """Imagem (RGBA) de um controle do player; guardada."""
        chave = ("player", tipo, lado, cor, circulo)
        foto = self._fotos_notif.get(chave)
        if foto is not None:
            return foto
        from PIL import Image, ImageDraw, ImageTk
        k = 4
        s = lado * k
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if circulo:
            d.ellipse((0, 0, s - 1, s - 1), fill=circulo)
        m = s / 2.0
        g = s * 0.44                      # o desenho (todos iguais)
        arred = max(2, int(g * 0.12))

        def triangulo(x_base, x_ponta, alto):
            pts = [(x_base, m - alto), (x_base, m + alto), (x_ponta, m)]
            d.polygon(pts, fill=cor)
            d.line(pts + [pts[0]], fill=cor, width=arred * 2, joint="curve")
            for x, y in pts:
                d.ellipse((x - arred, y - arred, x + arred, y + arred),
                          fill=cor)

        if tipo == "tocar":
            triangulo(m - g * 0.36, m + g * 0.5, g * 0.5)
        elif tipo == "pausar":
            w = g * 0.26
            for dx in (-g * 0.24, g * 0.24):
                d.rounded_rectangle((m + dx - w / 2, m - g * 0.48,
                                     m + dx + w / 2, m + g * 0.48),
                                    radius=w * 0.45, fill=cor)
        else:                                       # anterior / proxima
            lado_d = 1 if tipo == "prox" else -1
            alto = g * 0.4
            triangulo(m - lado_d * g * 0.36, m + lado_d * g * 0.3, alto)
            w = g * 0.13
            xb = m + lado_d * g * 0.42
            d.rounded_rectangle((xb - w / 2, m - alto - arred * 0.5,
                                 xb + w / 2, m + alto + arred * 0.5),
                                radius=w * 0.5, fill=cor)
        img = img.resize((lado, lado), Image.BOX)
        foto = ImageTk.PhotoImage(img, master=self)
        self._fotos_notif[chave] = foto
        return foto

    def _desenhar_player(self, pl, tamanho_mudou: bool = False) -> None:
        """Desenha tudo de novo quando a musica, a capa, o estado ou o
        tamanho mudam; a barra anda sozinha em `_pintar_barra_player`."""
        c, m = pl["frame"], pl.get("sessao")
        try:
            larg, alt = c.winfo_width(), c.winfo_height()
        except tk.TclError:
            return
        if not m or larg < 40:
            return
        tema = self._tema_player(pl, m)
        app = m["pacote"]
        assin = (larg, alt, pl["tema_de"], app, m["titulo"], m["artista"],
                 m["estado"], pl["pula"], self._icones_versao)
        if assin == pl["desenho"]:
            self._pintar_barra_player(pl)
            return
        pl["desenho"] = assin
        c.delete("all")
        # (03/out, print do celular dele: One UI 8) a CAPA COBRE O CARTAO
        # INTEIRO, so escurecida para o texto branco ler bem (sem miniatura)
        # O canto redondo vai NA PROPRIA IMAGEM (liso; os cantinhos soltos
        # nao casavam com a foto). O mini usa o raio do Windows 11.
        raio = E.px(8) if "fator" in pl else E.px(16)
        if pl["fundo_de"] != (pl["tema_de"], larg, alt, raio):
            pl["fundo_de"] = (pl["tema_de"], larg, alt, raio)
            try:
                import io
                from PIL import (Image, ImageDraw, ImageEnhance, ImageFilter,
                                 ImageOps, ImageTk)
                filtro = getattr(Image, "Resampling", Image).LANCZOS
                if pl.get("capa"):
                    img = ImageOps.fit(
                        Image.open(io.BytesIO(pl["capa"])).convert("RGB"),
                        (larg, alt), filtro)
                    img = img.filter(ImageFilter.GaussianBlur(E.px(1.5)))
                    img = ImageEnhance.Brightness(img).enhance(0.42)
                    pl["cor_media"] = "#%02X%02X%02X" % img.resize(
                        (1, 1), filtro).getpixel((0, 0))
                else:
                    img = Image.new("RGB", (larg, alt), tema["fundo"])
                    pl["cor_media"] = tema["fundo"]
                k4 = 4
                mascara = Image.new("L", (larg * k4, alt * k4), 0)
                ImageDraw.Draw(mascara).rounded_rectangle(
                    (0, 0, larg * k4 - 1, alt * k4 - 1), radius=raio * k4,
                    fill=255)
                fora = Image.new("RGB", (larg, alt), E.FUNDO)
                fora.paste(img, (0, 0), mascara.resize((larg, alt), filtro))
                pl["foto"] = ImageTk.PhotoImage(fora, master=self)
            except Exception:
                log.exception("player: fundo da capa")
                pl["foto"] = None
                pl["cor_media"] = tema["fundo"]
        if pl.get("foto") is not None:
            c.create_image(0, 0, image=pl["foto"], anchor="nw")
        else:
            c.create_rectangle(0, 0, larg, alt, fill=tema["fundo"], width=0)
        base = pl.get("cor_media") or tema["fundo"]
        pl["cor_base"] = base
        branco, apagado = "#FFFFFF", VN.misturar("#FFFFFF", base, 0.62)
        # (03/out) o mini player tem tamanho: tudo cresce junto
        k = pl.get("fator", 1.0)
        P = lambda n: int(round(E.px(n) * k))
        F = lambda tam, *a: E.fonte(tam * k, *a)
        mg = P(18)
        nome = self._nome_notif(app)
        # 1) no alto: o icone do app e o nome dele (o celular mostra a saida
        # do som ali); o x no canto
        ic = P(14)
        y1 = P(18)
        foto = None if self._config.apps.get("sem_icones") else \
            self._foto(app, ic)
        x_nome = mg
        if foto is not None:
            c.create_image(mg, y1, image=foto, anchor="w")
            x_nome = mg + ic + P(7)
        c.create_text(x_nome, y1, text=nome, anchor="w", fill=branco,
                      font=F(E.ROTULO))
        # (07/out) o x da casa (duas diagonais de ponta redonda, como o
        # icone de linha); a area de clique e um texto de espacos (o canvas
        # so acha o que tem area pintada)
        lx = P(18)
        cx, u = larg - mg - lx / 2.0 + P(4), lx / 24.0
        c.create_text(cx, y1, text="  ", font=F(E.CORPO), tags="fechar")
        for p0, q0 in (((-5, -5), (5, 5)), ((5, -5), (-5, 5))):
            c.create_line(cx + p0[0] * u, y1 + p0[1] * u, cx + q0[0] * u,
                          y1 + q0[1] * u, fill=apagado, width=max(1.5, 2 * u),
                          capstyle="round", tags=("fechar", "fechar_x"))
        pl["x_cor"] = apagado
        # 2) a musica: titulo em letra normal, artista menor e apagado
        largura_t = max(P(40), larg - 2 * mg)
        titulo = self._uma_linha(m["titulo"] or nome, F(E.CORPO + 1),
                                 largura_t)
        artista = self._uma_linha(m["artista"] or m.get("album") or "",
                                  F(E.PEQUENA), largura_t)
        c.create_text(mg, y1 + P(23), text=titulo, anchor="w", fill=branco,
                      font=F(E.CORPO + 1))
        if artista:
            c.create_text(mg, y1 + P(41), text=artista, anchor="w",
                          fill=apagado, font=F(E.PEQUENA))
        # 3) a barra (mais grossa, bolinha clara) e os tempos embaixo dela
        yb = y1 + P(62)
        x0, x1 = mg + P(4), larg - mg - P(4)
        pl["barra_x"] = (x0, x1, yb)
        grossura = max(3, P(5))
        c.create_line(x0, yb, x1, yb, fill=VN.misturar("#FFFFFF", base, 0.28),
                      width=grossura, capstyle="round", tags="trilho")
        c.create_line(x0, yb, x0, yb, fill=branco, width=grossura,
                      capstyle="round", tags="feito")
        c.create_oval(0, 0, 0, 0, fill=VN.misturar(tema["acento"], "#FFFFFF",
                                                    0.18),
                      outline="", tags="pino")
        c.create_rectangle(x0 - P(6), yb - P(9), x1 + P(6), yb + P(9),
                           fill="", outline="", tags="zona")
        yt = yb + P(15)
        c.create_text(x0 - P(4), yt, text="0:00", anchor="w", fill=apagado,
                      font=F(E.ROTULO), tags="t0")
        c.create_text(x1 + P(4), yt, text="0:00", anchor="e", fill=apagado,
                      font=F(E.ROTULO), tags="t1")
        # 4) os controles: so os icones brancos, no meio, espaco igual
        cy = yt + P(24)
        meio = larg / 2.0
        passo = P(52)
        self._desenhar_play(pl, meio, cy, P(17))
        for tag, cx in (("ant", meio - passo), ("prox", meio + passo)):
            self._desenhar_pular(pl, tag, cx, cy, P(34))
        self._pintar_barra_player(pl)

    def _desenhar_play(self, pl, cx, cy, r) -> None:
        c, m = pl["frame"], pl["sessao"]
        c.delete("play")
        base = pl.get("cor_base") or pl["tema"]["fundo"]
        tipo = "pausar" if m["estado"] == 3 else "tocar"
        lado = int(r * 2)
        normal = self._icone_player(tipo, lado, "#FFFFFF")
        aceso = self._icone_player(tipo, lado, "#FFFFFF",
                                   VN.misturar("#FFFFFF", base, 0.18))
        pl.setdefault("icones", {})["play"] = (normal, aceso)
        c.create_image(cx, cy, image=normal, tags=("play", "play_img"))
        pl["play_xy"] = (cx, cy, r)

    def _desenhar_pular(self, pl, tag: str, cx, cy, lado) -> None:
        """Anterior/proxima: so o icone; com o mouse, um circulo suave."""
        c = pl["frame"]
        base = pl.get("cor_base") or pl["tema"]["fundo"]
        lado = int(lado)
        normal = self._icone_player(tag, lado, "#FFFFFF")
        aceso = self._icone_player(tag, lado, "#FFFFFF",
                                   VN.misturar("#FFFFFF", base, 0.18))
        pl.setdefault("icones", {})[tag] = (normal, aceso)
        c.create_image(cx, cy, image=normal, tags=(tag, tag + "_img"))

    def _menu_player(self, evento, pl) -> str:
        """(07/out) Botao direito no player da aba notificacoes: abrir o app,
        tocar/pausar, anterior/proxima, levar ao mini player, fechar."""
        self._clique_em_qualquer_lugar(evento)
        m = pl.get("sessao")
        if not m:
            return "break"
        opcoes = []
        if self._app_abre(m["pacote"]):
            opcoes.append(("abrir o app", lambda: (
                pl["frame"].winfo_exists() and
                self._abrir_app_do_player(pl, do_menu=True))))
        opcoes.append(("pausar" if m["estado"] == 3 else "tocar",
                       lambda: self._comando_player("play-pause", pl)))
        opcoes.append(("música", [
            ("anterior", lambda: self._comando_player("previous", pl)),
            ("próxima", lambda: self._comando_player("next", pl))]))
        opcoes.append(("abrir no mini player",
                       lambda: getattr(self, "_mini", None) is None and
                       self.alternar_mini_player()))
        opcoes.append(None)
        opcoes.append(("fechar o player", self._fechar_player))
        menu, corpo = self._novo_menu()
        self._encher_menu(menu, corpo, evento, opcoes)
        return "break"

    def _fechar_player(self) -> None:
        m = (self._ui.get("player") or {}).get("sessao")
        if m:
            self.programa.notif.fechar_player(m["pacote"])

    def _comando_player(self, acao: str, pl=None) -> None:
        pl = pl or self._ui.get("player") or {}
        m = pl.get("sessao")
        if not m:
            return
        if acao == "play-pause":
            acao = "pause" if m["estado"] == 3 else "play"
            # Na hora, sem esperar o celular: o botao e a barra respondem.
            m["pos"] = self.programa.notif.posicao(m)
            m["recebido"] = time.monotonic()
            m["estado"] = 2 if acao == "pause" else 3
            if pl.get("play_xy") and pl.get("tema"):
                self._desenhar_play(pl, *pl["play_xy"])
                pl["desenho"] = None         # o proximo desenho confere
        self.programa.anotar("player: %s (%s)" % (acao, m["pacote"]))
        self.programa.notif.midia_comando(m["pacote"], acao)

    def _fracao_player(self, e, pl) -> float:
        x0, x1, _y = pl.get("barra_x", (0, 1, 0))
        return min(1.0, max(0.0, (e.x - x0) / float(max(1, x1 - x0))))

    def _arrastar_player(self, e, pl) -> None:
        if not pl.get("pula"):
            return
        pl["arraste"] = self._fracao_player(e, pl)
        self._pintar_barra_player(pl)

    def _soltar_player(self, e, pl) -> None:
        m = pl.get("sessao")
        if not pl.get("pula") or not m or pl.get("arraste") is None:
            return
        ms = int(self._fracao_player(e, pl) * m["dur"])
        pl["arraste"] = None
        m["pos"], m["recebido"] = ms, time.monotonic()     # na hora
        self._pintar_barra_player(pl)
        self.programa.anotar("player: pular para %s" % self._mmss(ms))
        self.programa.notif.midia_comando(m["pacote"], "seek", ms)

    def _pintar_barra_player(self, pl=None) -> None:
        """A barra e os tempos (chamado pelo relogio da janela: so mexe no
        canvas, sem remontar nada). `pl` = qual player (o das notificacoes
        ou o mini da bandeja); sem ele, o das notificacoes."""
        pl = pl or self._ui.get("player")
        if not pl or not pl["frame"].winfo_exists():
            return
        m = pl.get("sessao")
        # (02/out, revisao) Chegou foto nova do celular (so a posicao muda
        # nao repinta o cartao): pega a sessao nova, senao um "pular" feito
        # no celular nao aparecia na barra do PC.
        versao = self.programa.notif.midias_versao
        if m and pl.get("versao") != versao:
            pl["versao"] = versao
            novo = self.programa.notif.player()
            if novo and novo["pacote"] == m["pacote"]:
                pl["sessao"] = m = novo
        c = pl["frame"]
        x0, x1, yb = pl.get("barra_x", (0, 0, 0))
        if not m or x1 - x0 < 4 or not c.find_withtag("trilho"):
            return
        if pl.get("desenho") is None and pl.get("tema"):
            self._desenhar_player(pl)            # (tocar/pausar no PC)
            return
        dur = m["dur"]
        pos = self.programa.notif.posicao(m)
        frac = pl["arraste"] if pl.get("arraste") is not None else (
            pos / dur if dur else 0.0)
        x = x0 + frac * (x1 - x0)
        c.coords("feito", x0, yb, x, yb)
        c.itemconfigure("feito", state="normal" if x > x0 + 1 else "hidden")
        r = int(E.px(5) * pl.get("fator", 1.0)) if pl.get("pula") else 0
        c.coords("pino", x - r, yb - r, x + r, yb + r)
        c.itemconfigure("pino", state="normal" if r else "hidden")
        mostrado = int(frac * dur) if pl.get("arraste") is not None else pos
        for tag, texto in (("t0", self._mmss(mostrado)),
                           ("t1", self._mmss(dur) if dur else "--:--")):
            if c.itemcget(tag, "text") != texto:
                c.itemconfigure(tag, text=texto)

    # -- MINI PLAYER NA BANDEJA (03/out/2026, pedido dele) --------------------
    # Um cartao pequeno colado no relogio com o MESMO player das notificacoes
    # (capa de fundo, musica, barra, anterior/tocar/proxima). Abre pelo menu
    # do icone e pelo atalho "mini_player"; some ao clicar fora, no Esc e no x.

    def alternar_mini_player(self) -> None:
        j = getattr(self, "_mini", None)
        if j is not None and j.winfo_exists():
            self._fechar_mini("menu ou atalho")
        else:
            self._abrir_mini()

    # (03/out, pedido dele: "nao vi utilidade" + ajustar o tamanho) Os
    # ajustes ficam em NOTIFICACOES > ajustes, no config (opcoes):
    MINI_TAMANHOS = [("p", "pequeno"), ("m", "médio"), ("g", "grande")]
    MINI_FATOR = {"p": 0.8, "m": 1.0, "g": 1.3}
    MINI_AUTO_S = 8.0                   # aberto sozinho: some depois disto

    def _mini_ajuste(self, nome: str, padrao):
        return self._config.opcoes.get(nome, padrao)

    def _abrir_mini(self, auto: bool = False) -> None:
        """`auto` = abriu sozinho porque a musica comecou: nao pega o foco
        e some em MINI_AUTO_S (com o mouse em cima, espera)."""
        fator = self.MINI_FATOR.get(self._mini_ajuste("mini_tamanho", "m"),
                                    1.0)
        fixo = bool(self._mini_ajuste("mini_fixo", False))
        j = tk.Toplevel(self)
        j.withdraw()
        j.overrideredirect(True)
        # (03/out, pedido dele) cantos arredondados pelo Windows 11
        # (07/out, camadas) a borda das janelinhas de cima (aviso, menus)
        moldura.arredondar_ao_mostrar(j, borda=E.SUPERFICIE_BORDA)
        try:
            j.attributes("-topmost", True)
            transp = float(self._mini_ajuste("mini_transp", 0.0))
            j.attributes("-alpha", max(0.3, 1.0 - min(0.7, transp)))
        except (tk.TclError, TypeError, ValueError):
            pass
        j.configure(bg=E.FUNDO)          # a borda e a do Windows (arredondar)
        corpo = tk.Frame(j, bg=E.FUNDO)
        corpo.pack(fill="both", expand=True)
        pl = self._montar_player(corpo, ao_fechar=self._fechar_mini)
        pl["fator"] = fator
        pl["frame"].configure(highlightthickness=0,
                              height=int(E.px(self.PLAYER_ALTURA) * fator))
        vazio = tk.Label(corpo, text="nada tocando no celular.", bg=E.FUNDO,
                         fg=E.APAGADO, font=E.fonte(E.CORPO), pady=E.px(18))
        self._mini, self._mini_pl, self._mini_vazio = j, pl, vazio
        self._mini_larg = int(E.px(340) * fator)
        self._mini_tem = None
        self._mini_auto = auto
        self._acertar_mini()
        self._mini_entrar(j)
        if auto:
            from . import aviso_notif
            aviso_notif._sem_foco(j)
            # (03/out, pedido dele) Mouse e cliques NAO seguram nem zeram o
            # tempo; so mexer na barra da musica: enquanto arrasta ele nao
            # some, e ao soltar o tempo recomeca.
            j._parado = False
            c = pl["frame"]
            c.tag_bind("zona", "<Button-1>",
                       lambda _e: setattr(j, "_parado", True), add="+")
            c.tag_bind("zona", "<ButtonRelease-1>", lambda _e: (
                setattr(j, "_parado", False), self._mini_sumir_depois(j)),
                add="+")
            self._mini_sumir_depois(j)
        else:
            try:
                j.focus_force()
                pl["frame"].focus_set()
            except tk.TclError:
                pass
            # (03/out, teste no S22) Some quando OUTRA janela vem para a
            # frente depois que ele esteve na frente (ver `_tique_mini`). O
            # <FocusOut> do Tk fechava na hora: a janela do programa pegava
            # o foco de volta logo depois de abrir.
            j._teve_frente = False
            j._aberto_em = time.monotonic()
        if fixo:
            self._mini_arrastavel(j, pl["frame"])
        # (03/out, pedido dele) dois cliques = o app da musica numa janela
        pl["frame"].bind("<Double-Button-1>",
                         lambda _e: self._abrir_app_do_player(pl), add="+")
        # (07/out) botao direito = o menu da casa com o que o mini faz
        pl["frame"].bind("<Button-3>", lambda e: self._menu_mini(e, j, pl))
        vazio.bind("<Button-3>", lambda e: self._menu_mini(e, j, pl))
        j.bind("<Escape>", lambda _e: self._fechar_mini("esc"))
        self.programa.anotar("mini player: aberto%s" % (
            " sozinho (musica comecou)" if auto else ""))
        self._tique_mini()

    def _menu_mini(self, evento, j, pl) -> str:
        """(07/out, padrao do botao direito) Menu do mini player: abrir o
        app da musica, ficar aberto (chave), tamanho e fechar."""
        if getattr(self, "_mini_auto", False):
            self._mini_sumir_depois(j)   # aberto sozinho: o tempo recomeca
        tam = self._mini_ajuste("mini_tamanho", "m")
        opcoes = []
        if pl.get("sessao"):
            opcoes.append(("abrir o app", lambda: (
                j.winfo_exists() and
                self._abrir_app_do_player(pl, do_menu=True))))
        opcoes.append(("tamanho", [
            (r, lambda v=v: self._mini_mudou("mini_tamanho", v), v == tam)
            for v, r in (("p", "pequeno"), ("m", "médio"),
                         ("g", "grande"))]))
        opcoes.append(("ficar aberto", bool(self._mini_ajuste("mini_fixo",
                                                              False)),
                       lambda v: self._mini_mudou("mini_fixo", bool(v))))
        opcoes.append(None)
        opcoes.append(("fechar", lambda: self._fechar_mini("menu")))
        menu, corpo = self._novo_menu()
        menu._fora = True                # a janela do programa pode nao estar
        self._encher_menu(menu, corpo, evento, opcoes)
        return "break"

    def _abrir_app_do_player(self, pl, do_menu: bool = False) -> None:
        """O app que toca, no que o toque na notificacao de musica abriria
        (a tela do player dele); sem a notificacao, o app. `do_menu` = veio
        do botao direito (nao importa onde o mouse estava)."""
        c = pl["frame"]
        if not do_menu and set(c.gettags("current")) & {
                "ant", "play", "prox", "fechar", "zona"}:
            return                       # dois cliques num botao: so o botao
        m = pl.get("sessao")
        if not m:
            return
        n = next((x for x in self.programa.notif.todas()
                  if x.pacote == m["pacote"] and (
                      x.modelo == "MediaStyle" or x.categoria == "transport")),
                 None)
        self.programa.anotar("mini player: dois cliques, abrir %s"
                             % m["pacote"])
        if n is not None:
            self._abrir_notif(n.app, n.chave)
        elif self._app_abre(m["pacote"]):
            self.programa.abrir_pela_notificacao(m["pacote"])

    def _mini_mudou(self, nome: str, valor) -> None:
        """Ajuste do mini player: grava e, se ele esta aberto, reabre ja
        com o ajuste novo."""
        self._config.opcoes[nome] = valor
        if nome == "mini_fixo" and not valor:
            self._config.opcoes.pop("mini_pos", None)   # volta ao relogio
        ok = self._config.gravar()
        self.programa.anotar("mini player: %s = %s%s" % (
            nome, valor, "" if ok else " (NAO GRAVOU)"))
        self._conferir_gravacao(ok)
        if getattr(self, "_mini", None) is not None:
            self._fechar_mini()
            self._abrir_mini()

    def _mini_transp(self, v: float, soltou: bool) -> None:
        transp = round(max(0.0, min(1.0, v)) * 0.7, 2)
        lbl = self._ui.get("val_mini_transp")
        if lbl is not None:
            try:
                lbl.configure(text="%d%%" % round(transp * 100))
            except tk.TclError:
                pass
        j = getattr(self, "_mini", None)
        if j is not None:
            try:
                j.attributes("-alpha", max(0.3, 1.0 - transp))
            except tk.TclError:
                pass
        if soltou:
            self._config.opcoes["mini_transp"] = transp
            self._conferir_gravacao(self._config.gravar())

    def _altura_do_mini_no_canto(self) -> int:
        """A altura do mini player quando ele esta no canto do relogio (os
        avisos empilham acima dele); 0 se fechado ou arrastado para longe."""
        j = getattr(self, "_mini", None)
        try:
            if j is None or not j.winfo_ismapped():
                return 0
            # (03/out) o lugar FINAL (entrando, ele ainda esta fora da tela)
            jx, jy, larg, alt = getattr(j, "_xy", None) or (
                j.winfo_x(), j.winfo_y(), j.winfo_width(), j.winfo_height())
            x, y = moldura.canto_da_bandeja(self, larg, alt, E.px(12))
            perto = abs(jx - x) < E.px(40) and abs(jy - y) < E.px(40)
            return alt if perto else 0
        except tk.TclError:
            return 0

    def _mini_sumir_depois(self, j) -> None:
        anterior = getattr(j, "_sumir_id", None)
        if anterior is not None:
            try:
                j.after_cancel(anterior)
            except tk.TclError:
                pass
        if self._mini_ajuste("mini_fixo", False):
            return                       # "ficar aberto": nao some sozinho
        try:
            j._sumir_id = j.after(int(self.MINI_AUTO_S * 1000), lambda: (
                None if getattr(j, "_parado", False) or j is not self._mini
                else self._fechar_mini("sumiu sozinho")))
        except tk.TclError:
            pass

    def _mini_arrastavel(self, j, c) -> None:
        """Ficar aberto: arrasta-se pelo fundo (nao pelos botoes nem pela
        barra) e o lugar fica guardado."""
        CLICAVEIS = {"ant", "play", "prox", "fechar", "zona"}

        def pegou(e):
            tags = set(c.gettags("current"))
            j._arraste = None if tags & CLICAVEIS else (
                e.x_root - j.winfo_x(), e.y_root - j.winfo_y())

        def moveu(e):
            if getattr(j, "_arraste", None) is None:
                return
            dx, dy = j._arraste
            j.geometry("+%d+%d" % (e.x_root - dx, e.y_root - dy))

        def soltou(_e):
            if getattr(j, "_arraste", None) is None:
                return
            j._arraste = None
            if getattr(j, "_xy", None) is not None:
                j._xy = (j.winfo_x(), j.winfo_y(), j._xy[2], j._xy[3])
            self._config.opcoes["mini_pos"] = [j.winfo_x(), j.winfo_y()]
            self._config.gravar()

        c.bind("<ButtonPress-1>", pegou, add="+")
        c.bind("<B1-Motion>", moveu, add="+")
        c.bind("<ButtonRelease-1>", soltou, add="+")

    def _posicionar_mini(self) -> None:
        j = self._mini
        j.update_idletasks()
        larg = getattr(self, "_mini_larg", E.px(340))
        alt = j.winfo_reqheight()
        pos = self._mini_ajuste("mini_pos", None)
        if self._mini_ajuste("mini_fixo", False) and \
                isinstance(pos, list) and len(pos) == 2:
            x, y = self._dentro_da_tela(int(pos[0]), int(pos[1]), larg, alt)
        else:
            x, y = moldura.canto_da_bandeja(self, larg, alt, E.px(12))
        if getattr(j, "_anda", None) is not None:
            try:                           # parou no meio: ja visivel inteiro
                j.attributes("-alpha", self._mini_alfa())
            except tk.TclError:
                pass
        j._anda = None                     # um lugar novo para a animacao
        j._xy = (x, y, larg, alt)
        j.geometry("%dx%d+%d+%d" % (larg, alt, x, y))
        self.after(50, self._rearrumar_avisos)

    # (03/out, pedido dele) O mini ENTRA e SAI andando: da borda da tela mais
    # perto (a direita, quando esta no canto do relogio; senao de baixo) ate
    # o lugar dele, aparecendo -- 400 ms na entrada (FAST_OUT_SLOW_IN, como o
    # aviso do Android) e 300 ms na saida (FAST_OUT_LINEAR_IN).
    MINI_ENTRA_MS = 400
    MINI_SAI_MS = 300

    def _mini_de_onde(self, j) -> tuple:
        """O ponto fora da tela de onde o mini vem (e para onde vai)."""
        x, y, larg, alt = j._xy
        try:
            ax, ay, al, aa = moldura.area_util(self, (x + larg // 2,
                                                      y + alt // 2))
        except Exception:
            return x + E.px(60), y
        if x + larg >= ax + al - E.px(160):          # perto da direita
            return ax + al + E.px(8), y
        return x, ay + aa + E.px(8)                  # senao, de baixo

    def _mini_alfa(self) -> float:
        try:
            transp = float(self._mini_ajuste("mini_transp", 0.0))
        except (TypeError, ValueError):
            transp = 0.0
        return max(0.3, 1.0 - min(0.7, transp))

    def _mini_andar(self, j, de, ate, a0, a1, ms, curva, fim=None) -> None:
        from .lista_animada import PADRAO
        curva = curva or PADRAO
        inicio = time.monotonic()
        j._anda = inicio
        larg, alt = j._xy[2], j._xy[3]

        def passo():
            try:
                if not j.winfo_exists() or j._anda != inicio:
                    return
                t = min(1.0, (time.monotonic() - inicio) * 1000.0 / ms)
                k = curva(t)
                j.geometry("%dx%d+%d+%d" % (
                    larg, alt, round(de[0] + (ate[0] - de[0]) * k),
                    round(de[1] + (ate[1] - de[1]) * k)))
                j.attributes("-alpha", a0 + (a1 - a0) * k)
                if t < 1.0:
                    j.after(10, passo)
                elif fim is not None:
                    fim()
            except tk.TclError:
                if fim is not None:
                    fim()
        passo()

    def _mini_entrar(self, j) -> None:
        if not moldura.animacoes_ligadas() or getattr(j, "_xy", None) is None:
            j.deiconify()
            j.lift()
            return
        from .lista_animada import PADRAO
        x, y, larg, alt = j._xy
        fora = self._mini_de_onde(j)
        try:
            j.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        j.geometry("%dx%d+%d+%d" % (larg, alt, fora[0], fora[1]))
        j.deiconify()
        j.lift()
        self._mini_andar(j, fora, (x, y), 0.0, self._mini_alfa(),
                         self.MINI_ENTRA_MS, PADRAO)

    def _rearrumar_avisos(self) -> None:
        """Os avisos do canto sobem/descem quando o mini abre ou fecha."""
        av = getattr(self, "_avisos", None)
        if av is not None:
            try:
                av._arrumar()
            except Exception:
                pass

    def _giro_mini_auto(self) -> None:
        """Abrir sozinho quando uma MUSICA NOVA comeca a tocar (pausar e
        voltar a mesma nao abre). A que ja tocava quando o programa abriu
        nao conta."""
        if not self._mini_ajuste("mini_auto", False):
            return
        cel = bool((self.programa.celular or {}).get("serial"))
        m = self.programa.notif.player() if cel else None
        agora = (m["pacote"], m["titulo"]) if m and m["estado"] == 3 else None
        if agora is None:
            return
        if not hasattr(self, "_mini_ultima"):
            self._mini_ultima = agora
            return
        if agora != self._mini_ultima:
            self._mini_ultima = agora
            if getattr(self, "_mini", None) is None:
                self._abrir_mini(auto=True)

    def _acertar_mini(self) -> None:
        """Poe o mini em dia: o player, ou "nada tocando"."""
        j, pl = getattr(self, "_mini", None), getattr(self, "_mini_pl", None)
        if j is None or pl is None:
            return
        cel = bool((self.programa.celular or {}).get("serial"))
        m = self.programa.notif.player() if cel else None
        tem = m is not None
        if tem != self._mini_tem:
            self._mini_tem = tem
            if tem:
                self._mini_vazio.pack_forget()
                pl["frame"].pack(fill="x")
            else:
                pl["frame"].pack_forget()
                self._mini_vazio.pack(fill="x")
                pl["sessao"] = None
            self._posicionar_mini()
        if not tem:
            return
        if pl.get("sessao") is None or pl["sessao"]["pacote"] != m["pacote"]:
            pl["sessao"] = m
            pl["desenho"] = None
        pl["pula"] = bool(pl["sessao"]["acoes"] & self.ACAO_PULAR) and \
            pl["sessao"]["dur"] > 0
        self._desenhar_player(pl)

    def _tique_mini(self) -> None:
        j = getattr(self, "_mini", None)
        if j is None:
            return
        try:
            if not j.winfo_exists():
                return
            self._acertar_mini()
            if not getattr(self, "_mini_auto", False) and \
                    not self._mini_ajuste("mini_fixo", False) and \
                    self._mini_perdeu_a_frente(j):
                self._fechar_mini("clicou fora")
                return
        except tk.TclError:
            return
        except Exception:
            log.exception("mini player")
        self.after(250, self._tique_mini)

    def _mini_perdeu_a_frente(self, j) -> bool:
        """True quando o mini ja esteve na frente e agora outra janela esta
        (clicou fora). Sem nunca ter tido a frente (o Windows nao deu), nao
        fecha sozinho: sai pelo x, Esc ou o mesmo atalho/menu."""
        try:
            import ctypes
            u = ctypes.windll.user32
            meu = u.GetParent(j.winfo_id()) or j.winfo_id()
            frente = u.GetForegroundWindow()
        except Exception:
            return False
        menu = getattr(self, "_menu_app", None)
        try:
            do_menu = menu is not None and frente == int(menu.wm_frame(), 16)
        except (tk.TclError, ValueError):
            do_menu = False
        if frente == meu or do_menu:     # (07/out) o menu dele conta como dele
            j._teve_frente = True
            j._fora = 0
            return False
        # (03/out, teste no S22) No primeiro segundo a frente ainda vai e
        # volta (o Windows devolvendo para quem abriu): nao conta. Depois,
        # so fecha se a outra janela ficar na frente por 2 tiques (0,5 s).
        if time.monotonic() - getattr(j, "_aberto_em", 0.0) < 1.0 or \
                not getattr(j, "_teve_frente", False) or not frente:
            return False
        j._fora = getattr(j, "_fora", 0) + 1
        return j._fora >= 2

    def _fechar_mini(self, motivo: str = "") -> None:
        j, self._mini, self._mini_pl = getattr(self, "_mini", None), None, None
        if j is not None:
            if motivo:
                self.programa.anotar("mini player: fechado (%s)" % motivo)

            def sumir():
                try:
                    j.destroy()
                except tk.TclError:
                    pass
            self.after(50, self._rearrumar_avisos)
            try:
                andando = moldura.animacoes_ligadas() and j.winfo_ismapped() \
                    and getattr(j, "_xy", None) is not None
                if andando:
                    from .lista_animada import SAIDA
                    atual = (j.winfo_x(), j.winfo_y())
                    self._mini_andar(j, atual, self._mini_de_onde(j),
                                     float(j.attributes("-alpha")), 0.0,
                                     self.MINI_SAI_MS, SAIDA, sumir)
                    return
            except tk.TclError:
                pass
            sumir()

    def _copiar_texto(self, texto: str) -> None:
        """(02/out) "copiar texto" do menu da notificacao."""
        try:
            self.clipboard_clear()
            self.clipboard_append(texto)
            self.update_idletasks()
        except tk.TclError:
            return
        self.programa.anotar("notificacao: texto copiado")

    def _copiar_codigo(self, codigo: str, rotulo=None) -> None:
        """(01/out) Codigo de verificacao -> area de transferencia."""
        try:
            self.clipboard_clear()
            self.clipboard_append(codigo)
            self.update_idletasks()
        except tk.TclError:
            return
        self.programa.anotar("notificacao: codigo copiado")
        if rotulo is not None:
            try:
                antes = rotulo.cget("text")
                rotulo.configure(text="copiado ✓")
                rotulo.after(1500, lambda: rotulo.winfo_exists() and
                             rotulo.configure(text=antes))
            except tk.TclError:
                pass

    def _pintar_notif_hist(self, rol) -> None:
        c = self.programa.notif
        hist = c.historico_visivel()[:self.HIST_MAX]
        ids = tuple((h.get("chave"), h.get("quando"), h.get("titulo"),
                     h.get("texto")) for h in hist)
        assin = (ids, self._icones_versao)
        if assin == self._ui.get("notif_pintada"):
            return
        self._ui["notif_pintada"] = assin
        lista = self._lista_anim(rol)
        itens, horas, vistos = [], [], set()
        if not hist:
            itens.append(("msg", self._bloco_texto(
                "nada nas últimas 24 horas. o histórico guarda o que chega "
                "enquanto o scrcpy-f está conectado ao celular."),
                ("msg",), E.px(6)))
        for ident, h in zip(ids, hist):
            k = "h|%s|%s" % (ident[0], ident[1])
            if k in vistos:
                k += "|%d" % len(vistos)
            vistos.add(k)
            itens.append((k, lambda p, h=h: self._desenhar_linha_hist(p, h),
                          (ident, self._icones_versao), E.px(5)))
            horas.append((k, h.get("quando")))
        self._ui["notif_dados"] = {}
        # (07/out) o botao direito no historico precisa saber de quem e
        self._ui["hist_dados"] = {k: h for (k, _q), h in zip(horas, hist)}
        self._ui["notif_horas"] = horas
        self._ui["notif_horas_txt"] = {k: self._quando_notif(q)
                                        for k, q in horas}
        self._definir_lista(lista, itens)

    def _desenhar_linha_hist(self, p, h) -> int:
        app = str(h.get("app") or "")
        nome = self._nome_notif(app)
        pad = E.px(8)
        lado = E.px(16)
        x0 = p.x0 + pad
        xt = x0 + lado + E.px(8)
        larg = max(E.px(60), p.x1 - pad - xt)
        y = p.y + E.px(7)
        self._desenhar_icone(p, app, nome, x0, y + E.px(1), lado)
        _it, hh = p.texto(xt, y, "%s  ·  %s" % (
            nome, self._quando_notif(h.get("quando"))),
            E.fonte(E.ROTULO), E.APAGADO)
        y += hh
        if h.get("titulo"):
            _it, hh = p.texto(xt, y, self._uma_linha(
                str(h["titulo"]), E.fonte(E.PEQUENA), larg),
                E.fonte(E.PEQUENA), E.TEXTO)
            y += hh
        texto = str(h.get("texto") or "")
        if texto:
            if len(texto) > self.NOTIF_TEXTO_MAX:
                texto = texto[:self.NOTIF_TEXTO_MAX - 1] + "…"
            _it, hh = p.texto(xt, y, texto, E.fonte(E.ROTULO), E.TEXTO_2,
                              largura=larg)
            y += hh
        y += E.px(7)
        alto = int(y - p.y)
        fim = p.y + (int(p.corte) if p.corte is not None else alto)
        if fim - p.y >= E.px(16):
            p.cartao(p.y, fim, E.CAMADA_1, E.BORDA_1, extra=(p.tag + "f",))
            p.c.tag_lower(p.tag + "f")
        return alto

    def _apps_para_notif(self) -> list:
        """[(app, nome)] da lista de apps do celular + quem ja mandou
        notificacao, por nome. Sem o DeX."""
        vistos = {}
        for nome, p, _s in (self._apps or getattr(self.programa,
                                                  "apps_do_celular", None)
                            or []):
            if p != DEX:
                vistos[p] = nome
        c = self.programa.notif
        for n in c.todas():
            vistos.setdefault(n.app, self._nome_notif(n.app))
        for h in c.historico_visivel()[:200]:
            app = str(h.get("app") or "")
            if app:
                vistos.setdefault(app, self._nome_notif(app))
        return sorted(vistos.items(), key=lambda x: x[1].lower())

    def _pintar_notif_ajustes(self, rol) -> None:
        """
        LEVE (01/out, "a aba ajustes esta muito pesada"): as linhas sao
        montadas UMA vez por lista de apps (em lotes, como a de APPS) e a
        tela fica guardada (TELAS_GUARDADAS). Chave virada, geral, marca de
        "desligada no celular" e busca mudam NO LUGAR -- antes cada uma
        refazia as ~80 linhas.
        """
        c = self.programa.notif
        apps = self._apps_para_notif()
        chave = ("ajustes", tuple(apps), self._icones_versao)
        if chave != self._ui.get("notif_pintada"):
            self._ui["notif_pintada"] = chave
            self._acertar_linhas_notif(rol, apps)
        linhas = self._ui.get("notif_linhas") or {}
        bloq = c.bloqueados
        for app, (_linha, chave_w, marca, _ic) in linhas.items():
            ligada = c.ligada(app)
            if chave_w._ligado != ligada:
                chave_w.definir(ligada)
            bloqueado = app in bloq
            if bloqueado != bool(marca.winfo_manager()):
                if bloqueado:
                    marca.pack(side="top", fill="x")
                else:
                    marca.pack_forget()
        self._filtrar_notif()

    def _acertar_linhas_notif(self, rol, apps) -> None:
        """
        As linhas que JA existem ficam (destruir ~80 custava ~250 ms): app
        novo ganha linha (em lotes), app que saiu perde a dele, icones que
        chegaram trocam so o icone. A ordem vem do `_filtrar_notif`.
        """
        d = rol.dentro
        linhas: dict = self._ui.setdefault("notif_linhas", {})
        nomes = {a: n for a, n in apps}
        self._ui["notif_ordem"] = [a for a, _n in apps]
        self._ui["notif_nomes"] = {a: n.lower() for a, n in apps}
        if self._ui.get("notif_vazio") is None:
            self._ui["notif_vazio"] = E.Texto(
                d, "a lista de apps chega quando o celular conectar.",
                cor=E.APAGADO, bg=d.cget("bg"))
        for app in [a for a in linhas if a not in nomes]:
            linhas.pop(app)[0].destroy()
        versao = self._icones_versao
        if self._ui.get("notif_icones") != versao:
            self._ui["notif_icones"] = versao
            for app, (linha, chave_w, marca, ic) in list(linhas.items()):
                novo = self._icone_app(linha, app, nomes[app], E.px(16),
                                       fundo=d.cget("bg"))
                novo.pack(side="left", padx=(E.px(0), E.px(6)), before=ic)
                ic.destroy()
                linhas[app] = (linha, chave_w, marca, novo)
        c = self.programa.notif

        def fazer(item):
            app, nome = item
            if app in linhas:
                return
            # (08/out) na cor do painel em que a lista mora
            fundo = d.cget("bg")
            linha = tk.Frame(d, bg=fundo)
            ic = self._icone_app(linha, app, nome, E.px(16), fundo=fundo)
            ic.pack(side="left", padx=(E.px(0), E.px(6)))
            textos = tk.Frame(linha, bg=fundo)
            textos.pack(side="left", fill="x", expand=True, pady=E.px(3))
            tk.Label(textos, text=_encurtar(nome, 26), bg=fundo,
                     fg=E.TEXTO, font=E.fonte(E.ROTULO), anchor="w").pack(
                side="top", fill="x")
            marca = tk.Label(textos, text="desligada no celular",
                             bg=fundo, fg=E.ALERTA,
                             font=E.fonte(E.ROTULO - 1), anchor="w")
            if app in c.bloqueados:
                marca.pack(side="top", fill="x")
            chave_w = E.Chave(linha, c.ligada(app),
                              lambda v, a=app: self._virar_notif_app(a, v),
                              bg=fundo)
            chave_w.pack(side="right")
            linhas[app] = (linha, chave_w, marca, ic)

        novos = [x for x in apps if x[0] not in linhas]
        self._em_lotes(d, novos, fazer, primeiro=14, lote=16,
                       ao_fim=self._filtrar_notif)
        self._filtrar_notif()

    def _combina_notif(self, app: str) -> bool:
        termo = getattr(self, "_busca_notif", "").strip().lower()
        return not termo or termo in app.lower() or \
            termo in (self._ui.get("notif_nomes") or {}).get(app, "")

    def _filtrar_notif(self, animar: bool = False) -> None:
        """A busca so mostra/esconde as linhas ja montadas, na ordem.
        (09/out) Pelo `Arranjo`: a busca anima (sai esmaecendo, o resto
        anda); o resto (chave virada, linha nova) vai direto."""
        rol = self._ui.get("rolagem_notif")
        if rol is None or not rol.canvas.winfo_exists():
            return
        linhas = self._ui.get("notif_linhas") or {}
        ordem = self._ui.get("notif_ordem") or []
        vazio = self._ui.get("notif_vazio")
        chaves = [a for a in ordem if a in linhas and self._combina_notif(a)]
        if not chaves and vazio is not None and \
                len(linhas) >= len(ordem):
            vazio.configure(text="nenhum app encontrado." if ordem else
                            "a lista de apps chega quando o celular "
                            "conectar.")
            chaves = ["_vazio"]
        arr = self._ui.get("arranjo_notif")
        if arr is None:
            querido = [vazio if c == "_vazio" else linhas[c][0]
                       for c in chaves]
            self._repor_notif(rol.dentro, querido)   # so o que mudou
            return

        def criar(c):
            return vazio if c == "_vazio" else linhas[c][0]
        layout = FA.empilhar(arr, chaves, criar, 0)
        adiadas = arr.aplicar(layout, criar, animar=animar, topo=animar,
                              adiar=True)
        if adiadas:     # as de fora da vista vao para o lugar aos poucos
            self._em_lotes(rol.canvas, adiadas,
                           lambda c: arr.criar_adiado(c, criar), primeiro=0)

    def _virar_windows_notif(self, nome: str, ligado: bool) -> None:
        self._virar_opcao(nome, ligado)
        p = self.programa
        if nome == "player_windows":
            m = p.notif.player()
            p._windows_player(m, p.notif.posicao(m) if m else 0)
        elif not ligado and p.windows_notif is not None:
            p.windows_notif.limpar()

    def _virar_notif_geral(self, ligado: bool) -> None:
        self._conferir_gravacao(self._config.definir_notif_geral(ligado))
        self.programa.anotar("notificacoes no pc: geral %s (excecoes zeradas)"
                             % ("ligada" if ligado else "desligada"))
        self.programa._avisar_mudanca()     # as chaves viram no lugar

    def _virar_notif_app(self, app: str, ligado: bool) -> None:
        self._conferir_gravacao(self._config.definir_notif_app(app, ligado))
        self.programa.anotar("notificacoes no pc: %s %s" % (
            app, "ligada" if ligado else "desligada"))
        self.programa._avisar_mudanca()     # a lista compara as chaves

    def _remover_notif(self, chaves) -> None:
        self.programa.notif.remover(
            chaves, avisar=lambda t: self._da_outra_thread.put(
                lambda: self.programa.anotar("notificacoes: %s" % t)))

    def _limpar_notif(self, app: str = "") -> None:
        chaves = self.programa.notif.para_limpar(app)
        self.programa.anotar("notificacoes: limpar %s (%d)" % (
            app or "tudo", len(chaves)))
        if chaves:
            # (03/out) como o "limpar tudo" do Android: saem de lado uma
            # atras da outra
            if self._aba.get("notif") == "lista":
                for i, k in enumerate(chaves):
                    self._dispensar_notif(k, atraso_ms=i * 45)
            self._remover_notif(chaves)

    def _limpar_hist(self) -> None:
        self.programa.notif.limpar_historico()
        self._ui["notif_pintada"] = None
        self._pintar_notif()

    def _abrir_notif(self, app: str, chave: str = "") -> None:
        """(01/out) Clique no cartao: o que o toque no celular abriria (o
        destino e lido na hora: a notificacao pode ter mudado de alvo)."""
        alvo = next((n.alvo for n in self.programa.notif.todas()
                     if n.chave == chave), None)
        if alvo is not None or self._app_abre(app):
            self.programa.abrir_pela_notificacao(app, alvo, chave)

    HORAS_A_CADA_S = 20.0

    def _giro_notif(self) -> None:
        """Os avisos no canto da tela (`aviso_notif`), na thread do Tk; e a
        hora das notificacoes a vista, de tempos em tempos, no lugar."""
        if self._item == "notif" and self._na_tela():
            agora = time.monotonic()
            if agora - getattr(self, "_horas_em", 0.0) >= self.HORAS_A_CADA_S:
                self._horas_em = agora
                self._horas_notif()
            if self._aba.get("notif") == "lista":
                self._pintar_barra_player()      # a barra anda (so o canvas)
                # (02/out) cronometros e progresso indeterminado andam
                # (03/out: o bloco e refeito no canvas, sem piscar)
                lista = self._ui.get("notif_lista_anim")
                if lista is not None:
                    seg = int(time.time())
                    if seg != getattr(self, "_cronos_em", None):
                        self._cronos_em = seg
                        for k in self._ui.get("notif_cronos", ()):
                            lista.redesenhar(k)
                    for k in self._ui.get("notif_girando", ()):
                        lista.redesenhar(k)
        self._giro_chamada()
        self._giro_mini_auto()
        novas = self.programa.notif.proximos_avisos()
        if not novas:
            return
        self._criar_avisos()
        for n in novas[-3:]:
            botoes = []
            codigo = nt_codigo(n)
            if codigo:
                botoes.append(("copiar código %s" % codigo,
                               lambda cd=codigo: self._copiar_codigo(cd)))
            # (03/out) Com o ouvinte: os botoes do app e o responder no
            # proprio aviso; sem ele, os de antes.
            o = self.programa.notif.ouvida(n.chave) or {}
            responder = None
            acoes_app = (o.get("acoes") or [])[:3]
            for i, (rotulo, com_texto, _tela) in enumerate(acoes_app):
                # (07/out, pedido dele) o rotulo inteiro, sem "…"
                if com_texto and responder is None:
                    responder = (rotulo.strip().lower(),
                                 lambda texto, ao_fim, i=i, ap=n.app,
                                 k=n.chave: self._responder_do_aviso(
                                     ap, k, i, texto, ao_fim))
                elif not com_texto:
                    botoes.append((rotulo.strip().lower(),
                                   lambda i=i, ap=n.app, k=n.chave:
                                   self.programa.acao_notificacao(ap, k, i)))
            if not acoes_app:
                for rotulo, alvo in nt_botoes(n)[:2]:
                    botoes.append((rotulo.strip().lower(),
                                   lambda a=alvo, ap=n.app:
                                   self.programa.abrir_pela_notificacao(ap, a)))
            # (03/out) conversa: quem mandou e o que mandou, como no celular
            self._avisos.mostrar(n.app, self._nome_notif(n.app),
                                 n.conversa or n.titulo,
                                 self._curto_notif(n) if n.mensagens
                                 else n.texto or n.subtexto,
                                 self._quando_notif(n.quando), dado=n.chave,
                                 botoes=botoes, responder=responder,
                                 rosto=self._imagem_notif(
                                     o.get("icone"), E.px(18), E.SUPERFICIE,
                                     redonda=True))

    def _responder_do_aviso(self, app: str, chave: str, indice: int,
                            texto: str, ao_fim) -> None:
        """(03/out) A resposta digitada no aviso do canto."""
        def fim(ok, detalhe):
            motivo = self.programa.notif.motivo_legivel(detalhe)
            self._da_outra_thread.put(lambda: ao_fim(ok, motivo))
        self.programa.acao_notificacao(app, chave, indice, texto, fim)

    def _criar_avisos(self) -> None:
        if getattr(self, "_avisos", None) is None:
            from . import aviso_notif
            self._avisos = aviso_notif.Avisos(self, self._icone_app,
                                              self._clicou_aviso,
                                              self.programa.anotar)
            self._avisos.reserva = self._altura_do_mini_no_canto
            # (07/out) botao direito no aviso = o menu da notificacao
            self._avisos.ao_menu = lambda app, chave, e: self._menu_notif(
                e, app, chave, fora=True)

    def _giro_chamada(self) -> None:
        """(01/out) A chamada tocando: aviso proprio, ate ela acabar."""
        n = self.programa.notif.chamada
        chave = n.chave if n is not None else None
        if chave == getattr(self, "_chamada_vista", None):
            return
        self._chamada_vista = chave
        self._criar_avisos()
        self._avisos.fechar_chamada()
        if n is not None:
            self._avisos.mostrar_chamada(
                n.app, self._nome_notif(n.app), n.titulo or "chamada",
                n.texto, self.programa.atender_chamada,
                self.programa.recusar_chamada)

    def abrir_link(self, url: str, tentativa: int = 0) -> None:
        """
        (01/out) Clique numa notificacao na Central do Windows
        ("scrcpyf:notif?c=<chave>&a=<app>"): o mesmo que o clique no aviso.
        Com o programa recem-aberto o celular ainda nao foi lido: espera
        ate ~15 s pela notificacao; sem ela, abre o app (ou esta janela).
        """
        from . import central_windows
        chave, app = central_windows.ler_endereco(url)
        tipo, indice = central_windows.ler_tipo(url)
        if tentativa == 0:
            self.programa.anotar("windows: clique na central (%s%s)" % (
                app or url, "" if tipo == "notif" else
                ", %s %s" % (tipo, "" if indice is None else indice)))
        c = self.programa.notif
        n = next((x for x in c.todas() if x.chave == chave), None)
        # (03/out) os botoes ("acao") precisam do ouvinte em dia tambem
        falta = (n is None and not c.todas()) or \
            (tipo == "acao" and c.ouvida(chave) is None)
        if falta and tentativa < 30:
            self.after(500, lambda: self.abrir_link(url, tentativa + 1))
            return
        if tipo == "acao" and indice is not None:
            # um botao do app (marcar como lida, curtir...): o celular faz
            self.programa.acao_notificacao(app, chave, indice)
        elif tipo == "responder":
            # a caixa de resposta no proprio scrcpy-f (pela Central o
            # Windows nao repassa o texto digitado)
            self.abrir_em("notif", "lista")
            self.mostrar()
            self._notif_abertas.add(chave)
            self.after(300, lambda: self._respondendo != chave and
                       self._abrir_resposta(chave))
        else:
            self._clicou_aviso(app, chave)

    def _clicou_aviso(self, app: str, chave: str = "") -> None:
        """Clique no aviso: o que o toque no celular abriria, numa janela do
        PC; sem destino e sem janela possivel -> esta janela, nas
        notificacoes."""
        alvo = next((n.alvo for n in self.programa.notif.todas()
                     if n.chave == chave), None)
        if alvo is not None or self._app_abre(app):
            self.programa.abrir_pela_notificacao(app, alvo, chave)
        else:
            self.abrir_em("notif", "lista")
            self.mostrar()

    # ==========================================================================
    # OPCOES
    # ==========================================================================

    # (07/out, pedido dele: "organize as configuracoes gerais") OPCOES >
    # GERAL so com o PROGRAMA: como ele inicia e os avisos; a direita, as
    # atualizacoes. O que e do rodape (icones, gestos) ganhou aba propria.
    # Sub-opcao so aparece com a de origem ligada (iniciar mais rapido,
    # ao criar atalho). Escolha entre varios itens = LISTA SUSPENSA (a
    # pilula que abre o menu da casa); liga/desliga = chave.
    def _tela_opcoes_geral(self, area) -> None:
        esq, dir_ = self._duas(area)
        # com as sub-opcoes abertas passa da altura: rola
        rol = _Rolagem(esq)
        self._ui["rolagem_geral"] = rol
        col_esq = rol.dentro
        # (08/out, pedido dele: juntar por assunto) o PROGRAMA num painel:
        # iniciar e avisos
        esq = self._seg(col_esq, "programa")
        self._sub(esq, "iniciar", primeiro=True)
        if inicio_windows.disponivel():
            w = self._chave(esq, "abrir com o windows",
                            bool(self._windows_ligado),
                            lambda _v: self._virar_windows(),
                            explicacao="o programa já nasce na bandeja")
            self._ui["windows"] = w
            sub = tk.Frame(esq, bg=E.FUNDO)
            self._ui["sub_windows"] = sub
            self._ui["chave_rapido"] = self._chave(
                sub, "iniciar mais rápido",
                bool(self._windows_ligado)
                and bool(getattr(self, "_rapido_ligado", False)),
                lambda v: self._virar_rapido(v),
                explicacao="junto com o login; pede o administrador uma vez")
            if self._windows_ligado:
                sub.pack(side="top", fill="x", after=w.master,
                         padx=(E.px(16), 0))
        self._chave(esq, "mostrar a janela ao abrir",
                    self._config.opcao("abrir_janela_ao_iniciar"),
                    lambda v: self._virar_opcao("abrir_janela_ao_iniciar", v),
                    explicacao="desligado: abre só na bandeja", borda=False)
        atual = self._config.opcoes.get("pagina_inicial", "jogo") \
            if self._config.opcao("pagina_inicial_ligada") else "jogo"
        self._lista_suspensa(esq, "abrir em", list(self.NOMES_DAS_PAGINAS),
                             atual, self._escolheu_inicial,
                             pady=(E.px(6), E.px(0)))

        self._sub(esq, "avisos")
        av = self._chave(esq, "avisos do programa",
                         self._config.opcao("notificacoes"),
                         lambda v: (self._virar_opcao("notificacoes", v),
                                    self._acertar_sub_chaves()),
                         explicacao="avisos do windows ao ligar e desligar")
        sub = tk.Frame(esq, bg=E.FUNDO)
        self._ui["sub_avisos"] = sub
        self._ui["chave_aviso_atalho"] = self._chave(
            sub, "ao criar atalho",
            self._config.opcao("aviso_atalho"),
            lambda v: self._virar_opcao("aviso_atalho", v),
            explicacao="o aviso de atalho criado na área de trabalho",
            borda=False)
        self._ui["chave_avisos"] = av
        if self._config.opcao("notificacoes"):
            sub.pack(side="top", fill="x", after=av.master,
                     padx=(E.px(16), 0))
        # (08/out, pedido dele) COPIAR E COLAR entre o PC e o celular (o
        # que esta no ar sobe de novo ja com a escolha)
        self._sub(esq, "pc e celular")
        self._chave(esq, "área de transferência compartilhada",
                    self._config.opcao("area_compartilhada"),
                    lambda v: (self._virar_opcao("area_compartilhada", v),
                               self.programa.aplicar_area_compartilhada(
                                   reabrir=True)),
                    explicacao="copiar no celular cola no pc, e o contrário",
                    borda=False)

        self._coluna_atualizacoes(dir_)

    def _lista_suspensa(self, pai, nome: str, opcoes, valor, ao_escolher,
                        nome_larg: int = 10, pady=(0, 0)) -> tk.Label:
        """(07/out) ESCOLHA ENTRE VARIOS ITENS: o nome a esquerda e uma
        pilula "valor ▾" que abre o menu da casa logo abaixo, com a escolha
        de agora marcada. Teclado: Enter/espaco abre."""
        linha = tk.Frame(pai, bg=E.FUNDO)
        linha.pack(side="top", fill="x", pady=pady)
        # (08/out, padrao da qualidade) o nome numa coluna fixa em px e a
        # escolha num CARTAO (a cara dos cartoes de escolha), nao mais pilula
        linha.grid_columnconfigure(0, minsize=E.px(nome_larg * 7))
        tk.Label(linha, text=nome, bg=E.FUNDO, fg=E.TEXTO_2,
                 font=E.fonte(E.PEQUENA), anchor="w").grid(
            row=0, column=0, sticky="w")
        pilula = tk.Label(linha, bg=E.CAMADA_1, fg=E.TEXTO, anchor="w",
                          font=E.fonte(E.PEQUENA), padx=E.px(10),
                          pady=E.px(4), cursor="hand2", takefocus=1,
                          highlightthickness=1, highlightbackground=E.BORDA_1,
                          highlightcolor=E.FOCO)
        pilula.grid(row=0, column=1, sticky="w")
        pilula._valor = valor
        rotulos = dict(opcoes)

        def pintar():
            pilula.configure(text="%s  ▾" % rotulos.get(pilula._valor, "—"))
            E.cantos(pilula)

        def escolher(v):
            pilula._valor = v
            pintar()
            ao_escolher(v)

        def abrir(_e=None):
            if self._menu_alternar(pilula):
                return "break"
            if _e is not None and hasattr(_e, "x_root"):
                self._clique_em_qualquer_lugar(_e)
            menu, corpo = self._novo_menu()
            menu._dono = pilula
            itens = [(r, lambda v=v: escolher(v), True) if v == pilula._valor
                     else (r, lambda v=v: escolher(v)) for v, r in opcoes]
            import types
            onde = types.SimpleNamespace(
                x_root=pilula.winfo_rootx() - E.px(2),
                y_root=pilula.winfo_rooty() + pilula.winfo_height())
            self._encher_menu(menu, corpo, onde, itens,
                              largura_min=pilula.winfo_width())
            return "break"

        for ev in ("<Button-1>", "<Return>", "<space>"):
            pilula.bind(ev, abrir)
        pilula.bind("<Enter>", lambda _e: (pilula.configure(
            highlightbackground=E.BORDA_1_SOBRE), E.cantos(pilula)), add="+")
        pilula.bind("<Leave>", lambda _e: (pilula.configure(
            highlightbackground=E.BORDA_1), E.cantos(pilula)), add="+")
        pintar()
        return pilula

    # (07/out, pedido dele) OPCOES > RODAPE: a aparencia dos icones do
    # rodape e o que cada gesto faz neles (de fabrica, nada).
    def _tela_opcoes_rodape(self, area) -> None:
        col_esq, col_dir = self._duas(area)
        esq = self._seg(col_esq, "ícones")
        self._fila(esq, "tamanho", self.TAMANHOS_RODAPE,
                   self._config.opcoes.get("icones_rodape") or "m",
                   self._escolheu_tamanho_rodape, espaco=2, nome_larg=8)
        self._chave(esq, "porcentagem na bateria",
                    self._config.opcao("bateria_pct"),
                    lambda v: (self._virar_opcao("bateria_pct", v),
                               self._pintar_barra()),
                    explicacao="o número dentro da bateria")
        self._info(esq, "da esquerda: bateria, conexão, som e temperatura.",
                   "o rodapé\n"
                   "bateria: a cor vai do vermelho (10%) ao verde (100%)\n"
                   "temperatura: azul frio, âmbar aquecendo, vermelho "
                   "quente\n"
                   "a temperatura é lida a cada 90 s").pack(
            side="top", fill="x", pady=(E.px(8), E.px(0)))

        self._info(col_dir, "gestos: de fábrica os ícones só mostram.",
                   "gestos nos ícones\n"
                   "conexão: trocar = cabo / sem fio; desligar = desconecta "
                   "tudo\n"
                   "som: trocar = pc / celular; nos dois = pc e celular "
                   "(android 13+)\n"
                   "todos = o mesmo destino em todos os modos\n"
                   "as mesmas funções têm atalho em opções › atalhos").pack(
            side="top", fill="x", pady=(0, E.px(6)))
        # (08/out, padrao da qualidade) UM painel, numa tabela: o gesto na
        # linha, conexao e som nas colunas (dois paineis passavam da altura);
        # os nomes curtos (a coluna ja diz de quem e; o i explica)
        nomes_f = {"som": {"trocar": "trocar", "ambos": "nos dois",
                           "todos": "todos"},
                   "con": {"trocar": "trocar", "alternar": "desligar"}}
        dir_ = self._seg(col_dir, "gestos nos ícones")
        tabela = tk.Frame(dir_, bg=E.FUNDO)
        tabela.pack(side="top", fill="x")
        tabela.grid_columnconfigure(0, minsize=E.px(64))
        tabela.grid_columnconfigure((1, 2), weight=1, uniform="g")
        for col, cab in ((1, "conexão"), (2, "som")):
            tk.Label(tabela, text=cab, bg=E.FUNDO, fg=E.APAGADO,
                     font=E.fonte(E.ROTULO), anchor="w").grid(
                row=0, column=col, sticky="w", pady=(0, E.px(4)))
        for lin, (g, rot) in enumerate(self.GESTOS_IND, start=1):
            tk.Label(tabela, text=rot, bg=E.FUNDO, fg=E.TEXTO_2,
                     font=E.fonte(E.PEQUENA), anchor="w").grid(
                row=lin, column=0, sticky="w")
            for col, tipo in ((1, "con"), (2, "som")):
                cel = tk.Frame(tabela, bg=E.FUNDO)
                cel.grid(row=lin, column=col, sticky="w",
                         pady=(0, E.px(5)))
                opcoes = [("", "nada")] + [(f, nomes_f[tipo][f])
                                           for f, _r in self.FUNCOES_IND[tipo]]
                self._lista_suspensa(
                    cel, "", opcoes, self._config.gesto(tipo, g),
                    lambda v, t=tipo, gg=g: self._escolheu_gesto(t, gg, v),
                    nome_larg=0)

    def _escolheu_tamanho_rodape(self, valor: str) -> None:
        if valor == "m":
            self._config.opcoes.pop("icones_rodape", None)
        else:
            self._config.opcoes["icones_rodape"] = valor
        self._conferir_gravacao(self._config.gravar())
        self.programa.anotar("icones do rodape: %s" % valor)
        self._pintar_barra()

    def _escolheu_gesto(self, tipo: str, gesto: str, funcao) -> None:
        self._conferir_gravacao(self._config.definir_gesto(tipo, gesto,
                                                           funcao or ""))
        self.programa.anotar("indicador %s: %s = %s" % (tipo, gesto,
                                                         funcao or "nada"))
        self._pintar_barra()

    # -- OPCOES > geral, coluna da direita: ATUALIZACOES (r195) ----------------
    #
    # Pedido dele (30/set/2026): "mais bonita e facil de entender". Antes: a
    # pasta em 4 linhas no topo, um botao "procurar atualizacao" embaixo da
    # PASTA (mas procurava os dois programas), um rotulo com o mesmo nome do
    # botao, o resultado num texto so e a versao do scrcpy-f cortada no pe.
    # Agora, na ordem da pergunta que ele faz ("estou em dia?"):
    #   1. ATUALIZACOES: tabela scrcpy-f / scrcpy com a versao e o estado de
    #      cada um (verde em dia, laranja versao nova + "atualizar");
    #   2. quando conferiu + o botao (PROCURAR AGORA; sem scrcpy, INSTALAR
    #      O SCRCPY e o principal);
    #   3. PROCURAR SOZINHO: diario / semanal / mensal / nunca;
    #   4. PASTA DO SCRCPY numa linha (meio encurtado) + "trocar".

    def _coluna_atualizacoes(self, dir_) -> None:
        ok, texto = conexao.conferir_pasta(self._config.scrcpy)
        col = dir_
        dir_ = self._seg(col, "atualizações")
        tabela = tk.Frame(dir_, bg=E.LINHA)
        tabela.pack(side="top", fill="x")
        E.cantos(tabela, dentro=E.FUNDO_FUNDO, borda=E.LINHA)   # (03/out)
        linhas = {}
        for n, (chave, nome) in enumerate((("app", "scrcpy-f"),
                                           ("scrcpy", "scrcpy"))):
            lin = tk.Frame(tabela, bg=E.FUNDO_FUNDO)
            lin.pack(side="top", fill="x", padx=1,
                     pady=(1, 1) if n == 0 else (0, 1))
            tk.Label(lin, text=nome, bg=E.FUNDO_FUNDO, fg=E.TEXTO,
                     font=E.fonte(E.PEQUENA), anchor="w", width=9).pack(
                side="left", padx=(E.px(8), E.px(0)), pady=E.px(4))
            versao = tk.Label(lin, text="", bg=E.FUNDO_FUNDO, fg=E.TEXTO_2,
                              font=E.fonte(E.PEQUENA), anchor="w", width=7)
            versao.pack(side="left")
            estado = tk.Label(lin, text="", bg=E.FUNDO_FUNDO,
                              font=E.fonte(E.PEQUENA), anchor="e",
                              takefocus=0, highlightthickness=1,
                              highlightbackground=E.FUNDO_FUNDO,
                              highlightcolor=E.FOCO)
            estado.pack(side="right", padx=(E.px(0), E.px(8)))
            estado.bind("<Button-1>", lambda _e, w=estado: self._clicou_estado(w))
            estado.bind("<Return>", lambda _e, w=estado: self._clicou_estado(w))
            estado.bind("<space>", lambda _e, w=estado: self._clicou_estado(w))
            linhas[chave] = (versao, estado)
        self._ui["upd_linhas"] = linhas

        acao = tk.Frame(dir_, bg=E.FUNDO)
        acao.pack(side="top", fill="x", pady=(E.px(6), E.px(0)))
        if ok:
            # (08/out) o botao na linha do titulo: embaixo, ao lado do
            # "conferido", empurrava a coluna para alem da altura
            E.Botao(dir_._topo, "procurar agora", self._procurar_agora,
                    tipo="discreto").pack(side="right")
        # Quando conferiu -- ou, instalando, o andamento (acima do botao,
        # a vista; embaixo da pasta ele passava da borda da janela).
        quando = tk.Label(acao, text="", bg=E.FUNDO, fg=E.TEXTO_2,
                          font=E.fonte(E.PEQUENA), anchor="w",
                          justify="left",
                          wraplength=E.px(230))
        quando.pack(side="left", fill="x")
        self._ui["procura"] = quando
        if not ok:
            # (r166) Sem scrcpy, INSTALAR e o principal da tela inteira.
            E.Botao(dir_, "instalar o scrcpy", self._baixar,
                    tipo="acao").pack(side="top", fill="x",
                                      pady=(E.px(8), E.px(0)))

        # (08/out, pedido dele: juntar por assunto) tudo das atualizacoes
        # num painel so
        self._sub(dir_, "procurar sozinho")
        E.Segmentado(dir_, (("diario", "diário"), ("semanal", "semanal"),
                            ("mensal", "mensal"), ("nunca", "nunca")),
                     self.programa.prazo_atualizacao(),
                     self._escolheu_prazo).pack(side="top", fill="x")

        topo = self._sub(dir_, "pasta do scrcpy")
        # (r166) "usar outra pasta" pequeno: para quem nao tem
        # administrador, nao alcanca o GitHub ou quer outra versao.
        self._link(topo, "trocar" if self._config.scrcpy else
                   "usar outra pasta", self._escolher_pasta).pack(
            side="right")
        tk.Label(dir_, text=_encurtar_caminho(self._config.scrcpy or
                                      "nenhuma escolhida", 34),
                 bg=E.FUNDO, fg=E.TEXTO_2 if self._config.scrcpy
                 else E.APAGADO, font=E.fonte(E.PEQUENA),
                 anchor="w").pack(side="top", fill="x")
        # So o erro de uma pasta escolhida (sem pasta, "nenhuma escolhida"
        # ja diz) e o andamento do instalar.
        s = E.Texto(dir_, texto.lower() if self._config.scrcpy and not ok
                    else "", cor=E.ERRO, largura=E.px(230))
        s.pack(side="top", fill="x", pady=(E.px(4), E.px(0)))
        self._ui["status_pasta"] = s
        self._pintar_atualizacoes()

    def _pintar_atualizacoes(self) -> None:
        linhas = self._ui.get("upd_linhas")
        if not linhas or not linhas["app"][0].winfo_exists():
            return
        p = self.programa
        # (02/out, revisao) Roda a cada `_repintar` com OPCOES aberta: a pasta
        # (disco, na thread do Tk) e conferida no maximo a cada 5 s, e cada
        # rotulo so e mexido se mudou.
        agora = time.monotonic()
        guardada = getattr(self, "_pasta_conferida", None)
        if guardada and guardada[0] == self._config.scrcpy and \
                agora - guardada[1] < 5.0:
            ok = guardada[2]
        else:
            ok, _t = conexao.conferir_pasta(self._config.scrcpy)
            self._pasta_conferida = (self._config.scrcpy, agora, ok)

        def mudar(w, **kw):
            novo = {k: v for k, v in kw.items() if str(w.cget(k)) != str(v)}
            if novo:
                w.configure(**novo)

        v_scrcpy = getattr(p, "_versao_scrcpy", None)
        if ok and v_scrcpy is None and not getattr(self, "_lendo_versao",
                                                   False):
            self._lendo_versao = True

            def ler():
                try:
                    p.versao_do_scrcpy_guardada()
                finally:
                    self._da_outra_thread.put(lambda: (
                        setattr(self, "_lendo_versao", False),
                        self._pintar_atualizacoes()))
            threading.Thread(target=ler, daemon=True,
                             name="versao-scrcpy").start()
        procurando = getattr(self, "_procurando", False)
        versoes = {"app": VERSAO,
                   "scrcpy": (v_scrcpy or "…") if ok else "—"}
        for chave, (versao, estado) in linhas.items():
            mudar(versao, text=versoes[chave])
            tipo, texto = p.estado_atualizacao.get(chave, ("info", ""))
            if chave == "scrcpy" and not ok:
                tipo, texto = "falta", "não instalado"
            elif procurando:
                tipo, texto = "info", "procurando…"
            cor = {"ok": E.VERDE, "nova": E.ACENTO, "erro": E.ALERTA,
                   "falta": E.ALERTA}.get(tipo, E.APAGADO)
            marca = {"ok": "✓  ", "nova": "●  ", "erro": "!  ",
                     "falta": ""}.get(tipo, "")
            clicavel = tipo == "nova" and not procurando
            mudar(estado,
                  text=marca + texto + ("  ›" if clicavel else ""), fg=cor,
                  cursor="hand2" if clicavel else "arrow",
                  takefocus=1 if clicavel else 0)
            estado._clicavel = clicavel
        quando = self._ui.get("procura")
        if quando is not None and quando.winfo_exists():
            andamento = getattr(self, "_instalar_texto", None)
            if andamento:                   # (r166) instalando / falhou
                mudar(quando, text=andamento[0], fg=andamento[1])
            else:
                mudar(quando, text=_quando(self._config.opcoes.get(
                    "ultima_procura")), fg=E.TEXTO_2)

    def _clicou_estado(self, rotulo) -> str:
        # Versao nova: procurar de novo JA, que pergunta (manual ignora o
        # "nao" dado antes) e atualiza com o sim.
        if getattr(rotulo, "_clicavel", False):
            self._procurar_agora()
        return "break"

    # -- OPCOES > qualidade (23/set/2026) -------------------------------------
    #
    # Pedido dele: UMA qualidade para o programa inteiro (espelhar, extensao
    # e apps), com tres predefinicoes fixas e ate tres dele, que so aparecem
    # depois que ele criar. As fileiras ficam todas abertas.

    # (r196) QUALIDADE POR CONEXAO: a fileira "sem fio | cabo" no topo
    # escolhe QUAL conjunto a tela mostra e edita (nao muda a conexao). Abre
    # no da conexao em uso. Criar predefinicao salva no conjunto aberto.

    def _conexao_da_qualidade(self) -> str:
        # (03/out) sempre a conexao em uso (escolhe-se so em PAREAR)
        return self.programa.conexao_de()

    # (08/out/2026, REWORK pedido dele) So o que importa, em CARTOES DE
    # ESCOLHA (E.Escolha; pesquisa em docs\contexto\qualidade-08out.md):
    #   IMAGEM  540p / 720p / 1080p (4 / 8 / 16 mb/s), padrao 720p
    #   SOM     normal 128 / alto 192 (opus), padrao normal
    #   JANELA DOS APPS  pc / tablet (travado ate a verificacao; depois, so
    #           nos apps que tem tablet) | celular
    # Iguais no cabo e no sem fio. Quadros, mb/s, atraso e codec ficam
    # escondidos e fixos (qualidade.video_do_nivel / audio_do_som).

    def _opcoes_nivel(self, completo: bool = True) -> list:
        saida = []
        for c, r, p in qualidade.NIVEIS:
            o = {"valor": c, "titulo": "%dp" % p}
            if completo:
                o.update(sub=r, detalhe="%s mb/s" % qualidade.TAXA_DO_NIVEL[
                    c].rstrip("M"),
                    selo="padrão" if c == qualidade.NIVEL_PADRAO else "")
            saida.append(o)
        return saida

    def _opcoes_som(self, completo: bool = True) -> list:
        saida = []
        for c, nome, taxa in qualidade.SONS:
            o = {"valor": c, "titulo": nome}
            if completo:
                o.update(sub="%s kb/s" % taxa.rstrip("K"),
                         detalhe="voz e vídeo" if c == "normal"
                         else "música",
                         selo="padrão" if c == qualidade.SOM_PADRAO else "")
            saida.append(o)
        return saida

    def _opcoes_modo(self, pc_livre: bool, indicado: str = "",
                     detalhe_pc: str = "") -> list:
        return [{"valor": "pc", "titulo": "pc / tablet",
                 "sub": ("layout de tablet" if detalhe_pc else "tela 16:9")
                 if pc_livre else "após a verificação",
                 "detalhe": detalhe_pc, "travada": not pc_livre,
                 "selo": "indicado" if indicado == "pc" else ""},
                {"valor": "celular", "titulo": "celular",
                 "sub": "a tela do celular",
                 "detalhe": "",
                 "selo": "indicado" if indicado == "celular" else ""}]

    def _modo_geral(self) -> str:
        """O que vale de todos: pc so depois da verificacao."""
        if not self.programa.verificacao_feita():
            return "celular"
        return self._config.apps.get("modo") or "pc"

    # (08/out, pedido dele: "em uma primeira vista eu fiquei um pouco
    # confuso") A tela em LINHAS, como as configuracoes do Windows/Android:
    # a esquerda o NOME da escolha (texto, em cima) e uma legenda curta
    # (apagada, embaixo); a direita os cartoes. Uma decisao por linha, na
    # ordem de importancia, separadas por ESPACO (sem linhas). O que e longo
    # fica no ⓘ; o que vale para tudo, numa nota no pe da tela. A cor so
    # marca estado: laranja = escolhido, verde = deu certo, ambar = recado.
    COLUNA_NOME = 172
    # (08/out, pedido dele: "uma textura delimitando o espaco de cada
    # segmento, bem sutil") cada linha num PAINEL: meio tom acima do fundo
    # (abaixo dos cartoes: a ordem das camadas se mantem) e uma borda que
    # quase nao aparece, cantos redondos.
    PAINEL = E.PAINEL                    # (08/out) os do app todo
    PAINEL_BORDA = E.PAINEL_BORDA

    def _linha_qualidade(self, pai, titulo: str, legenda: str = "",
                         info: str = "", primeira: bool = False):
        """(linha, coluna da esquerda, legenda, coluna dos cartoes)."""
        P = self.PAINEL
        # o painel da casa: o que entrar depois na cor do fundo (links,
        # textos) e repintado na cor dele (E.camada, no after_idle)
        caixa = E.painel(pai, P, side="top", fill="x",
                         pady=(0 if primeira else E.px(6), 0))
        linha = tk.Frame(caixa, bg=P)
        linha.pack(fill="x", padx=E.px(12), pady=E.px(6))
        linha.grid_columnconfigure(1, weight=1)
        # coluna FIXA: todas as linhas com os cartoes no mesmo x
        linha.grid_columnconfigure(0, minsize=E.px(self.COLUNA_NOME + 14))
        esq = tk.Frame(linha, bg=P, width=E.px(self.COLUNA_NOME))
        esq.grid(row=0, column=0, sticky="nw", padx=(0, E.px(14)))
        topo = tk.Frame(esq, bg=P)
        topo.pack(side="top", fill="x")
        tk.Label(topo, text=titulo, bg=P, fg=E.TEXTO,
                 font=E.fonte_ui(E.CORPO, "semibold"), anchor="w").pack(
            side="left")
        if info:
            self._so_info(topo, info).pack(side="left", padx=(E.px(4), 0))
        leg = tk.Label(esq, text=legenda, bg=P, fg=E.APAGADO,
                       font=E.fonte_ui(E.ROTULO), anchor="w", justify="left",
                       wraplength=E.px(self.COLUNA_NOME))
        leg.pack(side="top", fill="x", pady=(E.px(3), 0))
        # a coluna do nome nunca encolhe nem cresce com o texto
        tk.Frame(esq, bg=P, width=E.px(self.COLUNA_NOME),
                 height=1).pack(side="top")
        dir_ = tk.Frame(linha, bg=P)
        dir_.grid(row=0, column=1, sticky="new")
        return linha, esq, leg, dir_

    def _so_info(self, pai, detalhe: str) -> tk.Label:
        """So o ⓘ (a dica da casa com o mouse em cima)."""
        i = tk.Label(pai, text="ⓘ", bg=pai.cget("bg"), fg=E.APAGADO,
                     font=E.fonte(E.PEQUENA), cursor="question_arrow",
                     padx=E.px(2), pady=0)
        i._tipo = "info"
        i._sobre = False

        def entrou(_e=None):
            i._sobre = True
            i.configure(fg=E.TEXTO)
            self.after(350, lambda: i._sobre and self._mostrar_dica_barra(
                i, detalhe))

        def saiu(_e=None):
            i._sobre = False
            try:
                i.configure(fg=E.APAGADO)
            except tk.TclError:
                pass
            self._esconder_dica_barra()
        i.bind("<Enter>", entrou)
        i.bind("<Leave>", saiu)
        return i

    def _tela_opcoes_qualidade(self, area) -> None:
        q = self._config.qualidade
        externo = self._uma(area)
        # o que vale para tudo: uma nota no pe, apagada, fora da rolagem
        tk.Label(externo, text="vale para espelhar, extensão e apps, no cabo "
                               "e no sem fio. cada modo ou app pode ter o "
                               "seu.",
                 bg=E.FUNDO, fg=E.APAGADO, font=E.fonte_ui(E.ROTULO),
                 anchor="w", justify="left").pack(side="bottom", fill="x",
                                                  pady=(E.px(6), 0))
        # (08/out, relato dele: "tem item pra baixo que nao da pra ver") as
        # linhas numa rolagem da casa
        caixa = tk.Frame(externo, bg=E.FUNDO)
        caixa.pack(side="top", fill="both", expand=True)
        rol = _Rolagem(caixa)
        self._ui["rolagem_qualidade"] = rol
        f = rol.dentro
        _l, _e, _g, d = self._linha_qualidade(
            f, "imagem", "a nitidez. mais alta pede mais da rede.",
            "imagem\n540p: leve, para wi-fi fraco\n720p: o equilíbrio (padrão)"
            "\n1080p: a mais nítida, pede rede boa ou cabo\n"
            "60 quadros, h.264, sem atraso: fixos", primeira=True)
        e_nivel = E.Escolha(d, self._opcoes_nivel(), qualidade.nivel_geral(q),
                            self._escolheu_nivel_geral, bg=self.PAINEL)
        e_nivel.pack(side="top", fill="x")

        _l, _e, _g, d = self._linha_qualidade(
            f, "som", "a qualidade do áudio no pc.")
        e_som = E.Escolha(d, self._opcoes_som(), qualidade.som_geral(q),
                          self._escolheu_som_geral, bg=self.PAINEL)
        e_som.pack(side="top", fill="x")

        feita = self.programa.verificacao_feita()
        _l, esq, leg, d = self._linha_qualidade(
            f, "janela dos apps", "",
            "como os apps abrem no pc\n"
            "pc / tablet: a tela de tablet do app, na largura dele, com a "
            "densidade certa para a resolução\n"
            "celular: o formato da tela do celular\n"
            "a verificação é automática: ao conectar, lê de cada app a "
            "tabela de telas que ele traz (nada é baixado). fica guardada; "
            "depois, só app novo ou atualizado é lido de novo")
        # (a contagem fica so na legenda da esquerda)
        modo = E.Escolha(
            d, self._opcoes_modo(feita),
            self._modo_geral(), self._escolheu_modo_geral,
            ao_travada=lambda _v: self._pediu_pc_travado(), bg=self.PAINEL)
        modo.pack(side="top", fill="x")
        self._ui["escolha_modo"] = modo
        self._bloco_analise(esq, leg)

        # (08/out, pedido dele: "aumentar ou diminuir um pouco a dpi em todas
        # resolucoes") o tamanho dos elementos nas janelas dos apps
        _l, _e, _g, d = self._linha_qualidade(
            f, "tamanho nos apps", "letras e botões dentro das janelas.",
            "tamanho nos apps\nmuda a densidade (dpi) da tela do app, em "
            "qualquer resolução: acima de 100% = letras e botões maiores, "
            "cabe menos na janela.\nno modo pc / tablet, 115% ou mais pode "
            "levar um app à tela de celular (o whatsapp só mostra duas "
            "colunas em 100% ou menos).\ncada app pode ter o seu "
            "(personalizados)")
        esc_tam = E.Segmentado(d, OPCOES_ESCALA,
                               self._config.apps.get("escala") or "normal",
                               lambda v: self._virar_apps(
                                   "escala", "" if v == "normal" else v))
        esc_tam.pack(side="top", fill="x")

        def viva():
            qq = self._config.qualidade
            e_nivel.definir(qualidade.nivel_geral(qq))
            e_som.definir(qualidade.som_geral(qq))
            modo.definir(self._modo_geral())
            esc_tam.definir(self._config.apps.get("escala") or "normal")
        self._viva(viva)
        self._ui["_vivas_completas"] = True

    def _pediu_pc_travado(self) -> None:
        """Clicou no pc / tablet travado: a verificacao e automatica; o
        recado diz o que falta."""
        estado = self.programa.analise_estado
        if estado is not None and not estado.get("fim"):
            self._ui_analise_recado = "espere a verificação acabar."
        else:
            self._ui_analise_recado = "conecte o celular: a verificação " \
                                      "começa sozinha."
        self._pintar_analise()

    def _escolheu_nivel_geral(self, nivel: str) -> None:
        self._config.qualidade["nivel"] = nivel
        self._qualidade_geral_mudou("nivel = %s" % nivel)

    def _escolheu_som_geral(self, som: str) -> None:
        self._config.qualidade["som"] = som
        self._qualidade_geral_mudou("som = %s" % som)

    def _escolheu_modo_geral(self, modo: str) -> None:
        self._virar_apps("modo", "" if modo == "pc" else modo)

    def _qualidade_geral_mudou(self, o_que: str) -> None:
        ok = self._config.gravar()
        self.programa.anotar("qualidade: %s%s" % (
            o_que, "" if ok else " (NAO GRAVOU)"))
        self._conferir_gravacao(ok)
        p = self.programa
        for nome in ("jogo", "extensao"):
            p.mudou_a_qualidade(nome)
        # a geral tambem e a dos apps (r123): reabre os abertos
        self._agendar_reabrir(p.apps_abertos())
        self._agendar_renovar()

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

        # (r195) O andamento aparece na linha de cima da coluna, a do
        # "conferido" (ver `_pintar_atualizacoes`).
        def mostrar(texto, cor=None):
            self._instalar_texto = (texto, cor or E.TEXTO_2) if texto else None
            self._pintar_atualizacoes()

        def avisar(texto):
            self._da_outra_thread.put(lambda t=texto: mostrar(t))

        def fim(ok, texto):
            self._instalando = False
            self._pasta_conferida = None        # a pasta mudou: confere ja
            if ok:
                # A tabela diz "em dia"; o texto volta ao "conferido".
                self._instalar_texto = None
                self._montar_conteudo()
            else:
                # O erro fica ate o proximo clique em instalar.
                mostrar("✗  " + texto.lower(), E.ERRO)

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
                         ("notif", "notificações"),
                         ("parear", "parear"), ("opcoes", "opções"))

    def _escolha_inicial(self, pai) -> None:
        """(r168) Caixa de escolha: clique (ou Enter/espaco) abre a lista.
        (r180) Travar e trocar o texto acontecem no lugar."""
        # (07/out, pedido dele) uma PILULA da casa (camada 2, como os itens
        # do menu que ela abre), do tamanho do texto -- era uma caixa de
        # digitar da largura toda, de outro estilo
        caixa = tk.Label(pai, anchor="w", bg=E.CAMADA_2,
                         font=E.fonte(E.PEQUENA), padx=E.px(10), pady=E.px(4),
                         highlightthickness=1, highlightbackground=E.BORDA_2,
                         highlightcolor=E.FOCO)
        caixa.pack(side="top", anchor="w", pady=(E.px(2), E.px(0)))
        self._ui["escolha_inicial"] = caixa
        E.cantos(caixa, raio=E.px(6))
        caixa.bind("<Enter>", lambda _e: self._config.opcao(
            "pagina_inicial_ligada") and (caixa.configure(
                highlightbackground=E.BORDA_1_SOBRE),
                E.cantos(caixa, raio=E.px(6))), add="+")
        caixa.bind("<Leave>", lambda _e: (caixa.configure(
            highlightbackground=E.BORDA_2), E.cantos(caixa, raio=E.px(6))),
            add="+")

        def abrir(_e=None):
            # (07/out, "padronizar o botao direito") a lista e o menu da casa
            # (era o menu do Tk, quadrado e laranja), logo abaixo da caixa
            if not self._config.opcao("pagina_inicial_ligada"):
                return "break"
            if self._menu_alternar(caixa):
                return "break"           # (07/out) aberta: o clique fecha
            if _e is not None:
                self._clique_em_qualquer_lugar(_e)
            atual = self._config.opcoes.get("pagina_inicial", "jogo")
            menu, corpo = self._novo_menu()
            menu._dono = caixa
            opcoes = [(rotulo, lambda v=valor: self._escolheu_inicial(v),
                       True) if valor == atual else
                      (rotulo, lambda v=valor: self._escolheu_inicial(v))
                      for valor, rotulo in self.NOMES_DAS_PAGINAS]
            import types
            onde = types.SimpleNamespace(
                x_root=caixa.winfo_rootx() - E.px(2),
                y_root=caixa.winfo_rooty() + caixa.winfo_height())
            self._encher_menu(menu, corpo, onde, opcoes,
                              largura_min=caixa.winfo_width())
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
        """(r180) As sub-chaves no lugar. (07/out, pedido dele) So APARECEM
        com a de origem ligada (antes ficavam travadas, apagadas)."""
        def mostrar(sub, pai, sim):
            if sub is None or not sub.winfo_exists():
                return
            if sim and not sub.winfo_manager():
                sub.pack(side="top", fill="x", after=pai.master,
                         padx=(E.px(16), 0))   # recuada: e "filha"
            elif not sim and sub.winfo_manager():
                sub.pack_forget()
        notif = self._config.opcao("notificacoes")
        c = self._ui.get("chave_aviso_atalho")
        if c is not None and c.winfo_exists():
            c.definir(self._config.opcao("aviso_atalho"))
        av = self._ui.get("chave_avisos")
        if av is not None and av.winfo_exists():
            mostrar(self._ui.get("sub_avisos"), av, notif)
        w = self._ui.get("windows")
        if w is not None and w.winfo_exists():
            w.definir(bool(self._windows_ligado))
            mostrar(self._ui.get("sub_windows"), w,
                    bool(self._windows_ligado))
        r = self._ui.get("chave_rapido")
        if r is not None and r.winfo_exists():
            r.definir(bool(self._windows_ligado)
                      and bool(getattr(self, "_rapido_ligado", False)))

    def _escolheu_inicial(self, valor: str) -> None:
        # (07/out) a lista "abrir em" substitui a chave + caixa: escolher
        # liga a pagina inicial (desligada era o mesmo que espelhar)
        self._config.opcoes["pagina_inicial_ligada"] = True
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
        pasta_antes = self._config.scrcpy

        def fim(texto):
            # (r195) O resultado vai para a tabela (um estado por programa,
            # `programa.estado_atualizacao`), nao mais num texto so.
            self._procurando = False
            self.programa.anotar("procurar atualizacao: %s" % texto)
            if self._config.scrcpy != pasta_antes:
                # Instalou/atualizou: a pasta mudou, a tela e refeita.
                self._montar_conteudo()
            else:
                self._pintar_atualizacoes()   # (r180) no lugar, sem piscar

        def trabalho():
            try:
                texto = self.programa.procurar_atualizacao(manual=True)
            except Exception as erro:
                log.exception("procurar atualizacao")
                texto = "algo deu errado: %s" % erro
            self._da_outra_thread.put(lambda: fim(texto))

        self._pintar_atualizacoes()
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
            self.programa._versao_scrcpy = None     # (r195) outra pasta
            self.programa.estado_atualizacao.pop("scrcpy", None)
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
        if recusadas:
            aviso = ("em vermelho: o windows não aceitou (outro programa já "
                     "usa). clique na linha e grave outra.", E.ERRO)
        else:
            aviso = ("valem em qualquer programa, com a janela fechada. "
                     "clique numa linha para gravar as teclas.", E.APAGADO)
        E.Texto(f, aviso[0], cor=aviso[1], tamanho=E.ROTULO,
                largura=E.px(560)).pack(side="bottom", fill="x",
                                        pady=(E.px(6), E.px(0)))
        # (03/out, pedido dele) a barra de busca da casa: filtra modos e apps
        busca = self._barra_de_busca(
            f, getattr(self, "_busca_atalhos", ""), "buscar",
            self._buscou_atalho, altura=E.px(30), chave_ui="busca_atalhos")
        busca.master.pack(side="top", fill="x", pady=(E.px(0), E.px(8)))
        caixa = tk.Frame(f, bg=E.FUNDO)
        caixa.pack(side="top", fill="both", expand=True)
        rol = _Rolagem(caixa)
        self._ui["rolagem_atalhos"] = rol
        if self._apps is None and not self._apps_carregando:
            self._carregar_apps()
        self._encher_atalhos(rol, recusadas)

    def _buscou_atalho(self) -> None:
        """Filtra 150 ms depois da ultima tecla: refaz SO a lista (a busca
        continua com o foco)."""
        b = self._ui.get("busca_atalhos")
        self._busca_atalhos = b.get() if b is not None else ""
        if getattr(self, "_busca_atalhos_id", None):
            self.after_cancel(self._busca_atalhos_id)

        def refazer():
            rol = self._ui.get("rolagem_atalhos")
            if rol is None or not rol.canvas.winfo_exists():
                return
            # (09/out, pedido dele) o filtro ANIMADO, sem refazer a lista
            self._encher_atalhos(rol, self.motor.falhas(), animar=True)
        self._busca_atalhos_id = self.after(150, refazer)

    def _encher_atalhos(self, rol, recusadas, animar: bool = False) -> None:
        """MODOS e APPS na lista, so os que batem com a busca. (09/out) Com
        o `Arranjo`: cada linha tem chave (com o que ela mostra); a busca
        so tira, poe e move linhas (filtro_animado)."""
        d = rol.dentro
        arr = self._ui.get("arranjo_atalhos")
        if arr is None or arr.pai is not d:
            for filho in d.winfo_children():
                filho.destroy()
            arr = self._ui["arranjo_atalhos"] = FA.Arranjo(d, rol.canvas,
                                                           E.FUNDO)
        termo = (getattr(self, "_busca_atalhos", "") or "").strip().lower()
        todos = [(a, t) for a, t in atalhos_mod.em_ordem(self._config)
                 if not a.startswith(atalhos_mod.APP)]
        lista = [(a, t) for a, t in todos if not termo or
                 termo in atalhos_mod.rotulo(a).lower() or
                 termo in (t or "").lower()]
        todos_apps = sorted(self._apps or [],
                            key=lambda a: (a[2], a[0].lower()))
        # so pelo NOME que aparece (o pacote "com.google..." confundia)
        apps = [a for a in todos_apps if not termo or termo in a[0].lower()]
        busca = self._ui.get("busca_atalhos")
        if busca is not None:
            self._contar_busca(busca, len(lista) + len(apps),
                               len(todos) + len(todos_apps))
        com_botao = bool(atalhos_mod.livres(self._config)) and not termo

        def topo():
            f = tk.Frame(d, bg=E.FUNDO)
            E.Rotulo(f, "modos").pack(side="left")
            if com_botao:
                b = E.Botao(f, "+ adicionar atalho", self._abrir_seletor,
                            tipo="discreto")
                b.pack(side="right")
                self._ui["botao_adicionar"] = b
            return f

        def criar(chave):
            tipo = chave[0]
            if tipo == "_topo":
                return topo()
            if tipo == "_msg":
                return E.Texto(d, chave[2], cor=E.APAGADO)
            if tipo == "_h":
                return E.Rotulo(d, "apps")
            if tipo == "m":
                return self._linha_de_atalho(d, chave[1], chave[2], chave[3])
            _t, pacote, nome, _teclas, rec = chave
            acao = atalhos_mod.APP + pacote
            atalhos_mod.NOMES_DE_APP.setdefault(pacote, nome)
            return self._linha_de_atalho_livre(d, acao, (pacote, nome), rec)

        cima = [("_topo", com_botao)]
        if not lista:
            cima.append(("_msg", "m", "nenhum atalho com esse nome." if termo
                         else "nenhum atalho ainda."))
        cima += [("m", a, t, a in recusadas) for a, t in lista]
        cima.append(("_h",))
        espacos = {"_topo": (0, E.px(6)), "m": (0, E.px(5)),
                   "_h": (E.px(12), E.px(6)), "_msg": (0, 0)}
        layout = FA.empilhar(arr, cima, criar,
                             lambda c: espacos.get(c[0], (0, 0)))
        _c, _x, y, _l, a = layout[-1]
        y += a + E.px(6)
        if apps:
            alt = self._altura_linha_atalho(d)
            for nome, pacote, _sis in apps:
                acao = atalhos_mod.APP + pacote
                chave = ("a", pacote, nome,
                         self._config.atalhos.get(acao, ""),
                         acao in recusadas)
                layout.append((chave, 0, y, None, alt))
                y += alt + E.px(4)
        else:
            if termo and todos_apps:
                texto = "nenhum app com esse nome."
            elif self._apps_carregando:
                texto = "lendo os apps do celular…"
            else:
                texto = ("os apps aparecem aqui quando a lista do celular "
                         "chegar.")
            layout += FA.empilhar(arr, [("_msg", "a", texto)], criar, 0,
                                  y0=y)
        # Em lotes: com ~100 apps a aba abria atrasada (23/set/2026); agora
        # so o que fica fora da vista vai nos lotes.
        adiadas = arr.aplicar(layout, criar, animar=animar, adiar=True,
                              topo=animar)
        if adiadas:
            def fazer(chave):
                arr.criar_adiado(chave, criar)
            self._em_lotes(rol.canvas, adiadas, fazer, primeiro=0)

    def _altura_linha_atalho(self, d) -> int:
        """A linha de app dos atalhos tem altura FIXA (a maior: com teclas
        e o x de tirar, ou com o "clique para definir")."""
        alt = getattr(self, "_alt_linha_atalho", 0)
        if not alt:
            for teclas in ("", "ctrl+x"):
                acao = atalhos_mod.APP + "x.medida"
                velho = self._config.atalhos.get(acao)
                self._config.atalhos[acao] = teclas
                try:
                    w = self._linha_de_atalho_livre(d, acao, ("x.medida", "x"),
                                                    False)
                    w.update_idletasks()
                    alt = max(alt, w.winfo_reqheight())
                    FA.destruir(w)
                finally:
                    if velho is None:
                        self._config.atalhos.pop(acao, None)
                    else:
                        self._config.atalhos[acao] = velho
            self._alt_linha_atalho = alt
        return alt

    def _linha_de_atalho(self, pai, acao: str, teclas: str,
                         recusado: bool) -> None:
        linha = self._cartao(pai, borda=E.ERRO if recusado else None,
                             foco=True)
        # (09/out) sem pack: o `Arranjo` dos atalhos a poe no lugar
        nome = tk.Label(linha, text=atalhos_mod.rotulo(acao),
                        bg=E.CAMADA_1, fg=E.TEXTO, font=E.fonte(E.PEQUENA),
                        anchor="w", cursor="hand2")
        nome.pack(side="left", padx=(E.px(10), E.px(0)), pady=E.px(7))
        self._x_de_tirar(linha, E.CAMADA_1,
                         lambda a=acao: self._tirar_atalho(a)).pack(
            side="right", padx=(E.px(2), E.px(6)))
        caixa = tk.Frame(linha, bg=E.CAMADA_1)
        caixa.pack(side="right", padx=(E.px(0), E.px(4)))
        partes = [p.strip() for p in teclas.split("+") if p.strip()] \
            if teclas else []
        if not partes:
            tk.Label(caixa, text="sem teclas", bg=E.CAMADA_1, fg=E.APAGADO,
                     font=E.fonte(E.ROTULO)).pack(side="left")
        teclas_w = []
        for i, p in enumerate(partes):
            if i:
                tk.Label(caixa, text="+", bg=E.CAMADA_1, fg=E.APAGADO,
                         font=E.fonte(E.ROTULO)).pack(side="left", padx=E.px(2))
            # (07/out) a tecla e uma "teclinha" da camada 2, de canto redondo
            t = tk.Label(caixa, text=p.upper(), bg=E.CAMADA_2,
                         fg=E.ERRO if recusado else E.TEXTO,
                         font=E.fonte(E.ROTULO + 1), padx=E.px(5), pady=1,
                         highlightthickness=1, cursor="hand2",
                         highlightbackground=E.ERRO if recusado
                         else E.BORDA_2)
            t.pack(side="left")
            E.cantos(t, raio=E.px(4))
            teclas_w.append(t)

        def regravar(_e=None, a=acao):
            self._comecar_gravacao(a)
            return "break"

        self._cartao_vivo(linha, (linha, nome, caixa, *caixa.winfo_children()))
        for peca in (linha, nome, caixa, *caixa.winfo_children()):
            peca.bind("<Button-1>", regravar)
        linha.bind("<Return>", regravar)
        linha.bind("<space>", regravar)
        linha.bind("<Delete>", lambda _e, a=acao: (self._tirar_atalho(a),
                                                   "break")[1])
        return linha

    def _abrir_seletor(self) -> None:
        """(07/out, pedido dele: "muitas opcoes la, muda pra um daqueles menu
        que abre e mostra as opcoes em lista") O menu da casa, logo abaixo do
        botao, com as acoes que ainda nao tem atalho; escolher = gravar."""
        b = self._ui.get("botao_adicionar")
        livres = list(atalhos_mod.livres(self._config))
        if b is None or not livres or not b.winfo_exists():
            self._atalhos_modo = "seletor"     # (sem o botao: a tela antiga)
            self._montar_conteudo()
            return

        class _Onde:
            x_root = b.winfo_rootx() + b.winfo_width()
            y_root = b.winfo_rooty() + b.winfo_height()
        opcoes = [(atalhos_mod.rotulo(a), lambda a=a: self._criar_atalho(a))
                  for a in livres]
        menu, corpo = self._novo_menu()
        menu._dono = b
        menu._alinhar = "direita"        # cresce para a esquerda do botao
        self._encher_menu(menu, corpo, _Onde, opcoes)

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
        tk.Label(pai, text=atalhos_mod.rotulo(self._gravando or ""),
                 bg=E.FUNDO, fg=E.TEXTO, font=E.fonte(E.CORPO, "bold"),
                 anchor="w").pack(side="top", fill="x", pady=(E.px(0), E.px(10)))
        caixa = tk.Frame(pai, bg=E.FUNDO_FUNDO, height=E.px(50),
                         highlightthickness=1, highlightbackground=E.ACENTO)
        caixa.pack(side="top", fill="x")
        caixa.pack_propagate(False)
        E.cantos(caixa)                  # (07/out) canto arredondado
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

    def _criar_atalho(self, acao: str) -> None:
        self._conferir_gravacao(self._config.definir_atalho(acao, ""))
        self._atalhos_modo = "lista"
        self._comecar_gravacao(acao)

    def _tirar_atalho(self, acao: str) -> None:
        self._conferir_gravacao(self._config.remover_atalho(acao))
        self.programa.anotar("atalho removido: %s" % acao)
        self._aplicar_atalhos()
        self._remontar_quieto()

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
        E.cantos(self._ui["alvo_caixa"])
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
        if not self._atualizar_vivas():
            self._remontar_quieto_depois()

    def _escolheu_ajuste(self, nome: str, secao: str, campo: str,
                         valor) -> None:
        perfil = self._config.perfil(nome)
        qualidade.escrever(perfil, secao, campo, valor)
        self._gravou(nome, "%s.%s = %s" % (secao, campo, valor))
        if campo == "codec" and not self._atualizar_vivas():
            self._remontar_quieto_depois()       # o kb/s acende ou apaga

    def _virar_campo(self, nome: str, secao: str, campo: str, valor,
                     remontar: bool = False) -> None:
        perfil = self._config.perfil(nome)
        perfil.setdefault(secao, {})[campo] = bool(valor)
        self._gravou(nome, "%s.%s = %s" % (secao, campo, valor))
        if remontar and not self._atualizar_vivas():
            self._remontar_quieto_depois()

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
                elif chave == "notif":
                    n = p.notif.contagem()
                    it.definir(selecionado=(chave == self._item),
                               tecla=(str(n) if n < 100 else "99+")
                               if n else "")
                else:
                    it.definir(selecionado=(chave == self._item))
        except tk.TclError:
            pass
        self._conferir_status()
        self._conferir_cache()
        if self._item == "apps":
            self._pintar_lista_apps()
        if self._item == "notif":
            self._pintar_notif()

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
        self._pintar_conexao()
        self._pintar_barra()             # (07/out) som e conexao na barra
        self._pintar_celular_em_uso()
        self._conferir_outros()
        if self._item == "opcoes":
            self._pintar_atualizacoes()     # (r195) a procura do prazo
        self._seguir_a_conexao()            # (r197)
        em_uso = cel.get("serial", "")
        if em_uso != getattr(self, "_lista_feita_para", None):
            self._lista_feita_para = em_uso
            self._mostrar_achados()

        icone = p.estado_do_icone()
        if icone != self._estado_do_icone:
            self._estado_do_icone = icone
            try:
                moldura.pintar_icone(self, icone)
            except Exception:
                pass

    def _nome_do_celular(self) -> str:
        """O modelo lido ("SM-S901E", como o celular diz: a aba nao e mais
        caixa alta) ou "celular" sem celular lido."""
        info = getattr(self.programa, "celular", None) or {}
        return str(info.get("modelo") or "")[:20] or "celular"

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
        # (01/out, "as notificacoes demoram a aparecer") Com as notificacoes
        # no ar o aviso no canto nao pode esperar o relogio lento.
        if getattr(getattr(p, "notif", None), "_serial", ""):
            return PASSO_MS
        return PASSO_PARADO_MS

    def _girar(self) -> None:
        # (r165) CADA PARTE NO SEU TRY: antes um erro que se repetisse no
        # passo do programa pulava todo giro os atalhos, o chamado e os
        # recados das threads -- o programa ficava surdo.
        self.programa.janela_na_tela = self._visivel   # (02/out) vigia
        self._parte_do_giro(self.programa.passo)
        self._parte_do_giro(self._giro_chamado)
        self._parte_do_giro(self._giro_atalhos)
        self._parte_do_giro(self._giro_notif)
        self._parte_do_giro(self._conferir_dica)
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
            elif pedido[0] == "link" and len(pedido) >= 2:
                self.abrir_link(pedido[1])
            else:
                self.mostrar()

    def _giro_atalhos(self) -> None:
        if self.motor is None or not self.motor.disponivel:
            return
        for acao in self.motor.pedidos():
            # (07/out) as funcoes dos indicadores sao da janela
            tipo, _, funcao = acao.partition("_")
            if tipo in self.FUNCOES_IND and funcao in dict(
                    self.FUNCOES_IND[tipo]):
                self.programa.anotar("atalho: %s" % acao)
                self._funcao_ind(tipo, funcao)
                continue
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

    def _sumir_ja(self) -> None:
        try:
            self._cancelar_deslize()
            self.withdraw()
            self.update_idletasks()
        except Exception:
            pass

    # -- BOTOES DA BARRA: som e conexao (07/out/2026, pedido dele) ----------

    _ICONES_BARRA: dict = {}

    # MEDIDAS DOS BOTOES DA BARRA (07/out, pesquisado): o Windows 11 usa
    # celulas de 46 x 32 (largura x altura da barra), encostadas, com o
    # icone pequeno no meio; acessibilidade (WCAG 2.5.8) pede alvo de 24 x 24
    # no minimo. Aqui: a ALTURA INTEIRA da barra, 40 de largura (na escala
    # do programa; 46 nao cabe com as abas da notificacao), icone de 16 na
    # grade de 24 (o mesmo desenho e o mesmo traco nos quatro); o realce
    # preenche a celula toda e o fechar encosta na borda da janela.
    CELULA_L = E.px(40)
    CELULA_ESTREITA = E.px(34)
    ICONE_BARRA = E.px(16)

    def _icone_barra(self, nome: str, cor: str, medidas=None,
                     brilho: bool = False):
        """A celula do botao pronta para o Tk (guardada). `medidas` =
        (largura, altura, icone); sem ela, a da barra. `brilho` = o icone
        do rodape na cor do estado, com o halo leve."""
        medidas = medidas or (self.CELULA_L, E.ALTURA_BARRA, self.ICONE_BARRA)
        chave = (nome, medidas, cor, brilho)
        if chave not in self._ICONES_BARRA:
            from PIL import ImageTk
            pil = self._pil_indicador(nome, cor, medidas, True) if brilho \
                else self._pil_celula(nome, cor, medidas=medidas)
            self._ICONES_BARRA[chave] = ImageTk.PhotoImage(pil, master=self)
        return self._ICONES_BARRA[chave]

    # OS ICONES (07/out, pedido dele: "pesquise bem pra ficarem bem
    # dimensionados e nao parecerem comuns demais") Sistema unico, o dos
    # icones de sistema (Material/Fluent): grade de 24, AREA VIVA de 20 (2 de
    # folga em volta), traco de 2 com ponta e juncao redondas, cantos de raio
    # 2-2,5, formas-chave (retrato 10x19, paisagem 18x12, circulo 20). Nada de
    # engrenagem/corrente (os "comuns demais"): OPCOES = tres trilhos com
    # botoes deslizantes (ajustar); PAREAR = o celular com um selo "+" (por
    # um celular); SOM = o alto-falante com o DESTINO do som ao lado (pc,
    # celular ou os dois); CONEXAO = sem fio (ondas), cabo (plugue) ou
    # nenhum (ondas cortadas) -- todos no mesmo traco.

    def _pil_celula(self, nome: str, cor: str, fundo: str = E.FUNDO,
                    medidas=None, traco: float | None = None):
        """A CELULA inteira do botao (imagem PIL lisa, feita 4x maior): o
        fundo e o icone de linha no meio -- pc, celular, ambos, sem_fio,
        cabo, nenhum (sem fio cortado), minimizar, fechar, opcoes, parear.
        `fundo` = a cor do preenchimento de segurar (com o icone escuro por
        cima). `medidas` = (largura, altura, icone); sem ela, a da barra."""
        larg, alt, lado = medidas or (self.CELULA_L, E.ALTURA_BARRA,
                                      self.ICONE_BARRA)
        from PIL import Image, ImageDraw
        # (07/out, pedido dele: "aumente a qualidade dos icones") desenhado
        # 8x maior e reduzido por MEDIA de area (BOX: sem o halo do
        # Lanczos); o icone comeca num pixel inteiro e o traco tem pelo menos
        # 1,5 px -- em 14-16 px o de 2/24 dava ~1,2 px e saia borrado.
        k = 8
        img = Image.new("RGB", (larg * k, alt * k), fundo)
        d = ImageDraw.Draw(img)
        L = lado * k
        u = L / 24.0
        g = int(round(max(2.0 * lado / 24.0, 1.5) * k))
        if traco:                        # (07/out) o rodape: traco comum
            g = int(round(traco * k))
        ox = int(round((larg - lado) / 2.0)) * k
        oy = int(round((alt - lado) / 2.0)) * k

        def P(*v):
            return [x * u + (ox if i % 2 == 0 else oy)
                    for i, x in enumerate(v)]

        meio = g / 2.0                   # a ponta redonda = meio traco

        def linha(*v):
            d.line(P(*v), fill=cor, width=g)
            for x, y in ((v[0], v[1]), (v[2], v[3])):
                cx_, cy_ = P(x, y)
                d.ellipse((cx_ - meio, cy_ - meio, cx_ + meio, cy_ + meio),
                          fill=cor)

        def caixa(x0, y0, x1, y1, r, encher=None):
            d.rounded_rectangle(P(x0, y0, x1, y1), radius=r * u,
                                outline=cor, width=g, fill=encher)

        def falante(x0=0.0, cheio=False):
            # o alto-falante (corpo + cone), fechado, juncoes redondas;
            # `cheio` = preenchido (07/out: no rodape, vazado sumia)
            pts = [(2.5 + x0, 9.5), (5.5 + x0, 9.5), (9.5 + x0, 6),
                   (9.5 + x0, 18), (5.5 + x0, 14.5), (2.5 + x0, 14.5),
                   (2.5 + x0, 9.5)]
            if cheio:
                d.polygon([c for p in pts for c in P(*p)], fill=cor)
            d.line([c for p in pts for c in P(*p)], fill=cor, width=g,
                   joint="curve")
            for p in pts:
                cx_, cy_ = P(*p)
                d.ellipse((cx_ - meio, cy_ - meio, cx_ + meio, cy_ + meio),
                          fill=cor)

        def circulo(cx, cy, r, encher=None):
            d.ellipse(P(cx - r, cy - r, cx + r, cy + r), outline=cor,
                      width=g, fill=encher)

        def ondas(cx, cy, raios=(3.2, 6.2), ang=(-48, 48)):
            # o som saindo (arcos para a direita, como o "volume" de sempre)
            px_, py_ = P(cx, cy)
            for r in raios:
                d.arc((px_ - r * u - g / 2, py_ - r * u - g / 2,
                       px_ + r * u + g / 2, py_ + r * u + g / 2),
                      ang[0], ang[1], fill=cor, width=g)

        # (07/out, pedido dele: "referencias mais usadas", simples e direto)
        # SOM = o aparelho de onde o som sai, com as ondas (o "volume" de
        # sempre): monitor, celular ou os dois.
        # (07/out, pedido dele: "mais diretos sobre o som no pc e som no
        # celular, coloque um alto-falante e um pc ou um celular") O
        # ALTO-FALANTE a esquerda (o simbolo que todo mundo le como "som") e,
        # ao lado, ONDE ele sai: o monitor, o celular ou os dois.
        if nome == "pc":
            falante(-1.0, cheio=True)
            caixa(11, 5.5, 22.5, 15, 1.5)
            linha(16.75, 15, 16.75, 18.5)
            linha(14, 18.5, 19.5, 18.5)
        elif nome == "celular":
            # o celular da altura do alto-falante (mais alto, ele encolhia)
            falante(-1.0, cheio=True)
            caixa(13, 4.5, 20, 19.5, 1.8)
            linha(15.9, 16.8, 17.1, 16.8)
        elif nome == "ambos":
            falante(-1.5, cheio=True)
            caixa(9.5, 4, 19.5, 12.5, 1.5)
            linha(14.5, 12.5, 14.5, 15.5)
            linha(12.5, 15.5, 16.5, 15.5)
            caixa(16, 9, 22.5, 21.5, 1.6, encher=fundo)
            linha(18.6, 18.6, 19.9, 18.6)
        elif nome == "opcoes":            # tres trilhos com botoes
            for y, xb in ((5.5, 15.5), (12, 7.5), (18.5, 13)):
                linha(3, y, 21, y)
                circulo(xb, y, 2.6, encher=fundo)
        elif nome == "parear":
            # PAREAR = o celular junto do computador (o "phonelink" do
            # Material / o do Phone Link do Windows): monitor + celular
            caixa(2, 3.5, 17.5, 14.5, 1.5)
            linha(8, 14.5, 8, 18.5)
            linha(5, 18.5, 11, 18.5)
            caixa(14, 9, 22, 21.5, 1.8, encher=fundo)
            linha(17.4, 18.8, 18.6, 18.8)
        elif nome == "nenhum":
            # (08/out, pedido dele: o simbolo do tamanho do traco que o
            # corta, na altura e na largura) o wifi de leque normal (+-45)
            # crescido ate 18 de largura por fora (3..21) e o traco de CANTO A
            # CANTO da caixa dele (3..21 x 3,35..17,65 por fora): os dois com
            # a mesma altura e a mesma largura; uma fresta fina na cor do
            # fundo para o traco nao embolar com as ondas
            cx, cy = P(12, 16.05)
            for r in (7, 11.7):
                d.arc((cx - r * u - g / 2, cy - r * u - g / 2,
                       cx + r * u + g / 2, cy + r * u + g / 2), 225, 315,
                      fill=cor, width=g)
            d.ellipse((cx - 1.6 * u, cy - 1.6 * u, cx + 1.6 * u,
                       cy + 1.6 * u), fill=cor)
            d.line(P(4, 4.35, 20, 16.65), fill=fundo, width=int(g * 1.7))
            linha(4, 4.35, 20, 16.65)
        elif nome == "sem_fio":
            # (07/out, relato dele: o wifi "uns px abaixo" do som) as ondas
            # subiram 1,5 na grade: o centro do desenho na linha dos outros
            cx, cy = P(12, 17)
            for r in (6.5, 11):
                d.arc((cx - r * u - g / 2, cy - r * u - g / 2,
                       cx + r * u + g / 2, cy + r * u + g / 2), 225, 315,
                      fill=cor, width=g)
            d.ellipse((cx - 1.6 * u, cy - 1.6 * u, cx + 1.6 * u,
                       cy + 1.6 * u), fill=cor)
        elif nome == "cabo":
            # (07/out) CABO = o simbolo do USB (o tridente), o mais
            # reconhecido para "ligado por cabo"
            linha(12, 5.5, 12, 18)
            d.polygon(P(12, 2, 9.4, 6, 14.6, 6), fill=cor)
            linha(12, 13.5, 7, 10.5)
            linha(7, 10.5, 7, 8.5)
            circulo(7, 7.2, 1.6, encher=cor)
            linha(12, 15.5, 17, 12.5)
            linha(17, 12.5, 17, 9.5)
            d.rectangle(P(15.6, 6.5, 18.4, 9.3), fill=cor)
            circulo(12, 19.6, 2, encher=cor)
        elif nome.startswith("termometro"):
            # (07/out, pedido dele) TERMOMETRO (o "thermostat" do Material):
            # haste de ponta redonda e o bulbo, com a coluna no meio
            # (em 14 px o traco cheio entupia a haste: haste mais larga,
            # coluna fina e o bulbo cheio por dentro)
            caixa(8.6, 1.8, 15.4, 15, 3.4)
            circulo(12, 17.4, 4.6)
            d.rectangle(P(10.6, 12.5, 13.4, 16.5), fill=fundo)
            fina = max(2, int(g * 0.6))
            # (07/out, pedido dele) a COLUNA sobe com a temperatura:
            # "termometro@0.6" = 60% da escala (ver `_cor_da_temperatura`)
            try:
                nivel = float(nome.split("@")[1]) if "@" in nome else 0.6
            except ValueError:
                nivel = 0.6
            topo = 15.5 - 8.5 * max(0.0, min(1.0, nivel))
            d.line(P(12, topo, 12, 16), fill=cor, width=fina)
            circulo(12, 17.4, 2.1, encher=cor)
        elif nome == "minimizar":
            linha(6, 12, 18, 12)
        elif nome == "fechar":
            linha(6.5, 6.5, 17.5, 17.5)
            linha(17.5, 6.5, 6.5, 17.5)
        filtro = getattr(Image, "Resampling", Image).BOX
        return img.resize((larg, alt), filtro)

    def _pil_indicador(self, nome: str, cor: str, medidas, brilho: bool):
        """(07/out, pedido dele) O icone do RODAPE na cor do estado com um
        BRILHO leve em volta (a mesma forma desfocada, alfa baixo) -- nao so
        a cor chapada."""
        from PIL import Image, ImageFilter
        mascara = self._pil_celula(nome, "#FFFFFF", "#000000",
                                   medidas=medidas).convert("L")
        img = Image.new("RGB", mascara.size, E.FUNDO)
        tinta = Image.new("RGB", mascara.size, cor)
        if brilho:
            # curto: a celula e quase do tamanho do icone e um halo largo era
            # cortado nas laterais (virava um retangulo)
            halo = mascara.filter(ImageFilter.GaussianBlur(E.px(1.3)))
            img.paste(tinta, (0, 0), halo.point(lambda v: int(v * 0.5)))
        img.paste(tinta, (0, 0), mascara)
        return img

    # (07/out, pedido dele) A BATERIA do rodape, como a do Android: deitada,
    # a carga enchendo da esquerda, a tampa a direita; carregando = um raio
    # no meio. Com a PORCENTAGEM dentro (opcao em OPCOES > geral) ela fica
    # maior e o numero sai em duas cores: escuro sobre a carga, claro sobre
    # o vazio (o numero nunca some).
    _BATERIAS: dict = {}

    # (07/out) os digitos de pixel 3x5 sairam: ilegiveis (relato dele)

    @staticmethod
    def _cor_da_carga(nivel: float) -> str:
        """(07/out, pedido dele: 100 = verde, 10 = vermelho, o meio
        calculado) Pela MATIZ (vermelho -> laranja -> amarelo -> verde), nao
        pela mistura das cores -- misturar vermelho com verde da marrom."""
        import colorsys

        def hls(c):
            return colorsys.rgb_to_hls(*(int(c[i:i + 2], 16) / 255.0
                                         for i in (1, 3, 5)))
        h0, l0, s0 = hls(E.ERRO)
        h1, l1, s1 = hls(E.VERDE)
        k = max(0.0, min(1.0, (float(nivel) - 10.0) / 90.0))
        k = round(k * 20) / 20.0         # 21 tons (o icone e guardado)
        r, g, b = colorsys.hls_to_rgb(h0 + (h1 - h0) * k, l0 + (l1 - l0) * k,
                                      s0 + (s1 - s0) * k)
        return "#%02X%02X%02X" % (round(r * 255), round(g * 255),
                                  round(b * 255))

    def _pil_bateria(self, nivel: int, cor: str, com_pct: bool,
                     carregando: bool, brilho: bool):
        """A bateria do rodape (07/out, pedido dele: com ou sem o numero, O
        MESMO icone): deitada, cheia, a carga na cor dela e o vazio no mesmo
        tom mais fraco, a tampa a direita; o numero (ou o raio, carregando)
        recortado no meio."""
        nivel = max(0, min(100, int(nivel)))
        # (07/out, pedido dele: "padronize as outras baterias como essa")
        # TODAS no estilo vazado: com o numero ou, sem ele, com o raio
        # recortado quando carrega
        return self._pil_bateria_vazada(nivel, cor, brilho, com_pct,
                                        carregando)

    def _pil_bateria_vazada(self, nivel: int, cor: str, brilho: bool,
                            numero: bool = True, carregando: bool = False):
        """(07/out, testado no tamanho real e escolhido por ele: "vamos
        testar a 2") A PORCENTAGEM VAZADA, como no iPhone: a bateria do
        tamanho padrao, CHEIA -- a parte carregada na cor da carga, a vazia
        no mesmo tom mais fraco -- e o numero RECORTADO (a cor do fundo),
        sem contorno: o algarismo usa toda a altura de dentro (com contorno
        sobravam ~6 px, ilegivel). A parte vazia vai a 50% (no prototipo,
        35% deixava 23% e 7% escuros demais para o numero)."""
        from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
        alt, S = self._celula_rodape_alt(), self._altura_rodape()
        traco = self._traco_rodape()
        # (07/out, pedido dele: "a bateria esta um pouco maior que os outros
        # icones, deixe todos com o exato mesmo tamanho") A CAIXA DOS
        # OUTROS: a altura da tinta deles (80% do termometro) e a largura
        # total -- com a tampa -- igual a do icone mais largo (o monitor do
        # som), medidas nos proprios icones deste tamanho
        del traco
        bh = max(6, int(round(S * 0.8)))
        largura_ref = self._mascara_rodape("pc").width - 2 * E.px(2)
        tampa = max(2, round(S * 0.1))
        bw = max(8, largura_ref - tampa)
        folga_l = E.px(2)
        larg = bw + tampa + 2 * folga_l
        k = 8
        x0, y0 = folga_l * k, ((alt - bh) // 2) * k
        x1, y1 = x0 + bw * k, y0 + bh * k
        cy = (y0 + y1) / 2.0
        grande = Image.new("L", (larg * k, alt * k), 0)
        d = ImageDraw.Draw(grande)
        d.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=bh * k * 0.3,
                            fill=255)
        tampa_m = Image.new("L", grande.size, 0)
        ImageDraw.Draw(tampa_m).rounded_rectangle(
            (x1 + 0.7 * k, cy - bh * k * 0.2, x1 + tampa * k,
             cy + bh * k * 0.2), radius=tampa * k * 0.45, fill=255)
        filtro = getattr(Image, "Resampling", Image).BOX
        corpo = grande.resize((larg, alt), filtro)
        tampa_m = tampa_m.resize((larg, alt), filtro)
        # a linha da carga (em pixel inteiro: nitida)
        corte = Image.new("L", (larg, alt), 0)
        ImageDraw.Draw(corte).rectangle(
            (0, 0, folga_l + int(round(bw * nivel / 100.0)) - 1, alt),
            fill=255)
        # (08/out, relato dele: "nao muda nada, so aparece o raio, falta o
        # glow") o halo sozinho mal saia da bateria (2 px de folga): agora o
        # RESPIRAR tambem acende a parte vazia (50% -> 75%) e o halo e mais
        # forte e mais largo; `resp` = 0 (expira) a 1 (inspira)
        resp = 0.0
        if brilho is not True and brilho:
            resp = max(0.0, min(1.0, (float(brilho) - 0.12) / 0.6))
        fraca = 0.5 + 0.25 * resp
        cheia = ImageChops.multiply(corpo, corte)
        vazia = ImageChops.multiply(corpo, ImageChops.invert(corte)).point(
            lambda v: int(v * fraca))
        # a tampa acompanha: na cor se cheia, fraca se nao
        tampa_m = tampa_m.point(lambda v: int(v * (1.0 if nivel >= 100
                                                   else fraca)))
        mascara = ImageChops.lighter(ImageChops.lighter(cheia, vazia),
                                     tampa_m)
        img = Image.new("RGB", (larg, alt), E.FUNDO)
        tinta = Image.new("RGB", (larg, alt), cor)
        if brilho:
            # `brilho` numero = a forca do halo (o RESPIRAR do carregando,
            # `_respirar_bateria`), um pouco mais largo
            forca = 0.4 if brilho is True else 0.25 + 0.95 * resp
            raio_b = E.px(1.3) if brilho is True else E.px(2)
            halo = ImageChops.lighter(corpo, tampa_m).filter(
                ImageFilter.GaussianBlur(raio_b))
            img.paste(tinta, (0, 0), halo.point(
                lambda v: min(255, int(v * forca))))
        img.paste(tinta, (0, 0), mascara)
        if not numero:
            if carregando:
                # o raio RECORTADO no meio (a cor do fundo), da altura toda
                raio_g = Image.new("L", grande.size, 0)
                mx = (x0 + x1) / 2.0
                a0, a1 = y0 + k * 0.8, y1 - k * 0.8
                ImageDraw.Draw(raio_g).polygon(
                    [(mx + 1.8 * k, a0), (mx - 3.0 * k, cy + 0.9 * k),
                     (mx - 0.1 * k, cy + 0.9 * k), (mx - 1.8 * k, a1),
                     (mx + 3.0 * k, cy - 0.9 * k),
                     (mx + 0.1 * k, cy - 0.9 * k)], fill=255)
                img.paste(Image.new("RGB", (larg, alt), E.FUNDO), (0, 0),
                          raio_g.resize((larg, alt), filtro))
            return img
        # o numero recortado: o maior que cabe com 1 px de folga em volta
        texto = str(nivel)
        caminho = None
        for nome_f in ("segoeuib.ttf", "seguisb.ttf", "arialbd.ttf"):
            try:
                ImageFont.truetype(nome_f, 10)
                caminho = nome_f
                break
            except OSError:
                continue
        medida = ImageDraw.Draw(Image.new("L", (1, 1)))
        tam = bh * 2
        while tam > 5:
            fonte = ImageFont.truetype(caminho, tam) if caminho else \
                ImageFont.load_default()
            bb = medida.textbbox((0, 0), texto, font=fonte)
            if bb[3] - bb[1] <= bh - 2 and bb[2] - bb[0] <= bw - 2:
                break
            tam -= 1
        topo = (alt - bh) // 2
        ImageDraw.Draw(img).text(
            (folga_l + (bw - (bb[2] - bb[0])) / 2.0 - bb[0],
             topo + (bh - (bb[3] - bb[1])) / 2.0 - bb[1]),
            texto, font=fonte, fill=E.FUNDO)
        return img

    def _img_bateria(self, nivel, cor, com_pct, carregando, brilho):
        chave = (nivel, cor, com_pct, carregando, brilho,
                 self._altura_rodape())
        if chave not in self._BATERIAS:
            from PIL import ImageTk
            if len(self._BATERIAS) > 40:
                self._BATERIAS.clear()
            self._BATERIAS[chave] = ImageTk.PhotoImage(
                self._pil_bateria(nivel, cor, com_pct, carregando, brilho),
                master=self)
        return self._BATERIAS[chave]

    # (07/out, pedido dele: "azul enquanto frio e vermelho quente") A cor do
    # termometro CORRE pela temperatura (sem degraus de cor): frio azul,
    # o normal de um celular (28-34) num azul bem claro, aquecendo ambar e
    # quente vermelho -- as faixas que o Android usa para a bateria (acima de
    # ~40 ja e quente; 45 e o limite de carga). A coluna sobe de 15 a 45.
    _ESCALA_TEMP = ((18.0, E.AZUL), (30.0, "#A8C8EA"), (36.0, "#D9D6CF"),
                    (40.0, E.ALERTA), (44.0, E.ERRO))

    def _cor_da_temperatura(self, t: float) -> tuple:
        esc = self._ESCALA_TEMP
        if t <= esc[0][0]:
            cor = esc[0][1]
        elif t >= esc[-1][0]:
            cor = esc[-1][1]
        else:
            for (t0, c0), (t1, c1) in zip(esc, esc[1:]):
                if t0 <= t <= t1:
                    # em 4 passos por faixa: o icone e guardado por cor
                    k = round((t - t0) / (t1 - t0) * 4) / 4.0
                    cor = E._mistura(c1, c0, k)
                    break
        nivel = round(max(0.0, min(1.0, (t - 15.0) / 30.0)) * 10) / 10.0
        return cor, nivel

    # (07/out, pedido dele: "ao detectar o carregador alem do raio ficar um
    # glow respirando na bateria, seguindo a cor dela") Um ciclo de 2,4 s
    # (o ritmo calmo de "respirar" dos indicadores de carga), a forca do
    # halo indo de 0,12 a 0,72 em 9 degraus (as imagens ficam guardadas);
    # so troca a imagem quando o degrau muda, e com a janela escondida o
    # laco dorme.
    RESPIRO_S = 2.4

    def _fase_respiro(self) -> float:
        import math
        fase = (time.monotonic() % self.RESPIRO_S) / self.RESPIRO_S
        k = 0.5 - 0.5 * math.cos(2 * math.pi * fase)
        return round(0.12 + 0.6 * round(k * 8) / 8.0, 3)

    def _respirar_bateria(self) -> None:
        # (08/out) o `_respiro_id` so volta a None quando o laco ACABA: com
        # None durante a pintura, o `_pintar_saude` abria um laco novo a cada
        # volta (2, 4, 8... lacos a cada 80 ms) e a janela travava
        cel = getattr(self.programa, "celular", None) or {}
        if not cel.get("carregando") or cel.get("bateria") is None:
            self._respiro_id = None
            return                       # parou de carregar: o laco acaba
        try:
            visivel = self.winfo_viewable()
        except tk.TclError:
            self._respiro_id = None
            return
        if visivel:
            self._pintar_saude()
        self._respiro_id = self.after(80 if visivel else 600,
                                      self._respirar_bateria)

    # (08/out, pedido dele) A BARRINHA DA VERIFICACAO no canto direito do
    # rodape: laranja, a altura dos outros icones (a do corpo da bateria),
    # o dobro da largura da bateria, enchendo da esquerda; o vazio no mesmo
    # tom mais fraco e o glow RESPIRANDO como o da bateria carregando. So
    # existe enquanto a verificacao dos apps roda.
    _PROGRESSOS: dict = {}

    def _pil_progresso(self, frac: float, brilho: float):
        from PIL import Image, ImageChops, ImageDraw, ImageFilter
        alt, S = self._celula_rodape_alt(), self._altura_rodape()
        bh = max(6, int(round(S * 0.8)))
        bw = 2 * (self._mascara_rodape("pc").width - 2 * E.px(2))
        folga = E.px(2)
        larg = bw + 2 * folga
        k = 8
        y0 = (alt - bh) // 2
        grande = Image.new("L", (larg * k, alt * k), 0)
        ImageDraw.Draw(grande).rounded_rectangle(
            (folga * k, y0 * k, (folga + bw) * k - 1, (y0 + bh) * k - 1),
            radius=bh * k * 0.3, fill=255)
        filtro = getattr(Image, "Resampling", Image).BOX
        corpo = grande.resize((larg, alt), filtro)
        corte = Image.new("L", (larg, alt), 0)
        cheio_x = folga + int(round(bw * max(0.0, min(1.0, frac))))
        if cheio_x > folga:
            ImageDraw.Draw(corte).rectangle((0, 0, cheio_x - 1, alt),
                                            fill=255)
        resp = max(0.0, min(1.0, (float(brilho) - 0.12) / 0.6))
        fraca = 0.35 + 0.2 * resp
        cheia = ImageChops.multiply(corpo, corte)
        vazia = ImageChops.multiply(corpo, ImageChops.invert(corte)).point(
            lambda v: int(v * fraca))
        mascara = ImageChops.lighter(cheia, vazia)
        img = Image.new("RGB", (larg, alt), E.FUNDO)
        tinta = Image.new("RGB", (larg, alt), E.ACENTO)
        forca = 0.25 + 0.95 * resp
        halo = corpo.filter(ImageFilter.GaussianBlur(E.px(2)))
        img.paste(tinta, (0, 0), halo.point(
            lambda v: min(255, int(v * forca))))
        img.paste(tinta, (0, 0), mascara)
        return img

    def _img_progresso(self, frac: float, brilho: float):
        frac = round(frac * 40) / 40.0           # 41 degraus guardados
        chave = (frac, brilho, self._altura_rodape())
        if chave not in self._PROGRESSOS:
            from PIL import ImageTk
            if len(self._PROGRESSOS) > 120:
                self._PROGRESSOS.clear()
            self._PROGRESSOS[chave] = ImageTk.PhotoImage(
                self._pil_progresso(frac, brilho), master=self)
        return self._PROGRESSOS[chave]

    def _laco_progresso(self) -> None:
        """Olha a verificacao: rodando = pinta a cada 80 ms (o respirar);
        parada = esconde e confere de novo a cada 1 s."""
        self._progresso_id = None
        b = getattr(self, "_progresso", None)
        try:
            if b is None or not b.winfo_exists():
                return
            estado = self.programa.analise_estado
            rodando = estado is not None and not estado.get("fim") and \
                estado.get("total", 0) > 0
            if not rodando:
                if b.winfo_manager():
                    b.pack_forget()
                    self._esconder_dica_barra()
                self._progresso_id = self.after(1000, self._laco_progresso)
                return
            visivel = self.winfo_viewable()
            if visivel:
                frac = estado["feitos"] / float(max(1, estado["total"]))
                img = self._img_progresso(frac, self._fase_respiro())
                if not b.winfo_manager():
                    b.pack(side="right")
                if b.cget("image") != str(img):
                    b.configure(image=img)
            self._progresso_id = self.after(80 if visivel else 600,
                                            self._laco_progresso)
        except tk.TclError:
            pass

    def _texto_progresso(self) -> str:
        e = self.programa.analise_estado or {}
        return "verificando os apps\n%d de %d · %s" % (
            min(e.get("feitos", 0) + 1, max(1, e.get("total", 0))),
            max(1, e.get("total", 0)), (e.get("app") or "").lower()[:22])

    def _dica_progresso(self, b) -> None:
        self._mostrar_dica_barra(b, self._texto_progresso())

    def _pintar_saude(self) -> None:
        """(07/out) Bateria e temperatura do rodape, do `programa.celular`
        (o vigia da bateria: nivel na hora, temperatura a cada 90 s)."""
        s = getattr(self, "_saude", None)
        if not s:
            return
        cel = getattr(self.programa, "celular", None) or {}
        nivel = cel.get("bateria")
        try:
            bat, temp, graus = s["bat"], s["temp"], s["graus"]
            con = (getattr(self, "_indicadores", None) or {}).get("con")
            if nivel is None:
                for w in (bat, temp, graus):
                    if w.winfo_manager():
                        w.pack_forget()
                return
            if not bat.winfo_manager():
                if con is not None:
                    bat.pack(side="left", before=con)   # o primeiro
                else:
                    bat.pack(side="left")
            carregando = bool(cel.get("carregando"))
            # (07/out, pedido dele) a COR DA CARGA: 100 verde, 10 vermelho e
            # o meio calculado (laranja, amarelo); com o brilho leve dos
            # outros estados. Nao acende com o mouse: nao e botao.
            cor, brilho = self._cor_da_carga(nivel), True
            if carregando:
                # (07/out, pedido dele) carregando: o brilho RESPIRA
                brilho = self._fase_respiro()
                if getattr(self, "_respiro_id", None) is None:
                    self._respiro_id = self.after(80, self._respirar_bateria)
            img = self._img_bateria(int(nivel), cor,
                                    self._config.opcao("bateria_pct"),
                                    carregando, brilho)
            if bat.cget("image") != str(img):
                bat.configure(image=img)
            t = cel.get("temperatura")
            if t is None:
                for w in (temp, graus):
                    if w.winfo_manager():
                        w.pack_forget()
                return
            if not temp.winfo_manager():
                temp.pack(side="left")
                graus.pack(side="left")
            cor_t, nivel_t = self._cor_da_temperatura(t)
            # (a coluna em 11 degraus: o icone e guardado por degrau)
            img_t = self._icone_rodape("termometro@%.1f" % nivel_t, cor_t,
                                       True)
            if temp.cget("image") != str(img_t):
                temp.configure(image=img_t)
            texto = "%d°" % round(t)
            # a letra acompanha o tamanho escolhido
            fonte = E.fonte({"p": E.ROTULO - 1, "g": E.PEQUENA}.get(
                self._config.opcoes.get("icones_rodape") or "m", E.ROTULO))
            if graus.cget("text") != texto or graus.cget("fg") != cor_t \
                    or getattr(graus, "_fonte", None) != fonte:
                graus._fonte = fonte
                graus.configure(text=texto, fg=cor_t, font=fonte)
        except tk.TclError:
            pass

    def _botao_barra(self, barra, tipo: str) -> tk.Label:
        """Uma celula da barra; quem chama liga o clique."""
        b = tk.Label(barra, bg=E.FUNDO, bd=0, highlightthickness=0,
                     cursor="hand2", padx=0, pady=0)
        b._tipo = tipo
        b._sobre = False
        if tipo != "fechar":
            # (07/out, pedido dele: "um pouquinho" mais estreitos, mais
            # harmonico) 34 em vez de 40; o fechar segue de borda a borda
            b._medidas = (self.CELULA_ESTREITA, E.ALTURA_BARRA,
                          self.ICONE_BARRA)
        self._botoes_barra[tipo] = b
        b.bind("<Enter>", lambda _e: self._barra_sobre(b, True))
        b.bind("<Leave>", lambda _e: self._barra_sobre(b, False))
        self.after_idle(self._pintar_barra)
        return b

    # -- o RODAPE da lista: os indicadores de conexao e som (07/out) --------

    # (funcao, rotulo) que cada indicador pode fazer -- em OPCOES > geral
    # cada gesto escolhe uma (ou nada, o de fabrica).
    FUNCOES_IND = {
        "som": [("trocar", "trocar pc / celular"),
                ("ambos", "no pc e no celular"),
                ("todos", "o mesmo em todos os modos")],
        "con": [("trocar", "trocar cabo / sem fio"),
                ("alternar", "desconectar / conectar")],
    }
    GESTOS_IND = [("clique", "clique"), ("segurar", "segurar"),
                  ("rodinha", "rodinha")]

    def _medidas_rodape(self) -> tuple:
        # (07/out, pedido dele) so o icone, pequeno (14), sem caixa; a celula
        # de 22 e a area do mouse (dica e gestos)
        # (07/out, pedido dele: "mais perto, nao colados") a celula quase do
        # tamanho do icone: ~3-4 px entre os dois desenhos
        return (E.px(15), E.px(22), E.px(14))

    # (07/out, pedido dele: "claramente com tamanhos diferentes") O RODAPE
    # TODO NA MESMA ALTURA: cada icone e desenhado para que a TINTA (o que
    # se ve, medido) tenha a mesma altura -- o wifi tinha 11 px e o celular
    # 15 na mesma grade -- com o MESMO traco em todos; a celula e a tinta +
    # uma folga igual dos dois lados (vao igual entre todos). Tres tamanhos
    # em OPCOES > geral.
    # (07/out, relato dele: "aumentou demais" e "nao pode interferir no
    # resto") O TERMOMETRO e a medida: cada icone cabe no MESMO QUADRADO
    # (o lado = a altura do termometro) -- os largos (wifi, monitor) ficam
    # na largura dele, sem passar em nenhuma direcao. A celula tem altura
    # FIXA (a de sempre): trocar o tamanho nao mexe no resto da janela.
    TAMANHOS_RODAPE = [("p", "pequeno"), ("m", "médio"), ("g", "grande")]
    _ALTURA_RODAPE = {"p": 10, "m": 11.5, "g": 13}    # o termometro
    _TINTAS: dict = {}

    def _altura_rodape(self) -> int:
        t = self._config.opcoes.get("icones_rodape") or "m"
        return E.px(self._ALTURA_RODAPE.get(t, 11.5))

    def _celula_rodape_alt(self) -> int:
        return E.px(22)                  # fixa, em qualquer tamanho

    def _traco_rodape(self) -> float:
        return max(1.5, self._altura_rodape() * 0.11)

    def _fracao_tinta(self, nome: str) -> tuple:
        """(altura, x0, y0, x1, y1) da tinta do icone na grade de 24, medida
        num desenho grande (fracoes do lado)."""
        if nome not in self._TINTAS:
            lado = 192
            m = self._pil_celula(nome, "#FFFFFF", "#000000",
                                 medidas=(lado, lado, lado),
                                 traco=16).convert("L")
            bb = m.point(lambda v: 255 if v > 40 else 0).getbbox() or \
                (0, 0, lado, lado)
            self._TINTAS[nome] = ((bb[3] - bb[1]) / float(lado),
                                  (bb[2] - bb[0]) / float(lado))
        return self._TINTAS[nome]

    def _mascara_rodape(self, nome: str):
        """A celula do rodape (mascara L) com o icone na altura comum."""
        from PIL import Image
        H = self._altura_rodape()
        alt = self._celula_rodape_alt()
        folga = E.px(2)
        fh, _fw = self._fracao_tinta(nome.split("@")[0])
        frac = fh or 1.0
        # (07/out, comparado lado a lado) o TERMOMETRO e a base, na altura
        # cheia; os outros (mais largos) em 80% dela parecem do mesmo
        # tamanho ao lado dele, que e fino
        if not nome.startswith("termometro"):
            H = max(6, int(round(H * 0.8)))
        # desenhado 8x maior, a tinta recortada e reduzida DIRETO para a
        # medida final (arredondar o lado deixava +-2 px de diferenca)
        k = 8
        lado = max(8, int(round(H * k / frac)))
        grande = lado + 8 * k
        m = self._pil_celula(nome, "#FFFFFF", "#000000",
                             medidas=(grande, grande, lado),
                             traco=self._traco_rodape() * k).convert("L")
        bb = m.point(lambda v: 255 if v > 8 else 0).getbbox() or \
            (0, 0, grande, grande)
        tinta = m.crop(bb)
        filtro = getattr(Image, "Resampling", Image).BOX
        escala = H / float(tinta.height)
        tinta = tinta.resize((max(1, int(round(tinta.width * escala))),
                              max(1, int(round(tinta.height * escala)))),
                             filtro)
        cel = Image.new("L", (tinta.width + 2 * folga, alt), 0)
        # centrados na mesma linha do meio (a da bateria)
        cel.paste(tinta, (folga, (alt - tinta.height) // 2))
        return cel

    def _icone_rodape(self, nome: str, cor: str, brilho: bool):
        chave = ("rodape", nome, cor, brilho, self._altura_rodape())
        if chave not in self._ICONES_BARRA:
            from PIL import Image, ImageFilter, ImageTk
            mascara = self._mascara_rodape(nome)
            img = Image.new("RGB", mascara.size, E.FUNDO)
            tinta = Image.new("RGB", mascara.size, cor)
            if brilho:
                halo = mascara.filter(ImageFilter.GaussianBlur(E.px(1.3)))
                img.paste(tinta, (0, 0), halo.point(lambda v: int(v * 0.5)))
            img.paste(tinta, (0, 0), mascara)
            self._ICONES_BARRA[chave] = ImageTk.PhotoImage(img, master=self)
        return self._ICONES_BARRA[chave]

    def _montar_rodape(self, rodape) -> None:
        """O rodape (07/out, pedido dele), da esquerda para a direita:
        BATERIA, CONEXAO, SOM e TEMPERATURA -- so os icones, todos na mesma
        altura (`_mascara_rodape`), com o mesmo vao entre eles. Conexao e som
        nao respondem ao clique de fabrica: so os gestos escolhidos em
        OPCOES. Bateria (na hora) e temperatura (a cada 90 s) so com um
        celular lido."""
        self._indicadores = {}
        caixa = tk.Frame(rodape, bg=E.FUNDO)
        caixa.pack(side="left", anchor="w")
        self._saude = {"caixa": caixa}
        # (08/out, pedido dele) a BARRINHA da verificacao, separada, alinhada
        # a direita; so aparece enquanto verifica
        prog = tk.Label(rodape, bg=E.FUNDO, bd=0, highlightthickness=0,
                        padx=0, pady=0)
        prog._tipo = "prog"
        prog._sobre = False
        prog.bind("<Enter>", lambda _e: self._dica_progresso(prog))
        prog.bind("<Leave>", lambda _e: self._esconder_dica_barra())
        self._progresso = prog
        self._progresso_id = self.after(1500, self._laco_progresso)

        def celula(tipo):
            b = tk.Label(caixa, bg=E.FUNDO, bd=0, highlightthickness=0,
                         padx=0, pady=0)
            b._tipo = tipo
            b._sobre = False
            b.bind("<Enter>", lambda _e, b=b: self._barra_sobre(b, True))
            b.bind("<Leave>", lambda _e, b=b: self._barra_sobre(b, False))
            return b

        self._saude["bat"] = celula("bat")
        for tipo in ("con", "som"):
            b = celula(tipo)
            b.pack(side="left")
            b._indicador = True
            self._indicadores[tipo] = b
            b.bind("<ButtonPress-1>", lambda _e, b=b: self._ind_apertou(b))
            b.bind("<ButtonRelease-1>", lambda _e, b=b: self._barra_soltou(b))
            b.bind("<ButtonRelease-2>", lambda _e, b=b: self._ind_gesto(
                b, "rodinha"))
        self._saude["temp"] = celula("temp")
        graus = celula("temp")
        graus.configure(fg=E.TEXTO_2)
        self._saude["graus"] = graus
        self.after_idle(self._pintar_barra)

    def _ind_ativo(self, tipo: str) -> bool:
        """Algum gesto deste indicador faz alguma coisa?"""
        return any(self._config.gesto(tipo, g) for g, _r in self.GESTOS_IND)

    def _ind_apertou(self, b) -> None:
        """Apertou um indicador: com SEGURAR escolhido, a cor enche (como o
        X); senao o clique vale no soltar."""
        self._esconder_dica_barra()
        if not self._config.gesto(b._tipo, "segurar"):
            if self._config.gesto(b._tipo, "clique"):
                self._ind_gesto(b, "clique")
            return
        self._barra_apertou(b)

    def _ind_gesto(self, b, gesto: str) -> None:
        funcao = self._config.gesto(b._tipo, gesto)
        if funcao:
            self._funcao_ind(b._tipo, funcao, b)

    def _funcao_ind(self, tipo: str, funcao: str, b=None) -> None:
        """Uma funcao de indicador (gesto ou atalho de teclado)."""
        p = self.programa
        b = b or (getattr(self, "_indicadores", None) or {}).get(tipo)
        if tipo == "som":
            alvo = self._alvo_do_som()
            if funcao == "trocar":
                onde = self._onde_do_som(alvo)
                self._mudar_som(alvo, "celular" if onde != "celular" else "pc")
            elif funcao == "ambos":
                if self._falta("pc_cel"):
                    p.anotar("som nos dois precisa do android 13")
                    if b is not None:
                        self._mostrar_dica_barra(
                            b, "som nos dois\nprecisa do android 13",
                            some_ms=1800)
                    return
                self._mudar_som(alvo, "ambos")
            elif funcao == "todos":
                self._som_para_todos(b)
                return
        elif tipo == "con":
            if funcao == "trocar":
                p.definir_conexao("cabo" if p.conexao_preferida() == "sem_fio"
                                  else "sem_fio")
            elif funcao == "alternar":
                if p.conexao_pausada:
                    p.retomar_conexao()
                else:
                    p.desconectar_tudo()
        p.anotar("indicador %s: %s" % (tipo, funcao))
        self._pintar_barra()

    def _abrir_pela_barra(self, b) -> None:
        """PAREAR / OPCOES da barra: a tela abre com a animacao nascendo do
        botao (um circulo que cresce dali)."""
        item = b._tipo
        if getattr(b, "_travado", False):
            return
        if item == self._item:
            self._voltar_ao_inicio()        # (09/out) ja nele: 1a aba
            return
        try:
            origem = (b.winfo_rootx() + b.winfo_width() // 2,
                      b.winfo_rooty() + b.winfo_height() // 2)
        except tk.TclError:
            origem = None
        self._escolher_item(item, origem=origem)

    def _estado_barra(self, tipo: str) -> tuple[str, str]:
        """(icone, texto) do botao agora."""
        p = self.programa
        if tipo == "fechar":
            return "fechar", "fechar"
        if tipo == "minimizar":
            return "minimizar", "minimizar"
        if tipo in ("opcoes", "parear"):
            return tipo, tipo
        if tipo == "som":
            onde = self._onde_do_som(self._alvo_do_som())
            return onde, TEXTO_SOM[onde]
        if p.conexao_pausada:
            return "nenhum", TEXTO_CON["pausada"]
        usa = p.conexao_em_uso()
        return ({"cabo": "cabo", "sem_fio": "sem_fio"}.get(usa, "nenhum"),
                TEXTO_CON[usa])

    def _pintar_barra(self) -> None:
        botoes = list((getattr(self, "_botoes_barra", None) or {}).items()) + \
            list((getattr(self, "_indicadores", None) or {}).items())
        for tipo, b in botoes:
            if getattr(b, "_enchendo", False):
                continue                 # segurando: o preenchimento manda
            try:
                icone, _t = self._estado_barra(tipo)
                ind = getattr(b, "_indicador", False)
                vivo = not ind or self._ind_ativo(tipo)
                brilho = False
                if ind:
                    # (07/out, pedido dele) conectado = VERDE (cabo ou sem
                    # fio); o som = AZUL; com brilho leve. Sem conexao, cinza.
                    if icone == "nenhum":
                        cor = E.APAGADO
                    else:
                        cor = E.VERDE if tipo == "con" else E.AZUL
                        brilho = True
                elif getattr(b, "_travado", False):
                    cor = E.LINHA_FORTE
                elif tipo == self._item and tipo in ("opcoes", "parear"):
                    cor = E.ACENTO       # a tela dele esta aberta
                elif b._sobre and vivo:
                    cor = E.TEXTO
                else:
                    cor = E.APAGADO if icone == "nenhum" else E.TEXTO_2
                img = self._icone_rodape(icone, cor, brilho) if ind else \
                    self._icone_barra(icone, cor,
                                      getattr(b, "_medidas", None), brilho)
                if b.cget("image") != str(img):
                    b.configure(image=img)
                cursor = "hand2" if vivo and not getattr(
                    b, "_travado", False) else "arrow"
                if b.cget("cursor") != cursor:
                    b.configure(cursor=cursor)
            except tk.TclError:
                pass
        self._pintar_saude()             # (07/out) bateria e temperatura

    def _barra_sobre(self, b, sobre: bool) -> None:
        """(07/out, pedido dele) Com o mouse em cima, SO o icone acende (sem
        fundo nem texto)."""
        b._sobre = sobre
        self._pintar_barra()
        # (07/out, pedido dele) repousou o mouse: a dica do que ele faz
        anterior = getattr(self, "_dica_barra_id", None)
        if anterior is not None:
            try:
                self.after_cancel(anterior)
            except Exception:
                pass
            self._dica_barra_id = None
        if sobre:
            self._dica_barra_id = self.after(
                600, lambda: b._sobre and getattr(self, "_barra_seg", None)
                is None and self._mostrar_dica_barra(b))
        else:
            self._esconder_dica_barra()

    def _gestos_texto(self, tipo: str) -> str:
        """As linhas "clique: ..." dos gestos escolhidos do indicador."""
        nomes = dict(self.FUNCOES_IND[tipo])
        tempo = {"som": "segure 1 s", "con": "segure 2 s"}[tipo]
        linhas = []
        for g, rot in self.GESTOS_IND:
            f = self._config.gesto(tipo, g)
            if f:
                linhas.append("%s: %s" % (tempo if g == "segurar" else
                                          "clique da rodinha" if g == "rodinha"
                                          else rot, nomes.get(f, f)))
        return "\n".join(linhas) or "gestos: em opções › rodapé"

    def _texto_dica_barra(self, tipo: str) -> str:
        p = self.programa
        if tipo == "fechar":
            return "fechar\nclique: esconde na bandeja\nsegure 1 s: sai do programa"
        if tipo == "minimizar":
            return "minimizar"
        if tipo == "opcoes":
            return "opções\najustes, atalhos e qualidade"
        if tipo == "parear":
            return "parear\nconexão e celular novo"
        if tipo == "som":
            alvo = self._alvo_do_som()
            nome = {"jogo": "espelhar", "extensao": "extensão",
                    "apps": "apps"}[alvo]
            onde = {"pc": "no pc", "celular": "no celular",
                    "ambos": "no pc e no celular"}[self._onde_do_som(alvo)]
            return "som %s (%s)\n%s" % (onde, nome, self._gestos_texto("som"))
        if tipo == "bat":
            cel = p.celular or {}
            nivel = cel.get("bateria")
            if nivel is None:
                return "bateria\nsem leitura"
            return "bateria\n%d%%%s\nporcentagem dentro: opções › rodapé" % (
                nivel, " · carregando" if cel.get("carregando") else "")
        if tipo == "temp":
            t = (p.celular or {}).get("temperatura")
            texto = ("%.1f °C" % t).replace(".", ",") if t is not None \
                else "sem leitura"
            return "temperatura da bateria\n%s · lida a cada 90 s" % texto
        if p.conexao_pausada:
            return "desconectado\n%s" % self._gestos_texto("con")
        usa = {"cabo": "pelo cabo", "sem_fio": "sem fio"}.get(
            p.conexao_em_uso(), "sem celular")
        return "conexão: %s\n%s" % (usa, self._gestos_texto("con"))

    def _mostrar_dica_barra(self, b, texto: str | None = None,
                            some_ms: int = 0) -> None:
        """A dica da casa (SUPERFICIE, canto redondo, esmaece) logo abaixo
        do botao, dentro da tela. `texto` = um recado no lugar da dica;
        `some_ms` = sai sozinha depois disso."""
        self._dica_barra_id = None
        self._esconder_dica_barra()
        try:
            if not b.winfo_viewable():
                return
        except tk.TclError:
            return
        linhas = (texto or self._texto_dica_barra(b._tipo)).split("\n")
        j = tk.Toplevel(self)
        j.withdraw()
        j.overrideredirect(True)
        moldura.arredondar_ao_mostrar(j, borda=E.SUPERFICIE_BORDA)
        j.attributes("-topmost", True)
        j.configure(bg=E.SUPERFICIE)
        corpo = tk.Frame(j, bg=E.SUPERFICIE)
        corpo.pack(padx=E.px(9), pady=E.px(6))
        for i, linha in enumerate(linhas):
            tk.Label(corpo, text=linha,
                     bg=E.SUPERFICIE, fg=E.TEXTO if i == 0 else E.TEXTO_2,
                     font=E.fonte(E.PEQUENA, "bold") if i == 0
                     else E.fonte(E.ROTULO),
                     anchor="w", justify="left").pack(side="top", fill="x")
        j.update_idletasks()
        larg, alt = j.winfo_reqwidth(), j.winfo_reqheight()
        x = b.winfo_rootx() + b.winfo_width() // 2 - larg // 2
        y = b.winfo_rooty() + b.winfo_height() + E.px(6)
        if getattr(b, "_indicador", False) or \
                getattr(b, "_tipo", "") in ("bat", "temp"):
            y = b.winfo_rooty() - alt - E.px(6)     # o rodape: a dica sobe
            # (07/out) no canto: comeca no icone, para a direita
            x = max(x, b.winfo_rootx() - E.px(8))
        try:
            ax, ay, al, aa = moldura.area_util(self, (x, y))
            x = max(ax + E.px(4), min(x, ax + al - larg - E.px(4)))
            y = max(ay, min(y, ay + aa - alt))
        except Exception:
            pass
        j.geometry("+%d+%d" % (x, y))
        if mov.ligadas():
            j.attributes("-alpha", 0.0)
        j.deiconify()
        mov.entrar(j)
        self._dica_barra_j = j
        if some_ms:
            self._dica_barra_id = self.after(
                some_ms, lambda: getattr(self, "_dica_barra_j", None) is j
                and self._esconder_dica_barra())

    def _esconder_dica_barra(self) -> None:
        j, self._dica_barra_j = getattr(self, "_dica_barra_j", None), None
        if j is not None:
            mov.sair(j, j.destroy)

    # SEGURAR (07/out, pedido dele: "a cor vai preenchendo a area do botao;
    # quando preencher, executa"): fechar (vermelho, 1 s = sair), som
    # (laranja, 1 s = os dois) e conexao (ambar, 2 s = desconectar tudo).
    # Duas camadas: EMBAIXO a cor nasce do centro e cresce (com brilho leve)
    # no ritmo do relogio; EM CIMA o icone, branco. Cores profundas para o
    # branco nao se perder (fechar = o vermelho do Windows). Soltar antes =
    # o clique do botao, e a cor volta para o centro.
    SEGURAR = {"fechar": (SEGURAR_X_MS, "#C42B1C"),
               "som": (SEGURAR_SOM_MS, "#B8400F"),
               "con": (SEGURAR_CON_MS, "#9A6A00")}

    def _barra_apertou(self, b) -> None:
        self._esconder_dica_barra()      # apertou: a dica sai
        if getattr(self, "_dica_barra_id", None) is not None:
            self.after_cancel(self._dica_barra_id)
            self._dica_barra_id = None
        if b._tipo not in self.SEGURAR:
            return
        self._cancelar_barra()
        ms, cor = self.SEGURAR[b._tipo]
        icone, _t = self._estado_barra(b._tipo)
        # o icone vira uma mascara (branco no preto) para ir POR CIMA
        if getattr(b, "_indicador", False):     # (07/out) o do rodape
            mascara = self._mascara_rodape(icone)
        else:
            mascara = self._pil_celula(icone, "#FFFFFF", "#000000",
                                       medidas=getattr(b, "_medidas", None)
                                       ).convert("L")
        seg = {"b": b, "feito": False, "p": 0.0, "cor": cor,
               "icone": mascara}
        self._barra_seg = seg
        b._enchendo = True

        def a_cada(p):
            seg["p"] = p
            self._quadro_barra(seg)

        mov.animar(b, "encher", ms, a_cada,
                   lambda: self._barra_segurou(b), curva=lambda t: t)

    def _quadro_barra(self, seg) -> None:
        """Um quadro do preenchimento. (07/out, refeito a pedido dele: o
        circulo "comecava rapido e demorava pra terminar") A cor nasce do
        CENTRO como um retangulo arredondado que escala por igual (chega nas
        4 bordas juntas; tamanho linear no tempo = comeca devagar, sem o
        rabo dos cantos), o raio diminuindo ate virar a celula. Atras, a
        mesma forma maior e desfocada (brilho leve); por cima, o icone
        branco. Borda lisa: mascara 3x reduzida."""
        from PIL import Image, ImageDraw, ImageFilter, ImageTk
        b = seg["b"]
        icone = seg["icone"]
        w, h = icone.size
        img = Image.new("RGB", (w, h), E.FUNDO)
        p = seg["p"]
        if p > 0.001:
            k = 3
            filtro = getattr(Image, "Resampling", Image).BOX
            cor = Image.new("RGB", (w, h), seg["cor"])
            # (07/out, gravado no real) no RODAPE a cor para numa pilula
            # DENTRO da celula -- cheia ate a borda, ela cobria a moldura
            # redonda da caixa. Na barra, vai de borda a borda (como antes).
            rodape = getattr(b, "_indicador", False)
            folga_fim = 0
            raio_fim = E.px(6) if rodape else 0      # rodape: celula redonda

            def forma(escala, folga):
                hw = ((w / 2.0 - folga_fim) * escala + folga) * k
                hh = ((h / 2.0 - folga_fim) * escala + folga) * k
                r = max(min(hw, hh) * (1.0 - p), raio_fim * k)
                m = Image.new("L", (w * k, h * k), 0)
                cx, cy = w * k / 2.0, h * k / 2.0
                ImageDraw.Draw(m).rounded_rectangle(
                    (cx - hw, cy - hh, cx + hw, cy + hh), radius=r, fill=255)
                return m.resize((w, h), filtro)
            # brilho: a forma um pouco maior, desfocada, alfa baixo
            brilho = forma(p, E.px(3) * p).filter(
                ImageFilter.GaussianBlur(E.px(3)))
            img.paste(cor, (0, 0), brilho.point(lambda v: int(v * 0.35)))
            img.paste(cor, (0, 0), forma(p, 0))
        img.paste(Image.new("RGB", (w, h), "#FFFFFF"), (0, 0), icone)
        foto = ImageTk.PhotoImage(img, master=self)
        b._foto = foto
        b.configure(image=foto)

    def _esvaziar_barra(self, seg) -> None:
        """A cor volta (rapido) e o botao fica como era."""
        b = seg["b"]
        de = seg["p"]

        def a_cada(k):
            seg["p"] = de * (1.0 - k)
            self._quadro_barra(seg)

        def fim():
            b._enchendo = False
            self._pintar_barra()
        mov.animar(b, "encher", mov.MS_POPUP_SAI, a_cada, fim,
                   curva=mov.SAIDA)

    def _barra_soltou(self, b) -> None:
        seg = getattr(self, "_barra_seg", None)
        if seg is None or seg["b"] is not b:
            return
        self._barra_seg = None
        if seg["feito"]:
            return
        mov.parar(b, "encher")
        self._esvaziar_barra(seg)
        self._barra_clicou(b)

    def _cancelar_barra(self) -> None:
        seg, self._barra_seg = getattr(self, "_barra_seg", None), None
        if seg is not None and not seg["feito"]:
            mov.parar(seg["b"], "encher")
            self._esvaziar_barra(seg)

    def _barra_clicou(self, b) -> None:
        if getattr(b, "_indicador", False):
            self._ind_gesto(b, "clique")     # soltou antes de encher
            return
        if b._tipo == "fechar":
            self.esconder()
            return
        if b._tipo == "som":
            alvo = self._alvo_do_som()
            onde = self._onde_do_som(alvo)
            self._mudar_som(alvo, "celular" if onde != "celular" else "pc")
        else:
            p = self.programa
            if p.conexao_pausada:
                p.retomar_conexao()
            else:
                p.definir_conexao("cabo" if p.conexao_preferida() == "sem_fio"
                                  else "sem_fio")
        self._pintar_barra()

    def _barra_segurou(self, b) -> None:
        seg = getattr(self, "_barra_seg", None)
        if seg is None or seg["b"] is not b:
            return
        seg["feito"] = True
        if getattr(b, "_indicador", False):
            self._ind_gesto(b, "segurar")
            self.after(160, lambda: self._esvaziar_barra(seg))
            return
        if b._tipo == "fechar":
            # A janela some NA HORA; o resto da despedida (derrubar as
            # sessoes) acontece com ela ja fora da tela.
            self._sumir_ja()
            self.sair_do_programa()
            return
        if b._tipo == "som":
            if self._falta("pc_cel"):
                self.programa.anotar("barra: som nos dois precisa do "
                                     "android 13")
            else:
                self._mudar_som(self._alvo_do_som(), "ambos")
        else:
            self.programa.desconectar_tudo()
        # cheio por um instante (o comando foi), depois a cor volta
        self.after(160, lambda: self._esvaziar_barra(seg))

    def _som_para_todos(self, b) -> None:
        """(07/out, pedido dele) Clique da rodinha no botao do som: onde o
        som sai agora (no modo da vez) vira o de espelhar, extensao e apps.
        Os apps personalizados com o seu proprio "onde" continuam com ele."""
        self._cancelar_barra()
        onde = self._onde_do_som(self._alvo_do_som())
        for modo in ("jogo", "extensao", "apps"):
            if self._onde_do_som(modo) != onde:
                self._mudar_som(modo, onde)
        self.programa.anotar("barra: som %s em todos os modos" % onde)
        self._pintar_barra()
        texto = {"pc": "no pc", "celular": "no celular",
                 "ambos": "no pc e no celular"}[onde]
        if b is not None:
            self._mostrar_dica_barra(b, "som %s\nem todos os modos" % texto,
                                     some_ms=1800)

    # o som: de QUAL modo (resposta dele: o que esta ligado; nada ligado =
    # o da aba aberta, ou espelhar)

    def _alvo_do_som(self) -> str:
        p = self.programa
        for nome in ("jogo", "extensao"):
            if p.ativo(nome) or p.ocupado(nome):
                return nome
        if p.apps_abertos():
            return "apps"
        return self._item if self._item in ("jogo", "extensao", "apps") \
            else "jogo"

    def _onde_do_som(self, alvo: str) -> str:
        if alvo == "jogo":
            perfil = self._perfil_jogo()
            if conteudo_do(perfil) == "imagem":
                return "celular"
            return "ambos" if (perfil.get("audio") or {}).get("duplicar") \
                else "pc"
        if alvo == "extensao":
            return qualidade.onde_do_perfil(self._perfil_ext())
        onde = self._config.apps.get("onde") or "celular"
        return onde if onde in TEXTO_SOM else "celular"

    def _mudar_som(self, alvo: str, onde: str) -> None:
        if alvo == "jogo":
            perfil = self._perfil_jogo()
            atual = conteudo_do(perfil)
            if onde == "celular":
                # espelhar sem som no pc = "so imagem"; guarda o de antes
                if atual != "imagem":
                    perfil["conteudo_antes"] = atual
                perfil["conteudo"] = "imagem"
                self._gravou("jogo", "som no celular (barra)")
            else:
                if atual == "imagem":
                    antes = perfil.pop("conteudo_antes", "ambos")
                    perfil["conteudo"] = antes if antes in ("ambos", "som") \
                        else "ambos"
                self._escolheu_onde_jogo(onde)
        elif alvo == "extensao":
            qualidade.aplicar_onde(self._perfil_ext(), onde)
            self._gravou("extensao", "onde o som toca = %s (barra)" % onde)
        else:
            self._virar_apps("onde", "" if onde == "celular" else onde)
        self.programa.anotar("barra: som de '%s' -> %s" % (alvo, onde))
        if self._visivel and not self._grande and (
                self._item == alvo or (alvo == "apps" and self._item == "apps"
                                       and self._aba["apps"] != "lista")):
            self._remontar_quieto()

    def minimizar(self) -> None:
        if self._gravando is not None:
            self._cancelar_gravacao()
        self._origem = "barra"
        self._cancelar_deslize()         # o veu e outra janela: nao fica
        moldura.minimizar(self)

    def _arrastou(self) -> None:
        self._pos = (self.winfo_x(), self.winfo_y())
        if getattr(self, "_veu", None) is not None:
            self._cancelar_deslize()

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
        # (03/out, relato dele: "ao iniciar pisca 2 ou 3x") A barra de
        # tarefas era arrumada 10 ms DEPOIS de aparecer, escondendo e
        # mostrando a janela no meio da animacao (e a conferencia a achava
        # "escondida" e mostrava de novo). Com ela ainda escondida, basta
        # trocar o estilo: o Windows o aplica quando ela aparece.
        if self._falta_arrumar_a_barra and \
                not moldura.situacao(self)[0] and \
                moldura.preparar_barra_escondida(self):
            self._falta_arrumar_a_barra = False
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
        self._cancelar_deslize()
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
            if getattr(self, "_avisos", None) is not None:
                self._avisos.fechar_todos()
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

    # (03/out/2026, pedido dele: "melhore o desenho do scrollbar") O cursor
    # virou uma pilula fina, sem o trilho de 1 px; discreta parada, laranja
    # com o mouse em cima ou arrastando.
    # `sobreposta` (aba APPS): a barra fica POR CIMA da lista, encostada na
    # direita, e so aparece rolando ou com o mouse na lista; `margem_topo` e
    # `margem_base` deixam espaco para o que flutua por cima (busca, aviso).

    def __init__(self, pai, sobreposta: bool = False, margem_topo: int = 0,
                 margem_base: int = 0, margem_lados: int = 0) -> None:
        self.sobreposta = sobreposta
        self.margem_topo = margem_topo
        self.margem_base = margem_base
        self.margem_lados = margem_lados
        self.canvas = tk.Canvas(pai, bg=E.FUNDO, highlightthickness=0, bd=0,
                                yscrollincrement=E.px(24))
        self.barra = tk.Canvas(pai, width=E.px(8), bg=E.FUNDO,
                               highlightthickness=0, bd=0, cursor="hand2")
        if sobreposta:
            self.canvas.pack(side="left", fill="both", expand=True)
            self.barra.place(relx=1.0, x=0, y=margem_topo, anchor="ne",
                             relheight=1.0, height=-(margem_topo + margem_base))
        else:
            self.barra.pack(side="right", fill="y", padx=(E.px(4), E.px(0)))
            self.canvas.pack(side="left", fill="both", expand=True)
        self.dentro = tk.Frame(self.canvas, bg=E.FUNDO)
        self._item = self.canvas.create_window(margem_lados, margem_topo,
                                               window=self.dentro, anchor="nw")
        self._pos = (0.0, 1.0)
        self._arraste = None
        self._sobre = False              # mouse em cima da barra
        self._a_vista_ate = 0.0          # sobreposta: aparece ate esta hora
        self.dentro.bind("<Configure>", lambda _e: self._medir())
        self.canvas.bind("<Configure>", self.largura)
        self.canvas.configure(yscrollcommand=self._rolou)
        self.barra.bind("<Configure>", lambda _e: self._pintar())
        self.barra.bind("<Button-1>", self._clicou)
        self.barra.bind("<B1-Motion>", self._arrastou)
        self.barra.bind("<ButtonRelease-1>", lambda _e: self._soltou())
        self.barra.bind("<Enter>", lambda _e: self._mouse(True))
        self.barra.bind("<Leave>", lambda _e: self._mouse(False))
        if sobreposta:
            for w in (self.canvas, self.dentro):
                w.bind("<Enter>", lambda _e: self._mostrar(2.5), add="+")
                w.bind("<Motion>", lambda _e: self._mostrar(2.5), add="+")

    def largura(self, evento) -> None:
        self.canvas.itemconfigure(
            self._item, width=max(1, evento.width - 2 * self.margem_lados))

    def largura_util(self) -> int:
        """A largura em que a lista e montada (sem as margens dos lados)."""
        return self.canvas.winfo_width() - 2 * self.margem_lados

    def _medir(self) -> None:
        caixa = self.canvas.bbox("all") or (0, 0, 0, 0)
        # A regiao comeca no 0 (a margem de cima conta) e ganha a de baixo.
        self.canvas.configure(scrollregion=(0, 0, caixa[2],
                                            caixa[3] + self.margem_base))

    def _rolou(self, primeiro, ultimo) -> None:
        novo = (float(primeiro), float(ultimo))
        if novo != self._pos:
            self._mostrar(1.2)
        self._pos = novo
        self._pintar()

    def _cabe_tudo(self) -> bool:
        return self._pos[1] - self._pos[0] >= 0.999

    def _mouse(self, sobre: bool) -> None:
        self._sobre = sobre
        if sobre:
            self._mostrar(2.5)
        self._pintar()

    def _mostrar(self, segundos: float) -> None:
        """Sobreposta: a barra aparece por `segundos` (e some sozinha)."""
        if not self.sobreposta:
            return
        import time as _t
        fim = _t.monotonic() + segundos
        if fim <= self._a_vista_ate:
            return
        a_vista = self._a_vista_ate > _t.monotonic()
        self._a_vista_ate = fim
        if not a_vista:
            self._pintar()
        try:
            self.barra.after(int(segundos * 1000) + 50, self._pintar)
        except tk.TclError:
            pass

    def _soltou(self) -> None:
        self._arraste = None
        self._pintar()

    def _pintar(self) -> None:
        import time as _t
        b = self.barra
        try:
            b.delete("all")
        except tk.TclError:
            return
        escondida = self._cabe_tudo() or (
            self.sobreposta and not self._sobre and self._arraste is None
            and _t.monotonic() > self._a_vista_ate)
        if self.sobreposta:
            # parada e sem o mouse: sai de cima dos icones de verdade
            # (a faixa e opaca e cobriria a borda deles)
            posta = bool(b.winfo_manager())
            if escondida and posta:
                b.place_forget()
            elif not escondida and not posta:
                b.place(relx=1.0, x=0, y=self.margem_topo, anchor="ne",
                        relheight=1.0,
                        height=-(self.margem_topo + self.margem_base))
        if escondida:
            return
        altura, larg = b.winfo_height(), b.winfo_width()
        if altura < 4:
            b.after(30, self._pintar)        # acabou de voltar: sem medida
            return
        grossura = max(3, E.px(4))
        x = larg / 2.0
        topo = int(self._pos[0] * altura)
        base = max(topo + E.px(24), int(self._pos[1] * altura))
        meia = grossura / 2.0 + 1
        ativa = self._sobre or self._arraste is not None
        b.create_line(x, topo + meia, x, base - meia, width=grossura,
                      capstyle="round",
                      fill=E.ACENTO if ativa else E.LINHA_FORTE)

    def _clicou(self, evento) -> None:
        altura = max(1, self.barra.winfo_height())
        fracao = evento.y / altura
        p0, p1 = self._pos
        if p0 <= fracao <= p1:
            self._arraste = (evento.y, p0)
        else:
            self._arraste = None
            self.mover(lambda: self.canvas.yview_moveto(
                max(0.0, fracao - (p1 - p0) / 2)))
        self._pintar()

    def _arrastou(self, evento) -> None:
        if self._arraste is None:
            return
        y0, p0 = self._arraste
        altura = max(1, self.barra.winfo_height())
        self.mover(lambda: self.canvas.yview_moveto(
            max(0.0, p0 + (evento.y - y0) / altura)))

    def mover(self, fazer) -> None:
        """Um passo da rolagem. (07/out, gravado) Travar a pintura do canvas
        (WM_SETREDRAW) durante o passo NAO tirou o quadro meio desenhado
        (o Windows copia os bits ao mover a lista) e pesava: fica direto."""
        fazer()

    def roda(self, evento):
        # (07/out) `na_borda(direcao)`: quem quer saber que a roda passou do
        # fim (+1) ou do comeco (-1) -- os grupos do editor do app.
        na_borda = getattr(self, "na_borda", None)
        if na_borda is not None:
            descer = evento.delta < 0
            if descer and self._pos[1] >= 0.999:
                return na_borda(1) or "break"
            if not descer and self._pos[0] <= 0.001:
                return na_borda(-1) or "break"
        if not self._cabe_tudo():
            passos = -int(evento.delta / 120) or (-1 if evento.delta > 0
                                                  else 1)
            self.mover(lambda: self.canvas.yview_scroll(
                passos * getattr(self, "passo_px", 1), "units"))
        return "break"

    def limpar(self, manter: bool = False) -> float:
        """Esvazia a lista. `manter`: volta ao mesmo ponto da rolagem depois
        de remontar (abrir um app nao joga a lista para o topo). Devolve o
        ponto, para quem monta em lotes repor no fim."""
        ponto = self._pos[0]
        for filho in self.dentro.winfo_children():
            filho.destroy()
        if manter:
            self.canvas.after_idle(lambda: self.canvas.yview_moveto(ponto))
        else:
            self.canvas.yview_moveto(0)
        return ponto


# (07/out, pedido dele) Processos do sistema sem app na lista: um nome que
# se le em vez do pacote cortado ("com.samsung.android.a...").
_PROCESSOS = {"system_server": "sistema android", "surfaceflinger": "tela",
              "adbd": "adb", "app_process": "scrcpy-f (no celular)",
              "com.android.systemui": "barra do sistema",
              "com.android.phone": "telefone", "cameraserver": "câmera",
              "audioserver": "áudio", "media.codec": "vídeo (codec)",
              "com.google.android.gms": "serviços do google",
              "com.samsung.android.app.spage": "samsung free",
              "com.sec.android.app.launcher": "tela inicial (one ui)"}
_GENERICAS = {"com", "android", "samsung", "google", "app", "sec", "apps",
              "service", "services", "provider", "mobile", "br", "org", "net"}


def _nome_de_processo(bruto: str) -> str:
    if bruto in _PROCESSOS:
        return _PROCESSOS[bruto]
    if "." not in bruto:
        return bruto
    partes = [p for p in bruto.split(".") if p.lower() not in _GENERICAS]
    return " ".join(partes[-2:]) if partes else bruto.split(".")[-1]


def _gb(n: float) -> str:
    """Bytes em GB, com virgula: 59177504768 -> "55,1 GB"."""
    return ("%.1f GB" % (n / 1024 ** 3)).replace(".", ",")


def _encurtar_caminho(texto: str, n: int) -> str:
    """(r195) Caminho numa linha: tira do MEIO (comeco e pasta final ficam).
    O `_encurtar` de cima corta o FIM (nomes de app)."""
    texto = str(texto)
    if len(texto) <= n:
        return texto
    fim = n * 2 // 3
    return texto[:n - fim - 1] + "…" + texto[-fim:]


def _quando(epoch) -> str:
    """(r195) "conferido hoje às 14:32" / "ontem" / "em 28/09"."""
    try:
        t = float(epoch or 0)
    except (TypeError, ValueError):
        t = 0
    if t <= 0:
        return "ainda não conferido."
    import datetime
    d = datetime.datetime.fromtimestamp(t)
    hoje = datetime.date.today()
    if d.date() == hoje:
        return "conferido hoje às %s." % d.strftime("%H:%M")
    if (hoje - d.date()).days == 1:
        return "conferido ontem às %s." % d.strftime("%H:%M")
    return "conferido em %s." % d.strftime("%d/%m")


def _mb(n: float) -> str:
    """Bytes em MB (ou GB, a partir de 1 GB)."""
    if n >= 1024 ** 3:
        return _gb(n)
    return "%d MB" % round(n / 1024 ** 2)
