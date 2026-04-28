@echo off
set TASK_NAME=ClaudeSlackRelay
set START_BAT=%~dp0start.bat
schtasks /Create /SC ONLOGON /TN "%TASK_NAME%" /TR "\"%START_BAT%\"" /RL HIGHEST /F
if %ERRORLEVEL% EQU 0 (
    echo ClaudeSlackRelay autostart installed. Bot will start automatically on login.
) else (
    echo Failed to install autostart. Try running as Administrator.
)
