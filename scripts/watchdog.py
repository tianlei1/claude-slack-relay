"""
Watchdog: starts the bot, monitors it and all its children every 10s.
- Bot main process: heartbeat-based (30s timeout → kill + restart)
- Child processes: status-based (zombie/stopped → kill + log)
"""
import os
import sys
import time
import subprocess
import psutil
import logging
import heartbeat

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT_SCRIPT = os.path.join(BASE_DIR, "scripts", "slack_claude_bot.py")
PID_FILE = os.path.join(BASE_DIR, "claudeBot.pid")
STOP_FLAG = os.path.join(BASE_DIR, "claudeBot.stop")
LOG_FILE = os.path.join(BASE_DIR, "watchdog.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s\t%(levelname)s\t%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger("watchdog")

HEARTBEAT_TIMEOUT = 30   # seconds without heartbeat → bot considered hung
CHECK_INTERVAL = 10      # seconds between each monitoring sweep
RESTART_DELAY = 5        # seconds to wait before restarting after a kill
MAX_RAPID_RESTARTS = 5   # max restarts allowed within RAPID_RESTART_WINDOW
RAPID_RESTART_WINDOW = 300  # 5 minutes


def kill_process_tree(pid: int, reason: str = ""):
    tag = f" ({reason})" if reason else ""
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
                log.warning(f"Force-killed PID {p.pid}{tag}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        log.info(f"Killed process tree rooted at PID {pid}{tag} ({len(all_procs)} proc(s))")
    except psutil.NoSuchProcess:
        pass


def check_children(bot_pid: int):
    """Kill any zombie/stopped children of the bot and log them."""
    try:
        for child in psutil.Process(bot_pid).children(recursive=True):
            try:
                status = child.status()
                if status in (psutil.STATUS_ZOMBIE, psutil.STATUS_STOPPED):
                    log.warning(
                        f"Child PID {child.pid} (status={status}) is unresponsive — killing"
                    )
                    try:
                        child.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass


def start_bot() -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-u", BOT_SCRIPT])
    log.info(f"Bot started (PID {proc.pid})")
    return proc


# ── startup ──────────────────────────────────────────────────────────────────

if os.path.exists(STOP_FLAG):
    os.remove(STOP_FLAG)

heartbeat.clear()

with open(PID_FILE, "w") as f:
    f.write(str(os.getpid()))
log.info(f"Watchdog started (PID {os.getpid()})")

restart_times: list[float] = []
restart_count = 0

# ── main loop ─────────────────────────────────────────────────────────────────

while True:
    if os.path.exists(STOP_FLAG):
        log.info("Stop flag detected, watchdog exiting cleanly")
        break

    # Rapid-restart guard
    now = time.time()
    restart_times = [t for t in restart_times if now - t < RAPID_RESTART_WINDOW]
    if len(restart_times) >= MAX_RAPID_RESTARTS:
        log.error(
            f"Bot crashed {MAX_RAPID_RESTARTS}× within {RAPID_RESTART_WINDOW}s "
            f"— halting watchdog to prevent restart loop"
        )
        break

    proc = start_bot()
    bot_pid = proc.pid
    heartbeat_missing_since: float | None = None

    # ── per-bot monitoring loop ───────────────────────────────────────────────
    while True:
        time.sleep(CHECK_INTERVAL)

        # Check stop flag
        if os.path.exists(STOP_FLAG):
            log.info("Stop flag detected during monitoring — killing bot and exiting")
            kill_process_tree(bot_pid, "stop requested")
            break

        # Check if bot exited on its own
        ret = proc.poll()
        if ret is not None:
            log.info(f"Bot exited on its own (PID {bot_pid}, code {ret})")
            kill_process_tree(bot_pid, "cleanup after natural exit")
            break

        # Check bot heartbeat
        if heartbeat.is_alive(HEARTBEAT_TIMEOUT):
            heartbeat_missing_since = None
        else:
            if heartbeat_missing_since is None:
                heartbeat_missing_since = time.time()
                log.warning(f"Bot heartbeat missing (PID {bot_pid})")
            elif time.time() - heartbeat_missing_since >= HEARTBEAT_TIMEOUT:
                log.error(
                    f"Bot PID {bot_pid} did not respond for {HEARTBEAT_TIMEOUT}s — killing and restarting"
                )
                kill_process_tree(bot_pid, "heartbeat timeout")
                break

        # Check children
        check_children(bot_pid)

    if os.path.exists(STOP_FLAG):
        break

    restart_count += 1
    restart_times.append(time.time())
    log.info(f"Restarting bot in {RESTART_DELAY}s (restart #{restart_count})...")
    heartbeat.clear()
    time.sleep(RESTART_DELAY)

# ── cleanup ───────────────────────────────────────────────────────────────────

if os.path.exists(STOP_FLAG):
    os.remove(STOP_FLAG)
if os.path.exists(PID_FILE):
    os.remove(PID_FILE)
heartbeat.clear()
log.info("Watchdog stopped")
