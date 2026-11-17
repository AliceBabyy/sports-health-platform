# 注册「体序」AI 运动报告自动生成任务（Windows 任务计划程序）
#
# 作用：每 30 分钟调用 scripts/generate_reports.py --scan。
#   周一凌晨会命中「上周周报」，每月 1 日会命中「上月月报」；
#   同一周期已 ready 或已软删除时脚本自动跳过，不会重复生成。
#
# 用法（在项目根目录、PowerShell 管理员窗口执行）：
#   powershell -ExecutionPolicy Bypass -File scripts\register_report_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\register_report_task.ps1 -IntervalMinutes 60
#   powershell -ExecutionPolicy Bypass -File scripts\register_report_task.ps1 -Uninstall
#
# 说明：本脚本不由开发流程自动执行，需要时手动运行。

param(
    [int]$IntervalMinutes = 30,
    [string]$TaskName = "SH-Report-Auto",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Script = Join-Path $Root "scripts\generate_reports.py"
$LogDir = Join-Path $Root "logs"

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "已卸载任务 $TaskName"
    } else {
        Write-Output "任务 $TaskName 不存在"
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $Python)) { throw "未找到虚拟环境 Python：$Python" }
if (-not (Test-Path -LiteralPath $Script)) { throw "未找到报告脚本：$Script" }
if (-not (Test-Path -LiteralPath $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

# 每 N 分钟触发一次；任务名固定，重复注册前先移除旧定义
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Script`" --scan" -WorkingDirectory $Root
# 以「每日触发 + 日内重复」表达每 N 分钟，兼容各版本任务计划程序（单次触发 + 超长重复时长易被拒）
$trigger = New-ScheduledTaskTrigger -Daily -At (Get-Date "00:02")
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date "00:02") `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -Hidden `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "体序 AI 运动报告自动生成：每 $IntervalMinutes 分钟扫描上周周报与上月月报" | Out-Null

Write-Output "已注册任务 $TaskName：每 $IntervalMinutes 分钟执行一次 --scan"
Write-Output "日志：$LogDir\report_task.log"
Write-Output "手动验证：& `"$Python`" `"$Script`" --scan --dry-run"
Write-Output "卸载：powershell -ExecutionPolicy Bypass -File scripts\register_report_task.ps1 -Uninstall"
