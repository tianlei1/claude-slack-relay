import os
import sys
import datetime
import json
import psutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PID_FILE = os.path.join(BASE_DIR, "claudeBot.pid")
LOG_FILE = os.path.join(BASE_DIR, "claudeBot.log")
HEARTBEAT_FILE = os.path.join(BASE_DIR, "heartbeat.json")

# ── Watchdog status ───────────────────────────────────────────────────────────

if not os.path.exists(PID_FILE):
    print("[STATUS] Watchdog is NOT running (no PID file)")
    sys.exit(1)

with open(PID_FILE) as f:
    watchdog_pid = int(f.read().strip())

try:
    wp = psutil.Process(watchdog_pid)
    w_mem = round(wp.memory_info().rss / 1024 / 1024, 1)
    w_uptime = round((datetime.datetime.now().timestamp() - wp.create_time()) / 60, 1)
    print(f"[STATUS] Watchdog RUNNING")
    print(f"         PID     : {watchdog_pid}")
    print(f"         Memory  : {w_mem} MB")
    print(f"         Uptime  : {w_uptime} min")
except psutil.NoSuchProcess:
    print(f"[STATUS] Watchdog NOT running (PID {watchdog_pid} not found)")
    os.remove(PID_FILE)
    sys.exit(1)

# ── Bot heartbeat ─────────────────────────────────────────────────────────────

print()
print("[BOT HEARTBEAT]")
try:
    with open(HEARTBEAT_FILE, encoding="utf-8") as f:
        hb = json.load(f)
    age = datetime.datetime.now().timestamp() - hb["ts"]
    bot_pid = hb.get("pid")
    status = "OK" if age <= 30 else f"STALE ({age:.0f}s ago)"
    print(f"  Last beat : {age:.0f}s ago  [{status}]")
    if bot_pid:
        try:
            bp = psutil.Process(bot_pid)
            b_mem = round(bp.memory_info().rss / 1024 / 1024, 1)
            b_uptime = round((datetime.datetime.now().timestamp() - bp.create_time()) / 60, 1)
            print(f"  Bot PID   : {bot_pid}  mem={b_mem}MB  uptime={b_uptime}min")
        except psutil.NoSuchProcess:
            print(f"  Bot PID   : {bot_pid}  (not found)")
except FileNotFoundError:
    print("  No heartbeat file — bot may not have started yet")
except Exception as e:
    print(f"  Error reading heartbeat: {e}")

# ── Active tasks ──────────────────────────────────────────────────────────────

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

print()
print(f"[ACTIVE TASKS]  {len(in_progress)}")
for entry in in_progress.values():
    pid = entry.get("pid")
    channel = entry["channel"]
    label = entry.get("label", "")
    label_str = f'"{label}"' if label else "(no label)"
    print()
    print(f"  Task: {label_str}")
    if pid:
        try:
            cp = psutil.Process(pid)
            mem = round(cp.memory_info().rss / 1024 / 1024, 1)
            print(f"    claude PID {pid}  mem={mem}MB  status={cp.status()}  channel={channel}")
            children = get_python_children(pid)
            if children:
                print(f"    {'PID':<8} {'Name':<28} {'Mem(MB)':>8}  Status")
                print(f"    {'-'*8} {'-'*28} {'-'*8}  {'-'*10}")
                for cpid, cname, cmem, cstatus in children:
                    print(f"    {cpid:<8} {cname:<28} {cmem:>8.1f}  {cstatus}")
        except psutil.NoSuchProcess:
            print(f"    claude PID {pid}  (already exited)  channel={channel}")
    else:
        print(f"    channel={channel}  (starting...)")

# ── MCP servers (all stdio) ───────────────────────────────────────────────────

WORK_DIR = os.path.dirname(BASE_DIR)
mcp_config_path = os.path.join(WORK_DIR, ".mcp.json")
print()
print("[MCP SERVERS]  stdio (per-request)")
try:
    with open(mcp_config_path, encoding="utf-8") as f:
        mcp_config = json.load(f)
    for name in mcp_config.get("mcpServers", {}):
        print(f"  {name}")
except Exception:
    print("  (could not read .mcp.json)")

# ── Python processes ──────────────────────────────────────────────────────────

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
