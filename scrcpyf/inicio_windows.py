"""
Iniciar junto com o Windows, pelo Agendador de Tarefas.

Porta do `inicio_windows.py` do LightWireless (que por sua vez veio do
AmbiSync), trocando so o nome da tarefa e os textos. O que cada decisao quer
dizer esta explicado la; o resumo:

- AGENDADOR, E NAO A CHAVE `Run`: a lista de inicializacao comum espera uns
  10 s depois da area de trabalho e abre um programa de cada vez. Tarefa "ao
  fazer logon" nao entra nessa fila.
- UM MECANISMO SO: se o Agendador recusar, `ativar()` devolve False, o botao
  volta sozinho e o motivo vai para o log. Nunca cai para outro caminho.
- SEM ARGUMENTO: quem decide se a janela aparece ao iniciar e a opcao
  `abrir_janela_ao_iniciar` do config, lida pelo proprio programa.
- ADMINISTRADOR SO QUANDO PRECISA: tenta as formas que dispensam elevacao e
  so no fim pede a confirmacao do Windows, por um .bat na pasta `ferramentas`.

Fora do Windows tudo responde sem quebrar: `disponivel()` da False.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

log = logging.getLogger(__name__)

def _nome_da_tarefa() -> str:
    """
    (r179) UM NOME POR COPIA NO PACOTE. O nome era um so por usuario: um
    pacote extraido em outra pasta via a tarefa/linha Run de outra copia e
    mostrava "abrir com o Windows" e "iniciar mais rapido" ja LIGADOS (teste
    dele). Agora o pacote usa "scrcpy-f-<8 letras do caminho do .exe>". Em
    codigo continua "scrcpy-f" (a tarefa da maquina dele).
    """
    if getattr(sys, "frozen", False):
        import hashlib
        caminho = os.path.abspath(sys.executable).lower().encode("utf-8")
        return "scrcpy-f-" + hashlib.sha1(caminho).hexdigest()[:8]
    return "scrcpy-f"


NOME_TAREFA = _nome_da_tarefa()


def _e_windows() -> bool:
    return os.name == "nt"


def disponivel() -> bool:
    """Da para mexer no inicio automatico nesta maquina?"""
    return _e_windows()


def _empacotado() -> bool:
    return bool(getattr(sys, "frozen", False))


# ---------------------------------------------------------------------------
# No .exe empacotado: a lista Run do usuario, e nao o Agendador
# ---------------------------------------------------------------------------
#
# 19/set/2026: o Windows Defender apagou o scrcpy-f.exe como
# "Behavior:Win32/Persistence.A!ml". O que ele viu: um .exe sem assinatura,
# recem-baixado, que chamava o `schtasks` logo ao abrir (so para PERGUNTAR se
# a tarefa existia) e ainda instala gancho de teclado.
#
# No pacote, entao:
# - ABRIR SO LE o registro (winreg, dentro do proprio processo): nenhum
#   programa do Windows e chamado.
# - SO O CLIQUE ESCREVE, na chave Run do PROPRIO usuario (HKCU): sem
#   administrador, sem elevacao, sem .bat.
# - Se o antivirus barrar a escrita, `ativar` devolve False e o botao volta
#   sozinho -- nunca mente que ligou. Saida manual: atalho em shell:startup
#   (LEIA-ME).
# A fila Run espera uns segundos depois da area de trabalho (o motivo de o
# codigo usar o Agendador); no pacote isso e o preco aceito.
# Rodando pelo codigo (a maquina de quem desenvolve) segue o Agendador.

CHAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _run_ler() -> str | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN) as chave:
            valor, _tipo = winreg.QueryValueEx(chave, NOME_TAREFA)
            return str(valor)
    except OSError:
        return None


def _run_ativo() -> bool:
    # So conta se aponta para ESTE .exe: pasta movida = desligado, e o
    # proximo clique regrava com o caminho novo.
    valor = _run_ler()
    return valor is not None and valor.strip().lower() == comando().lower()


def _run_ativar() -> bool:
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN) as chave:
            winreg.SetValueEx(chave, NOME_TAREFA, 0, winreg.REG_SZ, comando())
    except OSError as erro:
        log.warning("nao consegui gravar o inicio com o Windows: %s", erro)
        return False
    ok = _run_ativo()
    log.info("inicio com o Windows (Run) %s: %s",
             "gravado" if ok else "NAO confirmado", comando())
    return ok


def _run_desativar() -> bool:
    if _run_ler() is None:
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN, 0,
                            winreg.KEY_SET_VALUE) as chave:
            winreg.DeleteValue(chave, NOME_TAREFA)
    except OSError as erro:
        log.warning("nao consegui tirar o inicio com o Windows: %s", erro)
        return False
    log.info("inicio com o Windows (Run) removido")
    return _run_ler() is None


def _rodar(argumentos: list[str]) -> tuple[bool, str]:
    """
    Chama o schtasks sem piscar console.

    O app roda em `pythonw` (sem console proprio); sem CREATE_NO_WINDOW cada
    chamada abriria uma janela preta por um instante na cara do usuario.
    """
    if not _e_windows():
        return (False, "nao e Windows")

    try:
        resultado = subprocess.run(
            argumentos,
            capture_output=True,
            text=True,
            timeout=30,            # (r165) schtasks travado nao prende a tela
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as erro:
        return (False, f"{type(erro).__name__}: {erro}")

    saida = (resultado.stdout or "") + (resultado.stderr or "")
    # O schtasks quebra a mensagem em varias linhas; num log de uma linha por
    # evento isso vira sujeira e esconde o motivo real.
    return (resultado.returncode == 0, " ".join(saida.split()))


def comando() -> str:
    """
    Linha de comando que o Windows vai executar no logon.

    Congelado: o proprio .exe. Rodando pelo Python: o `pythonw.exe` ao lado do
    `python.exe` atual, porque `python.exe` abriria uma janela preta de
    console junto com o app -- toda vez que o Windows liga.

    Sem argumento nenhum: quem decide se a janela aparece ou nasce escondida e
    a opcao `abrir_janela_ao_iniciar`, lida do config pelo proprio programa.
    """
    from .caminhos import pasta_do_programa

    if getattr(sys, "frozen", False):
        return f'"{os.path.abspath(sys.executable)}" {ARGUMENTO_INICIO}'

    executavel = os.path.abspath(sys.executable)
    pasta, nome = os.path.split(executavel)

    if nome.lower().startswith("python") and not nome.lower().startswith("pythonw"):
        candidato = os.path.join(pasta, nome.lower().replace("python", "pythonw", 1))
        if os.path.exists(candidato):
            executavel = candidato

    alvo = os.path.join(str(pasta_do_programa()), "app.py")
    return f'"{executavel}" "{alvo}" {ARGUMENTO_INICIO}'


# Quem sobe pelo Windows leva este argumento (padrao da casa, 23/set/2026):
# se ja houver um aberto, sai quieto em vez de chamar o outro para a frente
# -- era a "janela que abre sozinha depois de um tempo" do iniciar mais
# rapido (a tarefa subia o programa e, mais tarde, a fila Run subia outro).
ARGUMENTO_INICIO = "--inicio"


def arrumar() -> None:
    """
    Na abertura: os dois caminhos nunca juntos. Tarefa existe -> a fila Run
    sai; e a linha da Run, se ficou de uma versao velha, e reescrita.
    """
    if not disponivel():
        return
    try:
        if tarefa_existe():
            if _run_ler() is not None:
                _run_desativar()
                log.info("inicio: tarefa e Run juntos -- a Run saiu")
        elif _run_ler() is not None and not _run_ativo():
            _run_ativar()
            log.info("inicio: linha da Run atualizada")
    except Exception as erro:
        log.info("inicio: nao consegui arrumar (%s)", erro)


CHAVE_TAREFAS = (r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule"
                 r"\TaskCache\Tree" + "\\" + NOME_TAREFA)


def _tarefa_no_registro() -> bool:
    """
    A tarefa existe? Lida no registro, DENTRO do processo: no .exe nenhum
    programa do Windows e chamado so para perguntar (a licao do Defender).
    """
    # Visao de 64 bits (o .exe pode ser de 32 e o Windows desviaria para
    # WOW6432Node) e "sem permissao" = a chave EXISTE: a opcao aparecia
    # desmarcada no publicado com a tarefa criada (teste dele, 23/set/2026).
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CHAVE_TAREFAS, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            return True
    except PermissionError:
        return True
    except OSError:
        return False


def _tarefa_existe_qualquer() -> bool:
    """A tarefa existe no Agendador (de qualquer copia do programa)?"""
    if not disponivel():
        return False
    if _empacotado():
        return _tarefa_no_registro()
    ok, _saida = _rodar(["schtasks", "/Query", "/TN", NOME_TAREFA])
    return ok


def tarefa_existe() -> bool:
    """A tarefa DESTA copia existe no Agendador? (o nome ja e da copia,
    r179 -- ler o destino da tarefa no registro exigia administrador.)"""
    return _tarefa_existe_qualquer()


def ativo() -> bool:
    """O app abre sozinho com o Windows (por qualquer um dos dois caminhos)?"""
    if not disponivel():
        return False
    if _empacotado():
        return _run_ativo() or tarefa_existe()
    return tarefa_existe() or _run_ativo()


def rapido() -> bool:
    """Abre pelo Agendador (na hora do logon), e nao pela fila comum?"""
    return tarefa_existe()


def definir_rapido(ligado: bool) -> bool:
    """
    INICIAR MAIS RAPIDO (pedido dele, 21/set/2026): sub-opcao do "abrir com o
    Windows". Ligada = tarefa no Agendador (abre no logon, fora da fila Run
    que espera a area de trabalho); pede administrador, que e o que o
    Windows exige para tarefa de logon. Desligada = volta para a fila Run.
    Os dois caminhos nunca ficam juntos (abriria duas vezes -- a segunda
    instancia so chamaria a primeira, mas e trabalho a toa).
    No .exe e EXATAMENTE o que o Defender estranhou em 19/set; aqui so
    acontece no clique dele, nunca ao abrir.
    """
    if not disponivel():
        return False
    if ligado:
        if not tarefa_existe():
            # Primeiro as formas que dispensam elevacao; so se todas forem
            # recusadas e que aparece a janela do administrador.
            for descricao, argumentos in _variacoes():
                ok, saida = _rodar(argumentos)
                if ok:
                    log.info("tarefa de logon criada [%s]: %s", descricao,
                             comando())
                    break
                log.info("tarefa de logon recusada [%s]: %s", descricao, saida)
        if not tarefa_existe():
            ativar_elevado()
        if tarefa_existe():
            _run_desativar()
            return True
        return False
    if tarefa_existe():
        ok, saida = _rodar(["schtasks", "/Delete", "/TN", NOME_TAREFA, "/F"])
        if not ok:
            log.info("remocao simples recusada: %s", saida)
            desativar_elevado()
    if tarefa_existe():
        return False
    return _run_ativar()


def _nomes_de_usuario() -> list[str]:
    """
    Como escrever o usuario para o `/RU`, do formato mais completo ao mais cru.

    Achado no AmbiSync (26/ago/2026): passar so o nome solto (`finjackin`) da
    "Parametro incorreto (40,4):UserId:" -- o schtasks quer o usuario
    QUALIFICADO, tipo `MAQUINA\\finjackin`, e recusa o nome cru.
    """
    usuario = os.environ.get("USERNAME") or ""
    if not usuario:
        return []

    dominio = os.environ.get("USERDOMAIN") or ""
    computador = os.environ.get("COMPUTERNAME") or ""

    nomes = []
    for prefixo in (dominio, computador):
        if prefixo:
            qualificado = f"{prefixo}\\{usuario}"
            if qualificado not in nomes:
                nomes.append(qualificado)
    nomes.append(usuario)
    return nomes


def _variacoes() -> list[tuple[str, list[str]]]:
    """
    Formas de pedir a mesma tarefa, da que menos exige privilegio para a que
    mais exige.

    `/SC ONLOGON` puro cria um gatilho valido para QUALQUER usuario da
    maquina, e isso exige administrador -- com razao. Amarrando ao usuario
    atual (`/RU`) e marcando como interativa (`/IT`, "so quando este usuario
    estiver logado"), nao ha senha para guardar nem sessao alheia envolvida, e
    a permissao normal costuma bastar.
    """
    base = ["schtasks", "/Create", "/TN", NOME_TAREFA, "/TR", comando()]
    fim = ["/SC", "ONLOGON", "/F"]

    tentativas: list[tuple[str, list[str]]] = []

    for nome in _nomes_de_usuario():
        tentativas.append((
            f"/RU {nome} /IT", base + ["/RU", nome, "/IT"] + fim,
        ))
        tentativas.append((
            f"/RU {nome}", base + ["/RU", nome] + fim,
        ))

    tentativas.append(("/IT sem /RU", base + ["/IT"] + fim))
    tentativas.append(("sem /RU", base + fim))

    return tentativas


def ativar(com_admin: bool = False) -> bool:
    """
    Liga o "abrir com o Windows". Devolve True se deu certo.

    OS DOIS CAMINHOS SEPARADOS (pedido dele, 23/set/2026): esta opcao e
    SEMPRE a fila comum do Windows (chave Run do proprio usuario, sem
    administrador). Quem vai para o Agendador -- que abre no logon, sem
    esperar a fila -- e a sub-opcao "iniciar mais rapido"
    (`definir_rapido`). Antes, rodando pelo codigo, esta opcao ja criava a
    tarefa e a sub-opcao nao tinha o que fazer.

    `com_admin` ficou sem uso; continua na assinatura para nao mexer em quem
    chama.
    """
    if not disponivel():
        return False
    if tarefa_existe():
        return True            # ja abre pelo caminho rapido
    return _run_ativar()


def desativar(com_admin: bool = False) -> bool:
    """
    Remove a tarefa. True se deu certo ou se ja nao existia.

    `com_admin=True` autoriza pedir elevacao quando o Windows recusar a
    remocao simples -- a tarefa foi criada por um processo elevado, entao
    apagar exige o mesmo privilegio.
    """
    if not disponivel():
        return False
    # Os dois caminhos saem: a fila Run e, se o "mais rapido" estava ligado,
    # a tarefa do Agendador.
    _run_desativar()

    if not tarefa_existe():
        return _run_ler() is None

    ok, saida = _rodar(["schtasks", "/Delete", "/TN", NOME_TAREFA, "/F"])
    if ok:
        log.info("tarefa de logon removida")
        return True

    log.info("remocao simples recusada: %s", saida)

    if com_admin:
        log.info("pedindo confirmacao de administrador para remover")
        return desativar_elevado()

    log.warning("nao consegui remover a tarefa de logon: %s", saida)
    return False


def definir(ligado: bool, com_admin: bool = False) -> bool:
    if ligado:
        return ativar(com_admin=com_admin)
    return desativar(com_admin=com_admin)


# ---------------------------------------------------------------------------
# Criacao com permissao de administrador
# ---------------------------------------------------------------------------
#
# Herdado do AmbiSync (26/ago/2026): naquela maquina, criar tarefa com
# gatilho de logon exigiu administrador mesmo com o usuario escrito certo.
# Ele aprova uma vez (a janela de confirmacao do Windows) e nos logons
# seguintes a tarefa ja existe e roda sem prompt.
#
# POR QUE VIA .BAT, E NAO PASSANDO OS ARGUMENTOS DIRETO
# --------------------------------------------------------
# O `/TR` carrega um comando com aspas dentro. Mandar isso por ShellExecute
# significa aspas dentro de aspas dentro de aspas. O .bat escreve o comando em
# texto puro, sem nivel extra de escape -- e fica na pasta como caminho
# alternativo (botao direito -> "Executar como administrador") se a janela de
# elevacao nao aparecer.

ARQUIVO_CRIAR = "criar-tarefa-inicio.bat"
ARQUIVO_REMOVER = "remover-tarefa-inicio.bat"


def _pasta_ferramentas() -> str:
    from .caminhos import pasta_ferramentas

    return str(pasta_ferramentas())            # (r172) oculta no pacote


def caminho_do_bat(nome: str = ARQUIVO_CRIAR) -> str:
    return os.path.join(_pasta_ferramentas(), nome)


def _escrever_bat(nome: str, titulo: str, linha_schtasks: str) -> str | None:
    """Gera um .bat de uma linha util. Devolve o caminho, ou None se falhou."""
    linhas = [
        "@echo off",
        f"REM {titulo}",
        "REM Gerado pelo proprio scrcpy-f -- pode apagar depois de usar.",
        "REM",
        "REM Se precisar rodar a mao: botao direito neste arquivo ->",
        "REM 'Executar como administrador'.",
        "",
        linha_schtasks,
        "",
        "if %ERRORLEVEL%==0 (",
        "    echo Pronto.",
        ") else (",
        "    echo Falhou. Codigo: %ERRORLEVEL%",
        # Sem `pause`: padrao da casa desde 10/set/2026. Desde 12/set/2026 a
        # tela que tem resultado pra ler PARA e espera ENTER, em vez de fechar
        # sozinha com contagem regressiva -- aqui e o caso de falha, que sempre
        # tem o que ler.
        # Aqui NAO vai `chcp 65001`, ao contrario dos .bat escritos a mao: este
        # arquivo e gravado em cp1252 (ver o open mais abaixo) e nao grava
        # relatorio nenhum, entao misturar as duas codificacoes so criaria
        # problema.
        # "auto" e o que o proprio programa passa quando roda este arquivo
        # escondido, pedindo administrador: ai ninguem ve a tela, e esperar
        # ENTER deixaria um console invisivel preso para sempre. Rodado a mao,
        # sem argumento, a falha continua esperando para ser lida.
        "    if not \"%~1\"==\"auto\" set /p \"TECLA=Leia o resultado. Aperte ENTER para fechar: \"",
        ")",
        "",
    ]

    destino = caminho_do_bat(nome)
    try:
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        with open(destino, "w", encoding="cp1252", errors="replace") as arq:
            arq.write("\r\n".join(linhas))
        return destino
    except OSError as erro:
        log.warning("nao consegui escrever o %s: %s", nome, erro)
        return None


def escrever_bat() -> str | None:
    """.bat que CRIA a tarefa."""
    nomes = _nomes_de_usuario()
    usuario = nomes[0] if nomes else ""

    # As aspas de dentro do /TR precisam ir escapadas com \" -- o comando ja
    # vem com aspas em volta do executavel e do script, e sem escapar o
    # schtasks fecha o argumento na primeira delas.
    alvo = comando().replace(chr(34), chr(92) + chr(34))

    return _escrever_bat(
        ARQUIVO_CRIAR,
        "Cria a tarefa que abre o scrcpy-f junto com o Windows.",
        f'schtasks /Create /TN "{NOME_TAREFA}" /TR "{alvo}" '
        f'/SC ONLOGON /RU "{usuario}" /IT /F',
    )


def escrever_bat_remocao() -> str | None:
    """.bat que REMOVE a tarefa."""
    return _escrever_bat(
        ARQUIVO_REMOVER,
        "Remove a tarefa de inicio automatico do scrcpy-f.",
        f'schtasks /Delete /TN "{NOME_TAREFA}" /F',
    )


def ativar_elevado() -> bool:
    """
    Pede a confirmacao de administrador e cria a tarefa.

    Devolve True so quando a tarefa passa a existir de verdade -- confirmado
    consultando o Agendador depois, nao pelo codigo de saida do .bat.
    """
    caminho = escrever_bat()
    if caminho is None or not _executar_elevado(caminho):
        return False

    if tarefa_existe():
        log.info("tarefa de logon criada com elevacao")
        return True

    log.warning("mesmo com elevacao a tarefa nao foi criada")
    return False


def desativar_elevado() -> bool:
    """Pede a confirmacao de administrador e remove a tarefa."""
    caminho = escrever_bat_remocao()
    if caminho is None or not _executar_elevado(caminho):
        return False

    if not tarefa_existe():
        log.info("tarefa de logon removida com elevacao")
        return True

    log.warning("mesmo com elevacao a tarefa nao foi removida")
    return False


def _executar_elevado(caminho: str, esperar: bool = True) -> bool:
    """Roda um .bat pedindo confirmacao de administrador. True se rodou."""
    # Vale tambem no .exe desde o "iniciar mais rapido" (21/set/2026): so
    # roda quando ele liga a sub-opcao, nunca sozinho.
    if not disponivel():
        return False

    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SW_HIDE = 0
    ERRO_CANCELADO = 1223  # ele clicou "Nao" na janela de administrador

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        info = SHELLEXECUTEINFOW()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = SEE_MASK_NOCLOSEPROCESS
        info.lpVerb = "runas"          # e isto que pede a elevacao
        info.lpFile = "cmd.exe"
        info.lpParameters = f'/c ""{caminho}" auto"'
        info.lpDirectory = os.path.dirname(caminho)
        info.nShow = SW_HIDE

        shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
        shell32.ShellExecuteExW.restype = wintypes.BOOL

        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            erro = ctypes.get_last_error()
            if erro == ERRO_CANCELADO:
                log.info("elevacao recusada pelo usuario")
            else:
                log.warning("nao consegui pedir elevacao (erro %s)", erro)
            return False

        if info.hProcess:
            # (r168) esperar=False: o .bat da atualizacao do proprio
            # programa espera ESTE processo fechar -- esperar por ele aqui
            # seria um esperando o outro.
            if esperar:
                kernel32.WaitForSingleObject(info.hProcess, 60_000)
            kernel32.CloseHandle(info.hProcess)

    except Exception as erro:
        log.warning("falha ao pedir elevacao: %s", erro)
        return False

    # Daqui so sai "o .bat rodou". Se ele FEZ o que devia, quem confere e o
    # chamador -- `ativar_elevado` olha se a tarefa passou a existir,
    # `desativar_elevado` olha se ela deixou de existir.
    return True
