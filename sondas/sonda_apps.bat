@echo off
REM ===========================================================================
REM SONDA DOS APPS EM JANELA (23/set/2026)
REM
REM Por que os icones nao vem, e como prender o app na janela dele. Abre
REM as Configuracoes numa janela por uns 10 segundos e fecha sozinha.
REM
REM Resultado em relatorios\sonda_apps.txt; abertura, fim e erros da
REM partida em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda dos apps

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_apps.bat] %DATE% %TIME%

echo.
echo    Sonda dos apps: uns 30 segundos. Uma janela das Configuracoes
echo    do celular vai abrir e fechar sozinha - nao mexa nela.
echo.

python sondas\sonda_apps.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Leia o resultado. Aperte ENTER para fechar: "
