"""
SONDA DO WI-FI DO CELULAR (21/set/2026)

Pergunta: o celular aceita, pelo adb, os modos de Wi-Fi "baixa latencia" e
"alto desempenho"? E, se aceita, eles cortam os picos de atraso?

Mede o ping ao celular em tres rodadas -- normal, baixa latencia, alto
desempenho -- com 1 s entre pings (a pausa e justamente onde o radio do
celular cochila). No fim DEVOLVE os dois modos ao normal.

RODAR COM O ESPELHAMENTO E A EXTENSAO DESLIGADOS: a extensao mantem o radio
acordado sozinha e esconderia a diferenca.

Grava relatorios\\sonda_wifi.txt (substituido a cada sonda).
"""

from __future__ import annotations

import os
import re
import statistics
import subprocess
import sys
import time

# As sondas moram em sondas\; config e relatorios sao os da raiz.
AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)

from scrcpyf import celular  # noqa: E402
from scrcpyf.config import Config  # noqa: E402

PINGS = 40
SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0
SAIDA = os.path.join(AQUI, "relatorios", "sonda_wifi.txt")

linhas: list[str] = []


def anotar(texto: str = "") -> None:
    linhas.append(texto)
    with open(SAIDA, "w", encoding="utf-8") as arq:
        arq.write("\n".join(linhas) + "\n")


def rodar(args, espera=30) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           timeout=espera, creationflags=SEM_JANELA,
                           encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as erro:
        return -1, "falhou: %s" % erro


def medir(ip: str, nome: str) -> dict:
    print("   medindo: %s (%d s)..." % (nome, PINGS))
    _, saida = rodar(["ping", "-n", str(PINGS), "-w", "1000", ip],
                     espera=PINGS * 3 + 10)
    tempos = [int(t) for t in re.findall(r"[=<](\d+)\s*ms", saida)]
    # a linha de resumo do ping tambem tem "=Nms": fica so com as respostas
    tempos = tempos[:PINGS]
    perdidos = PINGS - len(tempos)
    r = {"nome": nome, "n": len(tempos), "perdidos": perdidos}
    if tempos:
        ordenados = sorted(tempos)
        r.update(mediana=statistics.median(tempos),
                 p95=ordenados[min(len(ordenados) - 1,
                                   int(len(ordenados) * 0.95))],
                 pior=max(tempos),
                 acima_50=sum(1 for t in tempos if t > 50))
    anotar("[%s] respostas %d/%d  mediana %s ms  p95 %s ms  PIOR %s ms  "
           "acima de 50 ms: %s" % (
               nome, len(tempos), PINGS, r.get("mediana", "-"),
               r.get("p95", "-"), r.get("pior", "-"), r.get("acima_50", "-")))
    anotar("   tempos: %s" % " ".join(str(t) for t in tempos))
    return r


def main() -> int:
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    anotar("=== SONDA DO WI-FI %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    cfg = Config.carregar()
    adb = cfg.adb_exe
    anotar("adb: %s" % adb)
    serial = celular.achar(adb, cfg.ip_reserva, anotar=anotar)
    if not serial:
        anotar("PAREI: celular nao encontrado")
        print("\n   Nao achei o celular. Ele esta na mesma rede e pareado?")
        return 1
    anotar("celular: %s" % serial)
    sh = [adb, "-s", serial, "shell"]

    _, modelo = rodar(sh + ["getprop", "ro.product.model"])
    _, android = rodar(sh + ["getprop", "ro.build.version.release"])
    anotar("modelo: %s  android: %s" % (modelo, android))

    _, ajuda = rodar(sh + ["cmd", "wifi", "help"])
    anotar("")
    anotar("--- o que o 'cmd wifi' do celular oferece (so o que interessa) ---")
    for linha in ajuda.splitlines():
        if re.search(r"low-latency|hi-perf|power-save|latency", linha, re.I):
            anotar("  " + linha.strip())

    _, rota = rodar(sh + ["ip", "-f", "inet", "addr", "show", "wlan0"])
    achado = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", rota)
    ip = achado.group(1) if achado else (cfg.ip_reserva or "")
    anotar("ip do celular: %s" % (ip or "DESCONHECIDO"))
    if not ip:
        print("\n   Nao descobri o endereco do celular.")
        return 1

    anotar("")
    anotar("--- rodadas ---")
    print()
    normal = medir(ip, "normal")

    modos = [("force-low-latency-mode", "baixa latencia"),
             ("force-hi-perf-mode", "alto desempenho")]
    resultados = [normal]
    aceitos = {}
    for comando, nome in modos:
        cod, saida = rodar(sh + ["cmd", "wifi", comando, "enabled"])
        aceito = cod == 0 and not re.search(
            r"exception|denied|unknown|not allowed|error|permission", saida, re.I)
        aceitos[nome] = aceito
        anotar("pedido '%s enabled': codigo %s, resposta: %s -> %s" % (
            comando, cod, saida or "(vazia)",
            "ACEITO" if aceito else "RECUSADO"))
        if aceito:
            resultados.append(medir(ip, nome))
        rodar(sh + ["cmd", "wifi", comando, "disabled"])
        anotar("   devolvido ao normal (%s disabled)" % comando)

    anotar("")
    anotar("=== FIM %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))

    print()
    print("   RESULTADO")
    for nome, aceito in aceitos.items():
        print("   - modo %s: %s" % (nome, "o celular ACEITOU"
                                     if aceito else "o celular RECUSOU"))
    for r in resultados:
        if "pior" in r:
            print("   - %-16s pior atraso %4s ms, travadas acima de 50 ms: %s"
                  % (r["nome"], r["pior"], r["acima_50"]))
        else:
            print("   - %-16s nenhuma resposta" % r["nome"])
    print()
    print("   Detalhe em relatorios\\sonda_wifi.txt (me avise que eu leio)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        anotar("ERRO: %r" % erro)
        print("\n   A sonda quebrou; o motivo ficou em relatorios\\sonda_wifi.txt")
        sys.exit(1)
