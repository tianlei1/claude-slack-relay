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

if in_progress:
    print(f"        Active Tasks: {len(in_progress)}")
    for entry in in_progress.values():
        pid = entry.get("pid")
        channel = entry["channel"]
        if pid:
            try:
                cp = psutil.Process(pid)
                mem = round(cp.memory_info().rss / 1024 / 1024, 1)
                status = cp.status()
                print(f"          claude PID {pid}  channel={channel}  mem={mem}MB  status={status}")
            except psutil.NoSuchProcess:
                print(f"          claude PID {pid}  channel={channel}  (already exited)")
        else:
            print(f"          channel={channel}  (starting...)")
else:
    print(f"        Active Tasks: 0")
