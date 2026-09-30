@echo off
REM ===========================================================================
REM SONDA DO ATRASO (30/set/2026)
REM
REM Mede em milissegundos a volta inteira: clique no PC -> toque no celular
REM -> imagem de volta na tela do PC, em varias configuracoes do scrcpy.
REM
REM Resultado em relatorios\sonda_atraso.txt; abertura, fim e erros da
REM partida em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda do atraso

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_atraso.bat] %DATE% %TIME%

echo.
echo    Sonda do atraso: uns 3 minutos.
echo    Feche o scrcpy-f antes. Celular no CABO, desbloqueado.
echo    Deixe a depuracao SEM FIO ligada tambem, para medir o Wi-Fi.
echo    NAO mexa no mouse ate terminar: a sonda clica sozinha.
echo.

python sondas\sonda_atraso.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
echo    Pronto. Me avise que terminou.
set /p "TECLA=Aperte ENTER para fechar: "
