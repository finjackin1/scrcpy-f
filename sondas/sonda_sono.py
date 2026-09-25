"""
SONDA DO SONO (23/set/2026)

Pedido dele: app aberto no PC tem que continuar funcionando mesmo com a tela
do celular apagada pelo BOTAO. Teste dele: com o celular acordado (mesmo
bloqueado) o app funciona; dormindo, a janela fica preta.

O que esta sonda descobre:
  FASE 1 (45 s) -- um scrcpy SO DE CONTROLE (sem imagem, sem som, sem janela)
    com --turn-screen-off (apaga so a tela fisica) e --keep-active (simula
    atividade: o celular nao dorme por tempo). A janela do app segue viva?
  FASE 2 (40 s) -- ele aperta o botao de ligar. A sonda ve o celular dormir,
    acorda na hora (KEYCODE_WAKEUP) e sobe de novo o scrcpy de controle para
    reapagar a tela. Quanto tempo leva, e a janela volta?

Grava relatorios\\sonda_sono.txt (substituido a cada sonda); logs dos scrcpy
em relatorios\\sonda_sono_app.txt e sonda_sono_ctl.txt.
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
REL = os.path.join(AQUI, "relatorios")
SAIDA = os.path.join(REL, "sonda_sono.txt")
LOG_APP = os.path.join(REL, "sonda_sono_app.txt")
LOG_CTL = os.path.join(REL, "sonda_sono_ctl.txt")
APP = "com.whatsapp"
FASE1_S = 45
FASE2_S = 40
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
        return (r.stdout or b"").decode("utf-8", errors="replace")
    except Exception as erro:
        return "FALHOU: %s" % erro


def estado(adb, serial) -> str:
    """Awake / Asleep / Dozing, como o Android diz."""
    texto = shell(adb, serial, "dumpsys power | grep -m1 mWakefulness=", 5)
    m = re.search(r"mWakefulness=(\w+)", texto)
    return m.group(1) if m else ("?" + texto.strip()[:60])


def subir_controle(scr, serial, log):
    """scrcpy so de controle: apaga a tela fisica e nao deixa dormir."""
    return subprocess.Popen(
        [scr, "-s", serial, "--no-video", "--no-audio", "--no-window",
         "--turn-screen-off", "--keep-active"],
        stdout=log, stderr=subprocess.STDOUT, cwd=os.path.dirname(scr),
        creationflags=SEM_JANELA)


def parar(proc) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def main() -> int:
    anotar("=== SONDA DO SONO %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    cfg = Config.carregar()
    adb, scr = str(cfg.adb_exe), str(cfg.scrcpy_exe)
    serial = celular.achar(adb, cfg.ip_reserva, anotar=anotar)
    if not serial:
        anotar("PAREI: celular nao encontrado")
        print("\n   Nao achei o celular.")
        return 1
    anotar("celular: %s" % serial)
    shell(adb, serial, "input keyevent KEYCODE_WAKEUP")
    marca("estado inicial: %s" % estado(adb, serial))

    log_app = open(LOG_APP, "w", encoding="utf-8", errors="replace")
    log_ctl = open(LOG_CTL, "w", encoding="utf-8", errors="replace")
    app = subprocess.Popen(
        [scr, "-s", serial, "--new-display", "--no-vd-system-decorations",
         "--mouse-bind=b-b-:b-b-", "--shortcut-mod=rsuper",
         "--start-app=%s" % APP, "--no-audio", "--prefer-text",
         "--window-title=sonda do sono"],
        stdout=log_app, stderr=subprocess.STDOUT, cwd=os.path.dirname(scr),
        creationflags=SEM_JANELA)
    time.sleep(4)
    marca("janela do app aberta: %s" % (app.poll() is None))

    # ---- FASE 1 --------------------------------------------------------
    print()
    print("   FASE 1 (45 s): a tela do celular deve APAGAR agora.")
    print("   NAO toque no celular. Mexa na janela do WhatsApp de vez em")
    print("   quando (role uma conversa) e veja se ela continua viva.")
    print()
    ctl = subir_controle(scr, serial, log_ctl)
    marca("controle subiu (FASE 1)")
    antes = None
    fim = time.time() + FASE1_S
    while time.time() < fim:
        e = estado(adb, serial)
        if e != antes:
            marca("estado: %s | controle vivo: %s | app vivo: %s" % (
                e, ctl.poll() is None, app.poll() is None))
            antes = e
        time.sleep(0.5)
    marca("fim da FASE 1: estado %s" % estado(adb, serial))

    # ---- FASE 2 --------------------------------------------------------
    print("   FASE 2 (40 s): AGORA aperte o botao de ligar do celular UMA")
    print("   vez. A tela do celular pode piscar e deve apagar de novo.")
    print("   Veja se a janela do WhatsApp volta.")
    print()
    marca("FASE 2 comecou")
    reacordou = 0
    antes = None
    fim = time.time() + FASE2_S
    while time.time() < fim:
        e = estado(adb, serial)
        if e != antes:
            marca("estado: %s" % e)
            antes = e
        if e in ("Asleep", "Dozing"):
            t = time.time()
            shell(adb, serial, "input keyevent KEYCODE_WAKEUP", 5)
            marca("dormiu -> WAKEUP mandado (%.2f s)" % (time.time() - t))
            parar(ctl)
            log_ctl.write("\n=== controle de novo (%.1f s) ===\n"
                          % (time.time() - T0))
            log_ctl.flush()
            ctl = subir_controle(scr, serial, log_ctl)
            reacordou += 1
            marca("controle subiu de novo (%.2f s desde o sono visto); "
                  "estado agora: %s" % (time.time() - t, estado(adb, serial)))
            antes = None
            if reacordou >= 5:
                marca("PAREI a FASE 2: 5 reacordadas (seria laco)")
                break
        time.sleep(0.5)
    marca("fim da FASE 2: reacordou %d vez(es); app vivo: %s" % (
        reacordou, app.poll() is None))

    # ---- fim: tudo como era --------------------------------------------
    parar(ctl)
    parar(app)
    shell(adb, serial, "input keyevent KEYCODE_WAKEUP")
    log_app.close()
    log_ctl.close()
    for titulo, caminho in (("scrcpy do app", LOG_APP),
                            ("scrcpy de controle", LOG_CTL)):
        anotar("")
        anotar("--- log do %s (fim) ---" % titulo)
        for l in open(caminho, encoding="utf-8",
                      errors="replace").read().splitlines()[-30:]:
            anotar("  " + l)
    anotar("=== FIM %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    print("   Pronto. Me conte o que viu nas duas fases que eu leio o resto.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        anotar("ERRO: %r" % erro)
        print("\n   A sonda quebrou; o motivo ficou em relatorios\\sonda_sono.txt")
        sys.exit(1)
