@echo off
chcp 65001 >nul
title 木偶鱼定时任务调度器

echo ===============================================
echo          木偶鱼定时任务调度器
echo ===============================================
echo.

if not exist node_modules (
    echo 正在安装依赖...
    npm install
    if %errorlevel% neq 0 (
        echo 依赖安装失败，请检查 Node.js 是否安装
        pause
        exit /b 1
    )
    echo 依赖安装完成
    echo.
)

if not exist ..\logs (
    mkdir ..\logs
)

echo 正在读取配置...
echo.

node scheduler.js

pause