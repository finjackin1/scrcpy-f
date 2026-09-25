"""
SONDA DO FOCO (23/set/2026)

Sintoma: com dois apps em janela (ex.: Wild Rift + Instagram), rolar o
Instagram so com a roda do mouse faz o video reiniciar; tocando nele roda
normal. Hipotese: o Android da "atencao" (foco) a um app por vez -- o ultimo
que recebeu toque -- e a rolagem nao muda o foco.

Esta sonda abre Instagram e WhatsApp em janelas, ele clica no WhatsApp (tira
o foco do Instagram) e a sonda testa dois jeitos de devolver o foco ao
Instagram SEM clicar nele:
  A) `am start` da tela de entrada do Instagram na tela dele, trazendo a
     tarefa para a frente (como tocar no icone do app);
  B) um toque "cancelado" no canto da tela dele (DOWN + CANCEL): o foco
     segue o toque, mas o app nao recebe clique.

Grava relatorios\\sonda_foco.txt (substituido a cada sonda).
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
SAIDA = os.path.join(REL, "sonda_foco.txt")
APPS = (("instagram", "com.instagram.android"), ("whatsapp", "com.whatsapp"))
linhas: list[str] = []
T0 = time.time()


def anotar(texto: str = "") -> None:
    linhas.append(texto)
    os.makedirs(REL, exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arq:
        arq.write("\n".join(linhas) + "\n")


def marca(texto: str) -> None:
    anotar("[%6.1f s] %s" % (time.time() - T0, texto))


def shell(adb, serial, comando, espera=10) -> str:
    try:
        r = subprocess.run([adb, "-s", serial, "shell", comando],
                           capture_output=True, timeout=espera,
                           creationflags=SEM_JANELA)
        return ((r.stdout or b"") + (r.stderr or b"")).decode(
            "utf-8", errors="replace")
    except Exception as erro:
        return "FALHOU: %s" % erro


def foco(adb, serial) -> str:
    """Tela com o foco + janela com o foco, como o Android diz."""
    t = shell(adb, serial, "dumpsys window | grep -E "
              "'mTopFocusedDisplayId|mCurrentFocus=' | head -4", 6)
    tela = re.search(r"mTopFocusedDisplayId=(-?\d+)", t)
    janela = re.search(r"mCurrentFocus=(\S+ \S+ \S+)", t)
    return "tela %s | %s" % (tela.group(1) if tela else "?",
                             janela.group(1)[:90] if janela else "?")


def espiar(adb, serial, segundos: float, rotulo: str) -> None:
    """Anota o foco a cada meio segundo, so quando muda."""
    antes = None
    fim = time.time() + segundos
    while time.time() < fim:
        f = foco(adb, serial)
        if f != antes:
            marca("%s: foco em %s" % (rotulo, f))
            antes = f
        time.sleep(0.5)


def main() -> int:
    anotar("=== SONDA DO FOCO %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    cfg = Config.carregar()
    adb, scr = str(cfg.adb_exe), str(cfg.scrcpy_exe)
    serial = celular.achar(adb, cfg.ip_reserva, anotar=anotar)
    if not serial:
        anotar("PAREI: celular nao encontrado")
        print("\n   Nao achei o celular.")
        return 1
    anotar("celular: %s" % serial)
    shell(adb, serial, "input keyevent KEYCODE_WAKEUP")

    procs, logs, telas = [], [], {}
    for rotulo, pacote in APPS:
        caminho = os.path.join(REL, "sonda_foco_%s.txt" % rotulo)
        log = open(caminho, "w", encoding="utf-8", errors="replace")
        logs.append(log)
        procs.append(subprocess.Popen(
            [scr, "-s", serial, "--new-display", "--no-vd-system-decorations",
             "--mouse-bind=b-b-:b-b-", "--shortcut-mod=rsuper",
             "--start-app=%s" % pacote, "--no-audio", "--prefer-text",
             "--window-title=sonda do foco - %s" % rotulo],
            stdout=log, stderr=subprocess.STDOUT, cwd=os.path.dirname(scr),
            creationflags=SEM_JANELA))
        fim = time.time() + 20
        while rotulo not in telas and time.time() < fim:
            time.sleep(0.3)
            try:
                m = re.search(r"New display: (\d+)x(\d+).*?\(id=(\d+)\)",
                              open(caminho, encoding="utf-8",
                                   errors="replace").read())
                if m:
                    telas[rotulo] = (m.group(3), int(m.group(1)),
                                     int(m.group(2)))
            except Exception:
                pass
        marca("%s: tela %s" % (rotulo, telas.get(rotulo, "NAO ACHEI")))
    if "instagram" not in telas:
        anotar("PAREI: sem a tela do Instagram")
        print("\n   A janela do Instagram nao abriu.")
        for p in procs:
            p.terminate()
        return 1
    tela_ig, larg, alt = telas["instagram"]
    comp = shell(adb, serial, "cmd package resolve-activity --brief "
                 "com.instagram.android | tail -1").strip().splitlines()
    comp = comp[-1].strip() if comp else ""
    marca("tela de entrada do Instagram: %s" % comp)
    time.sleep(2)

    passos = (
        ("A", "am start (trazer para a frente)",
         "am start -f 0x10020000 --display %s -n %s" % (tela_ig, comp)),
        ("B", "toque cancelado no canto",
         "input -d %s motionevent DOWN %d %d; "
         "input -d %s motionevent CANCEL %d %d"
         % (tela_ig, larg - 2, 2, tela_ig, larg - 2, 2)),
    )
    for letra, nome, comando in passos:
        print()
        print("   ---- ANTES DO TESTE %s ----" % letra)
        print("   Clique UMA vez na janela do WHATSAPP (10 segundos).")
        espiar(adb, serial, 10, "antes de %s" % letra)
        print()
        print("   ---- TESTE %s (25 s) ----" % letra)
        print("   NAO clique no Instagram. So ROLE os videos dele com a roda")
        print("   do mouse e veja se eles rodam normal ou ficam reiniciando.")
        saida = shell(adb, serial, comando).strip()
        marca("TESTE %s (%s): mandado; resposta: %s"
              % (letra, nome, saida[:200] or "(nada)"))
        espiar(adb, serial, 25, "teste %s" % letra)

    for p in procs:
        try:
            p.terminate()
            p.wait(5)
        except Exception:
            pass
    for log in logs:
        log.close()
    anotar("")
    anotar("(tela do Instagram = %s; o teste deu certo se o foco foi para "
           "ela)" % tela_ig)
    anotar("=== FIM %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    print()
    print("   Pronto. Me diga, no teste A e no teste B, se os videos rodaram")
    print("   normal so rolando.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        anotar("ERRO: %r" % erro)
        print("\n   A sonda quebrou; o motivo ficou em relatorios\\sonda_foco.txt")
        sys.exit(1)
