"""
O `config.json`: onde esta o scrcpy, qual endereco tentar de reserva, e o que
cada PERFIL manda pro scrcpy.

O QUE E UM PERFIL
-----------------
Um perfil e um jeito de usar o celular. Nascem dois:

    jogo    espelha a tela no PC, com a tela do celular apagada
    audio   manda so o som do celular pro PC, sem imagem

Os dois tem exatamente os MESMOS campos -- o que muda e o valor. O modo audio
e simplesmente um perfil com `video.ligado = false`. Isso e de proposito: um
montador de linha de comando so serve os dois, e criar um perfil novo depois
("so espelhar, sem apagar a tela") nao exige codigo nenhum.

POR QUE TUDO EM DICIONARIO E NAO EM ATRIBUTO NOMEADO
-----------------------------------------------------
Cada opcao nova do scrcpy entra sem mexer nesta classe, e o arquivo continua
sendo um JSON simples de ler e editar a mao. Quem sabe o que cada campo
significa e o `sessao.py`, que e quem monta a linha de comando. Este modulo so
guarda e devolve.

CAMPO QUE FALTA NAO E CAMPO ERRADO
-----------------------------------
O que vem do disco e MESCLADO sobre o padrao, campo a campo. Um config gravado
por uma versao mais velha nao quebra na mais nova: ganha os campos que
surgiram, com o valor de fabrica. E um campo estranho no arquivo e ignorado em
silencio em vez de derrubar o programa.

ATALHO VAZIO NAO E O MESMO QUE SEM ATALHO
------------------------------------------
`atalhos` nasce vazio de proposito: o programa nao chega com tecla nenhuma
tomada. Uma acao com combinacao "" quer dizer "esta na lista, faltando as
teclas"; acao que nao esta no dicionario nao tem atalho e nao tenta registrar
nada.
"""

from __future__ import annotations

import json
import logging
import threading

from . import caminhos

log = logging.getLogger(__name__)

ARQUIVO = "config.json"

# Duas threads gravam o config: a da janela (a pessoa mexeu num ajuste) e a da
# partida (o celular respondeu num endereco novo). Sem a trava, duas gravacoes
# no mesmo instante poderiam intercalar e deixar um arquivo pela metade.
_TRAVA_DE_GRAVACAO = threading.Lock()

# As opcoes liga/desliga do programa, com o valor de fabrica. So as que estao
# aqui existem: nome desconhecido no arquivo e ignorado.
OPCOES_DE_FABRICA = {
    # A janela abre junto com o programa, ou ele nasce so na bandeja.
    # (r171) De fabrica LIGADA (pedido dele, 25/set/2026: na primeira vez,
    # so notificacoes e mostrar a janela ligadas; o resto desligado).
    "abrir_janela_ao_iniciar": True,
    # (08/out, pedido dele) copiar/colar entre PC e celular, de fabrica ligado
    "area_compartilhada": True,
    # Avisos do Windows ao ligar, desligar e cair (pedido dele, 20/set/2026:
    # opcao para ligar e desligar as notificacoes).
    "notificacoes": True,
    # (r161) O aviso "atalho criado" (pedido dele, 25/set/2026: opcao para
    # desligar). So vale com as notificacoes ligadas.
    "aviso_atalho": False,               # (r171) de fabrica desligado
    # (01/out) Notificacoes do celular no PC: a chave GERAL (o padrao de
    # todos os apps; cada app pode ser excecao em apps["notif"]).
    "notif_pc": True,
    # (01/out) No Windows: as notificacoes tambem na Central de Notificacoes
    # e o player nos controles de midia (central_windows).
    "notif_windows": True,
    "player_windows": True,
}

# Os dois arquivos soltos da versao de scripts. Existem so para a migracao da
# primeira execucao -- depois dela, quem manda e o config.json.
ARQUIVO_CAMINHO_ANTIGO = "caminho-scrcpy.txt"
ARQUIVO_IP_ANTIGO = "phone_ip.txt"


# Um perfil completo, com todos os campos que o `sessao.py` sabe montar.
# Serve de gabarito: e a partir daqui que o merge preenche o que falta.
PERFIL_BASE = {
    "titulo": "Celular",
    # So o espelhar usa: "ambos", "som" ou "imagem" (vazio = decide pelo
    # som ligado). Estava fora do gabarito e o merge o jogava fora ao abrir
    # (achado em 23/set/2026).
    "conteudo": "",
    # A predefinicao de qualidade deste modo; vazio = a de OPCOES.
    "predef": "",
    "video": {
        "ligado": True,
        "codec": "h264",          # h264, h265 ou av1
        "bitrate": "8M",          # = nivel "Padrao" do qualidade.py
        "fps_max": 60,
        "resolucao_max": 1280,    # 0 = a do celular; 1024 = lado maior em 1024
        "buffer_ms": 0,           # 0 = latencia minima; sobe se a imagem picotar
    },
    "audio": {
        "ligado": True,
        "codec": "opus",          # opus, aac, flac ou raw
        "bitrate": "128K",
        "buffer_ms": 50,
        "fonte": "output",        # output = som do celular; mic = microfone
        "duplicar": False,        # True = toca no PC E no celular (Android 13+)
        "exigir": False,          # True = nao sobe sem audio, em vez de subir mudo
    },
    "janela": {
        "tela_cheia": False,
        "sem_borda": False,
        "sempre_no_topo": False,
    },
    "controle": {
        "teclado_mouse": True,    # teclado e mouse do PC controlam o celular
        "joystick": False,        # controle plugado no PC vira controle do celular
    },
    "sessao": {
        "apagar_tela": True,           # apaga a tela do celular durante a sessao
        "tempo_tela_s": 86400,         # tempo de tela do celular enquanto durar
        "sem_protetor_de_tela": True,  # nao deixa o PC apagar a tela sozinho
        "gravar_em": "",               # caminho de arquivo; vazio = nao grava
    },
    # So o perfil "extensao" usa: onde o celular fica em relacao aos monitores
    # (ver `monitores.py`). Monitor vazio = o lado direito do mais a direita.
    "borda": {
        "monitor": "",
        "lado": "direita",
        "centro": 0.5,
        "tamanho": 0.5,
    },
}


def _mesclar(padrao, dados):
    """
    Devolve o padrao com o que veio do disco por cima, sem alterar nenhum dos
    dois. Desce nos dicionarios; qualquer outro valor e substituido inteiro.
    """
    if not isinstance(dados, dict):
        return json.loads(json.dumps(padrao))
    saida = {}
    for chave, valor in padrao.items():
        if isinstance(valor, dict):
            saida[chave] = _mesclar(valor, dados.get(chave))
        elif chave in dados:
            saida[chave] = dados[chave]
        else:
            saida[chave] = valor
    return saida


def perfis_de_fabrica() -> dict:
    """Os dois perfis que o programa cria quando nao ha config nenhum."""
    jogo = _mesclar(PERFIL_BASE, {"titulo": "Celular - jogo"})

    # O perfil de audio e o mesmo gabarito com a imagem desligada. `exigir`
    # ligado porque aqui o som e o unico conteudo: subir mudo seria uma sessao
    # que nao serve pra nada, e ninguem perceberia de cara.
    audio = _mesclar(PERFIL_BASE, {
        "titulo": "Celular - audio",
        "video": {"ligado": False},
        "audio": {"exigir": True},
        "controle": {"teclado_mouse": False},
        # No modo audio o programa nao encosta na tela do celular: quem esta
        # jogando no aparelho e quem decide quando ela apaga.
        "sessao": {"apagar_tela": False, "tempo_tela_s": 0,
                   "sem_protetor_de_tela": False},
    })
    # A EXTENSAO (a "borda", 18/set/2026): sem imagem, com mouse, teclado e
    # controle do PC virando aparelhos "de verdade" no celular, e o som junto.
    # A tela do celular segue normal -- ele esta sendo usado, nao espelhado.
    extensao = _mesclar(PERFIL_BASE, {
        "titulo": "scrcpy-f extensao",
        "video": {"ligado": False},
        # Som da extensao (pedido dele, 21/set/2026): Opus, 128 kb/s e 50 ms
        # de atraso. Jogando NO celular, 20 ms estalava; 50 e o equilibrio.
        "audio": {"codec": "opus", "bitrate": "128K", "buffer_ms": 50},
        "controle": {"teclado_mouse": True, "joystick": True},
        "sessao": {"apagar_tela": False, "tempo_tela_s": 0,
                   "sem_protetor_de_tela": False},
    })
    return {"jogo": jogo, "audio": audio, "extensao": extensao}


class Config:
    """O que o programa guarda em disco."""

    def __init__(self, scrcpy: str = "", ip_reserva: str = "",
                 perfis: dict | None = None, atalhos: dict | None = None,
                 opcoes: dict | None = None, apps: dict | None = None,
                 qualidade: dict | None = None) -> None:
        self.scrcpy = scrcpy
        self.ip_reserva = ip_reserva
        self.atalhos: dict = dict(atalhos or {})
        self.opcoes: dict = dict(opcoes or {})
        # APPS EM JANELA PROPRIA: "visual" (grade/lista), "nivel" e "som"
        # (valem para todos), "por_app" {pacote: {"nivel", "som"}} e "nomes"
        # {pacote: nome} -- o nome que o atalho de um app mostra.
        self.apps: dict = dict(apps or {})
        # (09/out) o "tamanho nos apps" (dpi) ia para apps["tamanho"], a
        # mesma chave do tamanho dos icones da lista (p/m/g): agora "escala"
        if self.apps.get("tamanho") in ("menor", "maior", "bem_maior"):
            self.apps["escala"] = self.apps.pop("tamanho")
        elif self.apps.get("tamanho") == "normal":
            self.apps.pop("tamanho")
        # QUALIDADE UNICA (23/set/2026): ver `qualidade.py`, fim do arquivo.
        from . import qualidade as _q
        base_q = _q.qualidade_de_fabrica()
        if isinstance(qualidade, dict):
            base_q.update({k: v for k, v in qualidade.items()
                           if k in base_q})
        self.qualidade: dict = base_q

        # True quando o config.json existe mas nao deu para ler. Nesse estado
        # o programa roda com o de fabrica e NAO GRAVA NADA: gravar seria
        # apagar o arquivo da pessoa (pasta do scrcpy, perfis, atalhos) com o
        # de fabrica, por causa de uma virgula sobrando.
        self.ilegivel = False

        # True so na PRIMEIRA execucao de todas (nao havia config.json). E o
        # unico caso em que a janela aparece sem a pessoa ter pedido -- sem
        # isso ela nao teria como apontar a pasta do scrcpy.
        self.novo = False

        # Cada perfil passa pelo gabarito: assim, mesmo um config editado a mao
        # com metade dos campos vira um perfil completo aqui dentro.
        base = perfis_de_fabrica()
        if perfis:
            self.perfis = {nome: _mesclar(PERFIL_BASE, dados)
                           for nome, dados in perfis.items()}
            for nome, dados in base.items():
                self.perfis.setdefault(nome, dados)
        else:
            self.perfis = base

    # -- leitura -------------------------------------------------------------

    def perfil(self, nome: str) -> dict:
        """Um perfil pelo nome. Cai no gabarito se o nome nao existir."""
        return self.perfis.get(nome) or _mesclar(PERFIL_BASE, {})

    # Reserva: uma pasta "scrcpy" ao lado do programa vale mesmo sem estar
    # no config. (O pacote publicado NAO leva mais o scrcpy -- quem aponta a
    # pasta e o Configurar --, mas quem quiser pode deixar uma ali.)
    PASTA_SCRCPY_JUNTO = "scrcpy"

    @property
    def pasta_scrcpy(self):
        """
        Onde estao o scrcpy.exe e o adb.exe: a pasta do config, se ela tiver
        os dois; senao a que veio junto no pacote, se houver. O config nunca
        e reescrito por isso -- quem apontou uma pasta continua com a dela.
        """
        from pathlib import Path
        if self.scrcpy and (Path(self.scrcpy) / "scrcpy.exe").exists():
            return Path(self.scrcpy)
        junto = caminhos.arquivo(self.PASTA_SCRCPY_JUNTO)
        if (junto / "scrcpy.exe").exists():
            return junto
        return Path(self.scrcpy) if self.scrcpy else None

    @property
    def adb_exe(self):
        pasta = self.pasta_scrcpy
        return pasta / "adb.exe" if pasta else None

    @property
    def scrcpy_exe(self):
        pasta = self.pasta_scrcpy
        return pasta / "scrcpy.exe" if pasta else None

    @property
    def instalacao_ok(self) -> bool:
        """Os dois executaveis estao onde o config diz?"""
        adb, scr = self.adb_exe, self.scrcpy_exe
        return bool(adb and scr and adb.exists() and scr.exists())

    @classmethod
    def carregar(cls) -> "Config":
        """
        Le o config. Nunca levanta excecao: arquivo ilegivel vira config de
        fabrica, e o programa abre dizendo o que falta em vez de nao abrir.
        """
        caminho = caminhos.arquivo(ARQUIVO)
        if caminho.exists():
            try:
                dados = json.loads(caminho.read_text(encoding="utf-8"))
                return cls(
                    scrcpy=dados.get("scrcpy", ""),
                    ip_reserva=dados.get("ip_reserva", ""),
                    perfis=dados.get("perfis") or None,
                    atalhos=dados.get("atalhos") or {},
                    opcoes=dados.get("opcoes") or {},
                    apps=dados.get("apps") or {},
                    qualidade=dados.get("qualidade"),
                )._zerar_se_versao_velha("qualidade" not in dados)
            except Exception as erro:
                log.warning("%s ilegivel (%s); usando o de fabrica, sem gravar",
                            ARQUIVO, erro)
                config = cls()
                config.ilegivel = True
                return config

        config = cls._dos_arquivos_antigos()
        config.novo = True
        # (07/out, pedido dele) primeiro uso: som no PC em todos os modos
        # (espelhar e extensao ja nascem assim; apps nascia no celular).
        # Qualidade: a "equilibrado" de cada conexao (ver qualidade.py).
        config.apps.setdefault("onde", "pc")
        config.gravar()
        return config

    @classmethod
    def _dos_arquivos_antigos(cls) -> "Config":
        """
        Aproveita o `caminho-scrcpy.txt` e o `phone_ip.txt` da versao de
        scripts. Sem isso, quem ja usava teria que reapontar a pasta do scrcpy
        a mao so porque o programa mudou de forma.
        """
        scrcpy = _primeira_linha(ARQUIVO_CAMINHO_ANTIGO)
        ip = _primeira_linha(ARQUIVO_IP_ANTIGO)
        if scrcpy or ip:
            log.info("config criado a partir dos arquivos da versao antiga")
        return cls(scrcpy=scrcpy, ip_reserva=ip)

    # -- escrita -------------------------------------------------------------

    def gravar(self) -> bool:
        """
        Grava o config. Devolve se conseguiu.

        Falhar aqui nao pode derrubar o programa: pasta somente leitura
        significa perder o que ele acabou de escolher, e nada mais.
        """
        if self.ilegivel:
            log.warning("nao gravei: o %s original esta ilegivel e seria "
                        "perdido", ARQUIVO)
            return False
        try:
            with _TRAVA_DE_GRAVACAO:
                for tentativa in range(3):
                    try:
                        self._gravar_sem_trava()
                        break
                    except RuntimeError:
                        # (r138) Outra thread (lista de apps, endereco do
                        # celular) mexeu no config no meio da leitura --
                        # "changed size during iteration". Na hora seguinte
                        # ja esta quieto: tenta de novo em vez de perder.
                        if tentativa == 2:
                            raise
                        threading.Event().wait(0.01)
            return True
        except Exception as erro:
            log.warning("nao consegui gravar o %s: %s", ARQUIVO, erro)
            return False

    def _gravar_sem_trava(self) -> None:
        """
        Escreve num arquivo ao lado e so entao troca pelo de verdade.

        Escrever direto por cima deixaria, numa queda de energia no meio, um
        config pela metade -- e config ilegivel vira config de fabrica, que e
        perder tudo o que foi ajustado. `replace` troca de uma vez so.
        """
        destino = caminhos.arquivo(ARQUIVO)
        provisorio = destino.with_name(destino.name + ".novo")
        provisorio.write_text(
            json.dumps(
                {
                    "scrcpy": self.scrcpy,
                    "ip_reserva": self.ip_reserva,
                    "perfis": self.perfis,
                    "atalhos": self.atalhos,
                    "opcoes": self.opcoes,
                    "apps": self.apps,
                    "qualidade": self.qualidade,
                },
                indent=2, ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )
        provisorio.replace(destino)

    def _zerar_se_versao_velha(self, velha: bool) -> "Config":
        """
        REORGANIZACAO DE 23/set/2026 (pedido dele: "todas configs que fiz
        voltam ao padrao"). Na primeira abertura com a qualidade unica, os
        ajustes de qualidade e de som que existiam em cada lugar saem: a
        qualidade nasce "equilibrado" e cada modo volta ao de fabrica no
        som. Pasta do scrcpy, celular, atalhos e a marca da extensao ficam.
        """
        if not velha:
            return self
        for campo in ("nivel", "nivel_som", "som", "video_fino",
                      "audio_fino", "por_app", "abertos_na_lista",
                      "abertos_no_rodape"):
            self.apps.pop(campo, None)
        fabrica = perfis_de_fabrica()
        for nome in ("jogo", "extensao", "audio"):
            if nome in self.perfis and nome in fabrica:
                self.perfis[nome]["video"] = dict(
                    fabrica[nome]["video"])
                self.perfis[nome]["audio"] = dict(
                    fabrica[nome]["audio"])
        log.info("config de versao velha: qualidade e som zerados")
        self.gravar()
        return self

    # -- qualidade unica -------------------------------------------------------

    # (r196) Tudo por CONEXAO ("sem_fio" = o `qualidade` de sempre, "cabo" =
    # `qualidade["cabo"]`); ver `qualidade.conjunto`.

    def _conj(self, conexao: str) -> dict:
        from . import qualidade as _q
        return _q.conjunto(self.qualidade, conexao)

    def definir_qualidade(self, secao: str, campo: str, valor,
                          conexao: str = "sem_fio") -> bool:
        """Uma fileira de OPCOES > qualidade. Com uma predefinicao DELE
        escolhida, grava nela tambem; com uma fixa, deixa de estar nela."""
        q = self._conj(conexao)
        q.setdefault(secao, {})[campo] = valor
        minha = self._minha(q.get("escolhida"))
        if minha is not None:
            minha.setdefault(secao, {})[campo] = valor
        else:
            q["escolhida"] = None
        return self.gravar()

    def escolher_predef(self, ident: str) -> bool:
        """A escolhida do conjunto a que a predefinicao pertence."""
        from . import qualidade as _q
        video, audio = _q.valores_da_predef(self.qualidade, ident)
        conexao = _q.conexao_da_predef(self.qualidade, ident)
        if video is None or conexao is None:
            return False
        q = self._conj(conexao)
        q["video"] = dict(video)
        q["audio"] = dict(audio)
        q["escolhida"] = ident
        return self.gravar()

    def _minha(self, ident):
        """A predefinicao DELE com esse id, de qualquer conjunto."""
        from . import qualidade as _q
        for con in _q.CONEXOES:
            for m in self._conj(con).get("minhas") or []:
                if isinstance(m, dict) and m.get("id") == ident:
                    return m
        return None

    def criar_predef(self, conexao: str = "sem_fio") -> str | None:
        """Salva a qualidade de agora (do conjunto da `conexao`) como
        predefinicao dele (max. 3 por conexao)."""
        from . import qualidade as _q
        q = self._conj(conexao)
        minhas = q.setdefault("minhas", [])
        if len(minhas) >= _q.MAX_MINHAS:
            return None
        letra = "c" if conexao == "cabo" else "p"
        usados = {m.get("id") for m in minhas}
        ident = next("%s%d" % (letra, i) for i in range(1, 10)
                     if "%s%d" % (letra, i) not in usados)
        nomes = {m.get("nome") for m in minhas}
        nome = next("minha %d" % i for i in range(1, 10)
                    if "minha %d" % i not in nomes)
        minhas.append({"id": ident, "nome": nome,
                       "video": dict(q.get("video") or {}),
                       "audio": dict(q.get("audio") or {})})
        q["escolhida"] = ident
        self.gravar()
        return ident

    def renomear_predef(self, ident: str, nome: str) -> bool:
        m = self._minha(ident)
        nome = " ".join(str(nome).split())[:18]
        if m is None or not nome:
            return False
        m["nome"] = nome
        return self.gravar()

    def apagar_predef(self, ident: str) -> bool:
        from . import qualidade as _q
        for con in _q.CONEXOES:
            q = self._conj(con)
            minhas = q.get("minhas") or []
            q["minhas"] = [m for m in minhas if m.get("id") != ident]
            if q.get("escolhida") == ident:
                q["escolhida"] = None
        # Modos e apps que usavam essa predefinicao voltam ao padrao (nas
        # duas chaves: "predef" = sem fio, "predef_cabo" = cabo).
        for dono in list(self.perfis.values()) + list(
                (self.apps.get("por_app") or {}).values()):
            if isinstance(dono, dict):
                for chave in _q.CHAVES_PREDEF.values():
                    if dono.get(chave) == ident:
                        dono.pop(chave, None)
        return self.gravar()

    # -- opcoes --------------------------------------------------------------

    def opcao(self, nome: str) -> bool:
        """Uma opcao liga/desliga, caindo no valor de fabrica."""
        if nome in self.opcoes:
            return bool(self.opcoes[nome])
        return bool(OPCOES_DE_FABRICA.get(nome, False))

    def definir_opcao(self, nome: str, ligado: bool) -> bool:
        """Grava na hora, nao ao fechar."""
        self.opcoes[nome] = bool(ligado)
        return self.gravar()

    # (07/out, pedido dele) OS INDICADORES DO RODAPE (som e conexao) nao
    # respondem ao clique de fabrica; em OPCOES > geral cada gesto (clique,
    # segurar, rodinha) pode ganhar uma funcao DO PROPRIO indicador.
    # Guardado em opcoes["indicadores"] = {"som": {"clique": "trocar"}, ...}.

    def gesto(self, indicador: str, gesto: str) -> str:
        tudo = self.opcoes.get("indicadores") or {}
        return str((tudo.get(indicador) or {}).get(gesto) or "")

    def definir_gesto(self, indicador: str, gesto: str, funcao: str) -> bool:
        tudo = dict(self.opcoes.get("indicadores") or {})
        este = dict(tudo.get(indicador) or {})
        if funcao:
            este[gesto] = funcao
        else:
            este.pop(gesto, None)
        if este:
            tudo[indicador] = este
        else:
            tudo.pop(indicador, None)
        if tudo:
            self.opcoes["indicadores"] = tudo
        else:
            self.opcoes.pop("indicadores", None)
        return self.gravar()

    def definir_atalho(self, acao: str, teclas: str) -> bool:
        """Grava a combinacao de uma acao. Grava na hora, nao ao fechar."""
        self.atalhos[acao] = teclas or ""
        return self.gravar()

    def remover_atalho(self, acao: str) -> bool:
        """Tira a acao da lista de atalhos por completo."""
        self.atalhos.pop(acao, None)
        return self.gravar()

    # -- apps em janela propria ---------------------------------------------

    def app(self, pacote: str) -> dict:
        """Os ajustes de UM app (so leitura; vazio = segue o de todos)."""
        return dict((self.apps.get("por_app") or {}).get(pacote) or {})

    def definir_app(self, pacote: str, campo: str, valor) -> bool:
        """Grava um ajuste de um app; valor vazio volta ao de todos."""
        por = self.apps.setdefault("por_app", {})
        conf = por.setdefault(pacote, {})
        if valor in (None, ""):
            conf.pop(campo, None)
        else:
            conf[campo] = valor
        if not conf:
            por.pop(pacote, None)
        return self.gravar()

    # FIXADOS E RECENTES (pedido dele, 23/set/2026): a lista de apps tem
    # "fixados" (na ordem em que ele fixou), "recentes" e "todos os apps".
    RECENTES_GUARDADOS = 12

    def fixados(self) -> list:
        return [p for p in (self.apps.get("fixados") or []) if isinstance(p, str)]

    def fixar(self, pacote: str, sim: bool) -> bool:
        lista = [p for p in self.fixados() if p != pacote]
        if sim:
            lista.append(pacote)
        if lista:
            self.apps["fixados"] = lista
        else:
            self.apps.pop("fixados", None)
        return self.gravar()

    def recentes(self) -> list:
        return [p for p in (self.apps.get("recentes") or [])
                if isinstance(p, str)]

    def lembrar_recente(self, pacote: str) -> bool:
        lista = [p for p in self.recentes() if p != pacote]
        lista.insert(0, pacote)
        self.apps["recentes"] = lista[:self.RECENTES_GUARDADOS]
        return self.gravar()

    def personalizados(self) -> list:
        """Os pacotes com algum ajuste proprio (a aba "personalizados")."""
        return [p for p, conf in (self.apps.get("por_app") or {}).items()
                if any(v not in (None, "", {}, [])
                       for v in (conf or {}).values())]

    def limpar_app(self, pacote: str) -> bool:
        """Volta o app inteiro ao de todos."""
        (self.apps.get("por_app") or {}).pop(pacote, None)
        return self.gravar()

    def definir_apps(self, campo: str, valor) -> bool:
        """Grava um ajuste que vale para todos os apps."""
        if valor in (None, ""):
            self.apps.pop(campo, None)
        else:
            self.apps[campo] = valor
        return self.gravar()

    # NOTIFICACOES DO CELULAR NO PC (01/out/2026, pedido dele): a geral e o
    # padrao; apps["notif"] = {app: True/False} sao as excecoes. Virar a
    # geral e "ativar todos / desativar todos": as excecoes saem.

    def notif_do_app(self, app: str) -> bool:
        excecoes = self.apps.get("notif") or {}
        if app in excecoes:
            return bool(excecoes[app])
        return self.opcao("notif_pc")

    def definir_notif_app(self, app: str, ligado: bool) -> bool:
        excecoes = self.apps.setdefault("notif", {})
        if bool(ligado) == self.opcao("notif_pc"):
            excecoes.pop(app, None)          # igual a geral: nao e excecao
        else:
            excecoes[app] = bool(ligado)
        if not excecoes:
            self.apps.pop("notif", None)
        return self.gravar()

    def definir_notif_geral(self, ligado: bool) -> bool:
        self.opcoes["notif_pc"] = bool(ligado)
        self.apps.pop("notif", None)
        return self.gravar()

    def lembrar_ip(self, ip: str) -> None:
        """Guarda o endereco em que o celular respondeu, se for outro."""
        if ip and ip != self.ip_reserva:
            log.info("endereco de reserva: %s -> %s",
                     self.ip_reserva or "(nenhum)", ip)
            self.ip_reserva = ip
            self.gravar()


def _primeira_linha(nome: str) -> str:
    """A primeira linha util de um arquivo ao lado do programa, ou vazio."""
    try:
        caminho = caminhos.arquivo(nome)
        if not caminho.exists():
            return ""
        for linha in caminho.read_text(encoding="utf-8", errors="ignore").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#"):
                return linha
    except Exception:
        pass
    return ""
