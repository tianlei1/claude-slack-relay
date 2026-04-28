@echo off
echo Starting ClaudeBot...
set BASE_DIR=%~dp0

:: 防止屏幕锁屏
powercfg /change monitor-timeout-ac 0 >nul 2>&1
powercfg /change standby-timeout-ac 0 >nul 2>&1
reg add "HKCU\Control Panel\Desktop" /v ScreenSaveActive /t REG_SZ /d 0 /f >nul 2>&1
reg add "HKCU\Control Panel\Desktop" /v ScreenSaverIsSecure /t REG_SZ /d 0 /f >nul 2>&1

powershell -Command "Start-Process -FilePath 'python' -ArgumentList @('-u', '%BASE_DIR%scripts\watchdog.py') -WindowStyle Hidden"
echo ClaudeBot started.
