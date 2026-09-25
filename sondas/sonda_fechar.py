"""
SONDA DO FECHAR (24/set/2026)

Pedido dele: fechar a janela de um app fecha o app no celular -- como
arrastar o app para fora da lista de recentes (NAO o "forcar parada", que
corta as notificacoes). E tem que valer no maximo de versoes do Android.

Abre o Instagram numa janela igual a do scrcpy-f, fecha a janela e olha o
que sobrou (tarefa nos recentes, processo). Depois tenta, na ordem, jeitos
de tirar a tarefa, conferindo cada um, e anota qual funcionou nesta versao.

Grava relatorios\\sonda_fechar.txt (substituido a cada sonda).
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
SAIDA = os.path.join(REL, "sonda_fechar.txt")
PACOTE = "com.instagram.android"
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
    """Saida E erro juntos (o `am` responde erro pelo canal de erro)."""
    try:
        r = subprocess.run([adb, "-s", serial, "shell", comando],
                           capture_output=True, timeout=espera,
                           creationflags=SEM_JANELA)
        return ((r.stdout or b"") + (r.stderr or b"")).decode(
            "utf-8", errors="replace")
    except Exception as erro:
        return "FALHOU: %s" % erro


def tarefas(adb, serial) -> list:
    """Ids das tarefas do app que o Android ainda lista (telas e recentes)."""
    texto = shell(adb, serial, "dumpsys activity recents; "
                  "dumpsys activity activities")
    achadas = []
    for m in re.finditer(r"Task\{\w+ #(\d+) [^\n]*?%s" % re.escape(PACOTE),
                         texto):
        if m.group(1) not in achadas:
            achadas.append(m.group(1))
    return achadas


def pid(adb, serial) -> str:
    return shell(adb, serial, "pidof %s" % PACOTE, 5).strip() or "(nenhum)"


def main() -> int:
    anotar("=== SONDA DO FECHAR %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    cfg = Config.carregar()
    adb, scr = str(cfg.adb_exe), str(cfg.scrcpy_exe)
    serial = celular.achar(adb, cfg.ip_reserva, anotar=anotar)
    if not serial:
        anotar("PAREI: celular nao encontrado")
        print("\n   Nao achei o celular.")
        return 1
    versao = shell(adb, serial, "getprop ro.build.version.release; "
                   "getprop ro.build.version.sdk", 5).split()
    anotar("celular: %s  android: %s" % (serial, " / sdk ".join(versao)))
    shell(adb, serial, "input keyevent KEYCODE_WAKEUP")
    marca("antes de abrir: pid %s, tarefas %s"
          % (pid(adb, serial), tarefas(adb, serial)))

    caminho = os.path.join(REL, "sonda_fechar_janela.txt")
    log = open(caminho, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [scr, "-s", serial, "--new-display", "--no-vd-system-decorations",
         "--start-app=%s" % PACOTE, "--no-audio",
         "--window-title=sonda do fechar"],
        stdout=log, stderr=subprocess.STDOUT, cwd=os.path.dirname(scr),
        creationflags=SEM_JANELA)
    print()
    print("   O Instagram abriu numa janela. Espere uns 8 segundos,")
    print("   a janela vai fechar sozinha. Nao mexa em nada.")
    time.sleep(8)
    marca("com a janela aberta: pid %s, tarefas %s"
          % (pid(adb, serial), tarefas(adb, serial)))
    proc.terminate()
    try:
        proc.wait(5)
    except Exception:
        pass
    log.close()
    time.sleep(1.5)
    sobrou = tarefas(adb, serial)
    marca("janela FECHADA: pid %s, tarefas que sobraram %s"
          % (pid(adb, serial), sobrou))
    if not sobrou:
        anotar("RESUMO: fechar a janela ja tirou o app dos recentes nesta "
               "versao (nada a fazer)")
        print("\n   Pronto (o app ja saiu sozinho). Pode fechar.")
        return 0

    certo = None
    for t in sobrou:
        jeitos = (
            ("1 am stack remove", "am stack remove %s" % t),
            ("2 cmd activity stack remove", "cmd activity stack remove %s" % t),
            ("3 am task remove", "am task remove %s" % t),
        )
        for nome, comando in jeitos:
            resp = shell(adb, serial, comando).strip()
            time.sleep(0.4)
            ficou = t in tarefas(adb, serial)
            marca("JEITO %s (tarefa %s): resposta %r; %s"
                  % (nome, t, resp[:160] or "(nada)",
                     "ainda la" if ficou else "SAIU"))
            if not ficou:
                certo = certo or nome
                break
    time.sleep(1.5)
    marca("no fim: pid %s, tarefas %s" % (pid(adb, serial),
                                           tarefas(adb, serial)))
    anotar("")
    anotar("RESUMO: jeito que funcionou = %s" % (certo or "NENHUM"))
    anotar("=== FIM %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    print()
    print("   Pronto. Olhe a lista de recentes do celular e me diga se o")
    print("   Instagram ainda aparece la.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        anotar("ERRO: %r" % erro)
        print("\n   A sonda quebrou; o motivo ficou em "
              "relatorios\\sonda_fechar.txt")
        sys.exit(1)
