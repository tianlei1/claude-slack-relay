import os
import sys
import psutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PID_FILE = os.path.join(BASE_DIR, "claudeBot.pid")
STOP_FLAG = os.path.join(BASE_DIR, "claudeBot.stop")
BOT_SCRIPT = os.path.join(BASE_DIR, "scripts", "slack_claude_bot.py")

# Signal watchdog not to restart
with open(STOP_FLAG, "w") as f:
    f.write("stop")

self_pid = os.getpid()
to_kill = set()

# Find all python processes running slack_claude_bot.py
for proc in psutil.process_iter(["pid", "name", "cmdline"]):
    try:
        if proc.pid == self_pid:
            continue
        name = (proc.info["name"] or "").lower()
        cmdline = proc.info["cmdline"] or []
        if "python" in name and any("slack_claude_bot" in arg for arg in cmdline):
            to_kill.add(proc.pid)
            for child in proc.children(recursive=True):
                to_kill.add(child.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

# Also check PID file as fallback
if os.path.exists(PID_FILE):
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        if pid != self_pid:
            to_kill.add(pid)
            try:
                for child in psutil.Process(pid).children(recursive=True):
                    to_kill.add(child.pid)
            except psutil.NoSuchProcess:
                pass
    except Exception:
        pass

if not to_kill:
    print("ClaudeBot is not running")
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    sys.exit(0)

procs = []
for pid in to_kill:
    try:
        procs.append(psutil.Process(pid))
    except psutil.NoSuchProcess:
        pass

for p in procs:
    try:
        p.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

gone, alive = psutil.wait_procs(procs, timeout=5)
for p in alive:
    try:
        p.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

if os.path.exists(PID_FILE):
    os.remove(PID_FILE)

print(f"ClaudeBot stopped ({len(to_kill)} process(es) killed)")
