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
python -m pip install -r requirements.txt -f ./libs --index-url https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com >nul 2>&1
if !errorlevel! neq 0 (python -m pip install -r requirements.txt -f ./libs --index-url https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn)
if !errorlevel! neq 0 (echo ❌ 安装依赖失败，请检查网络或 requirements.txt 是否存在 & pause & exit /b 1)
echo ✅ 所有依赖安装成功！
cls

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
