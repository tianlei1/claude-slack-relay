import os
import sys
import datetime
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
