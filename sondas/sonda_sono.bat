@echo off
REM ===========================================================================
REM SONDA DO SONO (23/set/2026)
REM
REM Abre o WhatsApp numa janela igual a do scrcpy-f, apaga so a tela fisica do
REM celular e testa se o app segue vivo -- inclusive depois do botao de ligar.
REM
REM Resultado em relatorios\sonda_sono.txt; abertura, fim e erros da partida
REM em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda do sono

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_sono.bat] %DATE% %TIME%

echo.
echo    Sonda do sono: uns 2 minutos. Feche o scrcpy-f antes.
echo    Siga as instrucoes que aparecerem aqui.
echo.

python sondas\sonda_sono.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Aperte ENTER para fechar: "
