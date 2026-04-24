@echo off
echo Starting ClaudeBot...
set BASE_DIR=%~dp0
powershell -Command "$p = Start-Process -FilePath 'python' -ArgumentList @('-u', '%BASE_DIR%scripts\slack_claude_bot.py') -WindowStyle Hidden -PassThru; $p.Id | Out-File -FilePath '%BASE_DIR%claudeBot.pid' -Encoding ascii -NoNewline"
echo ClaudeBot started.
