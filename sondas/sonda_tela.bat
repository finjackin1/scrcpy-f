@echo off
REM ===========================================================================
REM SONDA DA TELA (24/set/2026)
REM
REM So LE o celular (nao muda nada): por que a tela nao apaga sozinha --
REM tempo de tela, travas de tela acesa e sobras do scrcpy-f rodando nele.
REM
REM Resultado em relatorios\sonda_tela.txt; abertura, fim e erros da partida
REM em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda da tela

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_tela.bat] %DATE% %TIME%

echo.
echo    Sonda da tela: uns 10 segundos. Pode deixar o scrcpy-f aberto.
echo    Siga as instrucoes que aparecerem aqui.
echo.

python sondas\sonda_tela.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Aperte ENTER para fechar: "
