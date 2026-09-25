"""
Deixar o celular pronto para o scrcpy-f: a pasta do scrcpy e a conexao.

E a parte de "fazer" do Configurar (`configurar.py` desenha, isto aqui age).
Separado da tela de proposito: da para testar sem janela nenhuma e, se um dia
a tela mudar, a receita continua a mesma.

A REGRA DA CONEXAO (pedido dele, 19/set/2026): pelo cabo OU por codigo, o fim
tem que ser o celular falando SEM FIO com o PC. O cabo e so o jeito de chegar
la: com ele o PC ganha a autorizacao do celular, abre a porta sem fio
(`adb tcpip 5555`), descobre o endereco do celular na rede e confirma que a
conexao sem fio responde. So entao o endereco e dado como bom e guardado --
e ele que o programa usa como reserva quando a descoberta automatica falha.
Mesma receita do antigo `scrcpy_ativar_wifi.ps1`, agora sem console.

Todas as funcoes aqui DEMORAM (esperam o celular) e sao chamadas numa thread.
Elas contam o que estao fazendo por `avisar(texto)` e param cedo se o evento
`parar` for ligado (a pessoa fechou a janela no meio).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path

from . import celular

log = logging.getLogger(__name__)

PORTA_SEM_FIO = 5555
ESPERA_DO_CABO_S = 90
ESPERA_DEPOIS_DE_PAREAR_S = 20

# Onde o scrcpy e baixado (a pagina da ultima versao, com os arquivos de
# cada sistema; o de Windows e o "scrcpy-win64-...zip").


# ---------------------------------------------------------------------------
# A pasta do scrcpy
# ---------------------------------------------------------------------------

ARQUIVOS_NECESSARIOS = ("scrcpy.exe", "adb.exe", "scrcpy-server")


def conferir_pasta(pasta) -> tuple[bool, str]:
    """
    A pasta tem o que o programa precisa? Devolve (ok, texto para a tela).
    Aceita tambem a pasta DE CIMA da que tem os arquivos -- quem extrai um
    zip no Windows costuma ganhar uma pasta dentro de outra.
    """
    if not pasta:
        return False, "Nenhuma pasta escolhida ainda."
    pasta = Path(pasta)
    if not pasta.is_dir():
        return False, "Essa pasta não existe mais."
    faltando = [n for n in ARQUIVOS_NECESSARIOS if not (pasta / n).exists()]
    if not faltando:
        return True, "Tudo certo: o scrcpy está nessa pasta."
    if len(faltando) == len(ARQUIVOS_NECESSARIOS):
        return False, ("O scrcpy não está nessa pasta. Escolha a pasta onde "
                       "você extraiu o zip (a que tem o scrcpy.exe).")
    return False, ("A pasta do scrcpy está incompleta: falta %s. Extraia o "
                   "zip de novo, inteiro." % ", ".join(faltando))


def achar_pasta_dentro(pasta):
    """A propria pasta, ou a unica subpasta que tem o scrcpy.exe dentro."""
    pasta = Path(pasta)
    if (pasta / "scrcpy.exe").exists():
        return pasta
    try:
        dentro = [p for p in pasta.iterdir()
                  if p.is_dir() and (p / "scrcpy.exe").exists()]
    except Exception:
        dentro = []
    return dentro[0] if len(dentro) == 1 else pasta


# ---------------------------------------------------------------------------
# A conexao
# ---------------------------------------------------------------------------

class Resultado:
    def __init__(self, ok: bool, texto: str, modelo: str = "",
                 endereco: str = "", achados: list | None = None) -> None:
        self.ok = ok
        self.texto = texto          # o que a tela mostra
        self.modelo = modelo
        self.endereco = endereco    # IP na rede (vai para o config)
        self.achados = achados      # so do `procurar`: a lista para escolher


def _modelo(adb, serial: str) -> str:
    saida = celular._rodar([adb, "-s", serial, "shell", "getprop",
                            "ro.product.model"], espera=8)
    return saida.strip().splitlines()[0].strip() if saida.strip() else ""


def _endereco_por_wlan(adb, serial: str) -> str:
    """O IP do Wi-Fi do celular. Duas perguntas, porque cada Android responde
    a uma delas (a mesma dupla do script antigo)."""
    ip = celular.endereco_na_rede(adb, serial)
    if ip:
        return ip
    saida = celular._rodar([adb, "-s", serial, "shell", "ip", "-f", "inet",
                            "addr", "show", "wlan0"], espera=8)
    m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", saida)
    return m.group(1) if m else ""


def _seriais(adb) -> list[tuple[str, str]]:
    """[(serial, estado)] do `adb devices`."""
    saida = celular._rodar([adb, "devices"], espera=10)
    lista = []
    for linha in saida.replace("\r", "").split("\n")[1:]:
        partes = linha.split("\t")
        if len(partes) >= 2 and partes[0].strip():
            lista.append((partes[0].strip(), partes[1].strip()))
    return lista


def _pelo_cabo(serial: str) -> bool:
    return ":" not in serial and "._tcp" not in serial.lower()


def conectar_pelo_cabo(adb, avisar, parar: threading.Event) -> Resultado:
    """
    Com o celular no cabo: espera ele aparecer (e ser autorizado), abre a
    porta sem fio, acha o IP e CONFIRMA que a conexao sem fio responde.
    """
    celular._rodar([adb, "start-server"], espera=15)
    inicio = time.monotonic()
    serial = ""
    avisou_autorizar = False
    while not serial:
        if parar.is_set():
            return Resultado(False, "Cancelado.")
        passados = int(time.monotonic() - inicio)
        if passados >= ESPERA_DO_CABO_S:
            return Resultado(
                False, "Não achei o celular pelo cabo. Confira: o cabo passa "
                "dados (não só carga)? A Depuração USB está ligada? O aviso "
                "no celular foi aceito?")
        for s, estado in _seriais(adb):
            if not _pelo_cabo(s):
                continue
            if estado == "device":
                serial = s
                break
            if estado == "unauthorized" and not avisou_autorizar:
                avisou_autorizar = True
                avisar("No celular, toque em Permitir no aviso \"Permitir "
                       "depuração USB?\" (marque \"Sempre permitir\").")
        if not serial:
            if not avisou_autorizar:
                avisar("Esperando o celular pelo cabo... %ds" % passados)
            time.sleep(0.8)

    modelo = _modelo(adb, serial) or "celular"
    avisar("%s encontrado. Abrindo a conexão sem fio..." % modelo)
    celular._rodar([adb, "-s", serial, "tcpip", str(PORTA_SEM_FIO)],
                   espera=15)
    time.sleep(1.5)
    if parar.is_set():
        return Resultado(False, "Cancelado.")

    avisar("Procurando o endereço do celular na rede...")
    ip = ""
    for _vez in range(5):
        ip = _endereco_por_wlan(adb, serial)
        if ip:
            break
        time.sleep(0.8)
    if not ip:
        return Resultado(
            False, "O %s não está no Wi-Fi (não achei o endereço dele na "
            "rede). Ligue o Wi-Fi do celular, na mesma rede do PC, e tente "
            "de novo." % modelo, modelo=modelo)

    avisar("Testando a conexão sem fio com %s..." % ip)
    for _vez in range(3):
        saida = celular._rodar([adb, "connect", "%s:%d" % (ip, PORTA_SEM_FIO)],
                               espera=10)
        if "connected" in saida.lower() and "cannot" not in saida.lower():
            return Resultado(
                True, "Pronto: %s conectado sem fio (%s). Pode tirar o cabo."
                % (modelo, ip), modelo=modelo, endereco=ip)
        time.sleep(1.0)
    return Resultado(
        False, "Achei o %s pelo cabo, mas a conexão sem fio não respondeu "
        "em %s. Confira se ele está na MESMA rede Wi-Fi do PC (não em rede "
        "de convidados, sem VPN) e tente de novo." % (modelo, ip),
        modelo=modelo, endereco=ip)


def parear_por_codigo(adb, endereco: str, codigo: str, avisar,
                      parar: threading.Event) -> Resultado:
    """
    Depuracao sem fio do Android 11+: `adb pair` com o endereco e o codigo
    que a tela do celular mostra, e depois espera o celular aparecer.
    """
    endereco = (endereco or "").strip().replace(" ", "")
    codigo = re.sub(r"\D", "", codigo or "")
    if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}:\d{2,5}", endereco):
        return Resultado(False, "O endereço tem que ser como aparece no "
                         "celular: números com pontos, dois-pontos e a porta "
                         "(ex.: 192.168.0.10:37123).")
    if len(codigo) != 6:
        return Resultado(False, "O código de pareamento tem 6 números.")

    celular._rodar([adb, "start-server"], espera=15)
    avisar("Pareando com %s..." % endereco)
    saida = celular._rodar([adb, "pair", endereco, codigo], espera=20)
    if "success" not in saida.lower():
        return Resultado(
            False, "O celular recusou o pareamento. O código e o endereço "
            "mudam cada vez que aquela tela abre: confira se são os que "
            "estão na tela AGORA e tente de novo.")

    ip = endereco.split(":")[0]
    avisar("Pareado. Esperando o celular aparecer sem fio...")
    inicio = time.monotonic()
    while time.monotonic() - inicio < ESPERA_DEPOIS_DE_PAREAR_S:
        if parar.is_set():
            return Resultado(False, "Cancelado.")
        for s, estado in _seriais(adb):
            if estado == "device" and not _pelo_cabo(s):
                modelo = _modelo(adb, s) or "celular"
                ip_rede = celular.endereco_na_rede(adb, s) or ip
                return Resultado(True, "Pronto: %s conectado sem fio (%s)."
                                 % (modelo, ip_rede), modelo=modelo,
                                 endereco=ip_rede)
        time.sleep(1.0)
    # Pareado mas a descoberta automatica nao achou: o programa acha depois
    # (ela as vezes demora), e o endereco fica de reserva.
    return Resultado(True, "Pareado. O celular ainda não apareceu sem fio, "
                     "mas o programa procura sozinho ao ligar.",
                     endereco=ip)


# ---------------------------------------------------------------------------
# Procurar o que ja esta conectado (pedido dele, 19/set/2026: "escanear pra
# ver se ja tem algum celular conectado e usar ele invez de precisar parear
# de novo")
# ---------------------------------------------------------------------------

class Achado:
    def __init__(self, serial: str, modelo: str, sem_fio: bool,
                 endereco: str) -> None:
        self.serial = serial
        self.modelo = modelo or "Celular"
        self.sem_fio = sem_fio      # False = so pelo cabo, ainda
        self.endereco = endereco    # IP na rede, se souber

    @property
    def descricao(self) -> str:
        if self.sem_fio:
            return "%s  ·  sem fio%s" % (
                self.modelo, (" (%s)" % self.endereco) if self.endereco else "")
        return "%s  ·  pelo cabo" % self.modelo


def procurar(adb, ip_reserva: str, avisar,
             parar: threading.Event) -> Resultado:
    """
    Quem o PC ja alcanca, sem parear nada: o que o adb ja conhece, o que o
    Android anuncia sozinho na rede (a descoberta automatica leva uns
    segundos depois de o servidor subir, dai as duas olhadas) e o ultimo
    endereco que funcionou.
    """
    celular._rodar([adb, "start-server"], espera=15)
    if ip_reserva:
        avisar("Tentando o último celular (%s)..." % ip_reserva)
        celular._rodar([adb, "connect", "%s:%d" % (ip_reserva, PORTA_SEM_FIO)],
                       espera=6)
    vistos: dict[str, str] = {}
    for olhada in range(3):
        if parar.is_set():
            return Resultado(False, "Cancelado.")
        avisar("Procurando celulares... (%d de 3)" % (olhada + 1))
        for s, estado in _seriais(adb):
            vistos[s] = estado
        if any(e == "device" for e in vistos.values()) and olhada >= 1:
            break
        time.sleep(1.5)

    achados: list[Achado] = []
    por_modelo: dict[str, Achado] = {}
    autorizar = False
    for serial, estado in vistos.items():
        if estado == "unauthorized":
            autorizar = True
        if estado != "device":
            continue
        sem_fio = not _pelo_cabo(serial)
        modelo = _modelo(adb, serial)
        endereco = (serial.split(":")[0]
                    if sem_fio and "._tcp" not in serial.lower()
                    else _endereco_por_wlan(adb, serial))
        achado = Achado(serial, modelo, sem_fio, endereco)
        # O mesmo celular pode aparecer duas vezes (cabo E sem fio): fica a
        # entrada sem fio, que e a que o programa usa.
        antigo = por_modelo.get(achado.modelo)
        if antigo is not None:
            if sem_fio and not antigo.sem_fio:
                achados[achados.index(antigo)] = achado
                por_modelo[achado.modelo] = achado
            continue
        por_modelo[achado.modelo] = achado
        achados.append(achado)

    if achados:
        texto = ("Achei %d celular%s. Escolha qual usar."
                 % (len(achados), "" if len(achados) == 1 else "es"))
        return Resultado(True, texto, achados=achados)
    if autorizar:
        return Resultado(False, "Há um celular no cabo esperando permissão: "
                         "toque em Permitir no aviso da tela dele e procure "
                         "de novo.", achados=[])
    return Resultado(False, "Nenhum celular conectado. Conecte pelo cabo ou "
                     "com o código de pareamento.", achados=[])
