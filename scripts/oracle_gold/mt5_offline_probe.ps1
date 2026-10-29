param([Parameter(Mandatory=$true)][string]$OutDir)
$ErrorActionPreference='Stop'
# Fresh hosted runner only. Reuse the signed SDK acquisition and original S040
# compilation. No original source, account or historic research file is changed.
& ./scripts/oracle_gold/native_metaeditor.ps1 -OutDir (Join-Path $OutDir 'compile') -InitialiseSdkOffline -OnlyId S040
$install=Join-Path $env:RUNNER_TEMP 'oracle-official-sdk/platform'
$work=Join-Path $env:RUNNER_TEMP 'oracle-official-sdk'
$receipt=@{scope='OFFLINE_RUNTIME_REACHABILITY_ONLY_NOT_A_STRATEGY_BACKTEST'; broker_connection=$false; account_credentials_supplied=$false; native_strategy_parity=$false; attempts=@()}
try {
    if ((Get-Service MpsSvc).Status -ne 'Running') {throw 'Firewall is not running'}
    $compiler=Join-Path $install 'metaeditor64.exe'
    $terminal=Join-Path $install 'terminal64.exe'
    foreach ($name in @('terminal64.exe','metatester64.exe','metatester.exe')) {
        foreach ($file in @(Get-ChildItem $install -Filter $name -Recurse)) {
            foreach ($direction in @('Inbound','Outbound')) {
                New-NetFirewallRule -DisplayName "OracleProbe-$name-$direction" -Direction $direction -Action Block -Program $file.FullName -Profile Any -Enabled True | Out-Null
            }
        }
    }
    $receipt.network_policy='ALL_TERMINAL_AND_TESTER_INBOUND_OUTBOUND_BLOCKED; CLOUD_REMOTE_AGENTS_DISABLED'
    $scripts=Join-Path $install 'MQL5/Scripts'
    $experts=Join-Path $install 'MQL5/Experts'
    New-Item -ItemType Directory -Force $scripts,$experts | Out-Null
    $script=Join-Path $scripts 'OracleOfflineSymbolProbe.mq5'
    @'
#property strict
void OnStart() {
  bool connected=(bool)TerminalInfoInteger(TERMINAL_CONNECTED);
  if(connected) { Print("ORACLE_PROBE_REFUSED_CONNECTED"); return; }
  ResetLastError();
  bool made=CustomSymbolCreate("AIDY_OFFLINE_PROBE","AIDY_RESEARCH");
  int error=GetLastError();
  PrintFormat("ORACLE_OFFLINE_SYMBOL_PROBE connected=%d created=%d error=%d",connected,made,error);
  int f=FileOpen("oracle_offline_symbol_probe.txt",FILE_WRITE|FILE_TXT|FILE_COMMON);
  if(f!=INVALID_HANDLE) {FileWrite(f,"connected",connected,"created",made,"error",error);FileClose(f);}
}
'@ | Set-Content $script -Encoding ascii
    $expert=Join-Path $experts 'OracleMathProbe.mq5'
    @'
#property strict
int OnInit() {
  if(!MQLInfoInteger(MQL_TESTER)) return(INIT_FAILED);
  Print("ORACLE_MATH_PROBE_INIT tester=1 no_orders=1");
  return(INIT_SUCCEEDED);
}
void OnTick() {}
double OnTester() { Print("ORACLE_MATH_PROBE_TESTER_COMPLETED"); return(1.0); }
'@ | Set-Content $expert -Encoding ascii
    foreach ($file in @($script,$expert)) {
        $p=Start-Process $compiler -ArgumentList @('/portable',"/compile:`"$file`"",'/log') -PassThru
        if(-not $p.WaitForExit(60000)) {$p.Kill();throw 'Probe compilation timeout'}
        if(-not (Test-Path ([IO.Path]::ChangeExtension($file,'.ex5')))) {throw 'Probe did not compile'}
        Copy-Item ([IO.Path]::ChangeExtension($file,'.log')) (Join-Path $OutDir ([IO.Path]::GetFileName($file)+'.compile.log'))
    }
    $base=@('[Common]','Login=0','Server=','Password=','MQL5Login=','MQL5Password=','KeepPrivate=0','NewsEnable=0','CertInstall=0',
        '[Experts]','Enabled=0','AllowLiveTrading=0','AllowDllImport=0')
    $configs=@(
      @{name='custom_symbol_startup'; lines=@('[StartUp]','Script=OracleOfflineSymbolProbe','Symbol=EURUSD','Period=M1','ShutdownTerminal=1')},
      @{name='math_tester'; lines=@('[StartUp]','Expert=','Script=','[Tester]','Expert=OracleMathProbe','Symbol=EURUSD','Period=H1','Model=3','Optimization=0','FromDate=2023.01.01','ToDate=2023.01.02','Deposit=10000','Currency=USD','Leverage=1:1','UseLocal=1','UseRemote=0','UseCloud=0','Visual=0','Report=oracle_math_probe.htm','ReplaceReport=0','ShutdownTerminal=1')}
    )
    foreach ($config in $configs) {
        $ini=Join-Path $work ($config.name+'.ini')
        ($base+$config.lines)|Set-Content $ini -Encoding ascii
        foreach ($exe in @('terminal64.exe','metatester.exe','metatester64.exe')) {
            $key="HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\$exe"
            Remove-ItemProperty $key -Name Debugger -ErrorAction SilentlyContinue
        }
        try {
            $p=Start-Process $terminal -ArgumentList @('/portable',"/config:`"$ini`"") -PassThru
            $ended=$p.WaitForExit(45000)
            if(-not $ended){$p.Kill();$p.WaitForExit()}
            $receipt.attempts+=@{name=$config.name; native_process_exited=$ended; config_sha256=(Get-FileHash $ini -Algorithm SHA256).Hash.ToLower()}
        } finally {
            Get-Process terminal64,metatester64,metatester -ErrorAction SilentlyContinue | Stop-Process -Force
            foreach ($exe in @('terminal64.exe','metatester.exe','metatester64.exe')) {
                $key="HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\$exe"
                New-ItemProperty $key -Name Debugger -Value 'C:\Windows\System32\cmd.exe /c exit 0' -PropertyType String -Force | Out-Null
            }
        }
    }
    $common=Join-Path $env:APPDATA 'MetaQuotes/Terminal/Common/Files/oracle_offline_symbol_probe.txt'
    $receipt.custom_symbol_script_executed=Test-Path $common
    if(Test-Path $common){Copy-Item $common (Join-Path $OutDir 'custom_symbol_result.txt')}
    $allLogs=@(Get-ChildItem $install -Filter '*.log' -Recurse)
    $receipt.math_tester_callback_observed=$false
    $i=0
    foreach($log in $allLogs){
        $i++
        $text=Get-Content $log.FullName -Raw -ErrorAction SilentlyContinue
        if($text -match 'ORACLE_MATH_PROBE_TESTER_COMPLETED'){$receipt.math_tester_callback_observed=$true}
        Copy-Item $log.FullName (Join-Path $OutDir ("runtime-$i-"+$log.Name))
    }
    $receipt.original_EA_historical_execution_attempted=$false
    $receipt.blocker='If startup/tester callbacks are absent, preserve native logs: fresh account-free offline platform could not bootstrap custom-symbol/tester execution. No broker connection or assumed account allowed.'
} catch {$receipt.environment_blocker=$_.Exception.Message}
$receipt.remaining_terminal_processes=@(Get-Process terminal64,metatester64,metatester -ErrorAction SilentlyContinue).Count
if($receipt.remaining_terminal_processes -ne 0){throw 'Unexpected remaining terminal process'}
$receipt|ConvertTo-Json -Depth 12|Set-Content (Join-Path $OutDir 'offline_probe_report.json') -Encoding utf8
