@echo off
REM ===========================================================================
REM SONDA DA TROCA (24/set/2026)
REM
REM Abre o Instagram numa janela igual a do scrcpy-f e testa trocar a janela
REM por uma nova SEM reiniciar o app (passando o app de uma tela para outra).
REM
REM Resultado em relatorios\sonda_troca.txt; abertura, fim e erros da partida
REM em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda da troca

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_troca.bat] %DATE% %TIME%

echo.
echo    Sonda do foco: uns 2 minutos. Feche o scrcpy-f antes.
echo    Siga as instrucoes que aparecerem aqui.
echo.

python sondas\sonda_troca.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Aperte ENTER para fechar: "
