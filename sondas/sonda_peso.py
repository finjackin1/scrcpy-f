"""
SONDA DO PESO NO CELULAR (25/set/2026, revisao geral item C)

Com app em janela, o programa pergunta ao celular sem parar:
  - vigia dos apps: `dumpsys activity activities` a cada 0,4 s
  - vigia do sono:  `dumpsys power` a cada 0,4 s
Isto mede quanto cada pergunta custa NO CELULAR (tempo e processador) e
testa perguntas mais leves que poderiam substituir -- conferindo se elas
trazem o que o vigia precisa ("Display #" e "visible=true").

Cada comando roda 20x seguidas no proprio celular; o gasto de processador
vem do /proc/stat antes e depois (todos os nucleos somados). "nada" e o
custo do proprio laco, descontado dos outros.

Grava relatorios\\sonda_peso.txt (substituido a cada sonda).
"""

from __future__ import annotations

import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)

from scrcpyf import celular  # noqa: E402
from scrcpyf.config import Config  # noqa: E402

SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0
REL = os.path.join(AQUI, "relatorios")
SAIDA = os.path.join(REL, "sonda_peso.txt")
VEZES = 20
COMANDOS = [
    ("nada", "true"),
    ("vigia apps (hoje)", "dumpsys activity activities"),
    ("alt: stack list", "cmd activity stack list"),
    ("alt: containers", "dumpsys activity containers"),
    ("alt: window displays", "dumpsys window displays"),
    ("alt: window visivel", "dumpsys window visible-apps"),
    ("vigia sono (hoje)", "dumpsys power"),
    ("alt: sono leve", "cmd power get-wakefulness 2>/dev/null || "
                       "dumpsys power | grep -m1 mWakefulness="),
]
linhas: list[str] = []


def anotar(texto: str = "") -> None:
    linhas.append(texto)
    os.makedirs(REL, exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arq:
        arq.write("\n".join(linhas) + "\n")


def shell(adb, serial, comando, espera=120) -> str:
    try:
        r = subprocess.run([adb, "-s", serial, "shell", comando],
                           capture_output=True, timeout=espera,
                           creationflags=SEM_JANELA)
        return ((r.stdout or b"") + (r.stderr or b"")).decode(
            "utf-8", errors="replace")
    except Exception as erro:
        return "FALHOU: %s" % erro


def cpu(linha: str):
    """(ocupado, total) em jiffies da linha 'cpu ...' do /proc/stat."""
    n = [int(x) for x in linha.split()[1:] if x.isdigit()]
    if len(n) < 5:
        return None
    ocioso = n[3] + n[4]
    return sum(n) - ocioso, sum(n)


def medir(adb, serial, comando):
    laco = ("a=$(head -1 /proc/stat); t0=$(date +%%s%%N); i=0; "
            "while [ $i -lt %d ]; do %s >/dev/null 2>&1; i=$((i+1)); done; "
            "t1=$(date +%%s%%N); b=$(head -1 /proc/stat); "
            "echo \"@a $a\"; echo \"@b $b\"; echo \"@t $t0 $t1\""
            % (VEZES, comando))
    saida = shell(adb, serial, laco)
    a = b = t = None
    for l in saida.splitlines():
        if l.startswith("@a "):
            a = cpu(l[3:])
        elif l.startswith("@b "):
            b = cpu(l[3:])
        elif l.startswith("@t "):
            p = l.split()
            try:
                t = (int(p[2]) - int(p[1])) / 1e6        # ms
            except (IndexError, ValueError):
                t = None
    if not (a and b and t):
        return None, None, saida[-200:]
    ocupado_ms = (b[0] - a[0]) * 10.0                    # jiffy = 10 ms
    return t / VEZES, ocupado_ms / VEZES, ""


def main() -> int:
    config = Config.carregar()
    adb = str(config.adb_exe)
    serial = celular.achar(adb, config.ip_reserva)
    if not serial:
        anotar("celular NAO encontrado")
        print("\n   Nao achei o celular.")
        return 1
    anotar("celular: %s" % serial)
    anotar("android: %s  nucleos: %s" % (
        shell(adb, serial, "getprop ro.build.version.release").strip(),
        shell(adb, serial, "grep -c ^processor /proc/cpuinfo").strip()))
    anotar("telas: %s" % " ".join(
        l.split("(")[0].strip() for l in shell(
            adb, serial, "dumpsys activity activities | grep '^Display #'")
        .splitlines()))
    anotar()
    anotar("%-22s %9s %9s %9s  %s" % ("comando", "ms/vez", "cpu ms",
                                      "a 2,5/s", "traz o que o vigia usa?"))
    base = 0.0
    for nome, comando in COMANDOS:
        print("   medindo: %s" % nome)
        ms, cpu_ms, erro = medir(adb, serial, comando)
        if ms is None:
            anotar("%-22s  FALHOU %r" % (nome, erro))
            continue
        if nome == "nada":
            base = cpu_ms
        liquido = max(0.0, cpu_ms - base)
        texto = shell(adb, serial, comando + " 2>&1 | head -c 200000")
        traz = "Display# %d, visible=true %d, %d bytes" % (
            texto.count("Display #"), texto.count("visible=true"),
            len(texto.encode("utf-8")))
        if "sono" in nome:
            traz = "wakefulness: %s" % ("sim" if (
                "mWakefulness=" in texto or texto.strip() in (
                    "Awake", "Asleep", "Dozing", "Dreaming")) else "NAO")
        anotar("%-22s %9.1f %9.1f %8.0f%%  %s" % (
            nome, ms, liquido, liquido * 2.5 / 10.0, traz))
        if nome.startswith("alt:"):
            for l in texto.splitlines()[:4]:
                anotar("        | %s" % l[:150])
    anotar()
    anotar("'a 2,5/s' = %% de UM nucleo gasto se rodar 2,5x por segundo "
           "(o ritmo do vigia).")
    print("\n   Pronto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
