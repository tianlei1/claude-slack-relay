import os
import sys
import psutil
import pidfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOP_FLAG = os.path.join(BASE_DIR, "claudeBot.stop")

# Signal watchdog not to restart
with open(STOP_FLAG, "w") as f:
    f.write("stop")

self_pid = os.getpid()
to_kill = set()

# Collect PIDs from unified PID file
for pid in pidfile.read_all().values():
    if isinstance(pid, int) and pid != self_pid:
        to_kill.add(pid)

# Fallback: scan for bot/watchdog processes that may not have written a PID
BOT_KEYWORDS = ["slack_claude_bot", "watchdog"]

for proc in psutil.process_iter(["pid", "name", "cmdline"]):
    try:
        if proc.pid == self_pid:
            continue
        name = (proc.info["name"] or "").lower()
        cmdline = proc.info["cmdline"] or []
        if "python" in name and any(kw in arg for arg in cmdline for kw in BOT_KEYWORDS):
            to_kill.add(proc.pid)
            for child in proc.children(recursive=True):
                to_kill.add(child.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

if not to_kill:
    print("ClaudeBot is not running")
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

pidfile.clear()
print(f"ClaudeBot stopped ({len(to_kill)} process(es) killed)")
