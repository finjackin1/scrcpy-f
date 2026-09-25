"""
SONDA DOS APPS EM JANELA (23/set/2026)

Duas perguntas:
1. Por que o programinha dos icones morre ("Killed") no celular? Roda ele
   com cada passo anotado e le o registro do Android logo depois.
2. Como manter o app PRESO na janela dele? Abre as Configuracoes numa tela
   virtual SEM a area de trabalho do Samsung, anota o numero da tela, olha
   o que o Android diz que esta nela, aperta VOLTAR duas vezes (para o app
   sair) e olha de novo. E tambem guarda a ajuda completa do scrcpy.

Abre uma janela das Configuracoes por uns 10 segundos e fecha sozinha.
Grava relatorios\\sonda_apps.txt (substituido a cada sonda).
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
SAIDA = os.path.join(AQUI, "relatorios", "sonda_apps.txt")
LOG_SCRCPY = os.path.join(AQUI, "relatorios", "sonda_apps_scrcpy.txt")
linhas: list[str] = []


def anotar(texto: str = "") -> None:
    linhas.append(texto)
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arq:
        arq.write("\n".join(linhas) + "\n")


def rodar(args, titulo, limite=80, espera=40):
    t0 = time.perf_counter()
    try:
        r = subprocess.run(args, capture_output=True, timeout=espera,
                           creationflags=SEM_JANELA)
        saida = ((r.stdout or b"") + b"\n" + (r.stderr or b"")).decode(
            "utf-8", errors="replace")
        codigo = r.returncode
    except Exception as erro:
        saida, codigo = "FALHOU: %s" % erro, None
    ms = (time.perf_counter() - t0) * 1000
    anotar("")
    anotar("--- %s  (%.0f ms, codigo %s) ---" % (titulo, ms, codigo))
    todas = [l for l in saida.replace("\r", "").splitlines()]
    for linha in todas[:limite]:
        anotar("  " + linha)
    if len(todas) > limite:
        anotar("  ... (+%d linhas)" % (len(todas) - limite))
    print("   %-44s %5.0f ms" % (titulo, ms))
    return saida


def main() -> int:
    anotar("=== SONDA DOS APPS %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    cfg = Config.carregar()
    adb, scr = str(cfg.adb_exe), str(cfg.scrcpy_exe)
    serial = celular.achar(adb, cfg.ip_reserva, anotar=anotar)
    if not serial:
        anotar("PAREI: celular nao encontrado")
        print("\n   Nao achei o celular.")
        return 1
    anotar("celular: %s" % serial)
    sh = [adb, "-s", serial, "shell"]
    print()

    # 1. o programinha dos icones -----------------------------------------
    jar = os.path.join(AQUI, "android", "scrcpyf-icones.jar")
    rodar([adb, "-s", serial, "push", jar,
           "/data/local/tmp/scrcpyf-icones.jar"], "icones: mandar o jar")
    rodar(sh + ["ls -la /data/local/tmp/"], "icones: pasta no celular")
    rodar(sh + ["logcat -c"], "registro do android: limpar")
    rodar(sh + ["CLASSPATH=/data/local/tmp/scrcpyf-icones.jar app_process "
                "/ scrcpyf.Icones 48 com.android.settings "
                "$(pm list packages -3 | head -8 | cut -d: -f2) "
                "| cut -c1-1800; echo codigo:$?"],
          "icones: rodar com varios apps (sistema + 8 instalados)",
          limite=40)
    rodar(sh + ["logcat -d -t 400 | grep -i -E 'Icones|scrcpyf|AndroidRuntime"
                "|app_process|FATAL|Killing|kill|lowmem|denied|avc' | tail -60"],
          "icones: o que o android registrou", limite=70)
    rodar(sh + ["CLASSPATH=/data/local/tmp/scrcpy-server.jar app_process / "
                "com.genymobile.scrcpy.Server 4.0 2>&1 | head -5; "
                "echo codigo:$?"],
          "comparacao: o servidor do scrcpy nasce?", limite=10)

    # 2. o scrcpy e a tela virtual -----------------------------------------
    # Desligado em 23/set/2026: o voltar-na-raiz ja foi resolvido e a janela
    # preta so confundia. A sonda agora e so dos icones.
    if "--tela" not in sys.argv:
        anotar("")
        anotar("=== FIM (so icones) %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
        print()
        print("   Pronto. O resultado esta em relatorios\\sonda_apps.txt")
        print("   (me avise que eu leio)")
        return 0
    rodar([scr, "--help"], "scrcpy --help", limite=900, espera=20)
    try:
        log = open(LOG_SCRCPY, "w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(
            [scr, "-s", serial, "--new-display", "--no-vd-system-decorations",
             "--start-app=com.android.settings", "--no-audio",
             "--window-title=sonda scrcpy-f", "--verbosity=debug"],
            stdout=log, stderr=subprocess.STDOUT, cwd=os.path.dirname(scr),
            creationflags=SEM_JANELA)
    except Exception as erro:
        anotar("NAO consegui abrir o scrcpy: %s" % erro)
        return 1
    print("   (janela das Configuracoes aberta por uns segundos)")
    time.sleep(6)
    texto = open(LOG_SCRCPY, encoding="utf-8", errors="replace").read()
    m = re.search(r"\(id=(\d+)\)", texto) or re.search(r"display.*?id[= ](\d+)",
                                                      texto, re.I)
    tela = m.group(1) if m else ""
    anotar("")
    anotar("numero da tela virtual lido do log do scrcpy: %r" % tela)
    anotar("--- log do scrcpy ate aqui ---")
    for linha in texto.splitlines()[:60]:
        anotar("  " + linha)

    def olhar(titulo):
        rodar(sh + ["dumpsys activity activities | grep -E 'Display #|"
                    "mResumedActivity|topResumedActivity|\\* Task\\{|"
                    "ActivityRecord|mFocusedApp' | head -60"],
              "activities: " + titulo, limite=70)
        rodar(sh + ["dumpsys window displays | grep -E 'Display: mDisplayId|"
                    "mCurrentFocus|mFocusedApp|mFocusedWindow' | head -30"],
              "window: " + titulo, limite=40)

    olhar("com o app aberto")
    if tela:
        for _ in range(2):
            rodar(sh + ["input -d %s keyevent 4" % tela], "VOLTAR na tela %s"
                  % tela)
            time.sleep(1.2)
        olhar("depois de 2x VOLTAR")
        rodar(sh + ["cmd package resolve-activity --brief "
                    "com.android.settings | tail -1"],
              "a atividade de entrada das Configuracoes")
        rodar(sh + ["am start --display %s -n \"$(cmd package resolve-activity"
                    " --brief com.android.settings | tail -1)\"" % tela],
              "reabrir o app na mesma tela")
        time.sleep(1.5)
        olhar("depois de reabrir")
    try:
        proc.terminate()
        proc.wait(5)
    except Exception:
        pass
    log.close()
    texto = open(LOG_SCRCPY, encoding="utf-8", errors="replace").read()
    anotar("")
    anotar("--- log do scrcpy completo (fim) ---")
    for linha in texto.splitlines()[-40:]:
        anotar("  " + linha)

    anotar("")
    anotar("=== FIM %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    print()
    print("   Pronto. O resultado esta em relatorios\\sonda_apps.txt")
    print("   (me avise que eu leio)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        anotar("ERRO: %r" % erro)
        print("\n   A sonda quebrou; o motivo ficou em relatorios\\sonda_apps.txt")
        sys.exit(1)
