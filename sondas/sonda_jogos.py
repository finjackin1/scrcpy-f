"""
SONDA DOS JOGOS (23/set/2026)

Pergunta: o celular diz quais apps sao JOGOS? Se disser, o scrcpy-f abre jogo
no formato do monitor sozinho. Testa tres jeitos, em todos os apps com icone:
  A) `dumpsys package <app>` -- procura "category" / "game"
  B) `cmd game list-modes <app>` -- o servico de jogos do Android 12+
  C) `pm list packages` com a categoria (Android 14+ aceita filtro)
Grava relatorios\\sonda_jogos.txt (substituido a cada sonda).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)

from scrcpyf import celular  # noqa: E402
from scrcpyf.config import Config  # noqa: E402

SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0
SAIDA = os.path.join(AQUI, "relatorios", "sonda_jogos.txt")
linhas: list[str] = []


def anotar(texto: str = "") -> None:
    linhas.append(texto)
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arq:
        arq.write("\n".join(linhas) + "\n")


def shell(adb, serial, comando, espera=60) -> str:
    try:
        r = subprocess.run([adb, "-s", serial, "shell", comando],
                           capture_output=True, timeout=espera,
                           creationflags=SEM_JANELA)
        return ((r.stdout or b"") + (r.stderr or b"")).decode(
            "utf-8", errors="replace")
    except Exception as erro:
        return "FALHOU: %s" % erro


def main() -> int:
    anotar("=== SONDA DOS JOGOS %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    cfg = Config.carregar()
    adb = str(cfg.adb_exe)
    serial = celular.achar(adb, cfg.ip_reserva, anotar=anotar)
    if not serial:
        anotar("PAREI: celular nao encontrado")
        print("\n   Nao achei o celular.")
        return 1
    anotar("android sdk: %s" % shell(adb, serial,
                                     "getprop ro.build.version.sdk").strip())
    saida = shell(adb, serial, "cmd package query-activities --brief "
                  "-a android.intent.action.MAIN "
                  "-c android.intent.category.LAUNCHER")
    pacotes = sorted({l.strip().split("/")[0] for l in saida.splitlines()
                      if "/" in l})
    anotar("apps com icone: %d" % len(pacotes))
    print("   %d apps, uns 20 segundos..." % len(pacotes))

    # A e B num comando so no celular (um adb shell para todos).
    laco = ("for p in %s; do echo \"@@ $p\"; "
            "dumpsys package $p | grep -i -m3 -E 'category|isgame|game'; "
            "echo \"## B\"; cmd game list-modes $p 2>&1 | head -2; done"
            % " ".join(pacotes))
    anotar("")
    anotar("--- A (dumpsys) e B (cmd game) por app ---")
    for linha in shell(adb, serial, laco, espera=180).splitlines():
        anotar("  " + linha.rstrip()[:160])

    anotar("")
    anotar("--- C (pm list packages por categoria) ---")
    for arg in ("--category 0", "-c 0"):
        r = shell(adb, serial, "pm list packages %s 2>&1 | head -40" % arg)
        anotar("$ pm list packages %s" % arg)
        for linha in r.splitlines()[:40]:
            anotar("  " + linha.rstrip())
    anotar("")
    anotar("=== fim ===")
    print("\n   Pronto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
