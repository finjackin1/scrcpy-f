"""
SONDA DO APP DUPLICADO (25/set/2026)

Pedido dele: app duplicado (ex.: WhatsApp do Dual Messenger) tem que
aparecer duas vezes na lista e abrir cada um na sua janela. A copia mora
noutro USUARIO do Android (95 no Samsung, 999 no Xiaomi...): o
`scrcpy --list-apps` so ve o usuario 0 e o `--start-app` nao escolhe
usuario. Esta sonda confirma o caminho:
  1) `pm list users` -- quais usuarios existem;
  2) `cmd package query-activities --user N` -- os apps com icone de cada um;
  3) abre o ORIGINAL do jeito de sempre (--start-app) e, ao mesmo tempo, a
     COPIA numa tela virtual vazia + `am start --user N --display D`;
  4) confere no Android de qual usuario e a tarefa em cada tela.

Grava relatorios\\sonda_duplicado.txt (substituido a cada sonda).
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
SAIDA = os.path.join(REL, "sonda_duplicado.txt")
PREFERIDOS = ("com.whatsapp", "com.whatsapp.w4b", "com.instagram.android",
              "com.facebook.katana", "org.telegram.messenger")
LAUNCHER = "-a android.intent.action.MAIN -c android.intent.category.LAUNCHER"
linhas: list[str] = []
T0 = time.time()


def anotar(texto: str = "") -> None:
    linhas.append(texto)
    os.makedirs(REL, exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arq:
        arq.write("\n".join(linhas) + "\n")


def marca(texto: str) -> None:
    anotar("[%6.1f s] %s" % (time.time() - T0, texto))


def shell(adb, serial, comando, espera=15) -> str:
    try:
        r = subprocess.run([adb, "-s", serial, "shell", comando],
                           capture_output=True, timeout=espera,
                           creationflags=SEM_JANELA)
        return ((r.stdout or b"") + (r.stderr or b"")).decode(
            "utf-8", errors="replace")
    except Exception as erro:
        return "FALHOU: %s" % erro


def com_icone(adb, serial, usuario) -> dict:
    """{pacote: componente} dos apps com icone do usuario."""
    saida = shell(adb, serial, "cmd package query-activities --brief "
                  "--user %s %s" % (usuario, LAUNCHER))
    apps = {}
    for linha in saida.splitlines():
        linha = linha.strip()
        if "/" in linha and " " not in linha:
            apps.setdefault(linha.split("/")[0], linha)
    return apps, saida


def abrir(scr, serial, rotulo, extras):
    caminho = os.path.join(REL, "sonda_duplicado_%s.txt" % rotulo)
    log = open(caminho, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [scr, "-s", serial, "--new-display", "--no-vd-system-decorations",
         "--mouse-bind=b-b-:b-b-", "--shortcut-mod=rsuper", "--no-audio",
         "--prefer-text", "--window-title=sonda duplicado - %s" % rotulo]
        + extras,
        stdout=log, stderr=subprocess.STDOUT, cwd=os.path.dirname(scr),
        creationflags=SEM_JANELA)
    tela = None
    fim = time.time() + 20
    while tela is None and time.time() < fim:
        time.sleep(0.3)
        try:
            m = re.search(r"New display: \S+ \(id=(\d+)\)|"
                          r"New display: .*?\(id=(\d+)\)",
                          open(caminho, encoding="utf-8",
                               errors="replace").read())
            if m:
                tela = m.group(1) or m.group(2)
        except Exception:
            pass
    marca("%s: tela virtual %s" % (rotulo, tela or "NAO ACHEI"))
    return proc, log, tela


def de_quem(adb, serial, tela, pacote) -> str:
    """As linhas de tarefa do pacote na tela, como o Android lista."""
    bloco = shell(adb, serial, "dumpsys activity activities | sed -n "
                  "'/^ *Display #%s /,/^ *Display #/p' | grep -E "
                  "'Task|userId|%s' | head -12" % (tela, re.escape(pacote)))
    return bloco.strip() or "(nada na tela)"


def main() -> int:
    anotar("=== SONDA DO APP DUPLICADO %s ===" % time.strftime(
        "%d/%m/%Y %H:%M:%S"))
    cfg = Config.carregar()
    adb, scr = str(cfg.adb_exe), str(cfg.scrcpy_exe)
    serial = celular.achar(adb, cfg.ip_reserva, anotar=anotar)
    if not serial:
        anotar("PAREI: celular nao encontrado")
        print("\n   Nao achei o celular.")
        return 1
    anotar("celular: %s" % serial)
    anotar("android sdk: %s" % shell(adb, serial,
                                     "getprop ro.build.version.sdk").strip())
    anotar("fabricante: %s" % shell(
        adb, serial, "getprop ro.product.manufacturer").strip())
    usuarios_txt = shell(adb, serial, "pm list users")
    anotar("--- pm list users ---")
    anotar(usuarios_txt.rstrip())
    usuarios = re.findall(r"UserInfo\{(\d+):([^:}]*)", usuarios_txt)
    outros = [(u, n) for u, n in usuarios if u != "0"]
    if not outros:
        anotar("PAREI: nenhum usuario alem do 0 (sem app duplicado?)")
        print("\n   O celular nao mostrou nenhuma copia de app.")
        return 1
    base, _ = com_icone(adb, serial, 0)
    anotar("usuario 0: %d apps com icone" % len(base))
    escolha = None
    for u, nome in outros:
        apps, bruto = com_icone(adb, serial, u)
        dup = sorted(p for p in apps if p in base)
        anotar("usuario %s (%s): %d apps com icone; duplicados: %s"
               % (u, nome, len(apps), ", ".join(dup) or "(nenhum)"))
        if not apps:
            anotar("  resposta crua: %s" % bruto.strip()[:300])
        if escolha is None and dup:
            pac = next((p for p in PREFERIDOS if p in dup), dup[0])
            escolha = (u, pac, apps[pac])
    if not escolha:
        anotar("PAREI: nenhum app duplicado com icone")
        print("\n   Nao achei nenhum app duplicado com icone.")
        return 1
    usuario, pacote, comp = escolha
    marca("teste com %s (copia no usuario %s): %s" % (pacote, usuario, comp))
    shell(adb, serial, "input keyevent KEYCODE_WAKEUP")

    p1, l1, t1 = abrir(scr, serial, "original",
                       ["--start-app=%s" % pacote])
    time.sleep(1.5)
    p2, l2, t2 = abrir(scr, serial, "copia", [])
    if t2:
        resp = shell(adb, serial, "am start --user %s --display %s -n %s"
                     % (usuario, t2, comp)).strip()
        marca("am start da copia: %s" % (resp[:300] or "(nada)"))
    time.sleep(4)
    for rotulo, tela in (("original", t1), ("copia", t2)):
        if tela:
            anotar("--- tela %s (%s) ---" % (tela, rotulo))
            anotar(de_quem(adb, serial, tela, pacote))

    print()
    print("   Abriram duas janelas: 'original' e 'copia' de %s." % pacote)
    print("   Veja se cada uma mostra a SUA conta (ex.: numeros diferentes).")
    input("   Quando tiver olhado, aperte ENTER aqui: ")
    for p in (p1, p2):
        try:
            p.terminate()
            p.wait(5)
        except Exception:
            pass
    for log in (l1, l2):
        log.close()
    anotar("=== FIM %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    print()
    print("   Pronto. Me diga se as duas janelas abriram e se cada uma")
    print("   mostrou a sua conta.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        anotar("ERRO: %r" % erro)
        print("\n   A sonda quebrou; o motivo ficou em "
              "relatorios\\sonda_duplicado.txt")
        sys.exit(1)
