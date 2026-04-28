@echo off
set TASK_NAME=ClaudeSlackRelay
schtasks /Delete /TN "%TASK_NAME%" /F
if %ERRORLEVEL% EQU 0 (
    echo ClaudeSlackRelay autostart removed.
) else (
    echo Task not found or could not be removed.
)
