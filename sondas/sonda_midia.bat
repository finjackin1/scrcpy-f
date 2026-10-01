@echo off
REM ===========================================================================
REM SONDA DO PLAYER (01/out/2026)
REM
REM Com uma musica TOCANDO no celular: le o player, pausa e toca de novo,
REM pula 20 s e volta, e le os botoes das notificacoes.
REM
REM Resultado em relatorios\sonda_midia.txt; abertura, fim e erros da
REM partida em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."
title scrcpy-f - sonda do player

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_midia.bat] %DATE% %TIME%

echo.
echo    Sonda do player: uns 20 segundos.
echo    Deixe uma MUSICA TOCANDO no celular (YouTube Music, Spotify...).
echo    A musica vai pausar um instante, voltar e pular 20 s pra frente e
echo    voltar.
echo.

python sondas\sonda_midia.py 2>> "relatorios\partida.txt"

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%
echo.
echo    Pronto. Me avise que terminou.
set /p "TECLA=Aperte ENTER para fechar: "