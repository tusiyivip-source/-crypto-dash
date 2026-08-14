# 创建 Windows 计划任务：每30分钟运行一次 1小时涨幅推送
# 以管理员身份运行此脚本
# 用法: .\schedule_task.ps1 [-Webhook "https://oapi.dingtalk.com/robot/send?access_token=..." -Secret "SEC..."]
# 不传参数时从用户环境变量 DINGTALK_WEBHOOK / DINGTALK_SECRET 读取，仍未设置则交互式输入。

param(
    [string]$Webhook = "",
    [string]$Secret = ""
)

# 从环境变量读取钉钉配置（不在脚本中硬编码，避免 token 泄漏）
if (-not $Webhook) { $Webhook = [Environment]::GetEnvironmentVariable("DINGTALK_WEBHOOK", "User") }
if (-not $Secret)  { $Secret  = [Environment]::GetEnvironmentVariable("DINGTALK_SECRET", "User") }
if (-not $Webhook) {
    $Webhook = Read-Host "请输入钉钉 Webhook 地址 (https://oapi.dingtalk.com/robot/send?access_token=...)"
}
if (-not $Secret) {
    $Secret = Read-Host "请输入钉钉加签 Secret (SEC...)"
}
if (-not $Webhook -or -not $Secret) {
    Write-Host "错误: 未提供钉钉 Webhook / Secret，任务创建中止。" -ForegroundColor Red
    exit 1
}
# 持久化到用户环境变量（python 脚本会读取）
[Environment]::SetEnvironmentVariable("DINGTALK_WEBHOOK", $Webhook, "User")
[Environment]::SetEnvironmentVariable("DINGTALK_SECRET", $Secret, "User")
Write-Host "钉钉配置已从环境变量读取并写入用户环境变量。" -ForegroundColor Green

$taskName = "CryptoDashboard-1hGainers-DingTalk"
$scriptPath = "C:\Users\65762\crypto-dashboard\dingtalk_1h_gainers.py"
$pythonPath = (Get-Command python3).Source
$workingDir = "C:\Users\65762\crypto-dashboard"

# 删除旧任务（如果存在）
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop 2>$null
    Write-Host "已删除旧任务: $taskName"
} catch {
    Write-Host "无旧任务需要删除"
}

# 创建新任务
$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument "`"$scriptPath`"" `
    -WorkingDirectory $workingDir

# 每30分钟触发一次
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration ([TimeSpan]::MaxValue)

# 任务配置：后台运行，不依赖用户登录
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "每30分钟获取Binance 1小时涨幅TOP20并推送到钉钉"

Write-Host "============================================"
Write-Host "任务已创建: $taskName"
Write-Host "脚本路径: $scriptPath"
Write-Host "执行频率: 每30分钟"
Write-Host ""
Write-Host "管理命令:"
Write-Host "  查看任务: Get-ScheduledTask -TaskName '$taskName'"
Write-Host "  手动运行: Start-ScheduledTask -TaskName '$taskName'"
Write-Host "  删除任务: Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
Write-Host "  查看日志: Get-WinEvent -LogName 'Microsoft-Windows-TaskScheduler/Operational' | Where-Object {`$_.Message -like '*$taskName*'} | Select-Object -First 5"
Write-Host "============================================"

# 立即运行一次
Start-ScheduledTask -TaskName $taskName
Write-Host ""
Write-Host "已触发首次运行，请检查钉钉消息"
