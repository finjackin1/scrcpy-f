@echo off
REM ===========================================================================
REM SONDA DAS NOTIFICACOES (01/out/2026)
REM
REM Confere no celular o caminho das notificacoes do scrcpy-f: ler, eventos,
REM apps bloqueados e REMOVER uma notificacao comum (sai de verdade).
REM
REM Resultado em relatorios\sonda_notif.txt; abertura, fim e erros da
REM partida em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda das notificacoes

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_notif.bat] %DATE% %TIME%

echo.
echo    Sonda das notificacoes: uns 10 segundos.
echo    Celular conectado (cabo ou sem fio). Deixe pelo menos UMA notificacao
echo    comum no celular: a sonda vai remover uma para testar.
echo.

python sondas\sonda_notif.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
echo    Pronto. Me avise que terminou.
set /p "TECLA=Aperte ENTER para fechar: "
