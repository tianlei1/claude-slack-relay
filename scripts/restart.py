"""
Restart the bot: kill the old instance (if any), then launch a new detached process.
Safe to call manually or from the watchdog.
"""
import os
import sys
import subprocess
import time

import psutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT_SCRIPT = os.path.join(BASE_DIR, "scripts", "slack_claude_bot.py")

if __name__ == "__main__":
    our_pid = os.getpid()
    bot_script_name = os.path.basename(BOT_SCRIPT)

    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.pid == our_pid:
                continue
            cmdline = proc.info.get("cmdline") or []
            if any(bot_script_name in arg for arg in cmdline):
                print(f"Killing bot PID {proc.pid}")
                proc.terminate()
                proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    time.sleep(0.5)

    subprocess.Popen(
        [sys.executable, "-u", BOT_SCRIPT],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    print("Restart initiated")
