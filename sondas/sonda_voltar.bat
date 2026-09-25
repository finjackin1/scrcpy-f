@echo off
REM ===========================================================================
REM SONDA DO VOLTAR (23/set/2026)
REM
REM Abre o WhatsApp numa janela igual a do scrcpy-f e anota, por 25 segundos,
REM o que o Android diz das telas enquanto voce aperta VOLTAR.
REM
REM Resultado em relatorios\sonda_voltar.txt; abertura, fim e erros da
REM partida em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda do voltar

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_voltar.bat] %DATE% %TIME%

echo.
echo    Sonda do voltar: uns 30 segundos. Feche o scrcpy-f antes.
echo.

python sondas\sonda_voltar.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Aperte ENTER para fechar: "
