@echo off
rem 每周任务：同步 -> 会话卡 -> 周报 -> 按需成长报告。可挂到任务计划程序。
setlocal
cd /d "%~dp0"
if "%JOURNAL_HOME%"=="" set "JOURNAL_HOME=%USERPROFILE%\DeepSeekJournal"
set "PYTHONIOENCODING=utf-8"
if not exist "%JOURNAL_HOME%\logs" mkdir "%JOURNAL_HOME%\logs"
python -m journal.cli weekly %* >> "%JOURNAL_HOME%\logs\weekly.log" 2>&1
exit /b %ERRORLEVEL%
