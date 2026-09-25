@echo off
REM ===========================================================================
REM SONDA DO PESO NO CELULAR (25/set/2026)
REM
REM Mede quanto as perguntas do programa ao celular pesam la. Deixe o
REM scrcpy-f ABERTO com dois apps em janela (ex.: Instagram e WhatsApp).
REM
REM Resultado em relatorios\sonda_peso.txt; abertura, fim e erros da partida
REM em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda do peso

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_peso.bat] %DATE% %TIME%

echo.
echo    Sonda do peso: uns 2 minutos. Deixe 2 apps abertos em janela.
echo.

python sondas\sonda_peso.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Aperte ENTER para fechar: "
