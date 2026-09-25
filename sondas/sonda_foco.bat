@echo off
REM ===========================================================================
REM SONDA DO FOCO (23/set/2026)
REM
REM Abre Instagram e WhatsApp em janelas iguais as do scrcpy-f e testa dois
REM jeitos de dar a "atencao" do Android ao Instagram sem clicar nele.
REM
REM Resultado em relatorios\sonda_foco.txt; abertura, fim e erros da partida
REM em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda do foco

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_foco.bat] %DATE% %TIME%

echo.
echo    Sonda do foco: uns 2 minutos. Feche o scrcpy-f antes.
echo    Siga as instrucoes que aparecerem aqui.
echo.

python sondas\sonda_foco.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Aperte ENTER para fechar: "
