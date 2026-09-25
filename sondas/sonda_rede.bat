@echo off
REM ===========================================================================
REM SONDA DA REDE ATE O CELULAR (21/set/2026)
REM
REM Mede o caminho que o mouse faz ate o celular: quanto tempo leva, o quanto
REM esse tempo VARIA (e a variacao que faz o cursor engasgar, nao a media) e
REM quantos pacotes se perdem. Serve para separar "o Wi-Fi esta ruim" de "o
REM programa esta pesado" sem precisar de cabo.
REM
REM RODAR COM A EXTENSAO LIGADA e, de preferencia, mexendo o mouse no celular
REM enquanto ela corre -- e assim que a rede esta quando o problema aparece.
REM
REM Grava relatorios\sonda_rede.txt (substituido a cada sonda).
REM Caminhos relativos ao proprio script.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0.."

if not exist "relatorios" md "relatorios"
set "SONDA=relatorios\sonda_rede.txt"
>> "relatorios\partida.txt" echo.
>> "relatorios\partida.txt" echo [sonda_rede.bat] %DATE% %TIME%

set "ADB="
for /f "delims=" %%A in ('python -c "from scrcpyf.config import Config; print(Config.carregar().adb_exe)" 2^>^>"relatorios\partida.txt"') do set "ADB=%%A"
set "IP="
for /f "delims=" %%A in ('python -c "from scrcpyf.config import Config; print(Config.carregar().ip_reserva)" 2^>^>"relatorios\partida.txt"') do set "IP=%%A"

if not defined ADB (
  echo.
  echo   Nao achei o adb. Abra o Configurar e aponte a pasta do scrcpy.
  set /p "TECLA=Leia o resultado. Aperte ENTER para fechar: "
  exit /b 1
)

echo.
echo    Medindo a rede ate o celular... ^(uns 30 segundos^)
echo    Mexa o mouse no celular enquanto isso, se der.
echo.

> "%SONDA%" echo === SONDA DA REDE %DATE% %TIME% ===
>> "%SONDA%" echo celular: %IP%

>> "%SONDA%" echo.
>> "%SONDA%" echo --- o Wi-Fi do PC ---
netsh wlan show interfaces >> "%SONDA%" 2>&1

>> "%SONDA%" echo.
>> "%SONDA%" echo --- 100 idas e voltas ate o celular ---
if defined IP (
  ping -n 100 -w 1000 %IP% >> "%SONDA%" 2>&1
) else (
  >> "%SONDA%" echo sem endereco guardado; pulei
)

>> "%SONDA%" echo.
>> "%SONDA%" echo --- 30 idas e voltas passando pelo adb (como o mouse passa) ---
set "MEDIR=$m=@(); for($i=0;$i -lt 30;$i++){ $t=[Diagnostics.Stopwatch]::StartNew(); & $env:ADB shell echo ok ^| Out-Null; $t.Stop(); $m += $t.Elapsed.TotalMilliseconds }; $o=$m ^| Measure-Object -Average -Minimum -Maximum; '{0:N0} idas: minimo {1:N0} ms, media {2:N0} ms, PIOR {3:N0} ms' -f $o.Count,$o.Minimum,$o.Average,$o.Maximum"
powershell -NoProfile -ExecutionPolicy Bypass -Command "%MEDIR%" >> "%SONDA%" 2>&1

>> "%SONDA%" echo.
>> "%SONDA%" echo === FIM %DATE% %TIME% ===
>> "relatorios\partida.txt" echo [fim] %DATE% %TIME%

echo    Pronto. O resultado esta em relatorios\sonda_rede.txt
echo    ^(me avise que eu leio daqui^)
echo.
set /p "TECLA=Leia o resultado. Aperte ENTER para fechar: "
