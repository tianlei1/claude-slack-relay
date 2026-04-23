import os
import sys
import psutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PID_FILE = os.path.join(BASE_DIR, "claudeBot.pid")

if not os.path.exists(PID_FILE):
    print("ClaudeBot is not running (no PID file)")
    sys.exit(1)

with open(PID_FILE) as f:
    bot_pid = int(f.read().strip())

try:
    p = psutil.Process(bot_pid)
    p.terminate()
    p.wait(timeout=5)
    print(f"ClaudeBot stopped (PID {bot_pid})")
except psutil.NoSuchProcess:
    print(f"Process {bot_pid} not found, already stopped")
except psutil.TimeoutExpired:
    p.kill()
    print(f"ClaudeBot force killed (PID {bot_pid})")
finally:
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
