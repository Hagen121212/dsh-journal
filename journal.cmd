@echo off
rem 思维年轮 CLI 入口。用法：journal.cmd status / sync / weekly / serve ...
setlocal
cd /d "%~dp0"
if "%JOURNAL_HOME%"=="" set "JOURNAL_HOME=%USERPROFILE%\DeepSeekJournal"
set "PYTHONIOENCODING=utf-8"
python -m journal.cli %*
exit /b %ERRORLEVEL%
