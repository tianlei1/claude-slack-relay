import os
import subprocess
import json
import platform
import time
os.environ["PYTHONUTF8"] = "1"

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from logger import get_logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))
log = get_logger(__name__)

BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
app = App(token=BOT_TOKEN)

SESSIONS_FILE = os.path.join(BASE_DIR, "sessions.json")
IN_PROGRESS_FILE = os.path.join(BASE_DIR, "in_progress.json")
processed_events = set()


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


def mark_processing_start(channel, ts, pid=None):
    data = load_in_progress()
    entry = {"channel": channel, "ts": ts}
    if pid is not None:
        entry["pid"] = pid
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
    mcp_config = os.path.join(WORK_DIR, ".mcp.json")
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
        f"2. Never use 'rm -rf', 'rmdir /s', or any recursive delete on directories without explicit user confirmation."
    )


def ask_claude_and_update_reply(channel, text, client, status_ts):
    session_id = channel_sessions.get(channel)
    if session_id:
        cmd = ["claude", "--resume", session_id, "-p", text,
               "--output-format", "stream-json", "--verbose"]
        log.info(f"Resuming session {session_id} for channel {channel}")
    else:
        prompt = f"{build_system_context()}\n\n---\n\n{text}"
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"]
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

    had_output = True
    mark_processing_start(channel, status_ts)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            cwd=WORK_DIR
        )
        mark_processing_start(channel, status_ts, proc.pid)
        log.info(f"Claude subprocess started: PID {proc.pid}")

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
    except Exception:
        pass
    return None


ALLOWED_USER_EMAIL = lookup_ad_email()
log.info(f"Whitelist email: {ALLOWED_USER_EMAIL}")
_whitelist_user_id = None


def resolve_whitelist_user_id(client):
    global _whitelist_user_id
    if _whitelist_user_id:
        return _whitelist_user_id
    result = client.users_lookupByEmail(email=ALLOWED_USER_EMAIL)
    _whitelist_user_id = result["user"]["id"]
    return _whitelist_user_id


def is_allowed_user(client, user_id):
    try:
        return user_id == resolve_whitelist_user_id(client)
    except Exception as e:
        log.error(f"Failed to resolve whitelist user: {e}")
        return False


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
    if not text:
        log.warning(f"Received empty message from user {user_id}, ignored")
        return
    log.info(f"Received: {text[:80]}")

    if text.lower() == "!reset":
        channel = event.get("channel")
        self_pid = os.getpid()
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
                        if pid != self_pid:
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
        msg = "Conversation history cleared."
        if killed:
            msg += f" Killed {len(killed)} python process(es): PID {', '.join(str(p) for p in killed)}."
        if failed:
            msg += f" Failed to kill PID(s): {', '.join(str(p) for p in failed)}."
        log.info(f"Reset: session cleared, killed={killed}, failed={failed}")
        say(msg)
        return

    resp = say("Processing... Please wait, this may take a moment.")
    status_ts = resp.get("ts")
    result = ask_claude_and_update_reply(event.get("channel"), text, client, status_ts)
    try:
        client.chat_update(channel=event.get("channel"), ts=status_ts, text=result)
        log.info(f"Replied: {result[:80]}")
    except Exception as e:
        log.error(f"chat_update failed: {e}")
        say(result)


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


if __name__ == "__main__":
    log.info("ClaudeBot starting...")
    notify_interrupted_requests()
    SocketModeHandler(app, APP_TOKEN).start()
