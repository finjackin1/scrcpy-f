@echo off
REM ===========================================================================
REM SONDA DO DEX (25/set/2026)
REM
REM Abre o DeX em janela de 4 jeitos, um de cada vez (feche no X para ir ao
REM proximo). Depois diga no chat qual letra ficou certa.
REM
REM Resultado em relatorios\sonda_dex.txt; abertura, fim e erros da partida
REM em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda do DeX

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_dex.bat] %DATE% %TIME%

echo.
echo    Sonda do DeX: 4 janelas, uma de cada vez. Feche o scrcpy-f antes.
echo.

python sondas\sonda_dex.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Aperte ENTER para fechar: "
