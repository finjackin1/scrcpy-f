@echo off
REM Bancada da atualizacao do proprio scrcpy-f (r168). Precisa do pacote
REM pronto (publicar.bat). Abre uma COPIA do pacote achando que saiu a 9.9.9.
chcp 65001 > nul
cd /d "%~dp0.."

if not exist "relatorios" md "relatorios"
> "relatorios\partida.txt" echo [teste-atualizacao.bat] %DATE% %TIME%

python "%~dp0teste-atualizacao.py" 2>> "relatorios\partida.txt"
set CODIGO=%ERRORLEVEL%

>> "relatorios\partida.txt" echo [fim] %DATE% %TIME% codigo=%CODIGO%

if not "%CODIGO%"=="0" (
    echo.
    echo Nao consegui preparar o teste. O detalhe ficou em relatorios\teste-atualizacao.txt
    set /p "TECLA=Leia o resultado. Aperte ENTER para fechar: "
)
