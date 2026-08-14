# 钉钉推送配置

## ⚠️ 安全提醒（重要）
- 旧版本的 access_token / secret 曾硬编码在脚本中并提交到 git 历史。
- **如果你把这个仓库分享或公开过，请立即到钉钉机器人管理后台轮换 (重置) access_token 和 secret。**
- 现在所有脚本均从**环境变量**读取，不再包含任何硬编码凭据。

## 配置方式

### 1. 设置环境变量（推荐）
```powershell
[Environment]::SetEnvironmentVariable("DINGTALK_WEBHOOK", "https://oapi.dingtalk.com/robot/send?access_token=你的TOKEN", "User")
[Environment]::SetEnvironmentVariable("DINGTALK_SECRET", "SEC你的SECRET", "User")
```

### 2. 运行计划任务安装脚本
```powershell
# 以管理员身份运行 PowerShell
cd "C:\Users\65762\crypto-dashboard"
.\schedule_task.ps1
# 或直接传入凭据:
.\schedule_task.ps1 -Webhook "https://oapi.dingtalk.com/robot/send?access_token=..." -Secret "SEC..."
```
脚本会读取/写入用户环境变量，并创建每 30 分钟运行一次的 Windows 计划任务。

### 手动运行
```powershell
cd "C:\Users\65762\crypto-dashboard"
python3 dingtalk_1h_gainers.py
```

## 定时任务
- 方式1: Windows 计划任务 (schedule_task.ps1 创建, 永久)
- 方式2: Claude Code 内置调度 (`/cron`, 7天后过期需重新设置)

## 文件说明
- `dingtalk_1h_gainers.py` — 主脚本
- `output/1h_top20.png` — 生成的表格图片
- `schedule_task.ps1` — Windows 计划任务安装脚本
