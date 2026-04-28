"""
Watchdog: monitors bot and MCP servers via PID files.
Started by the bot on startup. Restarts dead processes.
- Bot: heartbeat-based (30s timeout) + PID check
- MCP servers: PID check, restart using cmd from runtime config
- On bot crash: kill all Claude subprocesses first, then restart bot
"""
import os
import sys
import json
import time
import subprocess
import psutil
import logging
import heartbeat

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESTART_SCRIPT = os.path.join(BASE_DIR, "scripts", "restart.py")
PIDS_DIR = os.path.join(BASE_DIR, "pids")
BOT_PID_FILE = os.path.join(PIDS_DIR, "bot.pid")
WATCHDOG_PID_FILE = os.path.join(PIDS_DIR, "watchdog.pid")
STOP_FLAG = os.path.join(BASE_DIR, "claudeBot.stop")
IN_PROGRESS_FILE = os.path.join(BASE_DIR, "in_progress.json")
RUNTIME_CONFIG = os.path.join(os.path.dirname(BASE_DIR), ".mcp.runtime.json")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s\t%(levelname)s\t%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(os.path.join(BASE_DIR, "watchdog.log"), encoding="utf-8", mode="a"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger("watchdog")

HEARTBEAT_TIMEOUT = 30
CHECK_INTERVAL = 10
RESTART_DELAY = 5
MAX_RAPID_RESTARTS = 5
RAPID_RESTART_WINDOW = 300


def read_pid(path):
    try:
        return int(open(path).read().strip())
    except Exception:
        return None


def is_alive(pid):
    if pid is None:
        return False
    try:
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except Exception:
        return False


def kill_tree(pid, reason=""):
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        all_procs = children + [parent]
        for p in all_procs:
            try:
                p.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        _, alive = psutil.wait_procs(all_procs, timeout=5)
        for p in alive:
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        tag = f" ({reason})" if reason else ""
        log.info(f"Killed PID {pid}{tag} + {len(children)} child(ren)")
    except psutil.NoSuchProcess:
        pass


def kill_claude_subprocesses():
    try:
        with open(IN_PROGRESS_FILE, encoding="utf-8") as f:
            in_progress = json.load(f)
    except Exception:
        return
    for entry in in_progress.values():
        pid = entry.get("pid")
        if pid and is_alive(pid):
            log.info(f"Killing Claude subprocess PID {pid} (channel={entry.get('channel')})")
            kill_tree(pid, "bot restart cleanup")
    try:
        with open(IN_PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)
    except Exception:
        pass


def start_bot():
    subprocess.run([sys.executable, RESTART_SCRIPT], capture_output=True)
    log.info("Bot restart initiated via restart.py")
    for _ in range(20):
        time.sleep(0.5)
        new_pid = read_pid(BOT_PID_FILE)
        if new_pid and is_alive(new_pid):
            log.info(f"Bot PID {new_pid} confirmed")
            break


def restart_mcp(name, info):
    """Restart a dead MCP server using command stored in runtime config."""
    cmd = info.get("cmd")
    env_overrides = info.get("env", {})
    if not cmd:
        log.warning(f"No restart command for MCP '{name}'")
        return None
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_path = os.path.join(LOGS_DIR, f"mcp_{name}.log")
    env = {**os.environ, **env_overrides}
    try:
        log_file = open(log_path, "a", encoding="utf-8")
        proc = subprocess.Popen(
            cmd, env=env,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
        )
        log_file.close()
        log.info(f"MCP '{name}' restarted (PID {proc.pid})")
        pid_file = os.path.join(PIDS_DIR, f"mcp_{name}.pid")
        with open(pid_file, "w") as f:
            f.write(str(proc.pid))
        return proc.pid
    except Exception as e:
        log.error(f"Failed to restart MCP '{name}': {e}")
        return None


def update_runtime_config_pid(name, new_pid):
    try:
        with open(RUNTIME_CONFIG, encoding="utf-8") as f:
            config = json.load(f)
        if name in config.get("mcpServers", {}):
            config["mcpServers"][name]["pid"] = new_pid
        with open(RUNTIME_CONFIG, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        log.warning(f"Failed to update runtime config PID for '{name}': {e}")


# ── startup ───────────────────────────────────────────────────────────────────

os.makedirs(PIDS_DIR, exist_ok=True)

# Kill any existing watchdog instance
old_pid = read_pid(WATCHDOG_PID_FILE)
if old_pid and old_pid != os.getpid() and is_alive(old_pid):
    log.info(f"Killing old watchdog PID {old_pid}")
    kill_tree(old_pid, "replaced by new instance")
    time.sleep(1)

with open(WATCHDOG_PID_FILE, "w") as f:
    f.write(str(os.getpid()))
log.info(f"Watchdog started (PID {os.getpid()})")

if os.path.exists(STOP_FLAG):
    os.remove(STOP_FLAG)

bot_restart_times = []
heartbeat_missing_since = None

# ── main loop ─────────────────────────────────────────────────────────────────

while True:
    if os.path.exists(STOP_FLAG):
        log.info("Stop flag detected, exiting")
        break

    time.sleep(CHECK_INTERVAL)

    # ── check bot ─────────────────────────────────────────────────────────────
    bot_pid = read_pid(BOT_PID_FILE)
    bot_process_dead = not is_alive(bot_pid)
    hb_ok = heartbeat.is_alive(HEARTBEAT_TIMEOUT)

    needs_restart = False
    restart_reason = ""

    if bot_process_dead:
        needs_restart = True
        restart_reason = f"process dead (PID {bot_pid})"
    elif not hb_ok:
        if heartbeat_missing_since is None:
            heartbeat_missing_since = time.time()
            log.warning(f"Bot heartbeat missing (PID {bot_pid})")
        elif time.time() - heartbeat_missing_since >= HEARTBEAT_TIMEOUT:
            needs_restart = True
            restart_reason = f"heartbeat timeout ({HEARTBEAT_TIMEOUT}s)"
    else:
        heartbeat_missing_since = None

    if needs_restart:
        log.warning(f"Bot needs restart: {restart_reason}")
        now = time.time()
        bot_restart_times = [t for t in bot_restart_times if now - t < RAPID_RESTART_WINDOW]
        if len(bot_restart_times) >= MAX_RAPID_RESTARTS:
            log.error(f"Bot crashed {MAX_RAPID_RESTARTS}x in {RAPID_RESTART_WINDOW}s — halting")
            break

        kill_claude_subprocesses()
        if bot_pid and not bot_process_dead:
            kill_tree(bot_pid, restart_reason)

        heartbeat.clear()
        heartbeat_missing_since = None
        bot_restart_times.append(time.time())
        log.info(f"Restarting bot in {RESTART_DELAY}s (restart #{len(bot_restart_times)})...")
        time.sleep(RESTART_DELAY)
        start_bot()

    # ── check MCP servers ──────────────────────────────────────────────────────
    try:
        with open(RUNTIME_CONFIG, encoding="utf-8") as f:
            runtime = json.load(f)
        for name, info in runtime.get("mcpServers", {}).items():
            if info.get("type") != "sse":
                continue
            pid = info.get("pid")
            if not is_alive(pid):
                log.warning(f"MCP '{name}' (PID {pid}) is dead, restarting...")
                new_pid = restart_mcp(name, info)
                if new_pid:
                    update_runtime_config_pid(name, new_pid)
    except Exception as e:
        log.debug(f"Could not check MCP servers: {e}")

# ── cleanup ───────────────────────────────────────────────────────────────────

if os.path.exists(STOP_FLAG):
    os.remove(STOP_FLAG)
try:
    os.remove(WATCHDOG_PID_FILE)
except Exception:
    pass
heartbeat.clear()
log.info("Watchdog stopped")
