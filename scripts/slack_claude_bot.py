import os
import re
import subprocess
import sys
import json
import glob
import platform
import tempfile
import time
import threading
import requests
import psutil
from collections import deque
os.environ["PYTHONUTF8"] = "1"

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from logger import get_logger
from mcp_manager import MCPServerManager
import heartbeat
import pidfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_path = os.path.join(BASE_DIR, ".env")
_env_loaded = load_dotenv(_env_path, encoding='utf-8-sig')
log = get_logger(__name__)
log.info(f".env path: {_env_path} (loaded={_env_loaded})")

BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
app = App(token=BOT_TOKEN)

SESSIONS_FILE = os.path.join(BASE_DIR, "sessions.json")
IN_PROGRESS_FILE = os.path.join(BASE_DIR, "in_progress.json")
WATCHDOG_SCRIPT = os.path.join(BASE_DIR, "scripts", "watchdog.py")
processed_events = set()
STOP_FLAG = os.path.join(BASE_DIR, "claudeBot.stop")
MAX_QUEUE_SIZE = 3
MAX_IMAGE_SIZE = 100 * 1024 * 1024

_channel_queues: dict = {}
_queue_lock = threading.Lock()


def load_sessions():
    try:
        with open(SESSIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_sessions(sessions):
    try:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f)
    except Exception as e:
        log.error(f"Failed to save sessions: {e}")


channel_sessions = load_sessions()

WORK_DIR = os.path.dirname(BASE_DIR)

mcp_manager = MCPServerManager(os.path.join(BASE_DIR, ".mcp.json"))


def load_in_progress():
    try:
        with open(IN_PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_in_progress(data):
    try:
        with open(IN_PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        log.error(f"Failed to save in_progress: {e}")


def mark_processing_start(channel, ts, pid=None, label=None):
    data = load_in_progress()
    entry = {"channel": channel, "ts": ts}
    if pid is not None:
        entry["pid"] = pid
    if label is not None:
        entry["label"] = label
    data[f"{channel}|{ts}"] = entry
    save_in_progress(data)


def mark_processing_done(channel, ts):
    data = load_in_progress()
    data.pop(f"{channel}|{ts}", None)
    save_in_progress(data)


def notify_interrupted_requests():
    data = load_in_progress()
    if not data:
        return
    client = WebClient(token=BOT_TOKEN)
    for entry in data.values():
        try:
            client.chat_update(
                channel=entry["channel"],
                ts=entry["ts"],
                text="Bot restarted during processing. Please resend your message."
            )
        except Exception as e:
            log.warning(f"Failed to notify interrupted request {entry}: {e}")
    save_in_progress({})
    log.info(f"Notified {len(data)} interrupted request(s) after restart")


def lookup_ad_display_name():
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "$s=New-Object System.DirectoryServices.DirectorySearcher;"
             "$s.Filter='(&(objectClass=user)(sAMAccountName=' + $env:USERNAME + '))';"
             "$s.PropertiesToLoad.Add('displayName')|Out-Null;"
             "($s.FindOne()).Properties['displayName'][0]"],
            capture_output=True, text=True, timeout=10
        )
        name = result.stdout.strip()
        if name:
            return name
    except Exception:
        pass
    return os.environ.get("USERNAME", "Unknown")


def read_mcp_server_names():
    mcp_config = os.path.join(BASE_DIR, ".mcp.json")
    try:
        with open(mcp_config, encoding="utf-8") as f:
            data = json.load(f)
            return ", ".join(data.get("mcpServers", {}).keys())
    except Exception:
        return "none"


def build_system_context():
    display_name = lookup_ad_display_name()
    os_name = f"{platform.system()} {platform.release()}"
    mcp_tools = read_mcp_server_names()
    return (
        f"You are an AI assistant running on {display_name}'s {os_name} computer "
        f"via Slack. Working directory: {WORK_DIR}. "
        f"You have full access to local files and MCP tools ({mcp_tools}). "
        f"IMPORTANT SAFETY RULES: "
        f"1. Never use 'taskkill /IM python.exe' or 'Stop-Process -Name python' — these kill ALL Python processes including this bot itself. Always kill by specific PID only (e.g. taskkill /PID 1234). "
        f"2. Never use 'rm -rf', 'rmdir /s', or any recursive delete on directories without explicit user confirmation. "
        f"IMAGE SHARING: To send an image to the user in Slack, include [IMAGE:/absolute/path/to/file.png] anywhere in your response. "
        f"The file will be uploaded automatically. You can use this with screenshots from the computer MCP tool."
    )


_IMAGE_PATTERN = re.compile(r'\[IMAGE:([^\]]+)\]')


def upload_images_to_slack(text: str, channel: str, client) -> str:
    paths = _IMAGE_PATTERN.findall(text)
    if not paths:
        return text
    for path in paths:
        path = path.strip()
        try:
            client.files_upload_v2(
                channel=channel,
                file=path,
                filename=os.path.basename(path),
                title=os.path.basename(path),
            )
            log.info(f"Uploaded image to Slack: {path}")
        except Exception as e:
            log.error(f"Failed to upload image {path}: {e}")
        finally:
            try:
                os.remove(path)
            except Exception:
                pass
    return _IMAGE_PATTERN.sub("", text).strip()


def download_slack_images(files, bot_token):
    """Download image files from Slack, return list of local temp file paths."""
    SUPPORTED = {"image/png", "image/jpeg", "image/gif", "image/webp"}
    EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
    paths = []
    for f in files:
        mimetype = f.get("mimetype", "")
        if mimetype not in SUPPORTED:
            continue
        url = f.get("url_private_download") or f.get("url_private")
        if not url:
            continue
        try:
            resp = requests.get(url, headers={"Authorization": f"Bearer {bot_token}"}, timeout=30)
            resp.raise_for_status()
            tmp = tempfile.NamedTemporaryFile(suffix=EXT.get(mimetype, ".png"), delete=False)
            tmp.write(resp.content)
            tmp.close()
            paths.append(tmp.name)
            log.info(f"Downloaded Slack image to {tmp.name}")
        except Exception as e:
            log.error(f"Failed to download Slack image: {e}")
    return paths


def ask_claude_and_update_reply(channel, text, client, status_ts, image_paths=None):
    session_id = channel_sessions.get(channel)
    mcp_args = mcp_manager.get_mcp_args()
    image_note = ""
    if image_paths:
        paths_str = ", ".join(image_paths)
        image_note = f"\n\n[用户发送了 {len(image_paths)} 张图片，已保存至: {paths_str}，请用 Read 工具读取并分析]"

    if session_id:
        cmd = ["claude", "--resume", session_id, "-p", text + image_note,
               "--output-format", "stream-json", "--verbose",
               "--dangerously-skip-permissions"] + mcp_args
        log.info(f"Resuming session {session_id} for channel {channel}")
    else:
        prompt = f"{build_system_context()}\n\n---\n\n{text}{image_note}"
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--dangerously-skip-permissions"] + mcp_args
        log.info(f"Starting new session for channel {channel}")

    tool_steps = []
    current_text = ""
    final_result = ""
    new_session_id = None
    is_error = False
    last_update_time = 0
    start_time = time.time()

    def build_live_message():
        parts = []
        if tool_steps:
            parts.append("\n".join(f"> {s}" for s in tool_steps))
        if current_text:
            if parts:
                parts.append("")
            parts.append(current_text[:2000])
        return "\n".join(parts) if parts else "Processing..."

    def throttled_update():
        nonlocal last_update_time
        now = time.time()
        if now - last_update_time >= 1.0:
            try:
                client.chat_update(channel=channel, ts=status_ts, text=build_live_message())
            except Exception:
                pass
            last_update_time = now

    label = text[:40].strip()
    had_output = True
    mark_processing_start(channel, status_ts, label=label)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            cwd=WORK_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        mark_processing_start(channel, status_ts, proc.pid, label=label)
        log.info(f"Claude subprocess started: PID {proc.pid}, label='{label}'")

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type")
            if etype == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use":
                        name = block.get("name", "")
                        inp = block.get("input", {})
                        first_val = next(iter(inp.values()), "") if inp else ""
                        summary = first_val[:60] if isinstance(first_val, str) else ""
                        step = f"{name}: {summary}" if summary else name
                        tool_steps.append(step)
                        log.info(f"Tool call: {step}")
                        throttled_update()
                    elif block.get("type") == "text":
                        current_text += block.get("text", "")
                        throttled_update()
            elif etype == "result":
                new_session_id = event.get("session_id")
                is_error = event.get("is_error", False) or event.get("subtype") == "error_during_execution"
                final_result = event.get("result", "").strip()

        stderr_output = proc.stderr.read().strip()
        proc.wait()
        elapsed = time.time() - start_time
        log.info(f"Claude subprocess finished: PID {proc.pid}, exit code {proc.returncode}, elapsed {elapsed:.1f}s")

        if stderr_output:
            log.warning(f"Claude stderr: {stderr_output[:200]}")
        had_output = bool(final_result or current_text.strip())
        final_result = final_result or current_text.strip()
        if not final_result:
            final_result = f"Error: {stderr_output[:500]}" if stderr_output else "Done (no output)"

        if is_error:
            log.error(f"Claude returned error: {final_result[:200]}")

    except FileNotFoundError:
        final_result = "claude command not found"
        log.error("Claude subprocess failed: 'claude' command not found in PATH")
    except Exception as e:
        final_result = f"Error: {e}"
        log.error(f"Claude subprocess exception: {e}")
    finally:
        mark_processing_done(channel, status_ts)
        for path in (image_paths or []):
            try:
                os.unlink(path)
            except Exception:
                pass

    if is_error or not had_output:
        channel_sessions.pop(channel, None)
        log.warning(f"Session cleared for channel {channel} ({'error' if is_error else 'no output'})")
    elif new_session_id:
        channel_sessions[channel] = new_session_id
        log.info(f"Session saved: {new_session_id} for channel {channel}")
    save_sessions(channel_sessions)

    return final_result[:3000]


def lookup_ad_email():
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "$s=New-Object System.DirectoryServices.DirectorySearcher;"
             "$s.Filter='(&(objectClass=user)(sAMAccountName=' + $env:USERNAME + '))';"
             "$s.PropertiesToLoad.Add('mail')|Out-Null;"
             "($s.FindOne()).Properties['mail'][0]"],
            capture_output=True, text=True, timeout=10
        )
        email = result.stdout.strip().lower()
        if "@" in email:
            return email
        log.warning(f"AD email lookup returned no valid email (output: '{result.stdout.strip()[:100]}')")
    except Exception as e:
        log.warning(f"AD email lookup failed: {e}")
    return None


_email_from_env = (os.environ.get("ALLOWED_USER_EMAIL") or "").strip() or None
_email_from_ad = lookup_ad_email() if not _email_from_env else None
ALLOWED_USER_EMAIL = _email_from_env or _email_from_ad
if not ALLOWED_USER_EMAIL:
    log.error("ALLOWED_USER_EMAIL not set and AD lookup failed — bot will reject all messages. Set ALLOWED_USER_EMAIL in .env")
elif _email_from_env:
    log.info(f"Whitelist email: {ALLOWED_USER_EMAIL} (from .env)")
else:
    log.info(f"Whitelist email: {ALLOWED_USER_EMAIL} (from AD)")
_whitelist_user_id = None


def resolve_whitelist_user_id(client):
    global _whitelist_user_id
    if _whitelist_user_id:
        return _whitelist_user_id
    if not ALLOWED_USER_EMAIL:
        raise ValueError("ALLOWED_USER_EMAIL is not configured")
    log.info(f"Looking up Slack user by email: {ALLOWED_USER_EMAIL!r}")
    result = client.users_lookupByEmail(email=ALLOWED_USER_EMAIL)
    _whitelist_user_id = result["user"]["id"]
    log.info(f"Whitelist user ID resolved: {_whitelist_user_id}")
    return _whitelist_user_id


def is_allowed_user(client, user_id):
    try:
        return user_id == resolve_whitelist_user_id(client)
    except ValueError:
        return False
    except Exception as e:
        log.error(f"Failed to resolve whitelist user: {e}")
        return False


def _enqueue(channel, text, image_paths, client):
    """Add to channel queue. Returns queue position (1-based), or None if full."""
    with _queue_lock:
        q = _channel_queues.setdefault(channel, deque())
        if len(q) >= MAX_QUEUE_SIZE:
            return None
        pos = len(q) + 1
        try:
            resp = client.chat_postMessage(channel=channel, text=f"已收到，排队第 {pos} 条，请稍候...")
            status_ts = resp["ts"]
        except Exception as e:
            log.error(f"Failed to post queue placeholder: {e}")
            return None
        q.append({"text": text, "image_paths": image_paths, "client": client,
                   "channel": channel, "status_ts": status_ts})
        log.info(f"Queued message for channel {channel} (pos={pos})")
        return pos


def _process_next_queued(channel):
    """Pop and process the next queued message for channel."""
    with _queue_lock:
        q = _channel_queues.get(channel)
        if not q:
            return
        entry = q.popleft()
    client = entry["client"]
    status_ts = entry["status_ts"]
    try:
        client.chat_update(channel=channel, ts=status_ts,
                           text="Processing... Please wait, this may take a moment.")
    except Exception:
        pass
    result = ask_claude_and_update_reply(channel, entry["text"], client, status_ts, entry["image_paths"])
    result = upload_images_to_slack(result, channel, client)
    try:
        client.chat_update(channel=channel, ts=status_ts, text=result or "​")
        log.info(f"Replied (queued): {result[:80]}")
    except Exception as e:
        log.error(f"chat_update failed (queued): {e}")
        try:
            client.chat_postMessage(channel=channel, text=result)
        except Exception:
            pass
    with _queue_lock:
        if _channel_queues.get(channel):
            threading.Thread(target=_process_next_queued, args=(channel,), daemon=True).start()


def process_slack_message(event, say, client):
    event_id = event.get("event_ts") or event.get("ts")
    if event_id in processed_events:
        return
    processed_events.add(event_id)
    if len(processed_events) > 500:
        processed_events.clear()

    user_id = event.get("user")
    if not is_allowed_user(client, user_id):
        log.warning(f"Rejected message from unauthorized user: {user_id}")
        return
    text = event.get("text", "").strip()
    files = event.get("files", [])
    image_paths = download_slack_images(files, BOT_TOKEN) if files else []

    if not text and not image_paths:
        log.warning(f"Received empty message from user {user_id}, ignored")
        return
    if not text and image_paths:
        text = "请分析这张图片"
    log.info(f"Received: {text[:80]}" + (f" + {len(image_paths)} image(s)" if image_paths else ""))

    if image_paths:
        total_size = sum(os.path.getsize(p) for p in image_paths if os.path.exists(p))
        if total_size > MAX_IMAGE_SIZE:
            say(f"图片总大小超过 100MB（{total_size // 1024 // 1024}MB），无法处理。")
            for p in image_paths:
                try:
                    os.unlink(p)
                except Exception:
                    pass
            return

    channel = event.get("channel")
    if text.lower() == "!reset":
        self_pid = os.getpid()
        # Collect PIDs to preserve: self, watchdog, and all MCP servers
        protected_pids = {self_pid}
        for pid in pidfile.read_all().values():
            if pid:
                protected_pids.add(pid)
        killed = []
        failed = []
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True
            )
            for line in result.stdout.strip().splitlines():
                parts = line.strip('"').split('","')
                if len(parts) >= 2:
                    try:
                        pid = int(parts[1])
                        if pid not in protected_pids:
                            r = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                                               capture_output=True)
                            if r.returncode == 0:
                                killed.append(pid)
                            else:
                                failed.append(pid)
                                log.warning(f"Failed to kill PID {pid}: {r.stderr.strip()}")
                    except Exception as e:
                        log.warning(f"Error processing PID entry '{line}': {e}")
        except Exception as e:
            log.warning(f"Failed to enumerate python processes: {e}")
        save_in_progress({})
        channel_sessions.pop(channel, None)
        save_sessions(channel_sessions)
        with _queue_lock:
            _channel_queues.pop(channel, None)
        msg = "Conversation history cleared."
        if killed:
            msg += f" Killed {len(killed)} python process(es): PID {', '.join(str(p) for p in killed)}."
        if failed:
            msg += f" Failed to kill PID(s): {', '.join(str(p) for p in failed)}."
        try:
            log_file = os.path.join(BASE_DIR, "claudeBot.log")
            with open(log_file, "w"):
                pass
            msg += " Log cleared."
        except Exception as e:
            log.warning(f"Failed to clear log: {e}")
        screen_dir = os.path.join(BASE_DIR, "screen")
        try:
            png_files = glob.glob(os.path.join(screen_dir, "*.png"))
            for f in png_files:
                try:
                    os.remove(f)
                except Exception as e:
                    log.warning(f"Failed to delete screenshot {f}: {e}")
            if png_files:
                msg += f" Deleted {len(png_files)} screenshot(s)."
        except Exception as e:
            log.warning(f"Failed to clean screen dir: {e}")
        log.info(f"Reset: session cleared, killed={killed}, failed={failed}")
        say(msg)
        return

    in_progress = load_in_progress()
    if any(v["channel"] == channel for v in in_progress.values()):
        pos = _enqueue(channel, text, image_paths, client)
        if pos is None:
            say(f"队列已满（{MAX_QUEUE_SIZE} 条排队中），请稍后再试。")
            for p in image_paths:
                try:
                    os.unlink(p)
                except Exception:
                    pass
        return

    resp = say("Processing... Please wait, this may take a moment.")
    status_ts = resp.get("ts")
    result = ask_claude_and_update_reply(channel, text, client, status_ts, image_paths)
    result = upload_images_to_slack(result, channel, client)
    try:
        client.chat_update(channel=channel, ts=status_ts, text=result or "​")  # Slack rejects empty text
        log.info(f"Replied: {result[:80]}")
    except Exception as e:
        log.error(f"chat_update failed: {e}")
        say(result)
    with _queue_lock:
        if _channel_queues.get(channel):
            threading.Thread(target=_process_next_queued, args=(channel,), daemon=True).start()


@app.event("message")
def on_direct_message(event, say, client):
    if event.get("subtype"):
        return
    process_slack_message(event, say, client)


@app.event("app_mention")
def on_app_mention(event, say, client):
    text = event.get("text", "")
    event = dict(event)
    event["text"] = " ".join(text.split()[1:]).strip()
    process_slack_message(event, say, client)


def _start_watchdog_if_needed():
    try:
        pid = pidfile.read_pid("watchdog")
        if pid and psutil.pid_exists(pid):
            log.info(f"Watchdog already running (PID {pid})")
            return
    except Exception:
        pass
    proc = subprocess.Popen(
        [sys.executable, "-u", WATCHDOG_SCRIPT],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log.info(f"Watchdog started (PID {proc.pid})")


if __name__ == "__main__":
    pidfile.write_pid("bot", os.getpid())
    log.info(f"Bot PID {os.getpid()} written")
    try:
        os.remove(STOP_FLAG)
        log.info("Cleared stale stop flag")
    except FileNotFoundError:
        pass

    heartbeat.start()
    _start_watchdog_if_needed()
    mcp_manager.start()

    log.info("ClaudeBot starting...")
    try:
        resolve_whitelist_user_id(app.client)
    except Exception as e:
        log.error(f"Failed to resolve whitelist user at startup: {e}")
    notify_interrupted_requests()
    SocketModeHandler(app, APP_TOKEN).start()
