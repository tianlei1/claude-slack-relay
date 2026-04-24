import os
import sys
import datetime
import json
import psutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PID_FILE = os.path.join(BASE_DIR, "claudeBot.pid")
LOG_FILE = os.path.join(BASE_DIR, "claudeBot.log")

if not os.path.exists(PID_FILE):
    print("[STATUS] ClaudeBot is NOT running (no PID file)")
    sys.exit(1)

with open(PID_FILE) as f:
    bot_pid = int(f.read().strip())

try:
    p = psutil.Process(bot_pid)
    mem = round(p.memory_info().rss / 1024 / 1024, 1)
    cpu = round(sum(p.cpu_times()[:2]), 1)
    uptime = round((datetime.datetime.now().timestamp() - p.create_time()) / 60, 1)
    print(f"[STATUS] ClaudeBot is RUNNING")
    print(f"        PID     : {bot_pid}")
    print(f"        Memory  : {mem} MB")
    print(f"        CPU     : {cpu} s")
    print(f"        Uptime  : {uptime} min")
    print(f"        Log     : {LOG_FILE}")
except psutil.NoSuchProcess:
    print(f"[STATUS] ClaudeBot is NOT running (process {bot_pid} not found)")
    os.remove(PID_FILE)
    sys.exit(1)

IN_PROGRESS_FILE = os.path.join(BASE_DIR, "in_progress.json")
try:
    with open(IN_PROGRESS_FILE, encoding="utf-8") as f:
        in_progress = json.load(f)
except Exception:
    in_progress = {}


def derive_process_name(cmdline):
    for part in cmdline:
        part_lower = part.lower()
        if "slack_claude_bot" in part_lower:
            return "ClaudeBot (bot)"
        if "status.py" in part_lower:
            return "status check"
        if "stop.py" in part_lower:
            return "stop script"
    if any("scons" in c.lower() for c in cmdline):
        return "SCons build worker"
    if any("sconstruct" in c.lower() for c in cmdline):
        return "SCons build"
    if any("msbuild" in c.lower() for c in cmdline):
        return "MSBuild"
    for part in reversed(cmdline):
        if part.endswith(".py"):
            return os.path.basename(part)
    return cmdline[1] if len(cmdline) > 1 else "python"


def get_python_children(pid):
    results = []
    try:
        for child in psutil.Process(pid).children(recursive=True):
            try:
                if child.name().lower() == "python.exe":
                    cmdline = child.cmdline()
                    mem = round(child.memory_info().rss / 1024 / 1024, 1)
                    results.append((child.pid, derive_process_name(cmdline), mem, child.status()))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return results


self_pid = os.getpid()

print(f"        Active Tasks: {len(in_progress)}")
for entry in in_progress.values():
    pid = entry.get("pid")
    channel = entry["channel"]
    label = entry.get("label", "")
    label_str = f'"{label}"' if label else "(no label)"
    print()
    print(f"          Task: {label_str}")
    if pid:
        try:
            cp = psutil.Process(pid)
            mem = round(cp.memory_info().rss / 1024 / 1024, 1)
            status = cp.status()
            print(f"            claude PID {pid}  mem={mem}MB  status={status}  channel={channel}")
            children = get_python_children(pid)
            if children:
                print(f"            {'PID':<8} {'Name':<28} {'Mem(MB)':>8}  Status")
                print(f"            {'-'*8} {'-'*28} {'-'*8}  {'-'*10}")
                for cpid, cname, cmem, cstatus in children:
                    print(f"            {cpid:<8} {cname:<28} {cmem:>8.1f}  {cstatus}")
            else:
                print(f"            (no child python processes)")
        except psutil.NoSuchProcess:
            print(f"            claude PID {pid}  (already exited)  channel={channel}")
    else:
        print(f"            channel={channel}  (starting...)")
