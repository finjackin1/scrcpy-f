@echo off
REM scrcpy-f -- abre o programa de fundo (icone na bandeja, ao lado do relogio).
REM Duplo clique aqui. Caminhos relativos ao proprio script, nunca absolutos.
REM
REM Dispara e fecha: nao ha nada pra ler quando da certo, entao a janela nao
REM espera tecla nenhuma. So a FALHA espera ENTER, porque falha sempre tem o
REM que ler.
REM
REM `pythonw` e nao `python`: e o que roda sem console. Um programa que fica de
REM fundo o dia inteiro nao pode deixar um console preto na barra de tarefas.
REM
REM `relatorios\partida.txt` e a testemunha do que morre ANTES de o log do
REM programa existir: Python ausente, biblioteca faltando, import quebrado. So
REM a saida de erro vai pra la.

setlocal
cd /d "%~dp0"
if not exist "relatorios" mkdir "relatorios"
set "PARTIDA=relatorios\partida.txt"

>>"%PARTIDA%" echo.
>>"%PARTIDA%" echo === PARTIDA %DATE% %TIME% ===

where pythonw >nul 2>&1
if errorlevel 1 (
    >>"%PARTIDA%" echo Python nao encontrado no PATH.
    echo.
    echo   Python nao encontrado.
    echo.
    echo   Instale o Python e marque a caixa "Add python.exe to PATH"
    echo   na primeira tela do instalador.
    echo.
    set /p "TECLA=  Aperte ENTER para sair: "
    exit /b 1
)

python -c "import PIL, pystray" >nul 2>>"%PARTIDA%"
if errorlevel 1 (
    echo.
    echo   Falta uma biblioteca. Instalando uma vez so...
    echo.
    python -m pip install -r publicacao\requirements.txt 2>>"%PARTIDA%"
    if errorlevel 1 (
        echo.
        echo   A instalacao falhou. Leia a mensagem acima.
        echo.
        set /p "TECLA=  Aperte ENTER para sair: "
        exit /b 1
    )
)

REM Ensaio da partida, preso a este console: se algum arquivo do programa
REM estiver quebrado, o erro cai no partida.txt AQUI. Sem isto, o pythonw
REM morreria em silencio e nao haveria nada pra ler em lugar nenhum.
REM A janela entra no ensaio so se o Tk existir nesta instalacao do Python:
REM sem ele o programa ainda sobe, so com a bandeja, e isso nao e falha.
python -c "import importlib.util as u, scrcpyf.bandeja, scrcpyf.programa, scrcpyf.registro, scrcpyf.motor_atalhos; u.find_spec('tkinter') and __import__('scrcpyf.janela')" 2>>"%PARTIDA%"
if errorlevel 1 (
    echo.
    echo   O programa nao conseguiu carregar. O motivo ficou gravado
    echo   em relatorios\partida.txt.
    echo.
    set /p "TECLA=  Aperte ENTER para sair: "
    exit /b 1
)

start "" pythonw app.py
>>"%PARTIDA%" echo programa disparado; este .bat saiu em seguida
exit /b 0
