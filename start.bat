@echo off
echo Starting ClaudeBot...
set BASE_DIR=%~dp0

:: 允许息屏但禁止锁屏
powercfg /change monitor-timeout-ac 10 >nul 2>&1
powercfg /change standby-timeout-ac 0 >nul 2>&1
reg add "HKCU\Control Panel\Desktop" /v ScreenSaveActive /t REG_SZ /d 0 /f >nul 2>&1
reg add "HKCU\Control Panel\Desktop" /v ScreenSaverIsSecure /t REG_SZ /d 0 /f >nul 2>&1
reg add "HKCU\Control Panel\Desktop" /v DelayLockInterval /t REG_DWORD /d 0xFFFFFFFF /f >nul 2>&1

powershell -Command "Start-Process -FilePath 'python' -ArgumentList @('-u', '%BASE_DIR%scripts\slack_claude_bot.py') -WindowStyle Hidden"
echo ClaudeBot started.
