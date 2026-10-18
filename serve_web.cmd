@echo off
rem 后台启动本地 Web 服务（已在运行则什么都不做）。
setlocal
cd /d "%~dp0"
if "%JOURNAL_HOME%"=="" set "JOURNAL_HOME=%USERPROFILE%\DeepSeekJournal"
netstat -ano | findstr ":8765" | findstr "LISTENING" >nul
if not errorlevel 1 exit /b 0
set "RUNNER=pythonw"
where pythonw >nul 2>nul || set "RUNNER=python"
start "" %RUNNER% -m journal.cli serve --port 8765
