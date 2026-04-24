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
    parent = psutil.Process(bot_pid)
    children = parent.children(recursive=True)
    for child in children:
        child.terminate()
    parent.terminate()
    gone, alive = psutil.wait_procs(children + [parent], timeout=5)
    for p in alive:
        p.kill()
    killed = len(children)
    print(f"ClaudeBot stopped (PID {bot_pid}" + (f", {killed} child process(es) also stopped" if killed else "") + ")")
except psutil.NoSuchProcess:
    print(f"Process {bot_pid} not found, already stopped")
finally:
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
