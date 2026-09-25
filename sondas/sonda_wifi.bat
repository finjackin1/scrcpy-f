@echo off
REM ===========================================================================
REM SONDA DO WI-FI DO CELULAR (21/set/2026)
REM
REM O celular aceita os modos de Wi-Fi "baixa latencia" e "alto desempenho"
REM pedidos pelo PC? E eles cortam os picos de atraso? Mede o ping ao celular
REM normal e com cada modo (~2 minutos) e no fim devolve tudo ao normal.
REM
REM RODAR COM O ESPELHAMENTO E A EXTENSAO DESLIGADOS.
REM
REM Resultado em relatorios\sonda_wifi.txt; abertura, fim e erros da partida
REM em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda do wi-fi

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_wifi.bat] %DATE% %TIME%

echo.
echo    Sonda do Wi-Fi do celular: leva uns 2 minutos.
echo    Deixe o celular parado, perto de onde voce costuma jogar.
echo.

python sondas\sonda_wifi.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Leia o resultado. Aperte ENTER para fechar: "
