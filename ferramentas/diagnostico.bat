@echo off
REM Levanta o estado da conexao com o celular e grava em relatorios\ultimo.txt
chcp 65001 > nul
cd /d "%~dp0.."

if not exist "relatorios" md "relatorios"
> "relatorios\partida.txt" echo [diagnostico.bat] %DATE% %TIME%

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0diagnostico.ps1" 2>> "relatorios\partida.txt"
set CODIGO=%ERRORLEVEL%

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME% codigo=%CODIGO%

if not "%CODIGO%"=="0" (
    echo.
    echo Nao consegui rodar. O detalhe ficou em relatorios\partida.txt
    set /p "TECLA=Leia o resultado. Aperte ENTER para fechar: "
)
