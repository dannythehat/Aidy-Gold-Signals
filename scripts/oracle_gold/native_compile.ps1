param([Parameter(Mandatory=$true)][string]$OutDir)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$work = Join-Path $env:RUNNER_TEMP 'oracle-mql-compile'
New-Item -ItemType Directory -Force -Path $work | Out-Null
$compiler = Join-Path $work 'mql64.exe'
$compilerUrl = 'https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mql64.exe'
$rows = @()
$compilerReceipt = @{url=$compilerUrl; available=$false; terminal_started=$false; broker_connection=$false}
try {
    Invoke-WebRequest -Uri $compilerUrl -OutFile $compiler -TimeoutSec 60
    $sig = Get-AuthenticodeSignature $compiler
    $compilerReceipt.sha256 = (Get-FileHash -Algorithm SHA256 $compiler).Hash.ToLower()
    $compilerReceipt.signature_status = [string]$sig.Status
    $compilerReceipt.signer = [string]$sig.SignerCertificate.Subject
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'MetaQuotes') {
        throw 'Original compiler signature is not verified'
    }
    $compilerReceipt.available = $true
    $compilerReceipt.file_version = (Get-Item $compiler).VersionInfo.FileVersion
} catch {
    $compilerReceipt.error = $_.Exception.Message
}
$sdk = Join-Path $work 'MQL5'
New-Item -ItemType Directory -Force -Path (Join-Path $sdk 'Indicators') | Out-Null
$pins = Get-Content 'research/gold_oracle/phase04/mql_compile_pins.json' -Raw | ConvertFrom-Json
# Compile the resource indicator first; every original byte remains unchanged.
$pins = $pins | Sort-Object @{Expression={if ($_.path -eq 'SuperTrendTV.mq5') {0} else {1}}},path
foreach ($pin in $pins) {
    $row = @{ids=$pin.ids; source_url=$pin.endpoint; source_sha256=$pin.sha256; path=$pin.path;
        status='NOT_COMPILED'; source_modified=$false; platform_execution_parity=$false}
    try {
        if (-not $compilerReceipt.available) {throw 'BLOCKED_OFFICIAL_COMPILER_UNAVAILABLE'}
        $dir = Join-Path $work $pin.sha256.Substring(0,16)
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $src = Join-Path $dir $pin.path
        Invoke-WebRequest -Uri $pin.endpoint -OutFile $src -TimeoutSec 45 -UserAgent 'Mozilla/5.0'
        if ((Get-FileHash -Algorithm SHA256 $src).Hash.ToLower() -ne $pin.sha256) {throw 'Original source hash mismatch'}
        $stdout = Join-Path $dir 'stdout.log'
        $stderr = Join-Path $dir 'stderr.log'
        $process = Start-Process -FilePath $compiler -ArgumentList @("`"$src`"", "/i:`"$sdk`"") -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        if (-not $process.WaitForExit(60000)) {$process.Kill(); throw 'Native compiler60second timeout'}
        $row.exit_code = $process.ExitCode
        $binary = [IO.Path]::ChangeExtension($src, '.ex5')
        $row.status = 'NATIVE_COMPILE_FAILED'
        if ((Test-Path $binary) -and (Get-Item $binary).Length -gt 0) {
            $row.status = 'NATIVE_COMPILED'
            $row.ex5_sha256 = (Get-FileHash -Algorithm SHA256 $binary).Hash.ToLower()
            if ($pin.path -eq 'SuperTrendTV.mq5') {Copy-Item $binary (Join-Path $sdk 'Indicators/SuperTrendTV.ex5')}
        }
        $logdir = Join-Path $OutDir $pin.sha256.Substring(0,16)
        New-Item -ItemType Directory -Force -Path $logdir | Out-Null
        foreach ($log in Get-ChildItem $dir -Filter '*.log') {
            Copy-Item $log.FullName (Join-Path $logdir $log.Name)
        }
        $row.standard_library_available = Test-Path (Join-Path $sdk 'Include/Trade/Trade.mqh')
    } catch {
        $row.error = $_.Exception.Message
        if (-not $compilerReceipt.available) {$row.status='BLOCKED_OFFICIAL_COMPILER_UNAVAILABLE'}
        else {$row.status='BLOCKED_SOURCE_OR_COMPILER_INVOCATION'}
    }
    $rows += $row
    Write-Output "$($pin.path): $($row.status)"
}
@{schema='oracle.gold.native_compile_attempt.v1'; compiler=$compilerReceipt; sources=$rows;
  notes='Official standalone compiler only. No MetaTrader terminal, broker login, strategy tester or account started. Missing native SDK is a dependency blocker, not a strategy loss.'} |
  ConvertTo-Json -Depth 12 | Set-Content (Join-Path $OutDir 'native_compile_report.json') -Encoding utf8
