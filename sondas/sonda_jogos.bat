@echo off
REM ===========================================================================
REM SONDA DOS JOGOS (23/set/2026)
REM
REM Descobre se o celular diz quais apps sao jogos. So LE, nao muda nada.
REM Resultado em relatorios\sonda_jogos.txt;
REM abertura, fim e erros em relatorios\partida.txt.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda dos jogos

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_jogos.bat] %DATE% %TIME%

echo.
echo    Sonda do top: uns 30 segundos. Pode deixar o scrcpy-f aberto.
echo.

python sondas\sonda_jogos.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Aperte ENTER para fechar: "
