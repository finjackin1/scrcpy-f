@echo off
setlocal EnableDelayedExpansion
chcp 65001 > nul
title scrcpy-f - publicar

rem ===========================================================================
rem Monta o scrcpy-f num pacote PRONTO PARA OUTRA PESSOA: um zip que ela
rem extrai e usa, sem instalar Python. O scrcpy NAO vai junto (decisao dele,
rem 19/set/2026): cada um baixa o seu, e na primeira abertura o proprio
rem programa abre em OPCOES pedindo a pasta dele.
rem
rem O QUE SAI
rem ---------
rem     dist\scrcpy-f\       <- SEM a versao no nome (pedido dele, 23/set/2026:
rem                               ele extrai sempre no mesmo lugar)
rem         scrcpy-f.exe              <- o programa
rem         _internal\                <- Python, Pillow, pystray (OCULTA; os
rem                                      relatorios tambem moram aqui)
rem         LEIA-ME.txt               <- o passo a passo para quem recebe
rem         README.md, LICENSE.txt, THIRD-PARTY-NOTICES.txt
rem     dist\scrcpy-f-<versao>.zip  <- e este que se manda
rem
rem O SEU config.json NAO VAI: tem o endereco do seu celular e as suas
rem escolhas. Na primeira abertura quem recebe escolhe a pasta do scrcpy
rem e pareia o celular dentro do proprio programa.
rem
rem LOG: a saida inteira da compilacao vai para relatorios\publicar.txt
rem (substituido a cada publicacao); abertura e fim em relatorios\partida.txt.
rem Caminhos relativos ao proprio script, nunca absolutos.
rem ===========================================================================

pushd "%~dp0"
if not exist "relatorios" mkdir "relatorios"
set "PARTIDA=relatorios\partida.txt"
set "LOG=%~dp0relatorios\publicar.txt"
>>"%PARTIDA%" echo.
>>"%PARTIDA%" echo === PUBLICAR %DATE% %TIME% ===
> "%LOG%" echo === PUBLICAR %DATE% %TIME% ===

if not exist "app.py" (
  echo [ERRO] Nao encontrei app.py. Este .bat precisa ficar na pasta do scrcpy-f.
  >>"%PARTIDA%" echo sem app.py em %CD%
  goto :fim
)

rem A versao e LIDA DO CODIGO (scrcpyf\__init__.py), nunca digitada aqui:
rem dois lugares com o mesmo numero acabam com um zip chamado 0.5.0 contendo
rem outra coisa.
set "VER="
for /f %%V in ('python -c "import scrcpyf; print(scrcpyf.VERSAO)" 2^>^>"%LOG%"') do set "VER=%%V"
if not defined VER (
  echo [ERRO] Nao consegui ler a versao com o Python. Ele esta no PATH?
  >>"%PARTIDA%" echo sem versao
  goto :fim
)

set "SAIDA=%~dp0dist"
set "BRUTO=%SAIDA%\scrcpy-f"
set "PACOTE=%BRUTO%"
set "ZIP=%SAIDA%\scrcpy-f-%VER%.zip"

echo.
echo    scrcpy-f %VER%
echo.

rem --------------------------------------------------------------------------
echo [1/6] Conferindo as ferramentas...
python -c "import PyInstaller, PIL, pystray" 2>nul
if errorlevel 1 (
  echo       Faltava alguma. Instalando uma vez so...
  python -m pip install -r publicacao\requirements.txt -r publicacao\requirements-build.txt >>"%LOG%" 2>&1
  python -c "import PyInstaller, PIL, pystray" 2>>"%LOG%"
  if errorlevel 1 (
    echo.
    echo [ERRO] A instalacao falhou. O detalhe esta em relatorios\publicar.txt
    >>"%PARTIDA%" echo falhou instalar ferramentas
    goto :fim
  )
)

rem --------------------------------------------------------------------------
rem O icone do .exe sai do MESMO desenho da bandeja (scrcpyf\icone.py), no
rem estado "extensao". Gerado a cada publicacao, nunca guardado: um .ico
rem pronto no projeto seria uma segunda marca livre para divergir.
echo [2/6] Desenhando o icone...
python -c "from scrcpyf import icone; icone.desenhar('extensao').resize((256, 256)).save('publicacao/scrcpy-f.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])" 2>>"%LOG%"
if errorlevel 1 (
  echo [ERRO] Nao consegui gerar o icone. Detalhe em relatorios\publicar.txt
  goto :fim
)

rem --------------------------------------------------------------------------
echo [3/6] Compilando... ^(demora um pouco, e normal^)
if exist "%BRUTO%" rmdir /s /q "%BRUTO%"
python -m PyInstaller --noconfirm --clean --distpath "%SAIDA%" --workpath "%~dp0build" "publicacao\scrcpy-f.spec" >>"%LOG%" 2>&1
if errorlevel 1 goto :erro_compila
if not exist "%BRUTO%\scrcpy-f.exe" goto :erro_compila

rem --------------------------------------------------------------------------
rem Os textos ficam AO LADO do .exe, nao dentro do _internal: documento que a
rem pessoa tem que cacar numa pasta de DLLs e documento que ninguem le. A
rem LICENCA E OBRIGATORIA: a GPLv3 exige o texto junto do binario.
echo [4/6] Juntando os textos...
copy /y "README.md"                          "%BRUTO%\" >nul
copy /y "LICENSE"                            "%BRUTO%\LICENSE.txt" >nul
copy /y "docs\THIRD-PARTY-NOTICES.txt"         "%BRUTO%\" >nul
copy /y "ferramentas\LEIA-ME-pacote.txt"     "%BRUTO%\LEIA-ME.txt" >nul
rem Segunda barreira: o config.json de quem publica nunca vai no pacote.
if exist "%BRUTO%\config.json" del /q "%BRUTO%\config.json"

rem A pasta NAO leva a versao (o zip sim): extraida, vira sempre
rem "scrcpy-f", e o caminho dele nao muda de versao para versao.

rem --------------------------------------------------------------------------
rem O zip leva a PASTA dentro, nao os arquivos soltos: zip que se abre
rem derramando um .exe e um _internal na Area de Trabalho faz a pessoa
rem desistir antes de rodar.
echo [5/6] Compactando...
if exist "%ZIP%" del /q "%ZIP%"
set "ALVO=%PACOTE%"
set "ALVOZIP=%ZIP%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path $env:ALVO -DestinationPath $env:ALVOZIP -Force" 2>>"%LOG%"
if errorlevel 1 (
  echo [ERRO] Nao consegui compactar. A pasta pronta continua em:
  echo        %PACOTE%
  goto :fim
)
rem So DEPOIS do zip: o Compress-Archive pula pasta oculta, e o pacote sairia
rem sem o _internal. Na pasta local ela ja fica escondida; em quem recebe, o
rem proprio programa esconde ao abrir (caminhos.ocultar_pasta_interna).
if exist "%PACOTE%\_internal" attrib +h "%PACOTE%\_internal" >nul

rem --------------------------------------------------------------------------
echo [6/6] Conferindo o tamanho...
set "BYTESZIP=0"
for /f %%A in ('powershell -NoProfile -Command "(Get-Item $env:ALVOZIP).Length"') do set "BYTESZIP=%%A"
set /a TAMZIP=%BYTESZIP%/1048576
>>"%PARTIDA%" echo pronto: scrcpy-f-%VER%.zip ^(%TAMZIP% MB^)

echo.
echo    Pronto.
echo.
echo    Mande este arquivo:  dist\scrcpy-f-%VER%.zip   ^(%TAMZIP% MB^)
echo.
echo    Quem receber: extrair o zip, abrir a pasta e ler o LEIA-ME.txt.
echo    Na primeira abertura o programa pede a pasta do scrcpy; o celular
echo    se conecta no item PAREAR da janela.
echo.
echo    ANTES DE MANDAR, teste voce mesmo o scrcpy-f.exe da pasta
echo    dist\scrcpy-f ^(feche o scrcpy-f normal antes^):
echo      1. o scrcpy-f.exe abre a janela nova e o icone ao lado do relogio?
echo      2. em OPCOES a pasta do scrcpy aparece como certa?
echo      3. espelhar ou a extensao ligaram?
goto :fim

:erro_compila
echo.
echo [ERRO] A compilacao falhou. As ultimas linhas do registro:
echo.
powershell -NoProfile -Command "Get-Content -Tail 15 $env:LOG" 2>nul
>>"%PARTIDA%" echo compilacao falhou

:fim
>>"%PARTIDA%" echo [fim] %DATE% %TIME%
popd
echo.
set /p "TECLA=Leia o resultado. Aperte ENTER para fechar: "
endlocal
