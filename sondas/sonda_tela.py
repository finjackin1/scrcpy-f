"""
SONDA DA TELA (24/set/2026)

Relato dele: a tela do celular nao apaga mais sozinha, mesmo com o tempo de
tela em 30 s. Esta sonda SO LE (nao muda nada) e grava o que pode estar
segurando a tela acesa: o tempo de tela, o "tela sempre acesa carregando",
as travas de tela acesa (wake locks) e o que do scrcpy-f ainda roda NO
CELULAR (servidor do scrcpy, lacos dos vigias).

Grava relatorios\\sonda_tela.txt (substituido a cada sonda).
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
REL = os.path.join(AQUI, "relatorios")
SAIDA = os.path.join(REL, "sonda_tela.txt")
linhas: list[str] = []


def anotar(texto: str = "") -> None:
    linhas.append(texto)
    os.makedirs(REL, exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arq:
        arq.write("\n".join(linhas) + "\n")


def shell(adb, serial, comando, espera=15) -> str:
    try:
        r = subprocess.run([adb, "-s", serial, "shell", comando],
                           capture_output=True, timeout=espera,
                           creationflags=SEM_JANELA)
        return ((r.stdout or b"") + (r.stderr or b"")).decode(
            "utf-8", errors="replace").rstrip()
    except Exception as erro:
        return "FALHOU: %s" % erro


PERGUNTAS = (
    ("android", "getprop ro.build.version.release; "
                "getprop ro.build.version.sdk"),
    ("tempo de tela (ms)", "settings get system screen_off_timeout"),
    ("tela acesa carregando", "settings get global "
                              "stay_on_while_plugged_in"),
    ("animacoes", "settings get global window_animation_scale; "
                  "settings get global transition_animation_scale; "
                  "settings get global animator_duration_scale"),
    ("estado de energia", "dumpsys power | grep -E 'mWakefulness=|"
                          "mStayOn|mHoldingWakeLockSuspendBlocker|"
                          "mHoldingDisplaySuspendBlocker|mScreenOffTimeout|"
                          "mUserActivityTimeoutOverride|"
                          "mMaximumScreenOffTimeoutFromDeviceAdmin|"
                          "mLastUserActivityTime='"),
    ("travas de tela acesa", "dumpsys power | sed -n "
                             "'/Wake Locks: size/,/^$/p' | head -40"),
    ("processos do scrcpy/lacos", "ps -A -o PID,PPID,ETIME,ARGS | grep -E "
                                  "'app_process|scrcpy|dumpsys|sleep 0' | "
                                  "grep -v grep | head -40"),
    ("telas virtuais", "dumpsys display | grep -E "
                       "'mDisplayId=|DisplayDeviceInfo\\{\"' | head -30"),
)


def main() -> int:
    anotar("=== SONDA DA TELA %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    cfg = Config.carregar()
    adb = str(cfg.adb_exe)
    serial = celular.achar(adb, cfg.ip_reserva, anotar=anotar)
    if not serial:
        anotar("PAREI: celular nao encontrado")
        print("\n   Nao achei o celular.")
        return 1
    for titulo, comando in PERGUNTAS:
        anotar("")
        anotar("--- %s ---" % titulo)
        anotar(shell(adb, serial, comando) or "(nada)")
    anotar("")
    anotar("=== FIM %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    print("\n   Pronto. Pode fechar.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        anotar("ERRO: %r" % erro)
        print("\n   A sonda quebrou; o motivo ficou em "
              "relatorios\\sonda_tela.txt")
        sys.exit(1)
