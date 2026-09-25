@echo off
REM scrcpy-f -- bancada de teste do nucleo.
REM Duplo clique e escolher pelo menu. Nao precisa de terminal.
REM Caminhos relativos ao proprio script, nunca absolutos.
REM
REM O relatorio de cada execucao vai para relatorios\ultimo.txt, e o acumulado
REM para relatorios\historico.txt -- e por ali que eu leio o resultado.
REM
REM NENHUMA espera por tecla: terminou a acao, o menu reaparece ABAIXO do
REM resultado. Por isso o `cls` so acontece na primeira entrada -- limpar a
REM tela a cada volta apagaria o resultado antes de ele ser lido.

setlocal
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f -- bancada de teste

if not exist "relatorios" md "relatorios"
> "relatorios\partida.txt" echo [teste.bat] %DATE% %TIME%

where python >nul 2>&1
if errorlevel 1 (
    >> "relatorios\partida.txt" echo ERRO: python nao encontrado no PATH
    echo.
    echo   Python nao encontrado.
    echo.
    echo   Instale o Python e marque a caixa "Add python.exe to PATH"
    echo   na primeira tela do instalador.
    echo.
    set /p "TECLA=Leia o resultado. Aperte ENTER para fechar: "
    exit /b 1
)

cls

:menu
echo.
echo    ============================================
echo     scrcpy-f  --  bancada de teste do nucleo
echo    ============================================
echo.
echo     [1]  Conferir tudo    (nao sobe nada, seguro)
echo     [2]  Modo jogo        (espelha a tela do celular)
echo     [3]  Modo audio       (so o som do celular)
echo.
echo     [0]  Sair
echo.
REM `choice` responde na hora, sem Enter. A ordem dos errorlevel e do maior
REM para o menor de proposito: `if errorlevel N` quer dizer "N ou mais".
choice /c 1230 /n /m "    Aperte o numero da opcao: "
if errorlevel 4 goto fim
if errorlevel 3 goto audio
if errorlevel 2 goto jogo
if errorlevel 1 goto conferir
goto menu

:conferir
set "ALVO="
goto rodar

:jogo
set "ALVO=jogo"
goto rodar

:audio
set "ALVO=audio"
goto rodar

:rodar
echo.
>> "relatorios\partida.txt" echo --- teste.py %ALVO% --- %DATE% %TIME%
python ferramentas\teste.py %ALVO% 2>> "relatorios\partida.txt"
echo.
echo    ------------------------------------------------------------
goto menu

:fim
>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
exit /b 0
