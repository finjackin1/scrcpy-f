@echo off
REM ===========================================================================
REM SONDA DA PRIORIDADE NO PC (21/set/2026)
REM
REM Marcar o trafego do espelhamento como prioritario no Windows corta os
REM picos de atraso? Mede sem e com a marca, alternando (~3 minutos), e no
REM fim desfaz tudo. Pede permissao de administrador (abre outra janela).
REM
REM RODAR COM O scrcpy-f FECHADO (a sonda reinicia o adb).
REM
REM Resultado em relatorios\sonda_prioridade.txt; abertura e erros da
REM partida em relatorios\partida.txt. Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."

if not exist "relatorios" md "relatorios"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_prioridade.bat] %DATE% %TIME%

python sondas\sonda_prioridade.py 2>> "relatorios\partida.txt"
if errorlevel 1 (
  >> "relatorios\partida.txt" echo [falhou] %DATE% %TIME%
  echo.
  set /p "TECLA=Leia o resultado. Aperte ENTER para fechar: "
  exit /b 1
)
>> "relatorios\partida.txt" echo [elevado disparado] %DATE% %TIME%
