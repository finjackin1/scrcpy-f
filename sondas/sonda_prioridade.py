"""
SONDA DA PRIORIDADE NO PC (21/set/2026)

Pergunta: marcar o trafego do adb (por onde passa TODO o scrcpy sem fio)
como prioritario no Windows corta os picos de atraso na rede compartilhada?

Como: 4 rodadas alternadas -- sem marca, COM marca, sem, COM -- de 30 idas
e voltas pela conversa com o celular (uma linha "echo" e a resposta), com o
radio do celular mantido acordado durante tudo (o mesmo truque do programa).
A marca e uma politica de QoS do Windows so na memoria (ActiveStore: some
sozinha ao reiniciar) para o adb.exe: prioridade "voz" (DSCP 46, 802.1p 6).

PRECISA DE ADMINISTRADOR (pede sozinho). No fim desfaz tudo: remove a
politica, devolve o ajuste do registro e derruba o adb elevado.

RODAR COM O scrcpy-f FECHADO: a sonda reinicia o adb entre as rodadas.

Grava relatorios\\sonda_prioridade.txt (substituido a cada sonda).
"""

from __future__ import annotations

import ctypes
import os
import queue
import statistics
import subprocess
import sys
import threading
import time

# As sondas moram em sondas\; config e relatorios sao os da raiz.
AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)

SAIDA = os.path.join(AQUI, "relatorios", "sonda_prioridade.txt")
SEM_JANELA = 0x08000000
IDAS = 30
ENTRE_IDAS_S = 0.5
POLITICA = "scrcpy-f-sonda"
CHAVE_QOS = r"SYSTEM\CurrentControlSet\Services\Tcpip\QoS"
VALOR_NLA = "Do not use NLA"

linhas: list[str] = []


def anotar(texto: str = "") -> None:
    linhas.append(texto)
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arq:
        arq.write("\n".join(linhas) + "\n")


def rodar(args, espera=60) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           timeout=espera, creationflags=SEM_JANELA,
                           encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as erro:
        return -1, "falhou: %s" % erro


def powershell(comando: str) -> tuple[int, str]:
    return rodar(["powershell", "-NoProfile", "-NonInteractive",
                  "-ExecutionPolicy", "Bypass", "-Command", comando])


def sou_administrador() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# -- registro: sem isto o Windows ignora a marca em PC fora de dominio ------

def ler_nla():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CHAVE_QOS) as k:
            return winreg.QueryValueEx(k, VALOR_NLA)[0]
    except OSError:
        return None


def gravar_nla(valor) -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, CHAVE_QOS) as k:
        if valor is None:
            try:
                winreg.DeleteValue(k, VALOR_NLA)
            except OSError:
                pass
        else:
            winreg.SetValueEx(k, VALOR_NLA, 0, winreg.REG_SZ, str(valor))


# -- a conversa com o celular ------------------------------------------------

class Conversa:
    """Um `adb shell` aberto; `ida()` mede uma ida e volta em ms."""

    def __init__(self, adb: str, serial: str) -> None:
        self.p = subprocess.Popen(
            [adb, "-s", serial, "shell"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=SEM_JANELA)
        self.fila: queue.Queue = queue.Queue()
        threading.Thread(target=self._ler, daemon=True).start()

    def _ler(self) -> None:
        for linha in self.p.stdout:
            self.fila.put(linha)

    def mandar(self, texto: str) -> None:
        self.p.stdin.write((texto + "\n").encode("ascii"))
        self.p.stdin.flush()

    def ida(self):
        while not self.fila.empty():
            self.fila.get_nowait()
        t0 = time.perf_counter()
        self.mandar("echo p")
        try:
            self.fila.get(timeout=3)
        except queue.Empty:
            return None
        return (time.perf_counter() - t0) * 1000.0

    def fechar(self) -> None:
        try:
            self.p.stdin.close()
            self.p.terminate()
        except Exception:
            pass


def rodada(adb: str, ip_reserva: str, nome: str) -> list[float]:
    from scrcpyf import celular
    rodar([adb, "kill-server"], espera=15)
    rodar([adb, "start-server"], espera=20)
    serial = celular.achar(adb, ip_reserva)
    if not serial:
        anotar("[%s] celular NAO encontrado depois de reiniciar o adb" % nome)
        return []
    acordado = Conversa(adb, serial)
    parar = threading.Event()

    def radio():
        while not parar.wait(0.08):
            try:
                acordado.mandar(":")
            except Exception:
                return

    threading.Thread(target=radio, daemon=True).start()
    medida = Conversa(adb, serial)
    time.sleep(1.5)                       # deixa o radio acordar de vez
    print("   rodada: %-9s (%d s)..." % (nome, int(IDAS * ENTRE_IDAS_S)))
    tempos = []
    for _ in range(IDAS):
        t = medida.ida()
        if t is not None:
            tempos.append(t)
        time.sleep(ENTRE_IDAS_S)
    parar.set()
    medida.fechar()
    acordado.fechar()
    if tempos:
        o = sorted(tempos)
        anotar("[%s] %d/%d  mediana %.0f ms  p95 %.0f ms  PIOR %.0f ms  "
               "acima de 50 ms: %d" % (
                   nome, len(tempos), IDAS, statistics.median(tempos),
                   o[min(len(o) - 1, int(len(o) * 0.95))], max(tempos),
                   sum(1 for t in tempos if t > 50)))
        anotar("   tempos: %s" % " ".join("%.0f" % t for t in tempos))
    else:
        anotar("[%s] nenhuma resposta" % nome)
    return tempos


def resumo(tempos: list[float]) -> str:
    if not tempos:
        return "sem respostas"
    return "tipico %3.0f ms, pior %4.0f ms, acima de 50 ms: %d de %d" % (
        statistics.median(tempos), max(tempos),
        sum(1 for t in tempos if t > 50), len(tempos))


def main() -> int:
    from scrcpyf.config import Config
    anotar("=== SONDA DA PRIORIDADE %s ===" % time.strftime(
        "%d/%m/%Y %H:%M:%S"))
    cfg = Config.carregar()
    adb = str(cfg.adb_exe)
    anotar("adb: %s" % adb)

    nla_antes = ler_nla()
    anotar("registro '%s' antes: %r" % (VALOR_NLA, nla_antes))
    sem, com = [], []
    try:
        gravar_nla("1")
        powershell("Remove-NetQosPolicy -Name '%s' -PolicyStore ActiveStore "
                   "-Confirm:$false -ErrorAction SilentlyContinue" % POLITICA)
        for volta in (1, 2):
            sem += rodada(adb, cfg.ip_reserva, "sem marca")
            cod, saida = powershell(
                "New-NetQosPolicy -Name '%s' -AppPathNameMatchCondition "
                "'adb.exe' -DSCPAction 46 -PriorityValue8021Action 6 "
                "-PolicyStore ActiveStore | Out-String" % POLITICA)
            anotar("politica criada (volta %d): codigo %s %s" % (
                volta, cod, " ".join(saida.split())[:300]))
            com += rodada(adb, cfg.ip_reserva, "COM marca")
            powershell("Remove-NetQosPolicy -Name '%s' -PolicyStore "
                       "ActiveStore -Confirm:$false" % POLITICA)
    finally:
        powershell("Remove-NetQosPolicy -Name '%s' -PolicyStore ActiveStore "
                   "-Confirm:$false -ErrorAction SilentlyContinue" % POLITICA)
        try:
            gravar_nla(nla_antes)
        except Exception as erro:
            anotar("NAO consegui devolver o registro: %r" % erro)
        rodar([adb, "kill-server"], espera=15)   # nada de adb elevado solto
        anotar("desfeito: politica removida, registro devolvido (%r), adb "
               "derrubado" % ler_nla())

    anotar("")
    anotar("TOTAL sem marca: %s" % resumo(sem))
    anotar("TOTAL COM marca: %s" % resumo(com))
    anotar("=== FIM %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))

    print()
    print("   RESULTADO")
    print("   - sem prioridade: %s" % resumo(sem))
    print("   - COM prioridade: %s" % resumo(com))
    print()
    print("   Tudo foi desfeito. Detalhe em relatorios\\sonda_prioridade.txt")
    print("   (me avise que eu leio)")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32" and not sou_administrador():
        # Reabre esta sonda como administrador, numa janela propria.
        r = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, '"%s"' % os.path.abspath(__file__),
            AQUI, 1)
        if r <= 32:
            print("\n   O Windows nao deu a permissao de administrador.")
            print("   Sem ela a sonda nao consegue marcar a prioridade.")
            sys.exit(1)
        print("\n   A sonda continua na janela de administrador que abriu.")
        sys.exit(0)
    codigo = 1
    try:
        codigo = main()
    except Exception as erro:
        anotar("ERRO: %r" % erro)
        print("\n   A sonda quebrou; o motivo ficou em "
              "relatorios\\sonda_prioridade.txt")
    print()
    input("   Leia o resultado. Aperte ENTER para fechar: ")
    sys.exit(codigo)
