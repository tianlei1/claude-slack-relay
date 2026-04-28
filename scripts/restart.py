"""
Restart the bot by launching it as a fully detached process.
The bot will start the watchdog if needed.
Safe to call from within the watchdog or any process.
"""
import os
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT_SCRIPT = os.path.join(BASE_DIR, "scripts", "slack_claude_bot.py")

subprocess.Popen(
    [sys.executable, "-u", BOT_SCRIPT],
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
    close_fds=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    stdin=subprocess.DEVNULL,
)
print("Restart initiated")
