"""
SONDA DO PLAYER (01/out/2026) -- com uma musica TOCANDO no celular:

  1. LER: o que o jar (scrcpyf.Midia) ve do player: app, estado, posicao,
     DURACAO (o dumpsys media_session nao traz), titulo, artista;
  2. PAUSAR e TOCAR de novo (a musica para ~2 s) -- confere o estado;
  3. PULAR TRECHO: +20 s e volta -- confere a posicao;
  4. VIGIAR: o modo de pe por 4 s (o que ele escreve sozinho);
  5. BOTOES DAS NOTIFICACOES: o "actions" do `cmd notification get` de cada
     notificacao (para os botoes que abrem tela).

Resultado em relatorios\\sonda_midia.txt.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)

from scrcpyf import celular  # noqa: E402
from scrcpyf.config import Config  # noqa: E402

SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
REL = os.path.join(AQUI, "relatorios")
SAIDA = os.path.join(REL, "sonda_midia.txt")
JAR = os.path.join(AQUI, "android", "scrcpyf-notif.jar")
NO_CEL = "/data/local/tmp/scrcpyf-notif.jar"
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
    anotar("=== SONDA DO PLAYER %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    cfg = Config.carregar()
    adb = str(cfg.adb_exe)
    rodar([adb, "start-server"], 15)
    serial = celular.descobrir(adb, 10) or \
        celular.tentar_reserva(adb, str(cfg.ip_reserva or ""), tentativas=3)
    anotar("celular: %s" % (serial or "-"))
    if not serial:
        print("\n   Nao achei o celular. Conecte e rode de novo.")
        return 1

    def sh(cmd, espera=20):
        return rodar([adb, "-s", serial, "shell", cmd], espera)

    def midia(*args):
        t = time.time()
        s = sh("CLASSPATH=%s app_process / scrcpyf.Midia %s"
               % (NO_CEL, " ".join(args)))
        return s.strip(), (time.time() - t) * 1000

    rodar([adb, "-s", serial, "push", JAR, NO_CEL])
    anotar("")
    anotar("--- 1. LER ---")
    foto, ms = midia("ler")
    marca("ler em %.0f ms" % ms)
    for l in foto.split("\n"):
        anotar("    " + l[:300])
    sessoes = [l.split("\t") for l in foto.split("\n") if l.startswith("M\t")]
    tocando = next((s for s in sessoes if s[2] == "3"), None)
    if not tocando:
        anotar("PAREI: nenhuma musica tocando (estado 3). Toque uma e rode de novo.")
        print("\n   Nenhuma musica tocando. Toque uma no celular e rode de novo.")
        return 1
    pkg = tocando[1]
    anotar("    tocando: %s | %s - %s | %s de %s ms"
           % (pkg, tocando[7], tocando[8], tocando[3], tocando[4]))

    # O modo de pe obedece comandos pela entrada: o mesmo que o programa usa.
    proc = subprocess.Popen([adb, "-s", serial, "shell",
                             "CLASSPATH=%s app_process / scrcpyf.Midia vigiar"
                             % NO_CEL], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            creationflags=SEM_JANELA)
    recebido: list[tuple[float, str]] = []

    def ler():
        for b in proc.stdout:
            recebido.append((time.time() - T0, b.decode("utf-8", "replace").rstrip()))

    threading.Thread(target=ler, daemon=True).start()
    time.sleep(1.5)

    def mandar(cmd):
        proc.stdin.write((cmd + "\n").encode()); proc.stdin.flush()
        marca("-> " + cmd)

    def estado():
        for _t, l in reversed(recebido):
            if l.startswith("M\t" + pkg + "\t"):
                return l.split("\t")
        return None

    anotar("")
    anotar("--- 2. PAUSAR E TOCAR ---")
    mandar("c %s pause" % pkg)
    time.sleep(1.5)
    e = estado()
    marca("depois do pause: estado %s posicao %s" % (e and e[2], e and e[3]))
    mandar("c %s play" % pkg)
    time.sleep(1.5)
    e = estado()
    marca("depois do play: estado %s posicao %s" % (e and e[2], e and e[3]))

    anotar("")
    anotar("--- 3. PULAR TRECHO (+20 s e volta) ---")
    e = estado()
    antes = int(e[3]) if e else 0
    mandar("c %s seek %d" % (pkg, antes + 20000))
    time.sleep(1.5)
    e = estado()
    marca("pediu %d ms; agora %s ms" % (antes + 20000, e and e[3]))
    mandar("c %s seek %d" % (pkg, antes + 1500))
    time.sleep(1.0)

    anotar("")
    anotar("--- 4. O QUE O MODO DE PE ESCREVEU ---")
    time.sleep(2.0)
    proc.stdin.close()
    for t, l in recebido[:40]:
        anotar("    [%5.1f] %s" % (t, l[:200]))

    anotar("")
    anotar("--- 5. BOTOES DAS NOTIFICACOES (actions) ---")
    for k in sh("cmd notification list").split():
        g = sh("cmd notification get '%s' | grep -A12 '^    actions={'" % k)
        if g.strip():
            anotar("  == " + k)
            for l in g.split("\n")[:13]:
                anotar("    " + l[:220])

    anotar("")
    anotar("=== fim em %.1f s ===" % (time.time() - T0))
    sh("rm -f %s" % NO_CEL)
    print("\n   Feito. Resultado em relatorios\\sonda_midia.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
