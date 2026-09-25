"""
Achar o celular pelo ADB.

Esta e a unica copia desta logica. Na versao de scripts ela existia DUAS vezes
-- uma em VBScript, outra em PowerShell -- e as duas precisavam ser corrigidas
juntas toda vez.

PERGUNTAR EM VEZ DE DECORAR
---------------------------
O caminho principal e perguntar ao ADB quem esta acessivel agora e usar o que
ele achar. Isso sobrevive ao roteador trocar o endereco do celular e ao modo de
porta fixa cair sozinho -- os dois motivos pelos quais a versao que decorava um
endereco falhava. O endereco guardado entra so como reserva.

ORDEM DE PREFERENCIA
--------------------
Sem fio pareado > por endereco > cabo USB. Com o cabo plugado junto (carregando,
por exemplo), o Wi-Fi continua sendo o escolhido, e o `-s` na linha do scrcpy
evita o erro de "mais de um dispositivo".

O REINICIO DO SERVIDOR E O ULTIMO RECURSO
------------------------------------------
`kill-server` derruba QUALQUER sessao em andamento, inclusive a do outro perfil
rodando ao mesmo tempo. Por isso as tentativas normais vem antes, e o reinicio
so acontece quando nada foi encontrado.
"""

from __future__ import annotations

import logging
import subprocess
import time

log = logging.getLogger(__name__)

# Sem isto, cada chamada de linha de comando pisca um console preto na tela.
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _rodar(argumentos, espera=20) -> str:
    """Roda um comando oculto e devolve a saida. Nunca levanta excecao."""
    # (r179) Sem scrcpy ainda (adb = None): nada a rodar. Antes cada procura
    # da abertura tentava e anotava um aviso por segundo no relatorio.
    if not argumentos or not argumentos[0]:
        return ""
    try:
        saida = subprocess.run(
            [str(a) for a in argumentos],
            capture_output=True, text=True, timeout=espera,
            creationflags=SEM_JANELA,
        )
        return (saida.stdout or "") + (saida.stderr or "")
    except Exception as erro:
        log.warning("comando falhou (%s): %s", argumentos[0], erro)
        return ""


def escolher_serial(texto: str) -> str:
    """
    Le a saida do `adb devices` e devolve o melhor candidato pronto pra uso.
    Vazio quando nao ha nenhum.
    """
    sem_fio = por_endereco = por_cabo = ""
    for linha in (texto or "").replace("\r", "").split("\n"):
        partes = linha.split("\t")
        if len(partes) < 2:
            continue
        serial, estado = partes[0].strip(), partes[1].strip()
        if estado != "device" or not serial:
            continue
        if "_adb-tls-connect._tcp" in serial.lower():
            sem_fio = sem_fio or serial
        elif ":" in serial:
            por_endereco = por_endereco or serial
        else:
            por_cabo = por_cabo or serial
    return sem_fio or por_endereco or por_cabo


def descobrir(adb, tentativas: int = 3) -> str:
    """
    Pergunta ao ADB quem esta acessivel. Tenta mais de uma vez porque a
    descoberta automatica leva alguns segundos quando o servidor acabou de
    subir.
    """
    for numero in range(1, tentativas + 1):
        escolhido = escolher_serial(_rodar([adb, "devices"]))
        if escolhido:
            return escolhido
        if numero < tentativas:
            time.sleep(1)
    return ""


def responde(ip: str) -> bool:
    """
    O celular responde nesse endereco? Desiste em menos de 2 segundos, no lugar
    dos muitos que o `adb connect` leva pra desistir sozinho.

    Duas tentativas porque o primeiro pacote as vezes se perde -- e um falso
    negativo aqui vira um "nao achei o celular" com o celular na rede.
    """
    for _ in range(2):
        try:
            fim = subprocess.run(
                ["ping", "-n", "1", "-w", "700", ip],
                capture_output=True, timeout=5, creationflags=SEM_JANELA,
            )
            if fim.returncode == 0:
                return True
        except Exception:
            return False
    return False


def tentar_reserva(adb, ip: str, porta: str = "5555", tentativas: int = 1) -> str:
    """Tenta o endereco guardado. O teste de alcance vem antes so pra nao
    pagar a espera longa de um `adb connect` num endereco morto."""
    if not ip:
        return ""
    if not responde(ip):
        return ""
    _rodar([adb, "connect", "%s:%s" % (ip, porta)])
    return descobrir(adb, tentativas)


def aquecer(adb) -> None:
    """
    Acorda o servidor do ADB assim que o programa abre, sem esperar ninguem
    clicar.

    POR QUE (20/set/2026): o relatorio dele mostrou o mesmo padrao tres vezes
    -- o primeiro "Ligar" depois de abrir dizia "nao achei o celular", e o
    clique seguinte, segundos depois, subia na hora. O servidor do ADB
    descobre o celular sem fio pela rede (mDNS), e isso leva alguns segundos
    DEPOIS de ele subir. Quem pagava essa espera era o primeiro clique.
    Agora ela acontece enquanto a janela abre, e o primeiro clique ja acha.

    Roda numa thread de quem chama; nunca levanta excecao.
    """
    _rodar([adb, "start-server"], espera=15)
    _rodar([adb, "devices"], espera=15)


def achar(adb, ip_reserva: str = "", anotar=None) -> str:
    """
    O caminho completo: descoberta, reserva, e -- so se nada aparecer --
    reinicio do servidor do ADB. Devolve o serial escolhido, ou vazio.

    `anotar` e uma funcao opcional que recebe cada passo em texto, pra quem
    quiser montar um relatorio.
    """
    def diga(txt):
        log.info(txt)
        if anotar:
            anotar(txt)

    alvo = descobrir(adb, 3)
    if alvo:
        diga("achado na primeira olhada: %s" % alvo)
        return alvo

    alvo = tentar_reserva(adb, ip_reserva, tentativas=1)
    if alvo:
        diga("achado pelo endereco de reserva: %s" % alvo)
        return alvo

    # Barato e sem derrubar nada: so limpa entradas mortas que o ADB ainda
    # acha que existem. As vezes e so isso que falta.
    _rodar([adb, "reconnect", "offline"], espera=10)
    alvo = descobrir(adb, 2)
    if alvo:
        diga("achado depois de limpar as conexoes mortas: %s" % alvo)
        return alvo

    diga("nada acessivel; reiniciando o servidor do ADB")
    _rodar([adb, "kill-server"])
    _rodar([adb, "start-server"])

    # PACIENCIA AQUI (20/set/2026): eram 8 olhadas (~8 s) e nao bastavam --
    # a descoberta pela rede levava mais, e o clique seguinte achava na hora.
    alvo = descobrir(adb, 18)
    if alvo:
        diga("achado depois do reinicio: %s" % alvo)
        return alvo

    alvo = tentar_reserva(adb, ip_reserva, tentativas=2)
    if alvo:
        diga("achado pela reserva depois do reinicio: %s" % alvo)
        return alvo

    diga("nao achei o celular")
    return ""


def achar_rapido(adb, ip_reserva: str = "") -> str:
    """
    (r159) So o caminho curto -- descoberta (ate ~5 s: logo depois de o
    servidor do ADB subir o celular sem fio ainda esta aparecendo) e o
    endereco de reserva. SEM reiniciar o servidor: quem chama (o atalho da
    area de trabalho) prefere dizer "nao conectado" a ficar esperando.
    """
    return descobrir(adb, 6) or tentar_reserva(adb, ip_reserva)


def endereco_na_rede(adb, serial: str) -> str:
    """
    O endereco do celular na rede, perguntado pra ele mesmo. Serve pra manter o
    endereco de reserva atualizado sem ninguem digitar nada.
    """
    if ":" in serial and not serial.lower().endswith("._tcp"):
        return serial.split(":")[0]
    saida = _rodar([adb, "-s", serial, "shell", "ip", "route"])
    for linha in saida.replace("\r", "").split("\n"):
        partes = linha.split()
        if "src" in partes:
            try:
                return partes[partes.index("src") + 1]
            except IndexError:
                pass
    return ""
