$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

$ipFile = Join-Path $projectRoot "phone_ip.txt"
$pathFile = Join-Path $projectRoot "caminho-scrcpy.txt"
$relDir = Join-Path $projectRoot "relatorios"
$ultimo = Join-Path $relDir "ultimo.txt"
$historico = Join-Path $relDir "historico.txt"

$Host.UI.RawUI.WindowTitle = "Diagnostico scrcpy-f"
Clear-Host

$linhas = New-Object System.Collections.ArrayList
function Reg($txt) { [void]$linhas.Add($txt) }

Reg "=== DIAGNOSTICO scrcpy-f - $(Get-Date) ==="
Reg ""

# ----------------------------------------------------------------------
# Configuracao
# ----------------------------------------------------------------------
$ipSalvo = $null
if (Test-Path $ipFile) {
    $ipSalvo = (Get-Content $ipFile -TotalCount 1).Trim()
    Reg "IP salvo em phone_ip.txt: $ipSalvo"
} else {
    Reg "phone_ip.txt: NAO EXISTE"
}

$adbExe = $null
if (Test-Path $pathFile) {
    $scrcpyDir = (Get-Content $pathFile -TotalCount 1).Trim()
    $adbExe = Join-Path $scrcpyDir "adb.exe"
    Reg "Pasta do scrcpy: $scrcpyDir"
    Reg "adb.exe existe: $(Test-Path $adbExe)"
} else {
    Reg "caminho-scrcpy.txt: NAO EXISTE"
}
Reg ""

Write-Host ""
Write-Host "  Diagnosticando... isso leva menos de um minuto." -ForegroundColor Cyan
Write-Host ""

# ----------------------------------------------------------------------
# Rede do PC
# ----------------------------------------------------------------------
Write-Host -NoNewline "  [1/5] Lendo a rede do PC..."
$bases = New-Object System.Collections.ArrayList
try {
    $enderecos = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" }
    foreach ($e in $enderecos) {
        Reg "IPv4 do PC: $($e.IPAddress)  (adaptador: $($e.InterfaceAlias))"
        $b = ($e.IPAddress -split '\.')[0..2] -join '.'
        if (-not $bases.Contains($b)) { [void]$bases.Add($b) }
    }
} catch {
    Reg "Get-NetIPAddress falhou: $($_.Exception.Message)"
}
if ($ipSalvo) {
    $b = ($ipSalvo -split '\.')[0..2] -join '.'
    if (-not $bases.Contains($b)) { [void]$bases.Add($b) }
}
Reg "Faixas que serao varridas: $($bases -join ', ')"
Reg ""
Write-Host " ok"

# ----------------------------------------------------------------------
# O IP salvo responde ao ping? (a checagem que os scripts usam hoje)
# ----------------------------------------------------------------------
Write-Host -NoNewline "  [2/5] Testando o endereco salvo..."
if ($ipSalvo) {
    $pingOk = $false
    for ($t = 1; $t -le 2; $t++) {
        & ping.exe -n 1 -w 700 $ipSalvo *> $null
        if ($LASTEXITCODE -eq 0) { $pingOk = $true; break }
    }
    Reg "PING no IP salvo ($ipSalvo): $(if ($pingOk) { 'RESPONDEU' } else { 'nao respondeu' })"
} else {
    Reg "PING no IP salvo: pulado (sem IP salvo)"
}
Write-Host " ok"

# ----------------------------------------------------------------------
# A porta do ADB esta aberta no IP salvo? (ignora o ping de proposito)
# ----------------------------------------------------------------------
function PortaAberta($enderecoIp, $porta, $esperaMs) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $ar = $c.BeginConnect($enderecoIp, $porta, $null, $null)
        $ok = $ar.AsyncWaitHandle.WaitOne($esperaMs, $false)
        $conectado = ($ok -and $c.Connected)
        $c.Close()
        return $conectado
    } catch { return $false }
}

Write-Host -NoNewline "  [3/5] Testando a porta do celular..."
if ($ipSalvo) {
    $portaOk = PortaAberta $ipSalvo 5555 1500
    Reg "PORTA 5555 no IP salvo ($ipSalvo): $(if ($portaOk) { 'ABERTA' } else { 'fechada/sem resposta' })"
} else {
    Reg "PORTA 5555 no IP salvo: pulado (sem IP salvo)"
}
Write-Host " ok"

# ----------------------------------------------------------------------
# Varredura: quem na rede tem a porta do ADB aberta?
# ----------------------------------------------------------------------
Write-Host -NoNewline "  [4/5] Procurando o celular na rede..."
$achados = New-Object System.Collections.ArrayList
foreach ($base in $bases) {
    $pendentes = @{}
    foreach ($n in 1..254) {
        $alvoIp = "$base.$n"
        try {
            $c = New-Object System.Net.Sockets.TcpClient
            $pendentes[$alvoIp] = @{ C = $c; A = $c.BeginConnect($alvoIp, 5555, $null, $null) }
        } catch { }
    }
    Start-Sleep -Milliseconds 2000
    foreach ($k in $pendentes.Keys) {
        try {
            if ($pendentes[$k].C.Connected) { [void]$achados.Add($k) }
            $pendentes[$k].C.Close()
        } catch { }
    }
}
if ($achados.Count -gt 0) {
    Reg "APARELHOS COM A PORTA 5555 ABERTA: $($achados -join ', ')"
} else {
    Reg "APARELHOS COM A PORTA 5555 ABERTA: nenhum encontrado"
}
Reg ""
Write-Host " ok"

# ----------------------------------------------------------------------
# O que o ADB acha de tudo isso
# ----------------------------------------------------------------------
Write-Host -NoNewline "  [5/5] Perguntando pro ADB..."
if ($adbExe -and (Test-Path $adbExe)) {
    Reg "--- adb devices (antes) ---"
    Reg ((& $adbExe devices 2>&1 | Out-String).Trim())

    if ($ipSalvo) {
        Reg "--- adb connect no IP salvo ---"
        Reg ((& $adbExe connect "${ipSalvo}:5555" 2>&1 | Out-String).Trim())
    }

    foreach ($a in $achados) {
        if ($a -ne $ipSalvo) {
            Reg "--- adb connect no candidato $a ---"
            Reg ((& $adbExe connect "${a}:5555" 2>&1 | Out-String).Trim())
        }
    }

    Reg "--- adb devices (depois) ---"
    Reg ((& $adbExe devices 2>&1 | Out-String).Trim())
} else {
    Reg "ADB nao encontrado - etapa pulada."
}
Reg ""

Reg "--- arp -a ---"
Reg ((& arp.exe -a 2>&1 | Out-String).Trim())
Reg ""
Reg "=== FIM ==="
Write-Host " ok"

# ----------------------------------------------------------------------
# Grava o relatorio
# ----------------------------------------------------------------------
if (-not (Test-Path $relDir)) { New-Item -ItemType Directory -Path $relDir -Force | Out-Null }
$texto = $linhas -join "`r`n"
Set-Content -Path $ultimo -Value $texto -Encoding UTF8
Add-Content -Path $historico -Value ($texto + "`r`n") -Encoding UTF8

Write-Host ""
Write-Host "  Pronto. Pode me avisar que rodou - eu leio o resultado daqui." -ForegroundColor Green
Write-Host ""
Read-Host "  Leia o resultado. Aperte ENTER para fechar"
