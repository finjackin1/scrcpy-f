"""
SONDA DO VOLTAR (23/set/2026)

O app em janela propria nao volta quando se aperta VOLTAR na tela inicial
dele. Esta sonda abre o WhatsApp numa janela igual a do programa e, por 25
segundos, anota o que o Android diz das telas a cada meio segundo (so quando
muda). Enquanto isso ele aperta VOLTAR ate o app sair da tela.

Grava relatorios\\sonda_voltar.txt (substituido a cada sonda).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

# As sondas moram em sondas\; config e relatorios sao os da raiz.
AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)

from scrcpyf import celular  # noqa: E402
from scrcpyf.config import Config  # noqa: E402

SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0
SAIDA = os.path.join(AQUI, "relatorios", "sonda_voltar.txt")
LOG_SCRCPY = os.path.join(AQUI, "relatorios", "sonda_voltar_scrcpy.txt")
APP = "com.whatsapp"
linhas: list[str] = []


def anotar(texto: str = "") -> None:
    linhas.append(texto)
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arq:
        arq.write("\n".join(linhas) + "\n")


def shell(adb, serial, comando, espera=10) -> str:
    try:
        r = subprocess.run([adb, "-s", serial, "shell", comando],
                           capture_output=True, timeout=espera,
                           creationflags=SEM_JANELA)
        return (r.stdout or b"").decode("utf-8", errors="replace")
    except Exception as erro:
        return "FALHOU: %s" % erro


def main() -> int:
    anotar("=== SONDA DO VOLTAR %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    cfg = Config.carregar()
    adb, scr = str(cfg.adb_exe), str(cfg.scrcpy_exe)
    serial = celular.achar(adb, cfg.ip_reserva, anotar=anotar)
    if not serial:
        anotar("PAREI: celular nao encontrado")
        print("\n   Nao achei o celular.")
        return 1
    anotar("celular: %s" % serial)
    # Acende a tela: com o celular dormindo o app nao desenha na janela.
    shell(adb, serial, "input keyevent KEYCODE_WAKEUP")
    log = open(LOG_SCRCPY, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [scr, "-s", serial, "--new-display", "--no-vd-system-decorations",
         "--mouse-bind=b-b-:b-b-", "--shortcut-mod=rsuper",
         "--start-app=%s" % APP, "--no-audio", "--prefer-text",
         "--window-title=sonda do voltar"],
        stdout=log, stderr=subprocess.STDOUT, cwd=os.path.dirname(scr),
        creationflags=SEM_JANELA)
    tela = ""
    fim = time.time() + 20
    while not tela and time.time() < fim:
        time.sleep(0.3)
        try:
            m = re.search(r"New display: .*?\(id=(\d+)\)",
                          open(LOG_SCRCPY, encoding="utf-8",
                               errors="replace").read())
            tela = m.group(1) if m else ""
        except Exception:
            pass
    anotar("tela virtual: %s" % (tela or "NAO ACHEI"))
    print()
    print("   A janela do WhatsApp abriu. AGORA: aperte VOLTAR (botao direito")
    print("   do mouse na janela) varias vezes, ate o app sair da tela.")
    print("   Depois so espere; a sonda termina sozinha em 25 segundos.")
    print()
    comp = shell(adb, serial, "cmd package resolve-activity --brief %s "
                 "| tail -1" % APP).strip()
    anotar("tela de entrada do app: %s" % comp)
    antes = None
    t0 = time.time()
    while time.time() - t0 < 25 and proc.poll() is None:
        texto = shell(adb, serial,
                      "dumpsys activity activities | grep -E "
                      "'^Display #|Task\\{|visible=|ResumedActivity|"
                      "mFocusedApp' | head -60")
        # Um retrato por mudanca, com o tempo desde o comeco.
        if texto != antes:
            antes = texto
            anotar("")
            anotar("--- %.1f s ---" % (time.time() - t0))
            for l in texto.replace("\r", "").splitlines():
                anotar("  " + l[:220])
        time.sleep(0.5)
    anotar("")
    anotar("scrcpy ainda aberto no fim: %s" % (proc.poll() is None))
    try:
        proc.terminate()
        proc.wait(5)
    except Exception:
        pass
    log.close()
    anotar("")
    anotar("--- log do scrcpy (fim) ---")
    for l in open(LOG_SCRCPY, encoding="utf-8",
                  errors="replace").read().splitlines()[-25:]:
        anotar("  " + l)
    anotar("=== FIM %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    print("   Pronto. Me avise que eu leio.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        anotar("ERRO: %r" % erro)
        print("\n   A sonda quebrou; o motivo ficou em relatorios\\sonda_voltar.txt")
        sys.exit(1)
