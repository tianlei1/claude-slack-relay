@echo off
echo Starting ClaudeBot...
powershell -Command "$p = Start-Process -FilePath 'python' -ArgumentList @('-u', 'C:\work\ClaudeBot\scripts\slack_claude_bot.py') -WindowStyle Hidden -PassThru; $p.Id | Out-File -FilePath 'C:\work\ClaudeBot\claudeBot.pid' -Encoding ascii -NoNewline"
echo ClaudeBot started.
