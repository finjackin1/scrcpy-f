"""
SONDA DAS NOTIFICACOES (01/out/2026) -- confere no celular o caminho que o
scrcpy-f usa (`scrcpyf\\notificacoes.py`):

  1. LER: `cmd notification list` + `cmd notification get` (titulo e texto);
  2. EVENTOS: as linhas do logcat de eventos (chegou/saiu);
  3. BLOQUEADOS: "AppSettings: ... importance=NONE" do dumpsys notification;
  4. REMOVER: tira de verdade UMA notificacao comum (limpavel, de app, nao
     fixa) pelo jar scrcpyf-notif e confere se saiu.

Resultado em relatorios\\sonda_notif.txt. So le, menos o passo 4
(`--sem-remover` pula ele).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)

from scrcpyf import celular, notificacoes  # noqa: E402
from scrcpyf.config import Config  # noqa: E402

SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
REL = os.path.join(AQUI, "relatorios")
SAIDA = os.path.join(REL, "sonda_notif.txt")
JAR = os.path.join(AQUI, "android", "scrcpyf-notif.jar")
NO_CEL = notificacoes.JAR_NO_CELULAR
T0 = time.time()
linhas: list[str] = []


def anotar(texto: str = "") -> None:
    linhas.append(texto)
    os.makedirs(REL, exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arq:
        arq.write("\n".join(linhas) + "\n")


def marca(texto: str) -> None:
    anotar("[%6.1f s] %s" % (time.time() - T0, texto))


def rodar(args, espera=20) -> str:
    try:
        r = subprocess.run([str(a) for a in args], capture_output=True,
                           timeout=espera, creationflags=SEM_JANELA)
        return ((r.stdout or b"") + (r.stderr or b"")).decode(
            "utf-8", errors="replace").replace("\r", "")
    except Exception as erro:
        return "FALHOU: %s" % erro


def main() -> int:
    anotar("=== SONDA DAS NOTIFICACOES %s ===" %
           time.strftime("%d/%m/%Y %H:%M:%S"))
    cfg = Config.carregar()
    adb = str(cfg.adb_exe)
    rodar([adb, "start-server"], 15)
    serial = celular.descobrir(adb, 10) or \
        celular.tentar_reserva(adb, str(cfg.ip_reserva or ""), tentativas=3)
    anotar("celular: %s" % (serial or "-"))
    if not serial:
        anotar("PAREI: nenhum celular conectado")
        print("\n   Nao achei o celular. Conecte (cabo ou sem fio) e rode de novo.")
        return 1

    def sh(cmd, espera=20):
        return rodar([adb, "-s", serial, "shell", cmd], espera)

    anotar("android %s (sdk %s), %s" % (
        sh("getprop ro.build.version.release").strip(),
        sh("getprop ro.build.version.sdk").strip(),
        sh("getprop ro.product.model").strip()))

    anotar("")
    anotar("--- 1. LER ---")
    t = time.time()
    chaves = [x.strip() for x in sh("cmd notification list").split("\n")
              if x.strip().count("|") >= 4]
    marca("list: %d chaves em %.0f ms" % (len(chaves), (time.time() - t) * 1000))
    ativas = []
    for chave in chaves:
        g = sh("cmd notification get '%s' | sed -n -e '/^  uid=/p' "
               "-e '/^  flags=/p' -e '/^    when=/p' "
               "-e '/^    extras={/,/^    }/p'" % chave.replace("'", "'\\''"))
        n = notificacoes.ler_detalhe(chave, g)
        if n is None:
            anotar("    %s -> nao li" % chave)
            continue
        ativas.append(n)
        anotar("    %s | %s | %s | fixa=%s limpavel=%s resumo=%s" % (
            n.app, n.titulo[:50], n.texto[:60].replace("\n", " / "), n.fixa,
            n.limpavel, n.resumo))

    anotar("")
    anotar("--- 2. EVENTOS (ultimos do buffer) ---")
    ev = sh("logcat -b events -d -t 300 | grep -E "
            "'notification_(enqueue|cancel)' | tail -n 8")
    for linha in ev.strip().split("\n"):
        tipo, chave = notificacoes.ler_evento(linha)
        anotar("    %s %s" % (tipo or "?", chave or linha[:100]))

    anotar("")
    anotar("--- 3. BLOQUEADOS NO CELULAR ---")
    bloq = notificacoes.ler_bloqueados(sh(
        "dumpsys notification | grep 'AppSettings:' | grep 'importance=NONE'",
        40))
    anotar("    %d apps: %s" % (len(bloq), ", ".join(sorted(bloq))))

    anotar("")
    anotar("--- 4. REMOVER UMA NOTIFICACAO COMUM ---")
    alvo = None if "--sem-remover" in sys.argv else next(
        (n for n in ativas if n.limpavel and not n.fixa and not n.resumo and
         n.pacote not in ("android", "com.android.systemui")), None)
    if alvo is None:
        anotar("    nenhuma para testar (ou --sem-remover)")
    else:
        anotar("    alvo: %s | %s" % (alvo.app, alvo.titulo[:60]))
        rodar([adb, "-s", serial, "push", JAR, NO_CEL])
        saida = sh("CLASSPATH=%s app_process / scrcpyf.Notif remover '%s'"
                   % (NO_CEL, alvo.chave.replace("'", "'\\''")))
        marca("jar: %s" % saida.strip()[:300])
        depois = sh("cmd notification list")
        anotar("    depois: %s" % ("FORA da lista" if alvo.chave not in depois
                                   else "AINDA na lista"))
        sh("rm -f %s" % NO_CEL)

    anotar("")
    anotar("=== fim em %.1f s ===" % (time.time() - T0))
    print("\n   Feito. Resultado em relatorios\\sonda_notif.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
