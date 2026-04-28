import os
import sys
import time
import subprocess
import psutil
import logging

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

if os.path.exists(STOP_FLAG):
    os.remove(STOP_FLAG)

with open(PID_FILE, "w") as f:
    f.write(str(os.getpid()))
log.info(f"Watchdog started (PID {os.getpid()})")


def kill_process_tree(pid):
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for p in children:
            try:
                p.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        try:
            parent.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        _, alive = psutil.wait_procs(children + [parent], timeout=5)
        for p in alive:
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except psutil.NoSuchProcess:
        pass


RESTART_DELAY = 5
MAX_RAPID_RESTARTS = 5
RAPID_RESTART_WINDOW = 300  # 5 分钟内连续崩溃超过5次则停止

restart_times = []
restart_count = 0

while True:
    if os.path.exists(STOP_FLAG):
        log.info("Stop flag detected, watchdog exiting")
        break

    now = time.time()
    restart_times = [t for t in restart_times if now - t < RAPID_RESTART_WINDOW]
    if len(restart_times) >= MAX_RAPID_RESTARTS:
        log.error(
            f"Bot crashed {MAX_RAPID_RESTARTS} times within {RAPID_RESTART_WINDOW}s "
            f"— stopping to prevent restart loop"
        )
        break

    log.info(f"Starting bot (restart #{restart_count})")
    proc = subprocess.Popen([sys.executable, "-u", BOT_SCRIPT])
    log.info(f"Bot started (PID {proc.pid})")

    try:
        proc.wait()
    except KeyboardInterrupt:
        log.info("Watchdog interrupted")
        kill_process_tree(proc.pid)
        break

    log.info(f"Bot exited (PID {proc.pid}, code {proc.returncode})")
    kill_process_tree(proc.pid)

    if os.path.exists(STOP_FLAG):
        log.info("Stop flag detected after bot exit, not restarting")
        break

    restart_count += 1
    restart_times.append(time.time())
    log.info(f"Restarting bot in {RESTART_DELAY}s...")
    time.sleep(RESTART_DELAY)

if os.path.exists(STOP_FLAG):
    os.remove(STOP_FLAG)
if os.path.exists(PID_FILE):
    os.remove(PID_FILE)
log.info("Watchdog stopped")
