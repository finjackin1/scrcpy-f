@echo off
REM ===========================================================================
REM SONDA DO TOP (23/set/2026)
REM
REM Roda o medidor de apps da aba status por 8 s de dois jeitos e anota a que
REM horas cada leitura chega no PC. Resultado em relatorios\sonda_top.txt;
REM abertura, fim e erros em relatorios\partida.txt.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda do top

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_top.bat] %DATE% %TIME%

echo.
echo    Sonda do top: uns 20 segundos. Pode deixar o scrcpy-f aberto.
echo.

python sondas\sonda_top.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Aperte ENTER para fechar: "
