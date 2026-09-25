@echo off
REM ===========================================================================
REM SONDA DO MOUSE NO CELULAR (20/set/2026)
REM
REM Pergunta ao celular tudo que manda no cursor do mouse: aceleracao ligada
REM ou desligada, velocidade do ponteiro, tamanho e densidade da tela, e o
REM aparelho de mouse que o scrcpy cria. E disso que a conta da extensao
REM precisa para saber onde o cursor esta.
REM
REM RODAR COM A EXTENSAO LIGADA: o mouse do scrcpy so existe enquanto ela
REM esta no ar.
REM
REM Grava tudo em relatorios\sonda_mouse.txt (substituido a cada sonda).
REM Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."

if not exist "relatorios" md "relatorios"
set "SONDA=relatorios\sonda_mouse.txt"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_mouse.bat] %DATE% %TIME%

set "ADB="
for /f "delims=" %%A in ('python -c "from scrcpyf.config import Config; print(Config.carregar().adb_exe)" 2^>^>"relatorios\partida.txt"') do set "ADB=%%A"
if not defined ADB (
  echo.
  echo   Nao achei o adb. Abra o Configurar e aponte a pasta do scrcpy.
  >> "relatorios\partida.txt" echo sem adb
  set /p "TECLA=Leia o resultado. Aperte ENTER para fechar: "
  exit /b 1
)

echo.
echo    Perguntando ao celular... ^(alguns segundos^)
echo.

> "%SONDA%" echo === SONDA DO MOUSE %DATE% %TIME% ===
>> "%SONDA%" echo adb: %ADB%

>> "%SONDA%" echo.
>> "%SONDA%" echo --- tela ---
"%ADB%" shell wm size >> "%SONDA%" 2>&1
"%ADB%" shell wm density >> "%SONDA%" 2>&1

>> "%SONDA%" echo.
>> "%SONDA%" echo --- ajustes do ponteiro (system) ---
"%ADB%" shell "settings list system | grep -i -E 'mouse|pointer|cursor|track'" >> "%SONDA%" 2>&1
>> "%SONDA%" echo --- ajustes do ponteiro (secure) ---
"%ADB%" shell "settings list secure | grep -i -E 'mouse|pointer|cursor|track'" >> "%SONDA%" 2>&1
>> "%SONDA%" echo --- ajustes do ponteiro (global) ---
"%ADB%" shell "settings list global | grep -i -E 'mouse|pointer|cursor|track'" >> "%SONDA%" 2>&1

>> "%SONDA%" echo.
>> "%SONDA%" echo --- o que o sistema diz do mouse ---
"%ADB%" shell "dumpsys input | grep -i -E 'pointer speed|acceleration|mouse|resolution|xdpi|ydpi|logicalFrame'" >> "%SONDA%" 2>&1

>> "%SONDA%" echo.
>> "%SONDA%" echo --- o mouse que o scrcpy cria ---
"%ADB%" shell "dumpsys input | grep -A 30 -i 'Device .*: scrcpy'" >> "%SONDA%" 2>&1

>> "%SONDA%" echo.
>> "%SONDA%" echo === FIM %DATE% %TIME% ===
>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%

echo    Pronto. O resultado esta em relatorios\sonda_mouse.txt
echo    ^(me avise que eu leio daqui^)
echo.
set /p "TECLA=Leia o resultado. Aperte ENTER para fechar: "
