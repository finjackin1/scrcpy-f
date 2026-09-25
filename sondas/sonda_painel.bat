@echo off
REM ===========================================================================
REM SONDA DO PAINEL (25/set/2026)
REM
REM Apaga a tela do celular como o programa faz e tenta religar de 2 jeitos,
REM um de cada vez. Olhe o CELULAR e diga no chat qual numero acendeu.
REM
REM Resultado em relatorios\sonda_painel.txt; abertura, fim e erros da partida
REM em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda do painel

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_painel.bat] %DATE% %TIME%

echo.
echo    Sonda do painel: uns 40 segundos. Feche o scrcpy-f antes.
echo.

python sondas\sonda_painel.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Aperte ENTER para fechar: "
