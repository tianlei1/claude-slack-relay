"""
Restart the bot by launching a new watchdog as a fully detached process.
The new watchdog kills the existing instance on startup.
Safe to call from within the bot or watchdog process tree.
"""
import os
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHDOG_SCRIPT = os.path.join(BASE_DIR, "scripts", "watchdog.py")

subprocess.Popen(
    [sys.executable, "-u", WATCHDOG_SCRIPT],
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    close_fds=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    stdin=subprocess.DEVNULL,
)
print("Restart initiated")
