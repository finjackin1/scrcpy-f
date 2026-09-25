@echo off
REM ===========================================================================
REM SONDA DO APP DUPLICADO (25/set/2026)
REM
REM Descobre as copias duplicadas (Dual Messenger / app clonado) e abre o
REM original e a copia, cada um na sua janela, ao mesmo tempo.
REM
REM Resultado em relatorios\sonda_duplicado.txt; abertura, fim e erros da
REM partida em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda do app duplicado

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_duplicado.bat] %DATE% %TIME%

echo.
echo    Sonda do app duplicado: menos de 1 minuto. Feche o scrcpy-f antes.
echo.

python sondas\sonda_duplicado.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Aperte ENTER para fechar: "
