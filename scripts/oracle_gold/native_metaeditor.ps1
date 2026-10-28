param([Parameter(Mandatory=$true)][string]$OutDir)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$work = Join-Path $env:RUNNER_TEMP 'oracle-official-sdk'
New-Item -ItemType Directory -Force -Path $work | Out-Null
$install = Join-Path $work 'platform'
$receipt = @{terminal_started=$false; broker_connection=$false; native_execution_parity=$false; sources=@()}
try {
    # Ephemeral hosted runner only. Intercept every terminal/tester launch
    # BEFORE installation, including any installer automatic startup.
    foreach ($exe in @('terminal.exe','terminal64.exe','metatester.exe','metatester64.exe')) {
        $key = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\$exe"
        New-Item -Path $key -Force | Out-Null
        New-ItemProperty -Path $key -Name Debugger -Value 'C:\Windows\System32\cmd.exe /c exit 0' -PropertyType String -Force | Out-Null
        if ((Get-ItemProperty $key).Debugger -ne 'C:\Windows\System32\cmd.exe /c exit 0') {throw 'Terminal execution interception not established'}
    }
    $receipt.terminal_execution_intercepted_before_install = $true
    $setup = Join-Path $work 'mt5setup.exe'
    $url = 'https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe'
    Invoke-WebRequest -Uri $url -OutFile $setup -TimeoutSec 60
    $sig = Get-AuthenticodeSignature $setup
    $receipt.installer = @{url=$url; sha256=(Get-FileHash $setup -Algorithm SHA256).Hash.ToLower(); signature=[string]$sig.Status; signer=[string]$sig.SignerCertificate.Subject}
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'MetaQuotes') {throw 'Official installer Authenticode not verified'}
    $p = Start-Process $setup -ArgumentList @('/auto',"/path:`"$install`"") -PassThru
    if (-not $p.WaitForExit(360000)) {$p.Kill(); throw 'Official SDK installer timeout'}
    $compiler = Join-Path $install 'metaeditor64.exe'
    if (-not (Test-Path $compiler)) {throw 'Official MetaEditor not installed'}
    $sig = Get-AuthenticodeSignature $compiler
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'MetaQuotes') {throw 'MetaEditor Authenticode not verified'}
    $receipt.compiler = @{sha256=(Get-FileHash $compiler -Algorithm SHA256).Hash.ToLower(); signature=[string]$sig.Status; signer=[string]$sig.SignerCertificate.Subject; version=(Get-Item $compiler).VersionInfo.FileVersion}
    $sdk = Join-Path $install 'MQL5'
    if (-not (Test-Path (Join-Path $sdk 'Include/Trade/Trade.mqh'))) {throw 'Official standard library not installed'}
    $receipt.standard_library_sha256 = @{}
    foreach ($f in Get-ChildItem (Join-Path $sdk 'Include') -Filter '*.mqh' -Recurse) {
        $receipt.standard_library_sha256[$f.FullName.Substring($sdk.Length+1)] = (Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLower()
    }
    $pins = Get-Content 'research/gold_oracle/phase04/mql_compile_pins.json' -Raw | ConvertFrom-Json
    $pins = $pins | Sort-Object @{Expression={if ($_.path -eq 'SuperTrendTV.mq5') {0} else {1}}},path
    foreach ($pin in $pins) {
        $row = @{ids=$pin.ids; source_url=$pin.endpoint; source_sha256=$pin.sha256; path=$pin.path; source_modified=$false; status='NOT_COMPILED'}
        try {
            $dir = Join-Path $work $pin.sha256.Substring(0,16)
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            $src = Join-Path $dir $pin.path
            Invoke-WebRequest -Uri $pin.endpoint -OutFile $src -TimeoutSec 45 -UserAgent 'Mozilla/5.0'
            if ((Get-FileHash $src -Algorithm SHA256).Hash.ToLower() -ne $pin.sha256) {throw 'Original bytes changed'}
            $p = Start-Process $compiler -ArgumentList @('/portable',"/compile:`"$src`"", "/include:`"$sdk`"",'/log') -PassThru
            if (-not $p.WaitForExit(60000)) {$p.Kill(); throw 'Compiler timeout'}
            $binary = [IO.Path]::ChangeExtension($src,'.ex5')
            $log = [IO.Path]::ChangeExtension($src,'.log')
            $row.status = 'NATIVE_COMPILE_FAILED'
            if ((Test-Path $binary) -and (Get-Item $binary).Length -gt 0) {
                $row.status = 'NATIVE_COMPILED'
                $row.ex5_sha256 = (Get-FileHash $binary -Algorithm SHA256).Hash.ToLower()
                if ($pin.path -eq 'SuperTrendTV.mq5') {Copy-Item $binary (Join-Path $sdk 'Indicators/SuperTrendTV.ex5') -Force}
            }
            if (Test-Path $log) {
                $row.log_sha256 = (Get-FileHash $log -Algorithm SHA256).Hash.ToLower()
                Copy-Item $log (Join-Path $OutDir ($pin.path+'.log'))
            }
        } catch {$row.error=$_.Exception.Message}
        $receipt.sources += $row
        Write-Output "$($row.path) $($row.status)"
    }
} catch {$receipt.environment_blocker=$_.Exception.Message}
$receipt.terminal_processes_running = @(Get-Process -Name terminal,terminal64,metatester,metatester64 -ErrorAction SilentlyContinue).Count
if ($receipt.terminal_processes_running -ne 0) {throw 'Unexpected terminal process'}
$receipt | ConvertTo-Json -Depth 12 | Set-Content (Join-Path $OutDir 'native_metaeditor_report.json') -Encoding utf8
