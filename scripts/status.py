import os
import sys
import datetime
import json
import psutil
import pidfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEARTBEAT_FILE = os.path.join(BASE_DIR, "heartbeat.json")
RUNTIME_CONFIG = os.path.join(BASE_DIR, ".mcp.runtime.json")
MCP_CONFIG = os.path.join(BASE_DIR, ".mcp.json")
IN_PROGRESS_FILE = os.path.join(BASE_DIR, "in_progress.json")


def proc_info(pid):
    if pid is None:
        return None
    try:
        p = psutil.Process(pid)
        mem = round(p.memory_info().rss / 1024 / 1024, 1)
        uptime = round((datetime.datetime.now().timestamp() - p.create_time()) / 60, 1)
        return p, mem, uptime
    except psutil.NoSuchProcess:
        return None


# ── Watchdog ──────────────────────────────────────────────────────────────────

watchdog_pid = pidfile.read_pid("watchdog")
info = proc_info(watchdog_pid)
if info:
    _, mem, uptime = info
    print(f"[WATCHDOG]  PID {watchdog_pid}  mem={mem}MB  uptime={uptime}min")
else:
    print(f"[WATCHDOG]  NOT running" + (f" (PID {watchdog_pid} not found)" if watchdog_pid else ""))

# ── Bot ───────────────────────────────────────────────────────────────────────

print()
bot_pid = pidfile.read_pid("bot")
info = proc_info(bot_pid)
if info:
    _, mem, uptime = info
    print(f"[BOT]  PID {bot_pid}  mem={mem}MB  uptime={uptime}min")
else:
    print(f"[BOT]  NOT running" + (f" (PID {bot_pid} not found)" if bot_pid else ""))

# ── Bot heartbeat ──────────────────────────────────────────────────────────────

try:
    with open(HEARTBEAT_FILE, encoding="utf-8") as f:
        hb = json.load(f)
    age = datetime.datetime.now().timestamp() - hb["ts"]
    status = "OK" if age <= 30 else f"STALE ({age:.0f}s ago)"
    print(f"  Heartbeat : {age:.0f}s ago  [{status}]")
except FileNotFoundError:
    print("  Heartbeat : no file")
except Exception as e:
    print(f"  Heartbeat : error ({e})")

# ── Active tasks ───────────────────────────────────────────────────────────────

try:
    with open(IN_PROGRESS_FILE, encoding="utf-8") as f:
        in_progress = json.load(f)
except Exception:
    in_progress = {}

print()
print(f"[ACTIVE TASKS]  {len(in_progress)}")
for entry in in_progress.values():
    pid = entry.get("pid")
    channel = entry["channel"]
    label = entry.get("label", "")
    label_str = f'"{label}"' if label else "(no label)"
    print(f"  {label_str}  channel={channel}", end="")
    if pid:
        try:
            p = psutil.Process(pid)
            mem = round(p.memory_info().rss / 1024 / 1024, 1)
            print(f"  PID {pid}  mem={mem}MB  status={p.status()}")
        except psutil.NoSuchProcess:
            print(f"  PID {pid}  (exited)")
    else:
        print("  (starting...)")

# ── MCP servers ────────────────────────────────────────────────────────────────

print()
print("[MCP SERVERS]")
cfg_path = RUNTIME_CONFIG if os.path.exists(RUNTIME_CONFIG) else MCP_CONFIG
try:
    with open(cfg_path, encoding="utf-8") as f:
        mcp_config = json.load(f)
    for name, cfg in mcp_config.get("mcpServers", {}).items():
        if "url" in cfg:
            pid = cfg.get("pid")
            info = proc_info(pid)
            if info:
                _, mem, uptime = info
                state = f"RUNNING  PID {pid}  mem={mem}MB  uptime={uptime}min"
            else:
                state = f"DEAD (PID {pid})"
            print(f"  {name:<16} SSE  {cfg['url']}  {state}")
        else:
            print(f"  {name:<16} stdio (per-request)")
except Exception:
    print("  (could not read MCP config)")

# ── Python processes ───────────────────────────────────────────────────────────

self_pid = os.getpid()


def derive_process_name(cmdline):
    for part in cmdline:
        part_lower = part.lower()
        if "slack_claude_bot" in part_lower:
            return "ClaudeBot (bot)"
        if "watchdog" in part_lower:
            return "watchdog"
        if "status.py" in part_lower:
            return "status check"
        if "stop.py" in part_lower:
            return "stop script"
        if "mcp-atlassian" in part_lower:
            return "MCP Atlassian"
        if "mcp_manager" in part_lower:
            return "MCP manager"
    if any("scons" in c.lower() for c in cmdline):
        return "SCons build worker"
    if any("msbuild" in c.lower() for c in cmdline):
        return "MSBuild"
    for part in reversed(cmdline):
        if part.endswith(".py"):
            return os.path.basename(part)
    return cmdline[1] if len(cmdline) > 1 else "python"


print()
print("[PYTHON PROCESSES]")
print(f"  {'PID':<8} {'Name':<30} {'Mem(MB)':>8}  Status")
print(f"  {'-'*8} {'-'*30} {'-'*8}  {'-'*10}")
for proc in psutil.process_iter(["pid", "name", "status"]):
    try:
        if proc.info["name"].lower() != "python.exe":
            continue
        pid = proc.info["pid"]
        if pid == self_pid:
            continue
        cmdline = proc.cmdline()
        mem = round(proc.memory_info().rss / 1024 / 1024, 1)
        label = derive_process_name(cmdline)
        print(f"  {pid:<8} {label:<30} {mem:>8.1f}  {proc.info['status']}")
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        continue
