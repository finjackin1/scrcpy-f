@echo off
REM ===========================================================================
REM SONDA DO FECHAR (24/set/2026)
REM
REM Abre o Instagram numa janela igual a do scrcpy-f, fecha a janela e testa
REM jeitos de fechar o app no celular (como tirar da lista de recentes).
REM
REM Resultado em relatorios\sonda_fechar.txt; abertura, fim e erros da partida
REM em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda do fechar

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_fechar.bat] %DATE% %TIME%

echo.
echo    Sonda do fechar: menos de 1 minuto. Feche o scrcpy-f antes.
echo    Siga as instrucoes que aparecerem aqui.
echo.

python sondas\sonda_fechar.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
set /p "TECLA=Aperte ENTER para fechar: "
