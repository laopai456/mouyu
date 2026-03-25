@echo off
chcp 65001 >nul
title 木偶鱼自动上传工具
cd /d "%~dp0"
python uploader.py
pause
