"""
SONDA DO DEX (25/set/2026)

Pedido dele: o "Samsung DeX" em janela fica estranho -- tudo em escala de
celular (o scrcpy cria a tela virtual com a densidade do celular: 369) e sem
a barra com o botao de iniciar do DeX de verdade.

Abre QUATRO janelas, uma de cada vez (ele fecha no X para ir a proxima):
  A  1920x1080 densidade 160
  B  1920x1080 densidade 213
  C  1920x1080 densidade 240
  D  1920x1080 densidade 160 + tenta abrir a area de trabalho do DeX
     (com.sec.android.app.desktoplauncher) nessa tela
Ele diz no chat qual letra ficou certa. Aqui fica o que o celular respondeu
em cada uma.

Grava relatorios\\sonda_dex.txt (substituido a cada sonda) e o log de cada
janela em relatorios\\sonda_dex_<letra>.txt.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)

from scrcpyf import celular  # noqa: E402
from scrcpyf.config import Config  # noqa: E402

SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0
REL = os.path.join(AQUI, "relatorios")
SAIDA = os.path.join(REL, "sonda_dex.txt")
LAUNCHER = "com.sec.android.app.desktoplauncher"
VARIANTES = [("A", 160, False), ("B", 213, False), ("C", 240, False),
             ("D", 160, True)]
linhas: list[str] = []
T0 = time.time()


def anotar(texto: str = "") -> None:
    linhas.append(texto)
    os.makedirs(REL, exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arq:
        arq.write("\n".join(linhas) + "\n")


def marca(texto: str) -> None:
    anotar("[%6.2f s] %s" % (time.time() - T0, texto))


def shell(adb, serial, comando, espera=10) -> str:
    try:
        r = subprocess.run([adb, "-s", serial, "shell", comando],
                           capture_output=True, timeout=espera,
                           creationflags=SEM_JANELA)
        return ((r.stdout or b"") + (r.stderr or b"")).decode(
            "utf-8", errors="replace").strip()
    except Exception as erro:
        return "FALHOU: %s" % erro


def ler_tela(caminho: str, proc) -> str:
    """O numero da tela virtual, pelo log do scrcpy (ate 20 s)."""
    fim = time.time() + 20
    while time.time() < fim and proc.poll() is None:
        try:
            with open(caminho, encoding="utf-8", errors="replace") as arq:
                m = re.search(r"New display: (\S+) \(id=(\d+)\)", arq.read())
            if m:
                marca("tela virtual %s (id=%s)" % (m.group(1), m.group(2)))
                return m.group(2)
        except OSError:
            pass
        time.sleep(0.1)
    return ""


def abrir_launcher(adb, serial, tela) -> None:
    """Tres jeitos, do mais direto ao alternativo; anota a resposta."""
    comp = shell(adb, serial, "cmd package resolve-activity --brief "
                 "-a android.intent.action.MAIN "
                 "-c android.intent.category.LAUNCHER %s | tail -1" % LAUNCHER)
    marca("entrada do launcher do DeX: %r" % comp)
    sec = shell(adb, serial, "cmd package resolve-activity --brief "
                "-a android.intent.action.MAIN "
                "-c android.intent.category.SECONDARY_HOME | tail -1")
    marca("SECONDARY_HOME do sistema: %r" % sec)
    jeitos = []
    if "/" in comp:
        jeitos.append("am start --display %s -n %s" % (tela, comp))
    jeitos.append("am start --display %s -a android.intent.action.MAIN "
                  "-c android.intent.category.SECONDARY_HOME -p %s"
                  % (tela, LAUNCHER))
    jeitos.append("am start --display %s -a android.intent.action.MAIN "
                  "-c android.intent.category.HOME -p %s" % (tela, LAUNCHER))
    for jeito in jeitos:
        resp = shell(adb, serial, jeito)
        marca("%s -> %s" % (jeito, resp[:300].replace("\n", " / ")))
        time.sleep(1.5)


def main() -> int:
    config = Config.carregar()
    adb, scr = str(config.adb_exe), str(config.scrcpy_exe)
    marca("scrcpy: %s" % scr)
    serial = celular.achar(adb, config.ip_reserva)
    if not serial:
        marca("celular NAO encontrado")
        print("\n   Nao achei o celular. Ligue a depuracao e tente de novo.")
        return 1
    marca("celular: %s" % serial)
    marca("densidade do celular: %s" % shell(adb, serial, "wm density"))
    marca("DeX ligado? %s" % shell(
        adb, serial, "settings get system desktop_mode_enabled; "
        "settings get global force_desktop_mode_on_external_displays"))
    shell(adb, serial, "cmd input keyevent KEYCODE_WAKEUP")
    for letra, dpi, launcher in VARIANTES:
        anotar()
        marca("=== %s: 1920x1080 densidade %d%s ===" % (
            letra, dpi, " + area de trabalho do DeX" if launcher else ""))
        print("\n   Janela %s aberta. Olhe como ficou e FECHE no X para ir"
              " a proxima." % letra)
        caminho = os.path.join(REL, "sonda_dex_%s.txt" % letra)
        with open(caminho, "w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.Popen(
                [scr, "-s", serial, "--new-display=1920x1080/%d" % dpi,
                 "--no-audio", "--max-size=1920", "--prefer-text",
                 "--window-title=DeX teste %s - densidade %d%s" % (
                     letra, dpi, " + area de trabalho" if launcher else "")],
                stdout=log, stderr=subprocess.STDOUT,
                cwd=os.path.dirname(scr), creationflags=SEM_JANELA)
            tela = ler_tela(caminho, proc)
            if launcher and tela:
                time.sleep(1.5)
                abrir_launcher(adb, serial, tela)
            proc.wait()
        marca("%s fechada (codigo %s)" % (letra, proc.returncode))
    anotar()
    marca("fim")
    print("\n   Pronto. Diga no chat qual letra ficou certa (A, B, C ou D).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        marca("ERRO: %r" % erro)
        raise
