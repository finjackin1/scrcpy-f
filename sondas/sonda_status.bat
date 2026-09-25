@echo off
REM ===========================================================================
REM SONDA DO STATUS DO CELULAR (23/set/2026)
REM
REM O que o celular deixa ler (bateria, espaco, RAM, CPU, GPU, uso por app)
REM e quanto tempo leva. So LE, nao muda nada. ~30 segundos.
REM
REM Resultado em relatorios\sonda_status.txt; abertura, fim e erros da
REM partida em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda do status

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_status.bat] %DATE% %TIME%

echo.
echo    Sonda do status do celular: uns 30 segundos.
echo    Deixe o WhatsApp aberto numa janela de APPS, se der.
echo.

python sondas\sonda_status.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Leia o resultado. Aperte ENTER para fechar: "
