@echo off
REM ===========================================================================
REM SONDA DO ICONE (25/set/2026)
REM
REM Abre duas janelas do celular e testa, em 3 passos, o icone e os botoes
REM separados na barra de tarefas. Tira fotos da tela sozinho; e so esperar.
REM
REM Resultado em relatorios\sonda_icone.txt; abertura, fim e erros da partida
REM em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda do icone

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_icone.bat] %DATE% %TIME%

echo.
echo    Sonda do icone: uns 40 segundos. Feche o scrcpy-f antes.
echo.

python sondas\sonda_icone.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Aperte ENTER para fechar: "
