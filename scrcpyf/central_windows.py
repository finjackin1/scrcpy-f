"""
AS NOTIFICACOES E O PLAYER DO CELULAR NO WINDOWS (01/out/2026, opcao 2 dele:
"se nao ficar bom vamos de 3").

- NOTIFICACOES NA CENTRAL DO WINDOWS: cada notificacao que da aviso entra
  tambem na Central de Notificacoes (e no historico do Windows), SEM o
  pop-up do Windows (`suppress_popup`) -- o pop-up e o aviso proprio do
  scrcpy-f. Saiu do celular -> sai da Central (pela tag). Clique = o
  protocolo "scrcpyf:" -> o scrcpy-f abre o destino (`app.py --link`).
  O Windows so aceita notificacao de quem tem identidade: o AUMID
  "finjackin.scrcpy-f" registrado em HKCU (nome e icone), sem admin.
- PLAYER NOS CONTROLES DE MIDIA DO WINDOWS: um SystemMediaTransportControls
  proprio (MediaPlayer com o command_manager desligado) com a musica do
  celular, a linha do tempo e os botoes; as teclas de midia do teclado
  chegam aqui quando ele e a sessao atual.

Testado em 01/out (prototipos): a sessao aparece na lista do Windows; a
notificacao entra na Central e sai pela tag. Peca: pywinrt (winrt-*, MIT).
Nada aqui levanta: sem pywinrt ou fora do Windows, `disponivel()` = False.
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import sys
import threading
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger(__name__)

AUMID = "finjackin.scrcpy-f"
GRUPO = "scrcpyf"
PROTOCOLO = "scrcpyf"


def disponivel() -> bool:
    """(08/out, otimizacao: o import do winrt -- asyncio junto -- custava
    ~130 ms na partida) So confere que o pywinrt esta instalado, sem
    importar; o import de verdade vai para uma thread (`aquecer`). Se algo
    faltar la dentro, as classes abaixo falham caladas e anotam (_falhou)."""
    if sys.platform != "win32":
        return False
    try:
        import importlib.util
        return importlib.util.find_spec("winrt") is not None
    except Exception:
        return False


def aquecer() -> None:
    """Importa o winrt fora da partida (thread): a 1a notificacao nao paga."""
    try:
        import winrt.windows.ui.notifications  # noqa: F401
        import winrt.windows.media.playback  # noqa: F401
    except Exception as erro:
        log.info("windows: winrt nao carregou (%s)", erro)


def _escrever(caminho: str, valores: dict) -> bool:
    """HKCU\\<caminho> com os valores (so grava o que mudou). True = mudou."""
    import winreg
    mudou = False
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, caminho) as k:
        for nome, valor in valores.items():
            try:
                atual, _t = winreg.QueryValueEx(k, nome)
            except OSError:
                atual = None
            if atual != valor:
                winreg.SetValueEx(k, nome, 0, winreg.REG_SZ, valor)
                mudou = True
    return mudou


def registrar(icone_png: Path, comando: list[str]) -> bool:
    """
    A identidade do scrcpy-f no Windows (nome e icone na Central) e o
    protocolo "scrcpyf:" (o clique na notificacao abre o scrcpy-f com
    `--link <endereco>`). So HKCU: nada de admin. True = deu certo.
    """
    try:
        _escrever(r"Software\Classes\AppUserModelId\%s" % AUMID,
                  {"DisplayName": "scrcpy-f", "IconUri": str(icone_png)})
        linha = " ".join('"%s"' % c for c in comando) + ' --link "%1"'
        _escrever(r"Software\Classes\%s" % PROTOCOLO,
                  {"": "URL:scrcpy-f", "URL Protocol": ""})
        _escrever(r"Software\Classes\%s\shell\open\command" % PROTOCOLO,
                  {"": linha})
        return True
    except Exception:
        log.exception("windows: registro")
        return False


def etiqueta(chave: str) -> str:
    """A tag da notificacao no Windows (curta: o Windows aceita ate 64)."""
    return hashlib.sha1(chave.encode("utf-8")).hexdigest()[:16]


def endereco(chave: str, app: str, tipo: str = "notif",
             indice: int | None = None) -> str:
    """O endereco que o Windows abre no clique. `tipo`: "notif" (o corpo),
    "acao" (um botao do app, `indice`) ou "responder" (abre a caixa de
    resposta no scrcpy-f)."""
    url = "%s:%s?c=%s&a=%s" % (PROTOCOLO, tipo, quote(chave, safe=""),
                               quote(app, safe=""))
    if indice is not None:
        url += "&i=%d" % indice
    return url


def ler_endereco(url: str) -> tuple[str, str]:
    """"scrcpyf:notif?c=..&a=.." -> (chave, app)."""
    from urllib.parse import parse_qs, urlsplit
    try:
        partes = parse_qs(urlsplit(url).query)
        return (partes.get("c", [""])[0], partes.get("a", [""])[0])
    except Exception:
        return "", ""


def ler_tipo(url: str) -> tuple[str, int | None]:
    """(tipo, indice) do endereco: ("notif", None), ("acao", 2)..."""
    from urllib.parse import parse_qs, urlsplit
    try:
        u = urlsplit(url)
        i = parse_qs(u.query).get("i", [None])[0]
        return (u.path or "notif").strip("/"), (int(i) if i is not None
                                                 else None)
    except Exception:
        return "notif", None


def _xml(texto: str) -> str:
    from xml.sax.saxutils import escape
    return escape(texto or "", {'"': "&quot;"})


class NotificacoesWindows:
    """A Central de Notificacoes do Windows (sem pop-up: o do scrcpy-f ja
    avisa)."""

    def __init__(self, anotar) -> None:
        self.anotar = anotar
        self._trava = threading.Lock()
        self._notificador = None
        self._falhou = False
        # (03/out) as notificacoes mostradas, por chave (para tirar depois).
        # Os botoes vao pelo endereco "scrcpyf:" (ver `_xml_acoes`).
        self._vivas: dict = {}

    def _notif(self):
        if self._notificador is None and not self._falhou:
            try:
                from winrt.windows.ui.notifications import \
                    ToastNotificationManager
                self._notificador = \
                    ToastNotificationManager.create_toast_notifier_with_id(AUMID)
            except Exception as erro:
                self._falhou = True
                self.anotar("windows: sem central de notificacoes (%s)" % erro)
        return self._notificador

    def mostrar(self, chave: str, app: str, nome_app: str, titulo: str,
                texto: str, icone: Path | None, acoes=None,
                rosto: Path | None = None) -> None:
        """`acoes` = [(indice, titulo, com_texto)] (do ouvinte): o primeiro
        com texto vira a caixa "responder" + enviar; os outros, botoes.
        `rosto` = foto de quem mandou (redonda, no lugar do icone)."""
        try:
            from winrt.windows.data.xml.dom import XmlDocument
            from winrt.windows.ui.notifications import ToastNotification
            with self._trava:
                notif = self._notif()
                if notif is None:
                    return
                imagem = ""
                if rosto is not None and Path(rosto).exists():
                    imagem = ('<image placement="appLogoOverride" '
                              'hint-crop="circle" src="%s"/>'
                              % _xml(Path(rosto).as_uri()))
                elif icone is not None and Path(icone).exists():
                    imagem = ('<image placement="appLogoOverride" '
                              'src="%s"/>' % _xml(Path(icone).as_uri()))
                botoes = self._xml_acoes(acoes or [], chave, app)
                doc = XmlDocument()
                doc.load_xml(
                    '<toast launch="%s" activationType="protocol">'
                    '<visual><binding template="ToastGeneric">'
                    '<text>%s</text><text>%s</text>'
                    '<text placement="attribution">%s</text>%s'
                    '</binding></visual>%s<audio silent="true"/></toast>'
                    % (_xml(endereco(chave, app)),
                       _xml((titulo or nome_app)[:120]),
                       _xml((texto or "")[:400]), _xml(nome_app), imagem,
                       botoes))
                t = ToastNotification(doc)
                t.tag = etiqueta(chave)
                t.group = GRUPO
                t.suppress_popup = True
                self._soltar(chave)
                self._vivas[chave] = (t, None)
                notif.show(t)
        except Exception as erro:
            log.warning("windows: notificacao (%s)", erro)

    @staticmethod
    def _xml_acoes(acoes, chave: str, app: str) -> str:
        """
        (03/out, relato dele: "marcar como lida nao faz nada" na Central)
        Os botoes com ativacao "foreground" dependem de um evento que o
        Windows NAO entrega a programa sem instalacao (sem COM registrado):
        o clique se perdia. Agora TODO botao e um endereco "scrcpyf:" -- o
        mesmo caminho do clique no corpo, que funciona: o Windows abre o
        scrcpy-f, que repassa o pedido ao que ja esta aberto. Por esse
        caminho o Windows nao manda texto digitado: o "responder" vira um
        botao que abre a caixa de resposta no proprio scrcpy-f.
        """
        partes = []
        resposta = next((a for a in acoes if a[2]), None)
        if resposta is not None:
            partes.append('<action content="%s" arguments="%s" '
                          'activationType="protocol"/>'
                          % (_xml(resposta[1].lower()[:30]),
                             _xml(endereco(chave, app, "responder",
                                           resposta[0]))))
        for indice, titulo, com_texto in acoes:
            if not com_texto and len(partes) < 5:
                partes.append('<action content="%s" arguments="%s" '
                              'activationType="protocol"/>'
                              % (_xml(titulo.lower()[:30]),
                                 _xml(endereco(chave, app, "acao", indice))))
        return "<actions>%s</actions>" % "".join(partes) if partes else ""

    def _soltar(self, chave: str) -> None:
        viva = self._vivas.pop(chave, None)
        if viva is not None and viva[1] is not None:
            try:
                viva[0].remove_activated(viva[1])
            except Exception:
                pass

    def remover(self, chave: str) -> None:
        with self._trava:
            self._soltar(chave)
        try:
            from winrt.windows.ui.notifications import ToastNotificationManager
            ToastNotificationManager.history.remove_grouped_tag_with_id(
                etiqueta(chave), GRUPO, AUMID)
        except Exception as erro:
            log.debug("windows: remover (%s)", erro)

    def limpar(self) -> None:
        with self._trava:
            for chave in list(self._vivas):
                self._soltar(chave)
        try:
            from winrt.windows.ui.notifications import ToastNotificationManager
            ToastNotificationManager.history.clear_with_id(AUMID)
        except Exception as erro:
            log.debug("windows: limpar (%s)", erro)


class PlayerWindows:
    """A musica do celular nos controles de midia do Windows. `ao_botao`
    recebe ("play"|"pause"|"next"|"previous"|"seek", ms) -- de uma thread
    do Windows."""

    def __init__(self, ao_botao, anotar) -> None:
        self.ao_botao = ao_botao
        self.anotar = anotar
        self._trava = threading.Lock()
        self._mp = None
        self._smtc = None
        self._mostrado = None          # o que esta no Windows (sem posicao)
        self._falhou = False

    def _criar(self):
        if self._smtc is not None or self._falhou:
            return self._smtc
        try:
            from winrt.windows.media.playback import MediaPlayer
            self._mp = MediaPlayer()
            self._mp.command_manager.is_enabled = False
            s = self._mp.system_media_transport_controls
            s.is_play_enabled = s.is_pause_enabled = True
            s.is_next_enabled = s.is_previous_enabled = True
            s.add_button_pressed(self._apertou)
            s.add_playback_position_change_requested(self._pulou)
            self._smtc = s
        except Exception as erro:
            self._falhou = True
            self.anotar("windows: sem controles de midia (%s)" % erro)
        return self._smtc

    def _apertou(self, _s, args) -> None:
        try:
            from winrt.windows.media import SystemMediaTransportControlsButton as B
            acao = {B.PLAY: "play", B.PAUSE: "pause", B.NEXT: "next",
                    B.PREVIOUS: "previous"}.get(args.button)
            if acao:
                self.ao_botao(acao, 0)
        except Exception:
            log.exception("windows: botao de midia")

    def _pulou(self, _s, args) -> None:
        try:
            pos = args.requested_playback_position
            self.ao_botao("seek", int(pos.total_seconds() * 1000))
        except Exception:
            log.exception("windows: pular trecho")

    def atualizar(self, m: dict | None, posicao_ms: int, nome_app: str,
                  icone: Path | None) -> None:
        """A sessao `m` (de notificacoes.Central.player) no Windows; None =
        some dos controles."""
        try:
            from winrt.windows.media import (
                MediaPlaybackStatus, MediaPlaybackType,
                SystemMediaTransportControlsTimelineProperties)
            with self._trava:
                if m is None:
                    if self._smtc is not None and self._mostrado is not None:
                        self._smtc.is_enabled = False
                        self._mostrado = None
                    return
                s = self._criar()
                if s is None:
                    return
                # (02/out) a imagem entra: a capa chega depois do titulo
                ident = (m["pacote"], m["titulo"], m["artista"], m["album"],
                         str(icone))
                if ident != self._mostrado:
                    du = s.display_updater
                    du.type = MediaPlaybackType.MUSIC
                    du.music_properties.title = m["titulo"] or nome_app
                    du.music_properties.artist = m["artista"] or ""
                    du.music_properties.album_title = m["album"] or ""
                    if icone is not None and Path(icone).exists():
                        # (02/out, testado) Pelo ARQUIVO (StorageFile): pelo
                        # endereco file:// o Windows deixava a imagem vazia.
                        try:
                            import asyncio
                            from winrt.windows.storage import StorageFile
                            from winrt.windows.storage.streams import \
                                RandomAccessStreamReference

                            async def abrir(caminho):
                                return await StorageFile \
                                    .get_file_from_path_async(caminho)
                            arquivo = asyncio.run(abrir(
                                str(Path(icone).resolve())))
                            du.thumbnail = RandomAccessStreamReference \
                                .create_from_file(arquivo)
                        except Exception as erro:
                            log.warning("windows: imagem do player (%s)",
                                        erro)
                    du.update()
                    s.is_enabled = True
                    self._mostrado = ident
                s.playback_status = {
                    3: MediaPlaybackStatus.PLAYING,
                    2: MediaPlaybackStatus.PAUSED,
                    1: MediaPlaybackStatus.STOPPED,
                }.get(m["estado"], MediaPlaybackStatus.CHANGING)
                if m["dur"] > 0:
                    tl = SystemMediaTransportControlsTimelineProperties()
                    fim = datetime.timedelta(milliseconds=m["dur"])
                    tl.start_time = tl.min_seek_time = datetime.timedelta(0)
                    tl.end_time = tl.max_seek_time = fim
                    tl.position = datetime.timedelta(
                        milliseconds=max(0, min(posicao_ms, m["dur"])))
                    s.update_timeline_properties(tl)
        except Exception as erro:
            log.warning("windows: player (%s)", erro)

    def encerrar(self) -> None:
        with self._trava:
            if self._smtc is not None:
                try:
                    self._smtc.is_enabled = False
                except Exception:
                    pass
