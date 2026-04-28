# claude-slack-relay

Control your local Claude Code via Slack. Send development tasks from your phone, watch the execution in real time, and receive results directly in Slack.

## Features

- Chat with your local Claude Code through Slack, including from mobile
- Live updates showing Claude's tool usage (file reads, command execution, etc.)
- Conversation context is maintained per channel, supporting multi-turn dialogue
- Send `!reset` to clear conversation history, kill all running subprocesses, and start fresh
- Only responds to the configured user — auto-detected from AD, or set manually in `.env`
- On startup, detects any interrupted tasks and notifies you to resend
- Watchdog process automatically restarts the bot if it crashes or stops responding
- MCP tools start on-demand per request and exit when done (no persistent background servers)
- Claude can take screenshots and send them directly to Slack via the `computer` MCP tool

## Prerequisites

- Windows (domain-joined recommended for auto email detection, but not required)
- Python 3.10+
- [Claude Code CLI](https://claude.ai/code) installed and authenticated (`claude` command must work in terminal)

## Setup

### 1. Clone the repository

```bat
git clone https://github.com/tianlei1/claude-slack-relay.git C:\work\claude-slack-relay
cd C:\work\claude-slack-relay
```

### 2. Install dependencies

```bat
pip install slack-bolt slack-sdk python-dotenv psutil requests
```

### 3. Get Slack Tokens

There are two ways to set up the Slack tokens depending on your situation.

---

#### Option A: Create your own Slack App (standalone setup)

Use this if you are setting up independently without a shared team app.

**3.1 Create the App**

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App**
2. Select **From scratch**
3. Enter an App Name (e.g. `ClaudeBot`), select your Workspace, and click **Create App**

**3.2 Configure Bot Permissions**

1. In the left sidebar, click **OAuth & Permissions**
2. Scroll to **Scopes** → **Bot Token Scopes**, click **Add an OAuth Scope**, and add:
   - `app_mentions:read` — receive @mention events
   - `bookmarks:read` — view bookmarks in channels
   - `bookmarks:write` — create and edit bookmarks
   - `calls:read` — view call information
   - `calls:write` — start and manage calls
   - `channels:history` — read messages in public channels
   - `channels:join` — join public channels
   - `channels:manage` — manage public channels
   - `channels:read` — list public channels and their info
   - `chat:write` — send and update messages
   - `chat:write.customize` — send messages with custom name/avatar
   - `chat:write.public` — post to channels without joining
   - `commands` — add slash commands
   - `dnd:read` — view do-not-disturb status
   - `emoji:read` — view custom emoji
   - `files:read` — download files and images
   - `files:write` — upload files and images
   - `groups:history` — read messages in private channels
   - `groups:read` — list private channels
   - `groups:write` — manage private channels
   - `im:history` — read direct messages
   - `im:read` — view DM info
   - `im:write` — open DMs
   - `links:read` — view URLs in messages
   - `links:write` — unfurl URLs in messages
   - `mpim:history` — read group DM history
   - `mpim:read` — view group DM info
   - `mpim:write` — send group DMs
   - `pins:read` — view pinned content
   - `pins:write` — pin and unpin messages
   - `reactions:read` — view emoji reactions
   - `reactions:write` — add and remove reactions
   - `reminders:read` — view reminders
   - `reminders:write` — create and manage reminders
   - `remote_files:read` — view remote files
   - `remote_files:share` — share remote files
   - `remote_files:write` — add and edit remote files
   - `stars:read` — view starred items
   - `stars:write` — add and remove stars
   - `team:read` — view workspace info
   - `usergroups:read` — view user groups
   - `usergroups:write` — manage user groups
   - `users.profile:read` — view user profile details
   - `users:read` — look up user information
   - `users:read.email` — look up users by email
   - `users:write` — update user presence

**3.3 Enable Socket Mode and generate App Token**

1. In the left sidebar, click **Socket Mode** and toggle **Enable Socket Mode** on
2. In the dialog, enter a Token Name (e.g. `socket-token`) and click **Generate**
3. Copy the **App Token** (`xapp-...`) and save it — it will not be shown again

**3.4 Subscribe to Events**

1. In the left sidebar, click **Event Subscriptions** and toggle **Enable Events** on
2. Expand **Subscribe to bot events**, click **Add Bot User Event**, and add:
   - `message.im` — receive direct messages
   - `app_mention` — receive @mentions in channels
3. Click **Save Changes**

**3.5 Install to Workspace and get Bot Token**

1. In the left sidebar, click **OAuth & Permissions**
2. Scroll to the top and click **Install to Workspace**, then click **Allow**
3. Copy the **Bot User OAuth Token** (`xoxb-...`)

---

#### Option B: Join a shared team app (recommended for teams)

Use this if your team already has a shared Slack App (e.g. ClaudeBot). You only need to generate your own App Token — the Bot Token is provided by the app owner.

**Why a separate App Token?** Each team member's bot must have its own dedicated Socket Mode connection so Slack routes your messages to your machine only. Sharing an App Token across multiple machines causes messages to be dropped.

1. Ask the app owner to open [api.slack.com/apps](https://api.slack.com/apps) → the shared App → **Basic Information** → **App-Level Tokens**
2. Click **Generate Token and Scopes**, enter your name as the Token Name, add the `connections:write` scope, and click **Generate**
3. Copy the **App Token** (`xapp-...`) — it will not be shown again
4. Get the **Bot Token** (`xoxb-...`) from the app owner

### 4. Configure environment variables

```bat
copy .env.example .env
```

Edit `.env` with your tokens:

```
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token

# Optional: set your Slack account email explicitly.
# Required on machines not joined to an AD domain, or if AD mail attribute is not populated.
ALLOWED_USER_EMAIL=your-email@example.com
```

### 5. Configure MCP tools (optional)

MCP tools are configured in `C:\work\.mcp.json`. All tools run in **stdio (per-request)** mode — they start when Claude needs them and exit automatically when the request is done. No persistent background servers are required.

Example configuration:

```json
{
  "mcpServers": {
    "jira": {
      "command": "mcp-atlassian",
      "args": [],
      "env": {
        "JIRA_URL": "https://your-jira.example.com",
        "JIRA_PERSONAL_TOKEN": "your-token"
      }
    }
  }
}
```

> **Note:** The MCP config file lives at `C:\work\.mcp.json` (one level above this repo), so it is shared across projects and not checked into version control.

## Usage

### Start

```bat
C:\work\claude-slack-relay\start.bat
```

`start.bat` first stops any running instance, then launches a **watchdog** process in the background. The watchdog starts the bot, monitors it every 10 seconds, and automatically restarts it if it crashes or stops responding (heartbeat timeout: 30 seconds). Logs are written to `claudeBot.log`; watchdog events are written to `watchdog.log`.

### Autostart on login (optional)

To have the bot start automatically when you log in to Windows:

```bat
C:\work\claude-slack-relay\autostart_install.bat
```

This registers a Windows Task Scheduler task that runs `start.bat` on every login. To remove it:

```bat
C:\work\claude-slack-relay\autostart_remove.bat
```

> **Note:** Run `autostart_install.bat` as Administrator if you encounter permission errors.

### Stop

```bat
python scripts\stop.py
```

Signals the watchdog not to restart, then terminates the bot and all its child processes.

### Check status

```bat
python scripts\status.py
```

Shows bot PID, memory, uptime, active tasks (with message label and claude subprocess info), MCP server status, and all Python child processes.

### Using in Slack

- Direct message ClaudeBot, or `@ClaudeBot` in a channel
- Claude will show `Processing...` and update it with live tool call progress
- The message is updated with the final result once complete
- Send `!reset` to clear conversation history and kill all running python subprocesses
- Ask Claude to take a screenshot — it will be saved to `screen/` and sent to you in Slack automatically

## Process architecture

```
start.bat
  └── watchdog.py          (monitors heartbeat, restarts on crash)
        └── slack_claude_bot.py   (bot main process, writes heartbeat every 10s)
              └── claude ...      (per-request Claude subprocess)
                    └── mcp servers  (started on-demand by Claude, exit when done)
```

## Files

| File | Description |
|---|---|
| `claudeBot.log` | Bot log (overwritten on each start) |
| `watchdog.log` | Watchdog restart/event log (append) |
| `claudeBot.pid` | PID of the watchdog process |
| `heartbeat.json` | Updated every 10s by the bot; watchdog uses this to detect hangs |
| `sessions.json` | Conversation session IDs per Slack channel |
| `in_progress.json` | Tasks in progress (used to notify on restart) |
| `screen/` | Screenshots taken by Claude via the `computer` MCP tool (not tracked in git) |
