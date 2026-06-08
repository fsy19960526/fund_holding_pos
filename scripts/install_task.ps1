# input: capture_position_snapshot.ps1 的绝对路径与 Windows 任务计划程序。
# output: 名为 FreqtradePositionAudit 的每日计划任务。
# pos: 仓位审计计划任务安装入口；一旦我被更新，务必更新开头注释以及 scripts\FOLDER_README.md。

param(
    [string]$TaskName = 'FreqtradePositionAudit',
    [string]$StartTime = '18:30',
    [string]$ScriptPath = 'D:\freqtrade_position_audit\scripts\capture_position_snapshot.ps1'
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "capture script not found: $ScriptPath"
}

$action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
schtasks /Create /TN $TaskName /SC DAILY /ST $StartTime /TR $action /F | Out-Host
schtasks /Query /TN $TaskName /FO LIST | Out-Host
