"""
Icone na bandeja do sistema, com menu.

DIFERENTE DA BANDEJA DO LIGHTWIRELESS
--------------------------------------
La sao dois gestos e nenhum menu -- pedido dele, e que obrigou a reescrever um
metodo interno da pystray para receber os cliques. Aqui ha DUAS acoes que
convivem (espelhar e ouvir), e um clique so nao da conta das duas. Entao aqui
vale o menu normal da biblioteca: caminho suportado, sem gambiarra para
quebrar numa atualizacao.

CUIDADO COM THREADS
-------------------
A pystray roda o icone na thread dela. Nada neste arquivo liga ou desliga
sessao: o clique so EMPILHA um pedido, e o laco do programa atende na thread
certa. E a mesma disciplina da bandeja do LightWireless, e e ela que deixa a
janela (Tkinter, na thread principal) conviver com a bandeja sem sustos.

Sem a pystray instalada, o programa continua de pe -- so sem bandeja. Por isso
`disponivel` existe: e um recurso a mais, nao um requisito.
"""

from __future__ import annotations

import logging
import threading

from . import VERSAO, icone

log = logging.getLogger(__name__)

TITULO = "scrcpy-f %s" % VERSAO

# O que cada estado escreve ao parar o mouse sobre o icone.
DICA = {
    "parado": "scrcpy-f - parado",
    "jogo": "scrcpy-f - espelhando",
    "audio": "scrcpy-f - som do celular no PC",
    "extensao": "scrcpy-f - extensao (borda) ligada",
}


class Bandeja:
    """
    Uso:
        bandeja = Bandeja(programa)
        if bandeja.disponivel:
            bandeja.iniciar()
    """

    def __init__(self, programa) -> None:
        self.programa = programa
        self._icone = None
        self._thread: threading.Thread | None = None
        self._estado = "parado"
        self.disponivel = self._checar()

    @staticmethod
    def _checar() -> bool:
        try:
            import PIL  # noqa: F401
            import pystray  # noqa: F401
            return True
        except Exception:
            # Nao so ImportError: a pystray escolhe o "motor" dela na hora do
            # import e, sem nenhum disponivel, levanta outro tipo de erro.
            return False

    # -- o menu --------------------------------------------------------------

    def _montar_menu(self):
        """
        O menu, com o texto de cada item calculado na hora de abrir.

        Os rotulos sao funcoes de proposito: assim o item diz "Parar o
        espelhamento" quando ele esta no ar e "Espelhar a tela" quando nao
        esta, sem precisar remontar o menu a cada mudanca.
        """
        import pystray

        def rotulo(nome, parado, rodando, ligando):
            def texto(_item):
                if self.programa.ocupado(nome):
                    return ligando
                return rodando if self.programa.ativo(nome) else parado
            return texto

        def pedir(nome):
            return lambda _icone, _item: self.programa.pedidos.put(nome)

        return pystray.Menu(
            # Item padrao: e o que o clique no icone dispara. Era o
            # espelhamento ate a v0.3.0; ele pediu (18/set/2026) que o clique
            # abra a janela, e o espelhamento ficou no menu e no atalho.
            pystray.MenuItem("Abrir a janela", pedir("mostrar"), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                rotulo("jogo", "Espelhar a tela", "Parar o espelhamento",
                       "Procurando o celular..."),
                pedir("jogo"),
            ),
            pystray.MenuItem(
                rotulo("extensao", "Usar como extensão (borda)",
                       "Parar a extensão", "Procurando o celular..."),
                pedir("extensao"),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Parear o celular...", pedir("configurar")),
            pystray.MenuItem("Sair", lambda _i, _it:
                             self.programa.pedidos.put("sair")),
        )

    # -- ciclo de vida -------------------------------------------------------

    def iniciar(self) -> bool:
        """Sobe o icone numa thread propria. False se nao der."""
        if not self.disponivel:
            return False
        try:
            import pystray

            self._icone = pystray.Icon(
                name="scrcpy-f",
                icon=icone.desenhar(self._estado),
                title=DICA["parado"],
                menu=self._montar_menu(),
            )
            self._thread = threading.Thread(target=self._icone.run,
                                            daemon=True, name="bandeja")
            self._thread.start()
            return True
        except Exception as erro:
            log.warning("bandeja indisponivel: %s", erro)
            self.disponivel = False
            return False

    def atualizar(self, estado: str) -> None:
        """
        Repinta o icone e reescreve o menu.

        Sai cedo quando o estado nao mudou: reenviar o icone para o Windows
        sem motivo seria trabalho de fundo a toa. O menu, esse, e atualizado
        sempre -- ele depende tambem do "procurando o celular...", que muda
        sem o estado do icone mudar.
        """
        if self._icone is None:
            return
        try:
            self._icone.update_menu()
            if estado == self._estado:
                return
            self._estado = estado
            self._icone.icon = icone.desenhar(estado)
            base, _, marca = estado.partition("+")
            self._icone.title = DICA.get(base, TITULO) + (
                " · celular conectado" if marca == "par" else "")
        except Exception:
            pass

    def notificar(self, titulo: str, mensagem: str) -> None:
        """
        Um aviso do Windows saindo do icone da bandeja.

        Notificacao e nao caixa de mensagem: ela aparece no canto, some
        sozinha e nao exige clique. Ligar e desligar acontece o tempo todo --
        uma caixa a cada vez viraria estorvo em uma tarde.

        Se o Windows estiver com as notificacoes desligadas, nada aparece e
        nada quebra: o estado continua visivel no icone.
        """
        if self._icone is None:
            return
        try:
            self._icone.notify(mensagem, titulo)
        except Exception as erro:
            log.warning("nao consegui notificar: %s", erro)

    def encerrar(self) -> None:
        if self._icone is not None:
            try:
                self._icone.stop()
            except Exception:
                pass
            self._icone = None
