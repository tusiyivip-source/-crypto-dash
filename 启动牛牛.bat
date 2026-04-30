@echo off
chcp 65001 >nul
title 牛牛盯盘系统
cd /d C:\Users\65762\crypto-dashboard
echo 正在启动牛牛盯盘系统...
start http://localhost:8080
python server.py
pause
