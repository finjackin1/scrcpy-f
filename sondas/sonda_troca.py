"""
SONDA DA TROCA (24/set/2026)

Pedido dele: mudar o ajuste de um app aberto tem que trocar a janela MUITO
rapido e SEM reiniciar o app. Reabrir (r123) leva ~2 s e reinicia: a tela
virtual velha some e o Android destroi o app que estava nela.

Ideia: subir a janela NOVA (tela virtual nova) com a velha ainda no ar,
PASSAR a tarefa do app da tela velha para a nova e so entao fechar a velha.
Esta sonda mede se o Android aceita passar a tarefa (tres jeitos, na
ordem, ate um dar certo), quanto tempo leva, e se o processo do app e o
mesmo antes e depois (mesmo PID = nao reiniciou).

Grava relatorios\\sonda_troca.txt (substituido a cada sonda).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)

from scrcpyf import celular, janela_scrcpy  # noqa: E402
from scrcpyf.config import Config  # noqa: E402

SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0
REL = os.path.join(AQUI, "relatorios")
SAIDA = os.path.join(REL, "sonda_troca.txt")
PACOTE = "com.instagram.android"
FLAGS = ["--new-display", "--no-vd-system-decorations",
         "--mouse-bind=b-b-:b-b-", "--shortcut-mod=rsuper", "--no-audio",
         "--prefer-text"]
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
            "utf-8", errors="replace")
    except Exception as erro:
        return "FALHOU: %s" % erro


def subir(scr, serial, rotulo, extras):
    caminho = os.path.join(REL, "sonda_troca_%s.txt" % rotulo)
    log = open(caminho, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [scr, "-s", serial] + FLAGS + extras +
        ["--window-title=sonda da troca - %s" % rotulo],
        stdout=log, stderr=subprocess.STDOUT, cwd=os.path.dirname(scr),
        creationflags=SEM_JANELA)
    tela = None
    fim = time.time() + 20
    while tela is None and time.time() < fim:
        time.sleep(0.05)
        try:
            m = re.search(r"New display: .*?\(id=(\d+)\)",
                          open(caminho, encoding="utf-8",
                               errors="replace").read())
            tela = m.group(1) if m else None
        except Exception:
            pass
    return proc, log, tela


def onde_esta(adb, serial) -> dict:
    """{tela: [ids das tarefas do Instagram]}, pelo dumpsys."""
    texto = shell(adb, serial, "dumpsys activity activities")
    achado: dict = {}
    tela = None
    for linha in texto.splitlines():
        m = re.match(r"\s*Display #(\d+)", linha)
        if m:
            tela = m.group(1)
            continue
        m = re.search(r"Task\{\w+ #(\d+) .*?%s" % re.escape(PACOTE), linha)
        if m and tela is not None:
            achado.setdefault(tela, [])
            if m.group(1) not in achado[tela]:
                achado[tela].append(m.group(1))
    return achado


def pid(adb, serial) -> str:
    return shell(adb, serial, "pidof %s" % PACOTE, 5).strip() or "(nenhum)"


def main() -> int:
    anotar("=== SONDA DA TROCA %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    cfg = Config.carregar()
    adb, scr = str(cfg.adb_exe), str(cfg.scrcpy_exe)
    serial = celular.achar(adb, cfg.ip_reserva, anotar=anotar)
    if not serial:
        anotar("PAREI: celular nao encontrado")
        print("\n   Nao achei o celular.")
        return 1
    anotar("celular: %s  android: %s" % (serial, shell(
        adb, serial, "getprop ro.build.version.release", 5).strip()))
    shell(adb, serial, "input keyevent KEYCODE_WAKEUP")

    velho, log_v, tela_v = subir(scr, serial, "velha",
                                 ["--start-app=%s" % PACOTE])
    marca("janela velha: tela %s" % tela_v)
    if not tela_v:
        anotar("PAREI: a janela velha nao abriu")
        velho.terminate()
        return 1
    print()
    print("   O Instagram abriu numa janela. Abra um VIDEO (reels) e deixe")
    print("   tocando. Daqui a 20 segundos a janela vai ser TROCADA por outra.")
    print("   Repare se o video CONTINUA de onde estava ou se o app reinicia.")
    time.sleep(20)

    pid_antes = pid(adb, serial)
    antes = onde_esta(adb, serial)
    marca("antes: pid %s, tarefas por tela %s" % (pid_antes, antes))
    lugar = None
    try:
        h = janela_scrcpy.achar(velho.pid)
        lugar = janela_scrcpy.area(h) if h else None
    except Exception as erro:
        marca("nao li o lugar da janela: %r" % erro)
    extras = []
    if lugar:
        extras = ["--window-x=%d" % lugar[0], "--window-y=%d" % lugar[1],
                  "--window-height=%d" % lugar[3]]
    t_ini = time.time()
    novo, log_n, tela_n = subir(scr, serial, "nova", extras)
    marca("janela nova: tela %s em %.2f s" % (tela_n, time.time() - t_ini))
    tarefas = antes.get(tela_v) or []
    if not tela_n or not tarefas:
        anotar("PAREI: sem tela nova (%s) ou sem a tarefa na velha (%s)"
               % (tela_n, tarefas))
        for p in (velho, novo):
            p.terminate()
        return 1
    tarefa = tarefas[0]
    comp = shell(adb, serial, "cmd package resolve-activity --brief %s | "
                 "tail -1" % PACOTE).strip().splitlines()
    comp = comp[-1].strip() if comp else ""
    jeitos = (
        ("1 am display move-stack",
         "am display move-stack %s %s" % (tarefa, tela_n)),
        ("2 cmd activity display move-stack",
         "cmd activity display move-stack %s %s" % (tarefa, tela_n)),
        ("3 am start na tela nova (trazer a tarefa)",
         "am start -f 0x10020000 --display %s -n %s" % (tela_n, comp)),
    )
    certo = None
    for nome, comando in jeitos:
        t = time.time()
        resp = shell(adb, serial, comando).strip()
        agora = onde_esta(adb, serial)
        passou = tarefa in (agora.get(tela_n) or [])
        marca("JEITO %s: %.2f s; resposta: %s; tarefas agora %s; %s"
              % (nome, time.time() - t, resp[:160] or "(nada)", agora,
                 "PASSOU" if passou else "nao passou"))
        if passou:
            certo = nome
            break
    time.sleep(0.3)
    velho.terminate()
    try:
        velho.wait(5)
    except Exception:
        pass
    marca("janela velha fechada; troca inteira em %.2f s"
          % (time.time() - t_ini))
    time.sleep(1.5)
    pid_depois = pid(adb, serial)
    marca("depois: pid %s (%s); tarefas %s" % (
        pid_depois, "MESMO processo" if pid_depois == pid_antes
        else "processo DIFERENTE", onde_esta(adb, serial)))
    print()
    print("   Troca feita. Olhe a janela nova por 15 segundos.")
    time.sleep(15)
    novo.terminate()
    for log in (log_v, log_n):
        log.close()
    anotar("")
    anotar("RESUMO: jeito que funcionou = %s" % (certo or "NENHUM"))
    anotar("=== FIM %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    print()
    print("   Pronto. Me diga: o video continuou de onde estava ou o")
    print("   Instagram reiniciou? E a troca foi rapida?")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        anotar("ERRO: %r" % erro)
        print("\n   A sonda quebrou; o motivo ficou em "
              "relatorios\\sonda_troca.txt")
        sys.exit(1)
