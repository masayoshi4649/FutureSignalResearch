# 92接続派生元SHA256: 0d4e06aedc8a21eac817c119d7574c9bf81e840d155c057514925ad87de8854e
<#
機能: 固定92のオフライン全66場を別プロセスで実行し、ネイティブ終了コードと指紋を保存する。
引数: OutputRoot (string) はwork配下の新規実行領域、ExecutablePath (string) は任意の固定SHA一致exe、ValidateOnly (switch) は読取確認だけにする指定。
返り値: 実行時は終了コード0/1。ValidateOnly時は検査済みパス情報を標準出力へ返す。実発注は行わない。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$ExecutablePath = '',
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'

function Write-TaskReceipt {
    <#
    機能: 既存記録へ上書きせずUTF-8の実行証拠を保存する。
    引数: Path (string) は新規先、Value (hashtable) は証拠。
    返り値: なし。既存先又は書込失敗は例外。
    #>
    param([string]$Path, [hashtable]$Value)
    $taskStream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew)
    $taskWriter = [IO.StreamWriter]::new($taskStream, [Text.UTF8Encoding]::new($false))
    try { $taskWriter.WriteLine(($Value | ConvertTo-Json -Depth 10)) } finally { $taskWriter.Dispose() }
}

# ----------------------------------------
$taskRepo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$taskConditionPath = Join-Path $taskRepo 'study/00092_価格帯奪還と保持後の独立再開/条件.json'
$taskCondition = Get-Content -LiteralPath $taskConditionPath -Raw -Encoding utf8 | ConvertFrom-Json
$taskManifest = Join-Path $taskRepo 'study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json'
$taskArea = if ([IO.Path]::IsPathRooted($OutputRoot)) { [IO.Path]::GetFullPath($OutputRoot) } else { [IO.Path]::GetFullPath((Join-Path $taskRepo $OutputRoot)) }
$taskWorkPrefix = [IO.Path]::GetFullPath((Join-Path $taskRepo 'work')) + [IO.Path]::DirectorySeparatorChar
if (-not $taskArea.StartsWith($taskWorkPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'OutputRootは本repoのwork配下の子領域へ指定してください' }
$taskExe = if ($ExecutablePath) { if ([IO.Path]::IsPathRooted($ExecutablePath)) { [IO.Path]::GetFullPath($ExecutablePath) } else { [IO.Path]::GetFullPath((Join-Path $taskRepo $ExecutablePath)) } } else { [IO.Path]::GetFullPath((Join-Path $taskRepo $taskCondition.実行ファイル)) }
$taskExeHash = (Get-FileHash -LiteralPath $taskExe -Algorithm SHA256).Hash.ToLowerInvariant()
$taskManifestHash = (Get-FileHash -LiteralPath $taskManifest -Algorithm SHA256).Hash.ToLowerInvariant()
$taskConditionHash = (Get-FileHash -LiteralPath $taskConditionPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($taskExeHash -ne $taskCondition.実行ファイルSHA256 -or $taskManifestHash -ne $taskCondition.入力台帳SHA256) { throw '固定exe又は入力台帳のSHAが一致しません' }
$taskDependencyCount = 0
foreach ($taskGroup in $taskCondition.PSObject.Properties) {
    if ($taskGroup.Name -eq 'コードと依存SHA256' -or $taskGroup.Name -match '^固定.+依存$') {
        foreach ($taskProperty in $taskGroup.Value.PSObject.Properties) {
            if ((Get-FileHash -LiteralPath (Join-Path $taskRepo $taskProperty.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskProperty.Value) { throw "固定依存が変化しています: $($taskProperty.Name)" }
            $taskDependencyCount++
        }
    }
}
$taskOutput = Join-Path $taskArea '全66場'
$taskStart = Join-Path $taskArea '全66場_起動.json'
$taskFinish = Join-Path $taskArea '全66場_完了.json'
$taskStdout = Join-Path $taskArea '全66場_標準出力.log'
$taskStderr = Join-Path $taskArea '全66場_標準エラー.log'
foreach ($taskPath in @($taskOutput, $taskStart, $taskFinish, $taskStdout, $taskStderr)) {
    if (Test-Path -LiteralPath $taskPath) { throw "新規出力領域が必要です: $taskPath" }
}
if ($ValidateOnly) {
    @{ '試行' = 92; '検査成功' = $true; '実行' = $false; '実行ファイル' = $taskExe; '出力' = $taskOutput; '条件SHA256' = $taskConditionHash; 'exeSHA256' = $taskExeHash; '固定依存照合数' = $taskDependencyCount; 'PowerShell' = $PSVersionTable.PSVersion.ToString() } | ConvertTo-Json
    return
}
New-Item -ItemType Directory -Path $taskArea -Force | Out-Null
$taskProcess = $null
$taskOutStream = $null
$taskErrStream = $null
try {
    $taskInfo = [Diagnostics.ProcessStartInfo]::new()
    $taskInfo.FileName = $taskExe
    $taskInfo.WorkingDirectory = $taskRepo
    $taskInfo.UseShellExecute = $false
    $taskInfo.CreateNoWindow = $true
    $taskInfo.RedirectStandardOutput = $true
    $taskInfo.RedirectStandardError = $true
    foreach ($taskArgument in @('-manifest', $taskManifest, '-out', $taskOutput, '-workers', '16')) { $taskInfo.ArgumentList.Add($taskArgument) }
    $taskOutStream = [IO.File]::Open($taskStdout, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    $taskErrStream = [IO.File]::Open($taskStderr, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    $taskProcess = [Diagnostics.Process]::new()
    $taskProcess.StartInfo = $taskInfo
    if (-not $taskProcess.Start()) { throw 'ネイティブプロセスを開始できませんでした' }
    $taskOutCopy = $taskProcess.StandardOutput.BaseStream.CopyToAsync($taskOutStream)
    $taskErrCopy = $taskProcess.StandardError.BaseStream.CopyToAsync($taskErrStream)
    Write-TaskReceipt -Path $taskStart -Value @{ '試行' = 92; '補助PID' = $PID; '計算PID' = $taskProcess.Id; '開始' = $taskProcess.StartTime.ToString('o'); '実行ファイルSHA256' = $taskExeHash; '条件SHA256' = $taskConditionHash; '入力台帳SHA256' = $taskManifestHash; '出力' = $taskOutput; 'worker' = 16 }
    # ----------------------------------------
    # 両出力を非同期に流し、会話handleとは別の実プロセスから終了コードを取得します。
    $taskProcess.WaitForExit()
    $taskOutCopy.GetAwaiter().GetResult()
    $taskErrCopy.GetAwaiter().GetResult()
    $taskOutStream.Dispose(); $taskOutStream = $null
    $taskErrStream.Dispose(); $taskErrStream = $null
    $taskExit = $taskProcess.ExitCode
    $taskAfterHash = (Get-FileHash -LiteralPath $taskExe -Algorithm SHA256).Hash.ToLowerInvariant()
    $taskAfterCondition = (Get-FileHash -LiteralPath $taskConditionPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $taskAfterManifest = (Get-FileHash -LiteralPath $taskManifest -Algorithm SHA256).Hash.ToLowerInvariant()
    $taskCount = @(Get-ChildItem -LiteralPath $taskOutput -File -Filter '*.json').Count
    $taskSuccess = ($taskExit -eq 0) -and ($taskCount -eq 66) -and ($taskExeHash -eq $taskAfterHash) -and ($taskConditionHash -eq $taskAfterCondition) -and ($taskManifestHash -eq $taskAfterManifest)
    Write-TaskReceipt -Path $taskFinish -Value @{ '試行' = 92; '終了コード' = [int]$taskExit; '処理完了' = $true; '成功' = $taskSuccess; '計算PID' = $taskProcess.Id; '終了' = (Get-Date).ToString('o'); '実行ファイルSHA256前' = $taskExeHash; '実行ファイルSHA256後' = $taskAfterHash; '条件SHA256前' = $taskConditionHash; '条件SHA256後' = $taskAfterCondition; '入力台帳SHA256前' = $taskManifestHash; '入力台帳SHA256後' = $taskAfterManifest; '保存場数' = $taskCount }
    if (-not $taskSuccess) { exit 1 }
} catch {
    if (-not (Test-Path -LiteralPath $taskFinish)) {
        Write-TaskReceipt -Path $taskFinish -Value @{ '試行' = 92; '処理完了' = $false; '成功' = $false; '例外' = $_.Exception.Message; '補助PID' = $PID; '計算PID' = $(if ($null -ne $taskProcess) { $taskProcess.Id } else { $null }); '終了' = (Get-Date).ToString('o') }
    }
    throw
} finally {
    if ($null -ne $taskOutStream) { $taskOutStream.Dispose() }
    if ($null -ne $taskErrStream) { $taskErrStream.Dispose() }
    if ($null -ne $taskProcess) { $taskProcess.Dispose() }
}
