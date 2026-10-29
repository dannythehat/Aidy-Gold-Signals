param([Parameter(Mandatory=$true)][string]$OutDir, [Parameter(Mandatory=$true)][string]$Quotes, [switch]$IndicatorsOnly)
$ErrorActionPreference='Stop'
# Reuse verified signed installation, SDK, custom-symbol and tester bootstrap.
& ./scripts/oracle_gold/mt5_offline_probe.ps1 -OutDir (Join-Path $OutDir 'bootstrap')
$install=Join-Path $env:RUNNER_TEMP 'oracle-official-sdk/platform'
$compiler=Join-Path $install 'metaeditor64.exe'
$terminal=Join-Path $install 'terminal64.exe'
$work=Join-Path $env:RUNNER_TEMP 'oracle-official-sdk'
$common=Join-Path $env:APPDATA 'MetaQuotes/Terminal/Common/Files'
$private=Join-Path $work 'private_parity'
python -m scripts.oracle_gold.mt5_signal_parity prepare --quotes $Quotes --common $common --private $private
if($LASTEXITCODE -ne 0){throw 'Private input preparation failed'}
$receipt=@{broker_connection=$false; source_modified=$false; order_path_invoked=$false; account_backtest=$false}
try {
    $sdk=Join-Path $install 'MQL5'
    $pin=Get-Content 'research/gold_oracle/phase04/mql_compile_pins.json' -Raw|ConvertFrom-Json|Where-Object {$_.ids -contains 'S040'}
    $original=Get-ChildItem $work -Filter GoldBreakoutEA.mq5 -Recurse|Select-Object -First 1
    if((Get-FileHash $original.FullName -Algorithm SHA256).Hash.ToLower() -ne $pin.sha256){throw 'Original EA bytes changed'}
    $srcDir=Join-Path $sdk 'Experts/OracleSignalParity'
    New-Item -ItemType Directory -Force $srcDir|Out-Null
    Copy-Item $original.FullName (Join-Path $srcDir 'GoldBreakoutEA.mq5')
    $ea=Join-Path $srcDir 'S040EntryOnly.mq5'
    @'
#define OnInit OriginalOnInit
#define OnDeinit OriginalOnDeinit
#define OnTick OriginalOnTick
#define OnTester OriginalOnTester
#include "GoldBreakoutEA.mq5"
#undef OnInit
#undef OnDeinit
#undef OnTick
#undef OnTester
int receipt=INVALID_HANDLE;
int OnInit() {
  if(!MQLInfoInteger(MQL_TESTER)) return(INIT_FAILED);
  int result=OriginalOnInit();
  if(result!=INIT_SUCCEEDED) return(result);
  receipt=FileOpen("oracle_s040_native_trace.csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',');
  if(receipt==INVALID_HANDLE) return(INIT_FAILED);
  FileWrite(receipt,"closed_epoch","open","high","low","close","ema","atr","direction");
  return(INIT_SUCCEEDED);
}
void OnTick() {
  if(!MQLInfoInteger(MQL_TESTER) || !IsNewBar()) return;
  if(Bars(_Symbol,_Period)<203) return;
  double av[1],em[1];
  if(CopyBuffer(g_atrHandle,0,1,1,av)!=1 || CopyBuffer(g_emaHandle,0,1,1,em)!=1) return;
  int signal=CheckBreakout();
  FileWrite(receipt,(long)iTime(_Symbol,_Period,1),DoubleToString(iOpen(_Symbol,_Period,1),10),DoubleToString(iHigh(_Symbol,_Period,1),10),DoubleToString(iLow(_Symbol,_Period,1),10),DoubleToString(iClose(_Symbol,_Period,1),10),DoubleToString(em[0],10),DoubleToString(av[0],10),signal);
}
void OnDeinit(const int reason) {if(receipt!=INVALID_HANDLE)FileClose(receipt);OriginalOnDeinit(reason);}
double OnTester() {FileFlush(receipt);Print("ORACLE_S040_UNCHANGED_ENTRY_ONLY_TEST_COMPLETE; orders=0");return(1.0);}
'@|Set-Content $ea -Encoding ascii
    $script=Join-Path $sdk 'Scripts/OracleImportRates.mq5'
    @'
#property strict
void OnStart() {
  if(TerminalInfoInteger(TERMINAL_CONNECTED)) return;
  string symbol="AIDY_GOLD_RESEARCH";
  if(!CustomSymbolCreate(symbol,"AIDY_RESEARCH")) {Print("IMPORT_CREATE_ERROR ",GetLastError());return;}
  // Precision is an import container only; no contract or broker terms invented.
  CustomSymbolSetInteger(symbol,SYMBOL_DIGITS,8);
  CustomSymbolSetDouble(symbol,SYMBOL_POINT,0.00000001);
  CustomSymbolSetString(symbol,SYMBOL_CURRENCY_BASE,"XAU");
  CustomSymbolSetString(symbol,SYMBOL_CURRENCY_PROFIT,"USD");
  CustomSymbolSetString(symbol,SYMBOL_CURRENCY_MARGIN,"USD");
  SymbolSelect(symbol,true);
  int f=FileOpen("oracle_rates.csv",FILE_READ|FILE_CSV|FILE_ANSI|FILE_COMMON,',');
  if(f==INVALID_HANDLE) {Print("IMPORT_FILE_ERROR ",GetLastError());return;}
  MqlRates rates[];ArrayResize(rates,10000);
  int used=0,total=0,stored=0;
  while(!FileIsEnding(f)) {
    string s=FileReadString(f);if(StringLen(s)==0)break;
    ZeroMemory(rates[used]);
    rates[used].time=(datetime)StringToInteger(s);
    rates[used].open=StringToDouble(FileReadString(f));rates[used].high=StringToDouble(FileReadString(f));
    rates[used].low=StringToDouble(FileReadString(f));rates[used].close=StringToDouble(FileReadString(f));
    rates[used].tick_volume=StringToInteger(FileReadString(f));
    used++;total++;
    if(used==10000){int n=CustomRatesUpdate(symbol,rates);if(n<0){Print("IMPORT_UPDATE_ERROR ",GetLastError());FileClose(f);return;}stored+=n;used=0;}
  }
  if(used>0){ArrayResize(rates,used);int n=CustomRatesUpdate(symbol,rates);if(n<0){Print("IMPORT_FINAL_ERROR ",GetLastError());FileClose(f);return;}stored+=n;}
  FileClose(f);
  PrintFormat("ORACLE_ACTUAL_BID_IMPORT source_rows=%d stored=%d connected=0",total,stored);
  int out=FileOpen("oracle_rates_import.txt",FILE_WRITE|FILE_TXT|FILE_COMMON);if(out!=INVALID_HANDLE){FileWrite(out,total,stored);FileClose(out);}
}
'@|Set-Content $script -Encoding ascii
    $indicator=Join-Path $sdk 'Scripts/OracleIndicatorRead.mq5'
    @'
#define OnInit OriginalOnInit
#define OnDeinit OriginalOnDeinit
#define OnTick OriginalOnTick
#define OnTester OriginalOnTester
#include "..\Experts\OracleSignalParity\GoldBreakoutEA.mq5"
#undef OnInit
#undef OnDeinit
#undef OnTick
#undef OnTester
void OnStart() {
  if(TerminalInfoInteger(TERMINAL_CONNECTED)) return;
  MqlRates rates[];double em[],av[];
  int count=0;
  for(int i=0;i<200;i++){count=CopyRates(_Symbol,PERIOD_H4,0,100000,rates);if(count>500)break;Sleep(50);}
  if(count<500){Print("ORACLE_INDICATOR_RATES_BLOCKED ",GetLastError());return;}
  if(OriginalOnInit()!=INIT_SUCCEEDED){Print("ORACLE_INDICATOR_INIT_FAILED ",GetLastError());return;}
  int ce=-1,ca=-1;
  for(int i=0;i<200;i++){ce=CopyBuffer(g_emaHandle,0,0,count,em);ca=CopyBuffer(g_atrHandle,0,0,count,av);if(ce==count&&ca==count)break;Sleep(50);}
  if(ce!=count||ca!=count){PrintFormat("ORACLE_INDICATOR_BUFFER_BLOCKED rates=%d ema=%d atr=%d error=%d",count,ce,ca,GetLastError());OriginalOnDeinit(0);return;}
  int lastSignal=CheckBreakout();
  int f=FileOpen("oracle_s040_native_trace.csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',');
  if(f==INVALID_HANDLE){OriginalOnDeinit(0);return;}
  FileWrite(f,"closed_epoch","open","high","low","close","ema","atr","direction","function_tested");
  for(int i=202;i<count-1;i++){
    bool tested=(i==count-2);
    FileWrite(f,(long)rates[i].time,DoubleToString(rates[i].open,10),DoubleToString(rates[i].high,10),DoubleToString(rates[i].low,10),DoubleToString(rates[i].close,10),DoubleToString(em[i],10),DoubleToString(av[i],10),tested?lastSignal:999,tested?1:0);
  }
  FileClose(f);OriginalOnDeinit(0);
  PrintFormat("ORACLE_NATIVE_READONLY_INDICATORS_COMPLETE bars=%d original_entry_calls=1 connected=0 orders=0",count);
}
'@|Set-Content $indicator -Encoding ascii
    foreach($file in @($ea,$script,$indicator)){
        $p=Start-Process $compiler -ArgumentList @('/portable',"/compile:`"$file`"","/include:`"$sdk`"",'/log') -PassThru
        if(-not $p.WaitForExit(60000)){$p.Kill();throw 'Native adapter compile timeout'}
        Copy-Item ([IO.Path]::ChangeExtension($file,'.log')) (Join-Path $OutDir ([IO.Path]::GetFileName($file)+'.log'))
        if(-not(Test-Path ([IO.Path]::ChangeExtension($file,'.ex5')))){throw 'Native adapter compile failed'}
    }
    $base=@('[Common]','Login=0','Server=','Password=','NewsEnable=0','CertInstall=0','MQL5Login=','MQL5Password=','[Experts]','Enabled=0','AllowLiveTrading=0','AllowDllImport=0')
    $configs=@(
      @{name='import_actual_bid'; wait=180000; lines=@('[StartUp]','Script=OracleImportRates','Symbol=EURUSD','Period=M1','ShutdownTerminal=1')},
      @{name='s040_entry_only'; wait=720000; lines=@('[StartUp]','Script=','Expert=','[Tester]','Expert=OracleSignalParity\S040EntryOnly','Symbol=AIDY_GOLD_RESEARCH','Period=H4','Model=1','Optimization=0','FromDate=2023.01.01','ToDate=2026.01.01','Deposit=10000','Currency=USD','Leverage=1:1','UseLocal=1','UseRemote=0','UseCloud=0','Visual=0','Report=oracle_s040_signal_only.htm','ReplaceReport=0','ShutdownTerminal=1')}
    )
    if($IndicatorsOnly){
        $configs=@($configs[0],@{name='readonly_native_indicators';wait=180000;lines=@('[StartUp]','Script=OracleIndicatorRead','Symbol=AIDY_GOLD_RESEARCH','Period=H4','ShutdownTerminal=1')})
        $receipt.price_strategy_tester_blocker_preserved='Previous native run refused price testing: account is not specified. Read-only script fallback uses no account or order path.'
    }
    $receipt.attempts=@()
    foreach($config in $configs){
        $ini=Join-Path $work ($config.name+'.ini');($base+$config.lines)|Set-Content $ini -Encoding ascii
        foreach($name in @('terminal64.exe','metatester.exe','metatester64.exe')){
            Remove-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\$name" -Name Debugger -ErrorAction SilentlyContinue
        }
        try{
            if((Get-Service MpsSvc).Status -ne 'Running'){throw 'Firewall stopped'}
            $p=Start-Process $terminal -ArgumentList @('/portable',"/config:`"$ini`"") -PassThru
            $ended=$p.WaitForExit($config.wait)
            if(-not $ended){$p.Kill();$p.WaitForExit()}
            $receipt.attempts+=@{name=$config.name; exited=$ended; config_sha256=(Get-FileHash $ini -Algorithm SHA256).Hash.ToLower()}
        }finally{
            Get-Process terminal64,metatester,metatester64 -ErrorAction SilentlyContinue|Stop-Process -Force
            foreach($name in @('terminal64.exe','metatester.exe','metatester64.exe')){
                New-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\$name" -Name Debugger -Value 'C:\Windows\System32\cmd.exe /c exit 0' -PropertyType String -Force|Out-Null
            }
        }
    }
    $receipt.original_source_sha256=(Get-FileHash (Join-Path $srcDir 'GoldBreakoutEA.mq5') -Algorithm SHA256).Hash.ToLower()
    if($receipt.original_source_sha256 -ne $pin.sha256){throw 'Source integrity changed after native execution'}
    python -m scripts.oracle_gold.mt5_signal_parity compare --private $private --common $common --out $OutDir
    if($LASTEXITCODE -ne 0){throw 'Native parity comparison failed'}
    # Confidential trace contains an entire H4 quote view; never public plaintext.
    $sealed=Join-Path $work 'private_trace';New-Item -ItemType Directory -Force $sealed|Out-Null
    foreach($file in @('oracle_s040_native_trace.csv','oracle_rates_import.txt')){
        $p=Join-Path $common $file;if(Test-Path $p){Copy-Item $p (Join-Path $sealed $file)}
    }
}catch{$receipt.blocker=$_.Exception.Message}
$i=0
foreach($log in @(Get-ChildItem $install -Filter '*.log' -Recurse)){$i++;Copy-Item $log.FullName (Join-Path $OutDir ("native-runtime-$i-"+$log.Name))}
$receipt.remaining_terminal_processes=@(Get-Process terminal64,metatester,metatester64 -ErrorAction SilentlyContinue).Count
$receipt|ConvertTo-Json -Depth 12|Set-Content (Join-Path $OutDir 'native_entry_probe_receipt.json') -Encoding utf8
