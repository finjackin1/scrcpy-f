"""
SONDA DO PAINEL (25/set/2026)

Pedido dele: acender a tela pelo botao SEM mexer no app do PC e com o menor
atraso. Hoje o celular dorme no toque (o app pisca) e o painel so volta num
ciclo dormir/acordar (~2 s). Queremos um jeito de RELIGAR O PAINEL na hora,
com o celular acordado o tempo todo.

1. Le o que o `cmd display` do celular sabe fazer (linhas com "power").
2. Apaga o painel como o programa faz (scrcpy so de controle).
3. Tenta cada jeito de religar, um de cada vez, com 6 s entre eles. Ele
   olha o celular e diz no chat QUAL NUMERO acendeu a tela.

Grava relatorios\\sonda_painel.txt (substituido a cada sonda).
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
SAIDA = os.path.join(REL, "sonda_painel.txt")
linhas: list[str] = []
T0 = time.time()


def anotar(texto: str = "") -> None:
    linhas.append(texto)
    os.makedirs(REL, exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arq:
        arq.write("\n".join(linhas) + "\n")


def marca(texto: str) -> None:
    anotar("[%6.2f s] %s" % (time.time() - T0, texto))


def shell(adb, serial, comando, espera=15) -> str:
    try:
        r = subprocess.run([adb, "-s", serial, "shell", comando],
                           capture_output=True, timeout=espera,
                           creationflags=SEM_JANELA)
        return ((r.stdout or b"") + (r.stderr or b"")).decode(
            "utf-8", errors="replace").strip()
    except Exception as erro:
        return "FALHOU: %s" % erro


def estado(adb, serial) -> str:
    return shell(adb, serial, "dumpsys power | grep -m1 mWakefulness=; "
                 "dumpsys display | grep -m2 -E 'mScreenState=|"
                 "mActualState='").replace("\n", " | ")


def apagar(adb, scr, serial):
    log = open(os.path.join(REL, "sonda_painel_scrcpy.txt"), "w",
               encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [scr, "-s", serial, "--no-video", "--no-audio", "--no-window",
         "--turn-screen-off", "--keep-active"],
        stdout=log, stderr=subprocess.STDOUT, cwd=os.path.dirname(scr),
        creationflags=SEM_JANELA)
    time.sleep(3)
    return proc, log


def main() -> int:
    config = Config.carregar()
    adb, scr = str(config.adb_exe), str(config.scrcpy_exe)
    serial = celular.achar(adb, config.ip_reserva)
    if not serial:
        marca("celular NAO encontrado")
        print("\n   Nao achei o celular.")
        return 1
    marca("celular: %s" % serial)
    ajuda = shell(adb, serial, "cmd display help 2>&1")
    for l in ajuda.splitlines():
        if "power" in l.lower():
            marca("cmd display: %s" % l.strip()[:160])
    ids = shell(adb, serial, "dumpsys SurfaceFlinger --display-id 2>/dev/null")
    marca("telas fisicas: %s" % ids.replace("\n", " | ")[:300])
    # O programinha proprio (android\scrcpyf-tela.jar): religa o painel
    # como o scrcpy desliga, sem mexer no estado do Android.
    jar = os.path.join(AQUI, "android", "scrcpyf-tela.jar")
    marca("jar: %s" % subprocess.run(
        [adb, "-s", serial, "push", jar, "/data/local/tmp/scrcpyf-tela.jar"],
        capture_output=True, text=True, creationflags=SEM_JANELA).stdout
        .strip()[-120:])
    tela = ("CLASSPATH=/data/local/tmp/scrcpyf-tela.jar app_process / "
            "scrcpyf.Tela on")
    jeitos = [
        ("1", tela),
        ("2", "cmd display power-on 0"),
    ]
    shell(adb, serial, "cmd input keyevent KEYCODE_WAKEUP")
    print("\n   Olhe o CELULAR. A tela vai apagar e eu tento acender de"
          " jeitos diferentes, numerados. Anote QUAL NUMERO acendeu.")
    for numero, comando in jeitos:
        proc, log = apagar(adb, scr, serial)
        marca("apagado; estado: %s" % estado(adb, serial))
        print("\n   Jeito %s agora..." % numero)
        t = time.time()
        resp = shell(adb, serial, comando)
        marca("jeito %s: %s -> %r (%.2f s)" % (numero, comando, resp[:200],
                                               time.time() - t))
        time.sleep(0.5)
        marca("depois do jeito %s: %s" % (numero, estado(adb, serial)))
        time.sleep(5)
        proc.terminate()
        try:
            proc.wait(5)
        except Exception:
            proc.kill()
        log.close()
        shell(adb, serial, "pkill -f 'video=false audio=false.*keep_active="
                           "tru[e]' ; true")
        # Volta ao normal para o proximo: dorme e acorda.
        shell(adb, serial, "cmd input keyevent KEYCODE_SLEEP")
        time.sleep(1)
        shell(adb, serial, "cmd input keyevent KEYCODE_WAKEUP")
        time.sleep(1.5)
    marca("fim")
    print("\n   Pronto. Diga no chat qual numero acendeu (ou nenhum).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        marca("ERRO: %r" % erro)
        raise
