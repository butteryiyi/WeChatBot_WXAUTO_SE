@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

:: --- [保留] 原有的微信版本和 Python 环境检查部分 ---
:: (此部分无需改动，保持原样即可)
set "wxversion="
for %%K in ("HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Weixin", "HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\WeChat") do (for /f "tokens=2,*" %%i in ('reg query %%K /v DisplayVersion 2^>nul ^| find "DisplayVersion"') do (set "wxversion=%%j" & set "RegPath=%%K" & goto :found_wxversion))
if not defined wxversion (echo ⚠️ 警告：未检测到微信安装或无法读取注册表！ & goto :check_python)
:found_wxversion
if not defined wxversion (echo ⚠️ 警告：无法获取微信版本号！ & goto :check_python)
for /f "tokens=1 delims=." %%a in ("!wxversion!") do (set "major=%%a")
if !major! lss 3 (echo ❌ 当前微信版本 !wxversion!，版本过低！ & pause)
if !major! geq 4 (echo ❌ 当前微信版本 !wxversion!，版本过高！ & pause)
echo ✅ 微信版本检查通过：!wxversion!

:check_python
echo 🔍 检查Python环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (echo ❌ Python 未安装或未添加到系统PATH！ & pause & exit /b 1)
for /f "tokens=2,*" %%i in ('python --version 2^>^&1') do set "pyversion=%%i"
echo 检测到Python版本：%pyversion%
for /f "tokens=1,2,3 delims=." %%a in ("%pyversion%") do (set "py_major=%%a" & set "py_minor=%%b")
if "%py_major%" neq "3" ( echo ❌ 不支持的Python主版本 & pause & exit /b 1 )
if %py_minor% lss 9 ( echo ❌ Python版本过低 & pause & exit /b 1 )
if %py_minor% gtr 12 ( echo ❌ Python版本过高 & pause & exit /b 1 )
echo ✅ Python版本检查通过：%pyversion%

:: --- [保留] 依赖安装部分 ---
echo 🔄 正在安装依赖...

:: ---------------------------
:: 选择最快的 pip 源
:: ---------------------------
echo 🚀 正在检测可用镜像源...

:: 阿里源
python -m pip install --upgrade pip --index-url https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com >nul 2>&1
if !errorlevel! equ 0 (
    set "SOURCE_URL=https://mirrors.aliyun.com/pypi/simple/"
    set "TRUSTED_HOST=mirrors.aliyun.com"
    echo ✅ 使用阿里源
    goto :INSTALL_DEPS
)

:: 清华源
python -m pip install --upgrade pip --index-url https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn >nul 2>&1
if !errorlevel! equ 0 (
    set "SOURCE_URL=https://pypi.tuna.tsinghua.edu.cn/simple"
    set "TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn"
    echo ✅ 使用清华源
    goto :INSTALL_DEPS
)

:: 官方源
python -m pip install --upgrade pip --index-url https://pypi.org/simple >nul 2>&1
if !errorlevel! equ 0 (
    set "SOURCE_URL=https://pypi.org/simple"
    set "TRUSTED_HOST="
    echo ✅ 使用官方源
    goto :INSTALL_DEPS
)

echo ❌ 无可用镜像源，请检查网络
pause
exit /b 1

:INSTALL_DEPS
if "!TRUSTED_HOST!"=="" (
    python -m pip install -r requirements.txt -f ./libs --index-url !SOURCE_URL! >nul 2>&1
) else (
    python -m pip install -r requirements.txt -f ./libs --index-url !SOURCE_URL! --trusted-host !TRUSTED_HOST! >nul 2>&1
)

if !errorlevel! neq 0 (
    echo ❌ 安装依赖失败，请检查网络或 requirements.txt 是否存在
    pause
    exit /b 1
)

echo ✅ 所有依赖安装成功！
cls

:: =================================================================
:: 【 新增 】GitHub Release 自动更新检查（可选，本地无 Git 时会跳过）
:: - 优先从 git remote 获取仓库地址；否则尝试读取 REPO.txt（内容形如 owner/repo）
:: - 本地当前版本从 version.txt 读取（不存在则跳过对比）
:: - 若检测到有新版本，提示是否打开最新 Release 页面
:: =================================================================
set "LATEST_VERSION="
set "REPO_SLUG="
set "CURRENT_VERSION="

for /f "tokens=1,2 delims==" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='SilentlyContinue'; ^
    $origin=(git config --get remote.origin.url) 2>$null; ^
    if(-not $origin -and (Test-Path 'REPO.txt')){ $origin=(Get-Content 'REPO.txt' -Raw).Trim() } ^
    $repo=$null; ^
    if($origin -match 'github\.com[:/](.+?)/(.*?)(\.git)?$'){ $repo=$Matches[1] + '/' + $Matches[2].TrimEnd('.git') } ^
    elseif($origin -match '^(?<o>[^/]+/[^/]+)$'){ $repo=$Matches['o'] } ^
    $current=(Test-Path 'version.txt') ? ((Get-Content 'version.txt' -Raw).Trim()) : ''; ^
    if($repo){ ^
        $api='https://api.github.com/repos/'+$repo+'/releases/latest'; ^
        try{ $resp=Invoke-RestMethod -UseBasicParsing -Headers @{ 'User-Agent'='curl'; 'X-GitHub-Api-Version'='2022-11-28'} -Uri $api } catch {} ^
        $latest = $null; if($resp){ $latest = if($resp.tag_name){$resp.tag_name}else{$resp.name} } ^
        if($latest){ Write-Output ('LATEST=' + $latest) } ^
        Write-Output ('REPO=' + $repo) ^
        Write-Output ('CURRENT=' + $current) ^
    } else { Write-Output 'REPO=' } ^
"') do (
    if "%%A"=="LATEST" set "LATEST_VERSION=%%B"
    if "%%A"=="REPO" set "REPO_SLUG=%%B"
    if "%%A"=="CURRENT" set "CURRENT_VERSION=%%B"
)

if not defined REPO_SLUG (
    echo ⚠️ 未能识别 GitHub 仓库（缺少 git 或 REPO.txt）。跳过更新检查。
) else (
    if defined LATEST_VERSION (
        if defined CURRENT_VERSION (
            for /f %%V in ('powershell -NoProfile -Command "try{ if([version]'%CURRENT_VERSION%' -lt [version]'%LATEST_VERSION%'){ exit 1 } else { exit 0 } } catch { if('%CURRENT_VERSION%' -ne '%LATEST_VERSION%'){ exit 1 } else { exit 0 } }"') do set "CMP=%%V"
        ) else (
            set "CMP=1"
        )
        if not defined CMP set "CMP=1"
        if "%CMP%"=="1" (
            echo 🔔 检测到新版本：%LATEST_VERSION%（当前：%CURRENT_VERSION%）
            choice /m "是否打开最新 Release 页面以查看更新？" /c YN /n
            if errorlevel 2 (
                echo 已跳过打开浏览器。
            ) else (
                start "" https://github.com/%REPO_SLUG%/releases/latest
            )
        ) else (
            echo ✅ 已是最新版本（当前：%CURRENT_VERSION%，最新：%LATEST_VERSION%）。
        )
    ) else (
        echo ⚠️ 无法从 GitHub 获取最新版本信息。可能是网络或 API 受限。
    )
)

:: ---------------------------
:: 本地更新器回退机制
:: ---------------------------
echo 🔄 运行本地更新器...
if exist "updater.py" (
    python updater.py
    echo ✅ 本地更新器运行完成
) else (
    echo ℹ️ 未找到本地更新器 updater.py，跳过本地更新
)

:: =================================================================
::【【【【【【【【【【【【【 优化后的启动逻辑 】】】】】】】】】】】】】
:: =================================================================
echo.
echo =========================================================
echo =           正在启动所有服务并打开浏览器...             =
echo =========================================================
echo.

echo 🟢 [1/3] 正在新窗口中独立启动 AI 朋友圈服务 (端口 5002)...
:: 使用 START 在一个独立的、有标题的新窗口中运行朋友圈服务
START "AI Moments Service (Port 5002)" cmd /c "python moments_app.py"

echo.
echo    ⏳ 正在等待服务初始化，请稍候 5 秒钟...
timeout /t 5 /nobreak >nul

echo.
echo 🟢 [2/3] 正在默认浏览器中打开两个服务的网页...
:: 使用 start 命令打开URL，空引号""是防止URL被误认为窗口标题
start "" http://localhost:5002

echo.
echo =========================================================
echo.
echo 🟢 [3/3] 正在此窗口中运行主程序 (配置编辑器, 端口 5000)...
echo.
echo    ✨ 所有服务均已启动！
echo.
echo    - 配置编辑器运行于: http://localhost:5000
echo    - AI 朋友圈运行于: http://localhost:5002
echo.
echo    - 一个名为 "AI Moments Service" 的新窗口已经打开，这是朋友圈服务，可以最小化但不要关闭。
echo    - ⚠️ 请保持本窗口开启，关闭它将终止主程序服务！
echo.
echo =========================================================
echo.

:: 直接在此窗口运行主程序，此命令会一直执行，直到你手动关闭本窗口
python config_editor.py
