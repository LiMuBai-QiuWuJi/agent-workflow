@echo off
REM 从同目录下的 .env 读取 Git 用户信息和提交说明，仓库地址手动输入
chcp 65001 >nul

if not exist .env (
    echo 当前目录没有 .env 文件，请先创建，格式：
    echo GIT_NAME=你的名字
    echo GIT_EMAIL=你的邮箱
    echo COMMIT_MSG=first commit
    pause
    exit /b 1
)

for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    if /i "%%a"=="GIT_NAME" set "GIT_NAME=%%b"
    if /i "%%a"=="GIT_EMAIL" set "GIT_EMAIL=%%b"
    if /i "%%a"=="COMMIT_MSG" set "COMMIT_MSG=%%b"
)

if "%GIT_NAME%"=="" (
    echo .env 里缺少 GIT_NAME，请检查。
    pause
    exit /b 1
)
if "%GIT_EMAIL%"=="" (
    echo .env 里缺少 GIT_EMAIL，请检查。
    pause
    exit /b 1
)
if "%COMMIT_MSG%"=="" set "COMMIT_MSG=first commit"

set /p "HTTP_URL=HTTP 仓库地址: "
set /p "SSH_URL=SSH 仓库地址: "

git init
git remote add origin "%HTTP_URL%"
git add .
git config --global user.name "%GIT_NAME%"
git config --global user.email "%GIT_EMAIL%"
git commit -m "%COMMIT_MSG%"
git remote set-url origin "%SSH_URL%"
git branch -m main
git push -u origin main

pause