"""
SONDA DO STATUS DO CELULAR (23/set/2026)

Pergunta: o que o celular deixa ler pelo adb, e quanto tempo cada leitura
leva? Bateria, espaco livre, RAM, CPU geral, GPU geral e o uso de cada app
(RAM, CPU e memoria de graficos). E disso que saem a tela "celular" e o
quadro que aparece ao parar o mouse num app.

So LE: nao muda nada no celular. Grava relatorios\\sonda_status.txt
(substituido a cada sonda).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

# As sondas moram em sondas\; config e relatorios sao os da raiz.
AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)

from scrcpyf import celular  # noqa: E402
from scrcpyf.config import Config  # noqa: E402

SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0
SAIDA = os.path.join(AQUI, "relatorios", "sonda_status.txt")
linhas: list[str] = []


def anotar(texto: str = "") -> None:
    linhas.append(texto)
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arq:
        arq.write("\n".join(linhas) + "\n")


def shell(adb, serial, comando, titulo, limite=60):
    """Roda no celular, anota o tempo e as primeiras `limite` linhas."""
    t0 = time.perf_counter()
    try:
        r = subprocess.run([adb, "-s", serial, "shell", comando],
                           capture_output=True, timeout=30,
                           creationflags=SEM_JANELA)
        saida = ((r.stdout or b"") + (r.stderr or b"")).decode(
            "utf-8", errors="replace")
    except Exception as erro:
        saida = "FALHOU: %s" % erro
    ms = (time.perf_counter() - t0) * 1000
    anotar("")
    anotar("--- %s  (%.0f ms) ---" % (titulo, ms))
    anotar("$ " + comando)
    todas = saida.replace("\r", "").splitlines()
    for linha in todas[:limite]:
        anotar("  " + linha)
    if len(todas) > limite:
        anotar("  ... (+%d linhas)" % (len(todas) - limite))
    print("   %-38s %5.0f ms" % (titulo, ms))
    return saida


def main() -> int:
    anotar("=== SONDA DO STATUS %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    cfg = Config.carregar()
    adb = str(cfg.adb_exe)
    serial = celular.achar(adb, cfg.ip_reserva, anotar=anotar)
    if not serial:
        anotar("PAREI: celular nao encontrado")
        print("\n   Nao achei o celular.")
        return 1
    anotar("celular: %s" % serial)
    print()

    shell(adb, serial, "getprop ro.product.model; getprop ro.build.version.release; getprop ro.hardware; getprop ro.board.platform", "modelo e chip")
    shell(adb, serial, "dumpsys battery", "bateria")
    shell(adb, serial, "df /data; df -h /data", "espaco livre")
    shell(adb, serial, "head -5 /proc/meminfo", "ram geral")
    shell(adb, serial, "head -1 /proc/stat; sleep 1; head -1 /proc/stat", "cpu geral (/proc/stat)")
    shell(adb, serial, "top -b -n 1 -m 12 -o PID,%CPU,%MEM,RES,ARGS", "cpu por processo (top)")
    shell(adb, serial, "dumpsys cpuinfo | head -15", "cpu (dumpsys cpuinfo)")
    shell(adb, serial, "ls /sys/kernel/gpu/ 2>&1; for f in /sys/kernel/gpu/gpu_busy /sys/kernel/gpu/gpu_load /sys/kernel/gpu/gpu_clock /sys/class/kgsl/kgsl-3d0/gpubusy /sys/class/kgsl/kgsl-3d0/gpu_busy_percentage /sys/class/misc/mali0/device/utilization; do echo \"== $f\"; cat $f 2>&1; done", "gpu geral (arquivos do sistema)")
    shell(adb, serial, "ls -d /sys/devices/platform/*gpu* /sys/devices/platform/*mali* /sys/devices/platform/*sgpu* 2>&1; cat /sys/devices/platform/*sgpu*/gpu_busy 2>&1; cat /sys/devices/platform/*sgpu*/utilization 2>&1", "gpu geral (procura)")
    shell(adb, serial, "dumpsys gpu | head -20", "gpu (dumpsys gpu)")
    shell(adb, serial, "ps -A -o PID,RSS,NAME | grep -i -E 'whatsapp|youtube|chrome' | head", "ram por app (ps)")
    shell(adb, serial, "dumpsys meminfo com.whatsapp | head -40", "ram de um app (meminfo whatsapp)")
    shell(adb, serial, "dumpsys gfxinfo com.whatsapp | grep -i -E 'memory|total' | head", "memoria de graficos (gfxinfo)")

    anotar("")
    anotar("=== FIM %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    print()
    print("   Pronto. O resultado esta em relatorios\\sonda_status.txt")
    print("   (me avise que eu leio)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        anotar("ERRO: %r" % erro)
        print("\n   A sonda quebrou; o motivo ficou em relatorios\\sonda_status.txt")
        sys.exit(1)
