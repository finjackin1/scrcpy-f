"""
As tres conversas com o Windows que o programa de fundo precisa ter:
sobreviver a nao ter console, ser um so, e conseguir avisar sem ter janela.

Nada aqui depende de biblioteca de fora -- so `ctypes`, que ja vem no Python.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading

log = logging.getLogger(__name__)

# Nome do mutex. Comeca com "Local\\" de proposito: assim a trava vale por
# SESSAO DE USUARIO. Com "Global\\", dois usuarios logados na mesma maquina
# disputariam a mesma trava, e o segundo nao conseguiria abrir o programa.
NOME_DA_TRAVA = "Local\\scrcpy-f-instancia-unica"

# O "chamado" que a segunda instancia deixa para a primeira: abrir a janela.
NOME_DO_CHAMADO = "Local\\scrcpy-f-abrir-janela"
_EVENT_MODIFY_STATE = 0x0002

_ERRO_JA_EXISTE = 183  # ERROR_ALREADY_EXISTS
_trava = None
_chamado = None


def garantir_saida() -> None:
    """
    Sem console (`pythonw`), `sys.stdout` e `sys.stderr` valem None, e
    qualquer `print` -- inclusive o de dentro de uma biblioteca -- levanta
    excecao. Apontar os dois para o buraco negro do sistema resolve de uma vez.

    Precisa rodar ANTES dos outros imports do programa.
    """
    for nome in ("stdout", "stderr"):
        if getattr(sys, nome, None) is None:
            try:
                setattr(sys, nome, open(os.devnull, "w", encoding="utf-8"))
            except Exception:
                pass


def instancia_unica() -> bool:
    """
    True se esta e a unica instancia; False se ja havia outra.

    Um mutex nomeado, e nao um arquivo de trava: arquivo sobrevive a um
    encerramento forcado e passa a impedir o programa de abrir para sempre --
    o classico "so funciona depois de apagar um arquivo escondido". O mutex
    morre junto com o processo, sempre.

    A referencia fica guardada num global de proposito: se ela for coletada,
    a trava e liberada e a garantia acaba junto.
    """
    global _trava
    try:
        _trava = ctypes.windll.kernel32.CreateMutexW(None, False, NOME_DA_TRAVA)
        return ctypes.windll.kernel32.GetLastError() != _ERRO_JA_EXISTE
    except Exception as erro:
        # Sem conseguir travar, o certo e deixar abrir: perder a garantia de
        # instancia unica incomoda; nao abrir o programa impede de usar.
        log.warning("nao consegui checar a instancia unica: %s", erro)
        return True


_k32 = None


def _kernel32():
    """
    O kernel32 com os tipos declarados: HANDLE nao cabe num int de 32 bits.
    Montado uma vez so -- a janela pergunta pelo chamado dez vezes por segundo.
    """
    global _k32
    if _k32 is not None:
        return _k32
    from ctypes import wintypes

    k = ctypes.windll.kernel32
    k.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL,
                               wintypes.LPCWSTR]
    k.CreateEventW.restype = ctypes.c_void_p
    k.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.OpenEventW.restype = ctypes.c_void_p
    k.SetEvent.argtypes = [ctypes.c_void_p]
    k.SetEvent.restype = wintypes.BOOL
    k.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    k.CloseHandle.restype = wintypes.BOOL
    _k32 = k
    return k


def ouvir_chamado() -> bool:
    """
    A instancia que ficou cria o ponto onde as proximas podem chamar.

    POR QUE: abrir o scrcpy-f de novo com ele ja rodando e, quase sempre,
    alguem querendo a JANELA -- nao um aviso de "ja esta aberto" para fechar.
    Entao a segunda instancia so toca este sinal e sai quieta, e a primeira
    abre a janela. E um evento nomeado do Windows: morre junto com o processo,
    sem arquivo nem porta de rede.
    """
    global _chamado
    try:
        _chamado = _kernel32().CreateEventW(None, False, False, NOME_DO_CHAMADO)
        return bool(_chamado)
    except Exception as erro:
        log.warning("nao consegui criar o chamado entre instancias: %s", erro)
        return False


def houve_chamado() -> bool:
    """Alguem tocou o sinal desde a ultima pergunta? Nao espera nada."""
    if not _chamado:
        return False
    try:
        return _kernel32().WaitForSingleObject(_chamado, 0) == 0
    except Exception:
        return False


def chamar_a_outra() -> bool:
    """A segunda instancia pede para a primeira abrir a janela."""
    try:
        k = _kernel32()
        alvo = k.OpenEventW(_EVENT_MODIFY_STATE, False, NOME_DO_CHAMADO)
        if not alvo:
            return False
        # Quem foi aberto agora e o programa da frente; a instancia antiga e de
        # fundo e o Windows nao deixaria ela pular para a frente. Esta linha
        # passa a vez: sem ela, a janela abriria atras das outras.
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        except Exception:
            pass
        ok = bool(k.SetEvent(alvo))
        k.CloseHandle(alvo)
        return ok
    except Exception as erro:
        log.warning("nao consegui chamar a instancia aberta: %s", erro)
        return False


# (r159) O que a segunda instancia quer, alem de "mostre a janela": um
# arquivo curto ao lado dos dados, escrito ANTES do sinal e lido (e apagado)
# por quem atende. Hoje so "app\t<pacote>\t<nome>" (o atalho de um app).
def _arquivo_de_pedido():
    from . import caminhos
    return caminhos.pasta_dados() / "chamado.txt"


def deixar_pedido(texto: str) -> None:
    try:
        _arquivo_de_pedido().write_text(texto, encoding="utf-8")
    except Exception as erro:
        log.warning("nao consegui deixar o pedido: %s", erro)


def ler_pedido() -> str:
    """O pedido deixado com o chamado ("" = so mostrar a janela)."""
    arq = _arquivo_de_pedido()
    try:
        texto = arq.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    try:
        arq.unlink()
    except Exception:
        pass
    return texto


def identidade_do_programa() -> bool:
    """
    (r161) O scrcpy-f com "nome proprio" no Windows. Sem isto, aberto pelo
    atalho de um app (ex.: Instagram) o Windows dava ao scrcpy-f o icone
    DAQUELE atalho na barra de tarefas (relato dele, 25/set/2026). Chamado
    antes de qualquer janela.
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "finjackin.scrcpy-f")
        return True
    except Exception as erro:
        log.warning("nao dei o nome proprio ao programa: %s", erro)
        return False


def avisar(mensagem: str, titulo: str = "scrcpy-f", esperar: bool = False) -> None:
    """
    Uma caixa de aviso do proprio Windows.

    Por padrao vai em thread separada, porque a caixa e MODAL: ela segura quem
    a chamou ate alguem clicar em OK, e travar o laco do programa deixaria a
    bandeja sem responder.

    `esperar=True` para o caso em que o programa VAI SAIR logo depois. A thread
    e daemon: se o processo termina, ela morre junto e a caixa nunca chega a
    aparecer -- foi exatamente o que aconteceu com o aviso de "ja esta aberto",
    que piscava e sumia sem ninguem ler nada.
    """
    def mostrar():
        try:
            # 0x40 = icone de informacao, 0x40000 = fica na frente.
            ctypes.windll.user32.MessageBoxW(0, mensagem, titulo, 0x40 | 0x40000)
        except Exception:
            log.warning("nao consegui mostrar o aviso: %s", mensagem)

    if esperar:
        mostrar()
        return
    threading.Thread(target=mostrar, daemon=True, name="aviso").start()


def perguntar(mensagem: str, titulo: str = "scrcpy-f") -> bool:
    """
    (r167) Caixa Sim/Nao do Windows, na frente de tudo. BLOQUEIA quem chama:
    so usar fora da thread da janela. Sem Windows (ou falhou) = Nao.
    """
    try:
        # 0x4 Sim/Nao, 0x20 interrogacao, 0x10000 foco, 0x40000 na frente
        r = ctypes.windll.user32.MessageBoxW(
            0, mensagem, titulo, 0x4 | 0x20 | 0x10000 | 0x40000)
        return r == 6                                  # IDYES
    except Exception:
        log.warning("nao consegui perguntar: %s", mensagem)
        return False


# ---------------------------------------------------------------------------
# Prioridade
# ---------------------------------------------------------------------------
#
# PEDIDO DELE (21/set/2026): "a prioridade e delay sobre estabilidade". O que
# mais atrasa o mouse na hora de trocar de tela nao e conta: e o Windows
# deixar a thread do vigia esperando a vez enquanto o jogo usa a maquina.
# ACIMA DO NORMAL, e nao ALTA: alta demais atrapalharia o proprio jogo, que e
# o que ele esta fazendo enquanto usa isto.

ACIMA_DO_NORMAL = 0x00008000
TEMPO_CRITICO = 15                     # THREAD_PRIORITY_TIME_CRITICAL
# MAIS ALTA QUE O NORMAL, SEM ATROPELAR (teste dele, 21/set/2026: com
# TEMPO_CRITICO "engasgou um pouco"). Uma thread critica acordando 120 vezes
# por segundo passa na frente ate do desenho do jogo; ALTA ja poe o vigia
# antes do trabalho comum e nao rouba o quadro de ninguem.
ALTA = 2                               # THREAD_PRIORITY_HIGHEST


def prioridade_do_programa() -> bool:
    """Poe o programa inteiro um degrau acima do normal. True se deu certo."""
    if os.name != "nt":
        return False
    try:
        k = ctypes.windll.kernel32
        return bool(k.SetPriorityClass(k.GetCurrentProcess(), ACIMA_DO_NORMAL))
    except Exception as erro:
        log.debug("nao consegui mudar a prioridade do programa: %s", erro)
        return False


def prioridade_da_thread(nivel: int = ALTA) -> bool:
    """
    Poe A THREAD DE AGORA na frente da fila. Usado pelo vigia da borda, que e
    quem precisa responder no quadro certo; as outras seguem normais.
    """
    if os.name != "nt":
        return False
    try:
        k = ctypes.windll.kernel32
        return bool(k.SetThreadPriority(k.GetCurrentThread(), nivel))
    except Exception as erro:
        log.debug("nao consegui mudar a prioridade da thread: %s", erro)
        return False
