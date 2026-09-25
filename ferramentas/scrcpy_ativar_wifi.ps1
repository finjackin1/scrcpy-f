$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

$ipFile = Join-Path $projectRoot "phone_ip.txt"
$pathFile = Join-Path $projectRoot "caminho-scrcpy.txt"
$Host.UI.RawUI.WindowTitle = "Configurar scrcpy Wi-Fi"

Clear-Host

if (-not (Test-Path $pathFile)) {
    Write-Host "  Falta o arquivo caminho-scrcpy.txt na pasta do projeto." -ForegroundColor Red
    Read-Host "  Pressione Enter para fechar"
    exit
}
$scrcpyDir = (Get-Content $pathFile -TotalCount 1).Trim()
$adbExe = Join-Path $scrcpyDir "adb.exe"
$scrcpyExe = Join-Path $scrcpyDir "scrcpy.exe"
if (-not (Test-Path $adbExe) -or -not (Test-Path $scrcpyExe)) {
    Write-Host "  Nao encontrei adb.exe / scrcpy.exe em:" -ForegroundColor Red
    Write-Host "  $scrcpyDir" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Abra caminho-scrcpy.txt e coloque o caminho certo da pasta do scrcpy." -ForegroundColor Yellow
    Read-Host "  Pressione Enter para fechar"
    exit
}

Write-Host ""
Write-Host "  Conecte o celular no PC com o cabo USB." -ForegroundColor Cyan
Write-Host "  Se aparecer um aviso no celular, toque em Permitir." -ForegroundColor Cyan
Write-Host ""

& $adbExe start-server *> $null

# ----------------------------------------------------------------------
# Espera o celular aparecer - com limite, pra nao ficar preso pra sempre
# se o cabo estiver ruim ou a depuracao USB desligada.
# ----------------------------------------------------------------------
$limite = 60
$inicio = Get-Date
$deviceSerial = $null
$authWarned = $false

while (-not $deviceSerial) {
    $passados = [int]((Get-Date) - $inicio).TotalSeconds
    if ($passados -ge $limite) {
        Write-Host ""
        Write-Host ""
        Write-Host "  Nao achei nenhum celular em $limite segundos." -ForegroundColor Red
        Write-Host ""
        Write-Host "  Confira:" -ForegroundColor Yellow
        Write-Host "   - o cabo esta conectado (e e um cabo de dados, nao so de carga)" -ForegroundColor Yellow
        Write-Host "   - 'Depuracao USB' esta ligada nas Opcoes do desenvolvedor" -ForegroundColor Yellow
        Write-Host "   - o aviso de autorizacao no celular foi aceito" -ForegroundColor Yellow
        Write-Host ""
        Read-Host "  Pressione Enter para fechar"
        exit
    }

    Write-Host -NoNewline ("`r  Aguardando o celular... {0}s de {1}s   " -f $passados, $limite)

    Start-Sleep -Milliseconds 800
    $lines = & $adbExe devices 2>$null | Select-Object -Skip 1 | Where-Object { $_.Trim() -ne "" }
    foreach ($line in $lines) {
        if ($line -match "^(\S+)\s+device$") {
            $deviceSerial = $matches[1]
            break
        } elseif ($line -match "^(\S+)\s+unauthorized$" -and -not $authWarned) {
            Write-Host ""
            Write-Host "  Autorize a depuracao USB na tela do celular." -ForegroundColor Red
            $authWarned = $true
        }
    }
}

Write-Host ""
Write-Host ""
Write-Host "  Celular conectado! Configurando..." -ForegroundColor Green
Write-Host ""

function Show-Bar($pct, $label) {
    $barLen = 30
    $filled = [int]($barLen * $pct / 100)
    $bar = ("#" * $filled).PadRight($barLen, '-')
    Write-Host -NoNewline ("`r  [{0}] {1,3}%  {2}          " -f $bar, $pct, $label)
}

Show-Bar 10 "Reiniciando ADB"
& $adbExe kill-server *> $null
& $adbExe start-server *> $null
Start-Sleep -Milliseconds 400

Show-Bar 35 "Ativando Wi-Fi ADB"
& $adbExe -s $deviceSerial tcpip 5555 *> $null
Start-Sleep -Milliseconds 1200

Show-Bar 60 "Detectando IP do celular"
$ip = $null
$routeOut = & $adbExe -s $deviceSerial shell ip route 2>$null
foreach ($l in $routeOut) {
    if ($l -match "wlan0.*src\s+(\d+\.\d+\.\d+\.\d+)") { $ip = $matches[1]; break }
}
if (-not $ip) {
    $addrOut = & $adbExe -s $deviceSerial shell ip -f inet addr show wlan0 2>$null
    foreach ($l in $addrOut) {
        if ($l -match "inet\s+(\d+\.\d+\.\d+\.\d+)") { $ip = $matches[1]; break }
    }
}

# ----------------------------------------------------------------------
# Teste de verdade: nao adianta dizer "pronto" sem confirmar que a
# conexao Wi-Fi responde - e ela que o jogo e o audio vao usar depois.
# ----------------------------------------------------------------------
Show-Bar 85 "Testando conexao Wi-Fi"
$conectou = $false
if ($ip) {
    $saida = & $adbExe connect "${ip}:5555" 2>&1 | Out-String
    $conectou = ($saida -match "connected")
    Start-Sleep -Milliseconds 400
}

Show-Bar 100 "Concluido"
Write-Host ""
Write-Host ""

# IP nao detectado: pede na mao e testa igual.
if (-not $ip) {
    Write-Host "  Nao consegui detectar o IP automaticamente." -ForegroundColor Red
    $ip = (Read-Host "  Digite o IP do celular (Ajustes > Wi-Fi)").Trim()
    if (-not $ip) {
        Write-Host "  Cancelado. Rode o script novamente." -ForegroundColor Red
        Read-Host "  Pressione Enter para fechar"
        exit
    }
    $saida = & $adbExe connect "${ip}:5555" 2>&1 | Out-String
    $conectou = ($saida -match "connected")
}

if (-not $conectou) {
    Write-Host "  Achei o celular pelo cabo, mas a conexao Wi-Fi nao respondeu." -ForegroundColor Red
    Write-Host "  IP testado: $ip" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Confira se o celular esta na mesma rede Wi-Fi do PC" -ForegroundColor Yellow
    Write-Host "  (e nao em rede de convidados ou com VPN ligada) e tente de novo." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Pressione Enter para fechar"
    exit
}

# So grava o IP depois de confirmar que ele funciona.
Set-Content -Path $ipFile -Value $ip -NoNewline
Write-Host "  Tudo pronto! Pode desconectar o cabo USB." -ForegroundColor Green
Write-Host "  So precisa repetir isso se reiniciar o celular." -ForegroundColor Green
Write-Host ""
Read-Host "  Leia o resultado. Aperte ENTER para fechar"
