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
                 endereco: str = "", achados: list | None = None,
                 serial: str = "") -> None:
        self.ok = ok
        self.texto = texto          # o que a tela mostra
        self.modelo = modelo
        self.endereco = endereco    # IP na rede (vai para o config)
        self.achados = achados      # so do `procurar`: a lista para escolher
        self.serial = serial        # quando ja se sabe QUAL serial usar


def _modelo(adb, serial: str) -> str:
    saida = celular._rodar([adb, "-s", serial, "shell", "getprop",
                            "ro.product.model"], espera=8)
    linhas = [x.strip() for x in saida.splitlines()
              if x.strip() and not x.strip().lower().startswith("error:")]
    return linhas[0] if linhas else ""


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

    modelo, id_cabo = _identidade(adb, serial)
    modelo = modelo or "celular"
    # (r192) SEM PARAR O ADB: o `tcpip` reinicia o adb DENTRO do celular e
    # derruba tudo que esta aberto nele. Se este celular (mesmo ro.serialno)
    # ja tem conexao sem fio de pe E ela responde, nao ha nada a abrir.
    for s, estado in _seriais(adb):
        if estado == "device" and not _pelo_cabo(s) and \
                _identidade(adb, s)[1] == id_cabo and _responde(adb, s):
            ip = s.split(":")[0] if "._tcp" not in s.lower() else \
                celular.endereco_na_rede(adb, s)
            return Resultado(True, "Pronto: %s já está conectado sem fio. "
                             "Pode tirar o cabo." % modelo, modelo=modelo,
                             endereco=ip, serial=s)
    avisar("%s encontrado. Abrindo a conexão sem fio..." % modelo)
    if parar.is_set():
        return Resultado(False, "Cancelado.")
    # (07/out) a mesma receita do cabo que abre sozinho (espera o adb do
    # celular voltar, insiste e confere a resposta)
    ip, como = abrir_sem_fio(adb, serial, True, avisar, parar)
    log.info("cabo -> sem fio: %s (%s)", ip or "nao", como)
    if parar.is_set():
        return Resultado(False, "Cancelado.")
    if ip:
        return Resultado(
            True, "Pronto: %s conectado sem fio (%s). Pode tirar o cabo."
            % (modelo, ip), modelo=modelo, endereco=ip,
            serial="%s:%d" % (ip, PORTA_SEM_FIO))
    # (limpeza 01/out) PREFERINDO O CABO, o sem fio e um extra: se ele nao
    # ficar pronto, o celular entra em uso pelo cabo mesmo (antes falhava
    # sem Wi-Fi -- em aberto desde o r194).
    if celular.PREFERENCIA == "cabo":
        return Resultado(True, "Pronto: %s em uso pelo cabo (o sem fio não "
                         "ficou pronto: %s)." % (modelo, como),
                         modelo=modelo, serial=serial)
    if como == "celular sem Wi-Fi":
        return Resultado(
            False, "O %s não está no Wi-Fi (não achei o endereço dele na "
            "rede). Ligue o Wi-Fi do celular, na mesma rede do PC, e tente "
            "de novo." % modelo, modelo=modelo)
    return Resultado(
        False, "Achei o %s pelo cabo, mas a conexão sem fio não respondeu. "
        "Confira se ele está na MESMA rede Wi-Fi do PC (não em rede de "
        "convidados, sem VPN) e tente de novo." % modelo, modelo=modelo)


ESPERA_SEM_FIO_S = 15      # (07/out) depois do tcpip, quanto insistir


def _responde(adb, alvo: str) -> bool:
    """O celular RESPONDE por `alvo` (um comando de verdade, nao so a
    conexao aberta: o adb as vezes lista uma conexao morta)."""
    saida = celular._rodar([adb, "-s", alvo, "shell", "echo ok"], espera=6)
    return "ok" in saida.split()


def _conectar(adb, alvo: str) -> bool:
    saida = celular._rodar([adb, "connect", alvo], espera=8).lower()
    return "connected" in saida and "cannot" not in saida and \
        "failed" not in saida


def abrir_sem_fio(adb, serial: str, pode_reiniciar: bool, avisar=None,
                  parar: threading.Event | None = None) -> tuple[str, str]:
    """
    (03/out, pedido dele depois do teste do amigo) O CABO ABRE O SEM FIO
    SOZINHO: com o celular `serial` no cabo, poe a conexao sem fio de pe.
    Primeiro so o `connect` (a porta pode ja estar aberta desde a ultima
    vez -- nao derruba nada); o `tcpip` reinicia o adb DENTRO do celular e
    derruba o que roda nele, entao so com `pode_reiniciar`.

    (07/out, relato dele: "tenho que plugar, tirar, plugar de novo e clicar")
    O `connect` vinha cedo demais: o adb do celular leva uns segundos para
    voltar depois do `tcpip` e as 3 tentativas (~4 s) acabavam antes. Agora:
    espera o cabo voltar, insiste por ESPERA_SEM_FIO_S e so da por pronto
    quando o celular RESPONDE pelo sem fio.
    Devolve (ip, como): ip vazio = nao ficou de pe; `como` vai para o log.
    """
    avisar = avisar or (lambda _t: None)
    ip = ""
    for _vez in range(4):                 # o Wi-Fi pode estar acordando
        ip = _endereco_por_wlan(adb, serial)
        if ip or (parar is not None and parar.is_set()):
            break
        time.sleep(0.8)
    if not ip:
        return "", "celular sem Wi-Fi"
    alvo = "%s:%d" % (ip, PORTA_SEM_FIO)
    if _conectar(adb, alvo) and _responde(adb, alvo):
        return ip, "porta ja estava aberta"
    if not pode_reiniciar:
        return "", "algo no ar pelo cabo; tcpip ficou para depois"
    avisar("Abrindo a conexão sem fio...")
    # uma conexao morta para o mesmo endereco atrapalha o connect novo
    celular._rodar([adb, "disconnect", alvo], espera=5)
    celular._rodar([adb, "-s", serial, "tcpip", str(PORTA_SEM_FIO)],
                   espera=15)
    inicio = time.monotonic()
    # o adb do celular reinicia: o cabo some e volta (ate ~8 s)
    time.sleep(1.5)
    while time.monotonic() - inicio < 8:
        if parar is not None and parar.is_set():
            return "", "cancelado"
        if any(s == serial and e == "device" for s, e in _seriais(adb)):
            break
        time.sleep(0.5)
    avisar("Testando a conexão sem fio com %s..." % ip)
    vez = 0
    while time.monotonic() - inicio < 8 + ESPERA_SEM_FIO_S:
        if parar is not None and parar.is_set():
            return "", "cancelado"
        vez += 1
        if _conectar(adb, alvo) and _responde(adb, alvo):
            return ip, "porta aberta agora (%d tentativa%s)" % (
                vez, "" if vez == 1 else "s")
        time.sleep(1.0)
    return "", "nao respondeu em %s (rede diferente do PC?)" % ip


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
    antes = {s for s, e in _seriais(adb) if e == "device"}
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
    vez = 0
    while time.monotonic() - inicio < ESPERA_DEPOIS_DE_PAREAR_S:
        if parar.is_set():
            return Resultado(False, "Cancelado.")
        # (01/out) E ESTE celular: um sem fio novo na lista, ou o do mesmo
        # IP (antes valia qualquer sem fio -- com outro ja conectado, pegava
        # o outro).
        for s, estado in _seriais(adb):
            if estado != "device" or _pelo_cabo(s):
                continue
            mesmo_ip = s.split(":")[0] == ip
            if s not in antes or mesmo_ip:
                modelo = _modelo(adb, s) or "celular"
                ip_rede = celular.endereco_na_rede(adb, s) or ip
                return Resultado(True, "Pronto: %s conectado sem fio (%s)."
                                 % (modelo, ip_rede), modelo=modelo,
                                 endereco=ip_rede, serial=s)
        # A descoberta automatica as vezes demora: liga direto no endereco
        # que o celular anuncia (a cada ~3 s).
        vez += 1
        if vez % 3 == 1:
            for _nome, servico, anunciado in anuncios(adb):
                if servico.startswith("_adb-tls-connect") and \
                        anunciado.split(":")[0] == ip:
                    celular._rodar([adb, "connect", anunciado], espera=6)
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

# (01/out) ESTADOS de um achado: "pronto" (o adb ja fala com ele), "permitir"
# (no cabo, esperando o "Permitir depuracao USB" no celular) e "parear" (a
# depuracao sem fio dele se anuncia na rede, mas ele nunca foi pareado com
# este PC -- so o codigo resolve).
PRONTO, PERMITIR, PAREAR = "pronto", "permitir", "parear"


class Achado:
    def __init__(self, serial: str, modelo: str, sem_fio: bool,
                 endereco: str, estado: str = PRONTO) -> None:
        self.serial = serial
        self.modelo = modelo or "Celular"
        self.sem_fio = sem_fio      # False = so pelo cabo, ainda
        self.endereco = endereco    # IP na rede, se souber
        self.estado = estado

    @property
    def descricao(self) -> str:
        if self.sem_fio:
            return "%s  ·  sem fio%s" % (
                self.modelo, (" (%s)" % self.endereco) if self.endereco else "")
        return "%s  ·  pelo cabo" % self.modelo


def _identidade(adb, serial: str) -> tuple[str, str]:
    """(modelo, ro.serialno) numa pergunta so."""
    saida = celular._rodar([adb, "-s", serial, "shell",
                            "getprop ro.product.model; getprop ro.serialno"],
                           espera=8)
    linhas = [x.strip() for x in saida.replace("\r", "").split("\n")]
    # (02/out) Conexao caindo: o adb responde "error: closed" e isso virava
    # o nome do celular na lista (log do amigo).
    linhas = [x for x in linhas if x and not x.lower().startswith("error:")]
    return (linhas[0] if linhas else ""), (linhas[1] if len(linhas) > 1 else "")


def anuncios(adb) -> list[tuple[str, str, str]]:
    """
    (01/out) O que a depuracao sem fio dos celulares anuncia na rede (mDNS),
    pelo `adb mdns services`: [(nome, servico, "ip:porta")]. O nome e
    "adb-<ro.serialno>-<sufixo>"; servico "_adb-tls-connect._tcp" (depuracao
    sem fio ligada) ou "_adb-tls-pairing._tcp" (tela "parear com codigo"
    aberta no celular -- o ip:porta e o endereco do parear).
    """
    lista = []
    for linha in celular._rodar([adb, "mdns", "services"],
                                espera=8).replace("\r", "").split("\n"):
        partes = [p.strip() for p in linha.split("\t")]
        if len(partes) >= 3 and partes[1].startswith("_adb-tls-") and \
                re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}:\d{2,5}", partes[2]):
            lista.append((partes[0], partes[1].rstrip("."), partes[2]))
    return lista


def _serial_do_anuncio(nome: str) -> str:
    m = re.match(r"adb-(.+)-[^-]+$", nome)
    return m.group(1) if m else ""


def endereco_de_parear(adb, ip: str = "") -> str:
    """O "ip:porta" que a tela "parear com codigo" do celular anuncia (o do
    `ip` primeiro, se dado); vazio se nenhuma esta aberta."""
    abertos = [e for _n, s, e in anuncios(adb)
               if s.startswith("_adb-tls-pairing")]
    for endereco in abertos:
        if endereco.split(":")[0] == ip:
            return endereco
    return abertos[0] if abertos else ""


def nome_guardado(serialno: str) -> str:
    """O modelo de um celular ja usado neste PC (guardado pelo programa em
    dados\\celulares\\<id>\\modelo.txt), para dar nome a quem ainda nao
    conectou."""
    if not serialno:
        return ""
    try:
        from . import caminhos
        arquivo = caminhos.pasta_dados() / "celulares" / serialno / "modelo.txt"
        return arquivo.read_text(encoding="utf-8").strip()[:40]
    except Exception:
        return ""


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

    # (01/out) Quem se anuncia na rede mas o adb nao conhece: primeiro um
    # `adb connect` (ja pareado e o adb ainda nao ligou sozinho = entra
    # aqui); quem nao entrar e porque nunca foi pareado com este PC.
    ligados = {s for s, e in vistos.items() if e == "device"}
    ips_ligados = {s.split(":")[0] for s in ligados
                   if ":" in s and "._tcp" not in s.lower()}
    candidatos = []
    for nome, servico, endereco in anuncios(adb):
        if servico.startswith("_adb-tls-connect") and \
                not any(s.startswith(nome) for s in ligados) and \
                endereco.split(":")[0] not in ips_ligados:
            candidatos.append((nome, endereco))
    if candidatos:
        avisar("Conferindo celulares na rede...")
    for nome, endereco in candidatos:
        if parar.is_set():
            return Resultado(False, "Cancelado.")
        celular._rodar([adb, "connect", endereco], espera=6)
    if candidatos:
        for s, estado in _seriais(adb):
            vistos[s] = estado

    achados: list[Achado] = []
    por_modelo: dict[str, Achado] = {}
    autorizar = False
    conhecidos: set[str] = set()     # ro.serialno de quem o adb ja fala
    ips: set[str] = set()
    for serial, estado in vistos.items():
        if estado == "unauthorized":
            autorizar = True
            if _pelo_cabo(serial):
                achados.append(Achado(serial, nome_guardado(serial), False,
                                      "", PERMITIR))
        if estado != "device":
            continue
        sem_fio = not _pelo_cabo(serial)
        modelo, serialno = _identidade(adb, serial)
        conhecidos.add(serialno or serial)
        if not sem_fio:
            conhecidos.add(serial)
        endereco = (serial.split(":")[0]
                    if sem_fio and "._tcp" not in serial.lower()
                    else _endereco_por_wlan(adb, serial))
        ips.add(endereco)
        achado = Achado(serial, modelo, sem_fio, endereco)
        # O mesmo celular pode aparecer duas vezes (cabo E sem fio): fica a
        # entrada da conexao PREFERIDA (r192), que e a que o programa usa.
        antigo = por_modelo.get(achado.modelo)
        if antigo is not None:
            if sem_fio != antigo.sem_fio and \
                    sem_fio == (celular.PREFERENCIA != "cabo"):
                achados[achados.index(antigo)] = achado
                por_modelo[achado.modelo] = achado
            continue
        por_modelo[achado.modelo] = achado
        achados.append(achado)

    # Os que seguem so anunciados: precisam do codigo de pareamento.
    vistos_pareando = set()
    for nome, endereco in candidatos:
        serialno = _serial_do_anuncio(nome)
        ip = endereco.split(":")[0]
        if (serialno and serialno in conhecidos) or ip in ips or \
                (serialno or ip) in vistos_pareando:
            continue
        vistos_pareando.add(serialno or ip)
        achados.append(Achado(nome, nome_guardado(serialno), True, ip,
                              PAREAR))

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
