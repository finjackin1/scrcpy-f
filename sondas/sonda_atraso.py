"""
SONDA DO ATRASO (30/set/2026, r200/r201)

Sintoma (palavras dele): "nao e engasgo, e delay" -- jogando PUBG pelo
scrcpy-f a imagem responde atrasada. Pelo cabo fica igual ao sem fio, e o
ritmo dos quadros esta bom (r199), entao a pergunta e ONDE esta o tempo.

Como mede a VOLTA INTEIRA (o que ele sente): liga a "localizacao do
ponteiro" do celular (barra de numeros no topo + cruz no toque), abre as
Configuracoes numa janela do scrcpy, o PC clica na janela (o scrcpy vira
toque) e cronometra ate a faixa de cima da janela mudar na tela do PC.
Mouse -> celular -> desenho -> codificador -> cabo -> decodificacao -> tela
do PC. ~20 medidas por variacao.

(r201) A 1a rodada usou "mostrar toques": a bolinha NAO aparece para toque
injetado (so dedo de verdade) -- tudo saiu "sem medida". A localizacao do
ponteiro reage ao toque injetado (conferido por screencap, 30/set).

Variacoes (uma coisa muda por vez, a partir da "virtual h264" = o jeito do
PUBG em janela propria):
  real      tela do proprio celular (espelhar)
  virtual   tela virtual 1920x1080 (app em janela), h264 16M
  h265      igual a virtual, com h265
  720p      igual a virtual, 1280x720
  baixa     igual a virtual + codificador em prioridade de tempo real e
            sem guardar quadros (--video-codec-options)
  sem_fio   igual a virtual, pelo Wi-Fi (se o celular estiver no sem fio)

Grava relatorios\\sonda_atraso.txt (substituido a cada sonda).
"""

from __future__ import annotations

import ctypes
import os
import statistics
import subprocess
import sys
import time
from ctypes import wintypes

import numpy as np

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)

from scrcpyf import celular  # noqa: E402
from scrcpyf.config import Config  # noqa: E402

SEM_JANELA = 0x08000000
REL = os.path.join(AQUI, "relatorios")
SAIDA = os.path.join(REL, "sonda_atraso.txt")
MEDIDAS = 20            # por variacao
AQUECER = 2             # primeiras medidas descartadas (foco da janela)
LIMITE_S = 1.5          # sem mudanca ate aqui = falhou
# Onde clicar (fracao da janela), alternando: o numero X da barra e a cruz
# mudam a cada toque mesmo se o "apertado" da barra ficar aceso. Altura do
# titulo das Configuracoes (toque sem efeito).
PONTOS = ((0.40, 0.12), (0.60, 0.12))
FAIXA = 0.16            # altura da faixa de cima lida (barra + cruz)
# (r201) Com a tela parada o celular reenvia a imagem retocando a
# qualidade: bytes mudam sem toque nenhum (1a conferencia deu 14 ms, falso).
# Conta so pixel com mudanca FORTE, e exige varios.
FORTE = 120             # soma |dR|+|dG|+|dB| de um pixel
MINIMO_PIXELS = 40

linhas: list[str] = []
T0 = time.time()

u32 = ctypes.WinDLL("user32", use_last_error=True)
g32 = ctypes.WinDLL("gdi32", use_last_error=True)
u32.FindWindowW.restype = wintypes.HWND
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.GetDC.restype = wintypes.HDC
u32.GetDC.argtypes = [wintypes.HWND]
u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
u32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
u32.SetForegroundWindow.argtypes = [wintypes.HWND]
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
g32.CreateCompatibleDC.restype = wintypes.HDC
g32.CreateCompatibleDC.argtypes = [wintypes.HDC]
g32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
g32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
g32.SelectObject.restype = wintypes.HGDIOBJ
g32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
g32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
g32.DeleteDC.argtypes = [wintypes.HDC]
g32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                       ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                       wintypes.DWORD]
g32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                          wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p,
                          wintypes.UINT]
ESQ_DESCE, ESQ_SOBE = 0x0002, 0x0004


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


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
            "utf-8", errors="replace").strip()
    except Exception as erro:
        return "FALHOU: %s" % erro


def esperar_sem_fio(adb, ip_reserva: str) -> tuple[str, str]:
    """(r204) Com o scrcpy-f fechado o adb esta parado: ao subir, o celular
    sem fio leva segundos para aparecer (rodadas 3 e 4 sairam sem Wi-Fi por
    isso). Espera ate ~10 s; sem ele, tenta o endereco de reserva."""
    cabo, sem_fio = seriais(adb)
    fim = time.time() + 10
    while not sem_fio and time.time() < fim:
        time.sleep(1.0)
        cabo, sem_fio = seriais(adb)
    if not sem_fio and ip_reserva:
        alvo = ip_reserva if ":" in ip_reserva else ip_reserva + ":5555"
        try:
            r = subprocess.run([adb, "connect", alvo], capture_output=True,
                               timeout=10, creationflags=SEM_JANELA)
            marca("adb connect %s: %s" % (alvo, (r.stdout or b"").decode(
                "utf-8", errors="replace").strip()))
        except Exception as erro:
            marca("adb connect %s FALHOU: %s" % (alvo, erro))
        time.sleep(1.0)
        cabo, sem_fio = seriais(adb)
    return cabo, sem_fio


def seriais(adb) -> tuple[str, str]:
    """(serial do cabo, serial do sem fio) prontos no adb; vazio se faltar."""
    try:
        r = subprocess.run([adb, "devices"], capture_output=True, timeout=10,
                           creationflags=SEM_JANELA)
        texto = (r.stdout or b"").decode("utf-8", errors="replace")
    except Exception:
        return "", ""
    cabo = sem_fio = ""
    for linha in texto.splitlines()[1:]:
        partes = linha.split()
        if len(partes) >= 2 and partes[1] == "device":
            if celular.e_cabo(partes[0]):
                cabo = cabo or partes[0]
            else:
                sem_fio = sem_fio or partes[0]
    return cabo, sem_fio


class Leitor:
    """Copia uma faixa da tela de uma vez (BitBlt) e devolve os bytes: a
    tela parada nao muda nem um byte, entao qualquer diferenca = chegou a
    imagem do toque. (A captura nao inclui o cursor do mouse.)"""

    def __init__(self, x, y, largura, altura):
        self.x, self.y, self.l, self.a = x, y, largura, altura
        self.tela = u32.GetDC(None)
        self.mem = g32.CreateCompatibleDC(self.tela)
        self.bmp = g32.CreateCompatibleBitmap(self.tela, largura, altura)
        self.velho = g32.SelectObject(self.mem, self.bmp)
        self.info = BITMAPINFOHEADER()
        self.info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        self.info.biWidth, self.info.biHeight = largura, -altura
        self.info.biPlanes, self.info.biBitCount = 1, 32
        self.buf = ctypes.create_string_buffer(largura * altura * 4)

    def ler(self):
        g32.BitBlt(self.mem, 0, 0, self.l, self.a, self.tela, self.x, self.y,
                   0x00CC0020)                         # SRCCOPY
        g32.SelectObject(self.mem, self.velho)
        g32.GetDIBits(self.mem, self.bmp, 0, self.a, self.buf,
                      ctypes.byref(self.info), 0)
        g32.SelectObject(self.mem, self.bmp)
        return np.frombuffer(self.buf.raw, dtype=np.uint8).reshape(
            self.a, self.l, 4)[:, :, :3].astype(np.int16)

    def fechar(self):
        g32.SelectObject(self.mem, self.velho)
        g32.DeleteObject(self.bmp)
        g32.DeleteDC(self.mem)
        u32.ReleaseDC(None, self.tela)


def mudou(base, agora) -> bool:
    fortes = int((np.abs(agora - base).sum(axis=2) >= FORTE).sum())
    return fortes >= MINIMO_PIXELS


def achar_janela(titulo: str, segundos: float = 25):
    fim = time.time() + segundos
    while time.time() < fim:
        h = u32.FindWindowW(None, titulo)
        if h:
            return h
        time.sleep(0.2)
    return None


def medir(hwnd, rotulo: str) -> dict:
    """Clica e cronometra ate a faixa de cima mudar, MEDIDAS vezes."""
    r = wintypes.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(r))
    canto = wintypes.POINT(0, 0)
    u32.ClientToScreen(hwnd, ctypes.byref(canto))
    cliques = [(canto.x + int(r.right * fx), canto.y + int(r.bottom * fy))
               for fx, fy in PONTOS]
    # Faixa da LARGURA TODA. (r202) Tentei estreitar para igualar a
    # precisao entre janelas: no meio e a partir de 70% a deteccao FALHOU
    # (conferencia aqui). A diferenca de precisao vai para o resumo
    # ("corrigida" = mediana - metade da leitura).
    leitor = Leitor(canto.x, canto.y, r.right, max(8, int(r.bottom * FAIXA)))
    marca("%s: janela %dx%d em %d,%d; cliques em %s"
          % (rotulo, r.right, r.bottom, canto.x, canto.y, cliques))
    tempos, falhas, leituras = [], 0, []
    try:
        for i in range(AQUECER + MEDIDAS):
            x, y = cliques[i % len(cliques)]
            u32.SetForegroundWindow(hwnd)
            u32.SetCursorPos(x, y)
            time.sleep(0.35)                 # a tela assenta
            base = leitor.ler()
            t0 = time.perf_counter()
            u32.mouse_event(ESQ_DESCE, 0, 0, 0, 0)
            achou, n = None, 0
            while time.perf_counter() - t0 < LIMITE_S:
                n += 1
                if mudou(base, leitor.ler()):
                    achou = time.perf_counter() - t0
                    break
            u32.mouse_event(ESQ_SOBE, 0, 0, 0, 0)
            if n:
                leituras.append((time.perf_counter() - t0) / n * 1000)
            if i < AQUECER:
                continue
            if achou is None:
                falhas += 1
                marca("%s: medida %d SEM MUDANCA em %.1f s"
                      % (rotulo, i - AQUECER + 1, LIMITE_S))
            else:
                tempos.append(achou * 1000)
            time.sleep(0.45)                 # o toque acaba antes do proximo
    finally:
        leitor.fechar()
    res = {"rotulo": rotulo, "tempos": tempos, "falhas": falhas,
           "leitura_ms": statistics.median(leituras) if leituras else 0}
    if tempos:
        t = sorted(tempos)
        res.update(mediana=statistics.median(t), menor=t[0], maior=t[-1],
                   p90=t[min(len(t) - 1, int(len(t) * 0.9))])
        marca("%s: %s ms" % (rotulo, " ".join("%.0f" % v for v in tempos)))
    return res


def rodar_variacao(scr, adb, serial, rotulo, extras, tela_real) -> dict:
    titulo = "sonda do atraso - %s" % rotulo
    caminho = os.path.join(REL, "sonda_atraso_scrcpy.txt")
    linha = [scr, "-s", serial, "--video-buffer=0", "--no-audio",
             "--always-on-top", "--window-title=%s" % titulo,
             "--print-fps"] + extras
    if tela_real:
        shell(adb, serial, "am start -a android.settings.SETTINGS")
    else:
        linha += ["--new-display=1920x1080/450", "--no-vd-system-decorations",
                  "--start-app=com.android.settings"]
    marca("%s: %s" % (rotulo, " ".join(linha[1:])))
    with open(caminho, "a", encoding="utf-8", errors="replace") as log:
        log.write("\n=== %s ===\n" % rotulo)
        log.flush()
        proc = subprocess.Popen(linha, stdout=log, stderr=subprocess.STDOUT,
                                cwd=os.path.dirname(scr),
                                creationflags=SEM_JANELA)
        try:
            hwnd = achar_janela(titulo)
            if not hwnd:
                marca("%s: a janela NAO abriu" % rotulo)
                return {"rotulo": rotulo, "tempos": [], "falhas": MEDIDAS,
                        "leitura_ms": 0, "erro": "janela nao abriu"}
            time.sleep(3.0)                  # app aberto e imagem de pe
            return medir(hwnd, rotulo)
        finally:
            try:
                proc.terminate()
                proc.wait(5)
            except Exception:
                pass
            time.sleep(1.0)


def main() -> int:
    anotar("=== SONDA DO ATRASO %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    cfg = Config.carregar()
    adb, scr = str(cfg.adb_exe), str(cfg.scrcpy_exe)
    try:
        os.remove(os.path.join(REL, "sonda_atraso_scrcpy.txt"))
    except OSError:
        pass
    cabo, sem_fio = esperar_sem_fio(adb, str(cfg.ip_reserva or ""))
    anotar("cabo: %s | sem fio: %s" % (cabo or "-", sem_fio or "-"))
    if not cabo:
        anotar("PAREI: celular nao esta no cabo")
        print("\n   Nao achei o celular no CABO. Ligue o cabo e rode de novo.")
        return 1
    shell(adb, cabo, "input keyevent KEYCODE_WAKEUP")
    antes = shell(adb, cabo, "settings get system pointer_location")
    anotar("localizacao do ponteiro antes: %s" % antes)
    shell(adb, cabo, "settings put system pointer_location 1")

    # Rodadas anteriores (CONTEXTO r200-r203): no cabo ~72-83 ms; baixa
    # generica, chave QTI da Qualcomm, 120 qps e h265 sem ganho; 720p -6/8.
    # (r204) RODADA 5: so o Wi-Fi, intercalado com o cabo de referencia,
    # para fechar a pergunta TCP x UDP no sem fio.
    normal = ["--video-codec=h264", "--video-bit-rate=16M", "--max-fps=60"]
    if not sem_fio:
        anotar("PAREI: celular nao apareceu no Wi-Fi")
        print("\n   Nao achei o celular no SEM FIO. Ligue a depuracao sem fio")
        print("   no celular (mesmo Wi-Fi do PC) e rode de novo.")
        shell(adb, cabo, "settings put system pointer_location %s"
              % (antes if antes in ("0", "1") else "0"))
        return 1
    variacoes = [
        ("cabo1", cabo, normal, False),
        ("wifi1", sem_fio, normal, False),
        ("cabo2", cabo, normal, False),
        ("wifi2", sem_fio, normal, False),
    ]

    resultados = []
    try:
        for n, (rotulo, serial, extras, real) in enumerate(variacoes, 1):
            print("   %d de %d: %s..." % (n, len(variacoes), rotulo))
            resultados.append(rodar_variacao(scr, adb, serial, rotulo, extras,
                                             real))
    finally:
        valor = antes if antes in ("0", "1") else "0"
        shell(adb, cabo, "settings put system pointer_location %s" % valor)
        shell(adb, cabo, "input keyevent KEYCODE_HOME")
        anotar("localizacao do ponteiro devolvida: %s" % valor)

    anotar("")
    anotar("RESUMO (ms, volta inteira: clique no PC -> imagem do toque no PC)")
    anotar("%-9s %8s %9s %6s %6s %6s %6s %7s" % (
        "variacao", "mediana", "corrigida", "menor", "p90", "maior",
        "falhas", "leitura"))
    print()
    print("   %-9s %8s %6s %6s" % ("", "mediana", "menor", "maior"))
    for r in resultados:
        if r.get("tempos"):
            anotar("%-9s %8.0f %9.0f %6.0f %6.0f %6.0f %6d %6.1f"
                   % (r["rotulo"], r["mediana"],
                      r["mediana"] - r["leitura_ms"] / 2, r["menor"],
                      r["p90"], r["maior"], r["falhas"], r["leitura_ms"]))
            print("   %-9s %6.0f ms %4.0f ms %4.0f ms"
                  % (r["rotulo"], r["mediana"], r["menor"], r["maior"]))
        else:
            anotar("%-9s  SEM MEDIDA (%s)" % (r["rotulo"],
                                              r.get("erro", "nada mudou")))
            print("   %-9s  sem medida" % r["rotulo"])
    anotar("(leitura = ms por leitura da faixa; e a precisao da medida)")
    anotar("=== FIM %s ===" % time.strftime("%d/%m/%Y %H:%M:%S"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        anotar("ERRO: %r" % erro)
        print("\n   A sonda quebrou; o motivo ficou em relatorios\\sonda_atraso.txt")
        sys.exit(1)
