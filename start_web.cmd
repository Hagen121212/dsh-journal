@echo off
rem 确保本地 Web 服务在跑，然后打开浏览器。
setlocal
cd /d "%~dp0"
if "%JOURNAL_HOME%"=="" set "JOURNAL_HOME=%USERPROFILE%\DeepSeekJournal"
netstat -ano | findstr ":8765" | findstr "LISTENING" >nul
if errorlevel 1 (
  call "%~dp0serve_web.cmd"
  timeout /t 2 /nobreak >nul
)
start "" "http://127.0.0.1:8765/"
