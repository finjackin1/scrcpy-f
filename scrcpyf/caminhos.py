"""
Onde ficam as coisas em disco.

Um lugar so para responder "de onde eu leio o config?", porque a resposta muda
conforme o programa esta rodando pelo Python ou empacotado. `sys.executable`
aponta para o python.exe num caso e para o scrcpy-f.exe no outro; usar
`__file__` funcionaria so no primeiro.

Tudo fica ao LADO do programa, nunca no AppData: a distribuicao e portable, e
programa portable que espalha arquivo pelo sistema deixa lixo quando some.
"""

from __future__ import annotations

import sys
from pathlib import Path


def empacotado() -> bool:
    """True quando esta rodando como .exe do PyInstaller."""
    return getattr(sys, "frozen", False)


def pasta_do_programa() -> Path:
    """A pasta onde o programa mora."""
    if empacotado():
        return Path(sys.executable).resolve().parent
    # ...\scrcpy-f\scrcpyf\caminhos.py -> ...\scrcpy-f
    return Path(__file__).resolve().parent.parent


def arquivo(nome: str) -> Path:
    """Caminho de um arquivo ao lado do programa."""
    return pasta_do_programa() / nome


def pasta_interna() -> Path:
    """
    Onde mora o que a pessoa nao precisa ver. No pacote e a `_internal` do
    PyInstaller (as DLLs e .pyd do Python), que o programa esconde ao abrir
    (ver `ocultar_pasta_interna`); em codigo e a propria pasta do projeto.
    """
    if empacotado():
        interna = getattr(sys, "_MEIPASS", None)
        if interna:
            return Path(interna)
        return pasta_do_programa() / "_internal"
    return pasta_do_programa()


def pasta_dados() -> Path:
    """
    Onde o programa guarda o que ele mesmo gera (cache de cada celular,
    icone da janela). No pacote: a `_internal`, como sempre. Em codigo: a
    pasta `dados` do projeto, para a raiz ficar so com o que se usa (pedido
    dele, 23/set/2026).
    """
    if empacotado():
        return pasta_interna()
    pasta = pasta_do_programa() / "dados"
    try:
        pasta.mkdir(exist_ok=True)
    except Exception:
        pass
    return pasta


def pasta_ferramentas() -> Path:
    """
    Onde o programa escreve os .bat que pedem administrador. (r172, pedido
    dele: no pacote ela fica OCULTA como a _internal -- a unica pasta a
    vista e a do scrcpy.)
    """
    pasta = pasta_do_programa() / "ferramentas"
    pasta.mkdir(parents=True, exist_ok=True)
    _ocultar(pasta)
    return pasta


def _ocultar(pasta: Path) -> None:
    if not empacotado() or sys.platform != "win32":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.GetFileAttributesW.restype = ctypes.c_uint32
        atual = k.GetFileAttributesW(str(pasta))
        if atual != 0xFFFFFFFF and not (atual & 0x2):
            k.SetFileAttributesW(str(pasta), atual | 0x2)
    except Exception:
        pass


def ocultar_pasta_interna() -> None:
    """
    PACOTE LIMPO (pedido dele, 21/set/2026): quem abre a pasta do programa
    via o scrcpy-f.exe, o config e os textos -- e nao uma pasta cheia de .pyd.
    O zip nao guarda o atributo "oculto" do Windows, por isso o proprio
    programa marca a pasta ao abrir. So o atributo OCULTO (nao o de sistema):
    esconder como arquivo de sistema e o tipo de coisa que antivirus estranha.
    """
    _ocultar(pasta_interna())
    ferr = pasta_do_programa() / "ferramentas"
    if ferr.exists():
        _ocultar(ferr)                     # (r172) a de versoes anteriores


def pasta_relatorios() -> Path:
    """
    A pasta dos relatorios, criada se ainda nao existir. No pacote ela mora
    DENTRO da pasta interna escondida (pedido dele: nada de relatorio a
    mostra na versao publicada); em codigo, ao lado do programa, como sempre.
    """
    pasta = pasta_interna() / "relatorios"
    try:
        pasta.mkdir(exist_ok=True)
    except Exception:
        pass
    return pasta


# O programa do pacote. Ate a v0.5.1 havia um segundo, o Configurar; desde a
# v0.6.0 o parear e a pasta do scrcpy moram na propria janela.
PROGRAMAS = {
    "principal": ("scrcpy-f.exe", "app.py"),
}


def comando(qual: str, *argumentos: str) -> list[str]:
    """A linha de comando que abre o programa."""
    exe, script = PROGRAMAS[qual]
    pasta = pasta_do_programa()
    if empacotado():
        return [str(pasta / exe), *argumentos]
    python = Path(sys.executable)
    sem_console = python.with_name(python.name.lower().replace(
        "python.exe", "pythonw.exe"))
    if sem_console.exists():
        python = sem_console
    return [str(python), str(pasta / script), *argumentos]


def abrir(qual: str, *argumentos: str):
    """Abre o programa e devolve o processo (ou None)."""
    import subprocess
    try:
        return subprocess.Popen(comando(qual, *argumentos),
                                cwd=str(pasta_do_programa()))
    except Exception:
        return None
