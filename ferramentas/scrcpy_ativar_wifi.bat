@echo off
REM Roda 1x (com o cabo USB conectado), ou toda vez que o celular reiniciar.
chcp 65001 > nul
cd /d "%~dp0.."

if not exist "relatorios" md "relatorios"
> "relatorios\partida.txt" echo [scrcpy_ativar_wifi.bat] %DATE% %TIME%

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scrcpy_ativar_wifi.ps1" 2>> "relatorios\partida.txt"
set CODIGO=%ERRORLEVEL%

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME% codigo=%CODIGO%

if not "%CODIGO%"=="0" (
    echo.
    echo Nao consegui rodar. O detalhe ficou em relatorios\partida.txt
    set /p "TECLA=Leia o resultado. Aperte ENTER para fechar: "
)
