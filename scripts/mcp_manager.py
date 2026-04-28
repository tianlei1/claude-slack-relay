import os
import json
import socket
import subprocess
import time

from logger import get_logger

log = get_logger(__name__)

RUNTIME_CONFIG_FILENAME = ".mcp.runtime.json"
BASE_PORT = 18000
READY_TIMEOUT = 15


class MCPServerManager:
    def __init__(self, mcp_config_path):
        self.mcp_config_path = mcp_config_path
        self._base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._pids_dir = os.path.join(self._base_dir, "pids")
        self._logs_dir = os.path.join(self._base_dir, "logs")
        self._runtime_config_path = os.path.join(
            os.path.dirname(mcp_config_path), RUNTIME_CONFIG_FILENAME
        )

    def start(self):
        os.makedirs(self._pids_dir, exist_ok=True)
        os.makedirs(self._logs_dir, exist_ok=True)

        if not os.path.exists(self.mcp_config_path):
            log.warning(f"MCP config not found: {self.mcp_config_path}")
            return

        try:
            with open(self.mcp_config_path, encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            log.error(f"Failed to read MCP config: {e}")
            return

        servers = config.get("mcpServers", {})
        log.info(f"MCP config loaded: {len(servers)} server(s): {', '.join(servers.keys())}")

        port = BASE_PORT
        runtime_config = {"mcpServers": {}}

        for name, server_config in servers.items():
            if not self._supports_sse(server_config):
                log.info(f"MCP server '{name}': stdio (per-request)")
                runtime_config["mcpServers"][name] = server_config
                continue
            cmd = self._build_cmd(server_config, port)
            env_cfg = server_config.get("env", {})
            env = {**os.environ, **env_cfg}
            if self._port_open(port):
                log.info(f"MCP server '{name}' already running on port {port}, reusing")
                existing_pid = self._read_pid(name)
                runtime_config["mcpServers"][name] = self._sse_entry(port, existing_pid, cmd, env_cfg)
            else:
                pid = self._start_sse(name, cmd, env, port)
                if pid:
                    runtime_config["mcpServers"][name] = self._sse_entry(port, pid, cmd, env_cfg)
                else:
                    log.warning(f"MCP server '{name}' failed SSE mode, falling back to stdio")
                    runtime_config["mcpServers"][name] = server_config
            port += 1

        try:
            with open(self._runtime_config_path, "w", encoding="utf-8") as f:
                json.dump(runtime_config, f, indent=2)
            log.info(f"MCP runtime config written: {self._runtime_config_path}")
        except Exception as e:
            log.error(f"Failed to write MCP runtime config: {e}")

    def _supports_sse(self, server_config):
        command = server_config.get("command", "")
        args = server_config.get("args", [])
        cmd_name = os.path.basename(command).lower()
        return cmd_name in ("python", "python3", "python.exe") and bool(args) and args[0].endswith(".py")

    def _build_cmd(self, server_config, port):
        command = server_config.get("command")
        args = server_config.get("args", [])
        return [command] + args + ["--transport", "sse", "--port", str(port), "--host", "127.0.0.1"]

    def _sse_entry(self, port, pid, cmd, env):
        return {
            "type": "sse",
            "url": f"http://localhost:{port}/sse",
            "pid": pid,
            "cmd": cmd,
            "env": env,
        }

    def _start_sse(self, name, cmd, env, port):
        log_path = os.path.join(self._logs_dir, f"mcp_{name}.log")
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
            log.info(f"MCP server '{name}' starting on port {port} (PID {proc.pid})...")
            if self._wait_for_port(port):
                log.info(f"MCP server '{name}' ready on port {port} (PID {proc.pid})")
                self._write_pid(name, proc.pid)
                return proc.pid
            else:
                log.error(f"MCP server '{name}' did not become ready within {READY_TIMEOUT}s")
                try:
                    proc.kill()
                except Exception:
                    pass
                return None
        except Exception as e:
            log.error(f"MCP server '{name}': failed to start: {e}")
            return None

    def _port_open(self, port):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            return False

    def _wait_for_port(self, port):
        deadline = time.time() + READY_TIMEOUT
        while time.time() < deadline:
            if self._port_open(port):
                return True
            time.sleep(0.5)
        return False

    def _pid_file(self, name):
        return os.path.join(self._pids_dir, f"mcp_{name}.pid")

    def _write_pid(self, name, pid):
        try:
            with open(self._pid_file(name), "w") as f:
                f.write(str(pid))
        except Exception as e:
            log.warning(f"Failed to write PID file for MCP '{name}': {e}")

    def _read_pid(self, name):
        try:
            return int(open(self._pid_file(name)).read().strip())
        except Exception:
            return None

    def get_mcp_args(self):
        if os.path.exists(self._runtime_config_path):
            return ["--mcp-config", self._runtime_config_path, "--strict-mcp-config"]
        return []
