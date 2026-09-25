"""
SONDA DO TOP (23/set/2026)

A aba status nao atualiza a lista de apps: so muda ao sair e entrar na aba.
Suspeita: o `top` do celular, escrevendo para um cano (e nao para uma tela),
guarda a saida em bloco e so manda de tempos em tempos. Esta sonda roda o
MESMO comando do programa por 8 s de dois jeitos -- normal e com terminal
(`adb shell -tt`) -- e anota a que horas cada quadro chega no PC.

Grava relatorios\\sonda_top.txt (substituido a cada sonda).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)

from scrcpyf import celular  # noqa: E402
from scrcpyf.config import Config  # noqa: E402

SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0
SAIDA = os.path.join(AQUI, "relatorios", "sonda_top.txt")
TOPO = "top -b -d 0.25 -m 12 -s 1 -o %CPU,RES,NAME"
DURACAO_S = 8
linhas: list[str] = []


def anotar(texto: str = "") -> None:
    linhas.append(texto)
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arq:
        arq.write("\n".join(linhas) + "\n")


def rodada(adb: str, serial: str, extra: list[str], nome: str) -> None:
    anotar("")
    anotar("--- %s: adb -s %s shell %s%s ---" % (
        nome, serial, " ".join(extra) + " " if extra else "", TOPO))
    try:
        proc = subprocess.Popen([adb, "-s", serial, "shell", *extra, TOPO],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL,
                                creationflags=SEM_JANELA)
    except Exception as erro:
        anotar("FALHOU: %s" % erro)
        return
    inicio = time.perf_counter()
    quadros: list[str] = []
    amostra: list[str] = []
    bytes_ = [0]

    def ler():
        n = 0
        for bruta in proc.stdout:
            bytes_[0] += len(bruta)
            linha = bruta.decode("utf-8", "replace").rstrip()
            ms = (time.perf_counter() - inicio) * 1000
            if linha.lstrip().startswith("Tasks:"):
                n += 1
                quadros.append("%6.0f ms  quadro %d (bytes ate aqui: %d)"
                               % (ms, n, bytes_[0]))
            elif n in (2, 3) and len(amostra) < 30:
                amostra.append("q%d  %s" % (n, linha[:90]))

    t = threading.Thread(target=ler, daemon=True)
    t.start()
    time.sleep(DURACAO_S)
    try:
        proc.terminate()
    except Exception:
        pass
    t.join(2)
    anotar("quadros que chegaram em %d s: %d" % (DURACAO_S, len(quadros)))
    for q in quadros:
        anotar("  " + q)
    anotar("amostra dos quadros 2 e 3:")
    for a in amostra:
        anotar("  " + a)


def main() -> int:
    anotar("=== SONDA DO TOP %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    cfg = Config.carregar()
    adb = str(cfg.adb_exe)
    serial = celular.achar(adb, cfg.ip_reserva, anotar=anotar)
    if not serial:
        anotar("PAREI: celular nao encontrado")
        print("\n   Nao achei o celular.")
        return 1
    print("   Rodada 1 de 2 (8 s)...")
    rodada(adb, serial, [], "NORMAL (como o programa)")
    print("   Rodada 2 de 2 (8 s)...")
    rodada(adb, serial, ["-tt"], "COM TERMINAL")
    anotar("")
    anotar("=== fim ===")
    print("\n   Pronto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
