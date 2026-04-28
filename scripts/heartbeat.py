"""
Heartbeat module: the bot writes a timestamp every 10s;
the watchdog reads it to detect hangs.
"""
import os
import json
import time
import threading

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEARTBEAT_FILE = os.path.join(BASE_DIR, "heartbeat.json")
INTERVAL = 10  # seconds between heartbeat writes


def start():
    """Start the heartbeat writer thread. Call once from the bot process."""
    def _loop():
        while True:
            try:
                with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
                    json.dump({"ts": time.time(), "pid": os.getpid()}, f)
            except Exception:
                pass
            time.sleep(INTERVAL)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()


def is_alive(timeout: int = 30) -> bool:
    """Return True if the bot wrote a heartbeat within `timeout` seconds."""
    try:
        with open(HEARTBEAT_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return (time.time() - data["ts"]) <= timeout
    except Exception:
        return False


def clear():
    """Remove the heartbeat file (call on clean shutdown)."""
    try:
        os.remove(HEARTBEAT_FILE)
    except FileNotFoundError:
        pass
