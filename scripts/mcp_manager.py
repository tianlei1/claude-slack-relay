import os
import json
import socket
import subprocess
import threading
import time

from logger import get_logger

log = get_logger(__name__)

RUNTIME_CONFIG_FILENAME = ".mcp.runtime.json"
BASE_PORT = 18000
READY_TIMEOUT = 15


class MCPServerManager:
    def __init__(self, mcp_config_path):
        self.mcp_config_path = mcp_config_path
        self._servers = {}  # name -> {proc, port, config}
        self._runtime_config_path = None
        self._lock = threading.Lock()
        self._watcher_thread = None

    def start(self):
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
            if self._supports_sse(name, server_config):
                proc = self._start_sse(name, server_config, port)
                if proc:
                    with self._lock:
                        self._servers[name] = {
                            "proc": proc,
                            "port": port,
                            "config": server_config
                        }
                    runtime_config["mcpServers"][name] = {
                        "type": "sse",
                        "url": f"http://localhost:{port}/sse"
                    }
                    port += 1
                else:
                    log.warning(f"MCP server '{name}' failed to start in SSE mode, falling back to stdio")
                    runtime_config["mcpServers"][name] = server_config
            else:
                log.info(f"MCP server '{name}': stdio mode (per-request)")
                runtime_config["mcpServers"][name] = server_config

        runtime_path = os.path.join(
            os.path.dirname(self.mcp_config_path), RUNTIME_CONFIG_FILENAME
        )
        try:
            with open(runtime_path, "w", encoding="utf-8") as f:
                json.dump(runtime_config, f, indent=2)
            self._runtime_config_path = runtime_path
            log.info(f"MCP runtime config written: {runtime_path}")
        except Exception as e:
            log.error(f"Failed to write MCP runtime config: {e}")

        if self._servers:
            self._watcher_thread = threading.Thread(
                target=self._watch_servers, daemon=True
            )
            self._watcher_thread.start()

    def _supports_sse(self, name, server_config):
        command = server_config.get("command", "")
        if command == "npx":
            return False
        try:
            result = subprocess.run(
                [command, "--help"],
                capture_output=True, text=True, timeout=10
            )
            output = result.stdout + result.stderr
            return "--transport" in output and "sse" in output.lower()
        except Exception as e:
            log.warning(f"MCP server '{name}': could not check SSE support: {e}")
            return False

    def _start_sse(self, name, server_config, port):
        command = server_config.get("command")
        args = server_config.get("args", [])
        env = {**os.environ, **server_config.get("env", {})}
        cmd = [command] + args + [
            "--transport", "sse",
            "--port", str(port),
            "--host", "127.0.0.1"
        ]
        try:
            proc = subprocess.Popen(
                cmd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL
            )
            log.info(f"MCP server '{name}' starting on port {port} (PID {proc.pid})...")
            if self._wait_for_port(port):
                log.info(f"MCP server '{name}' ready on port {port}")
                return proc
            else:
                stderr = proc.stderr.read(500) if proc.stderr else b""
                log.error(
                    f"MCP server '{name}' did not become ready within {READY_TIMEOUT}s"
                    + (f": {stderr.decode(errors='replace')}" if stderr else "")
                )
                proc.kill()
                return None
        except Exception as e:
            log.error(f"MCP server '{name}': failed to start: {e}")
            return None

    def _wait_for_port(self, port):
        deadline = time.time() + READY_TIMEOUT
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return True
            except OSError:
                time.sleep(0.5)
        return False

    def _watch_servers(self):
        while True:
            time.sleep(10)
            with self._lock:
                for name, info in list(self._servers.items()):
                    if info["proc"].poll() is not None:
                        log.warning(
                            f"MCP server '{name}' (PID {info['proc'].pid}) exited unexpectedly, restarting..."
                        )
                        proc = self._start_sse(name, info["config"], info["port"])
                        if proc:
                            info["proc"] = proc
                            log.info(f"MCP server '{name}' restarted on port {info['port']}")
                        else:
                            log.error(f"MCP server '{name}' failed to restart")

    def get_mcp_args(self):
        if self._runtime_config_path and os.path.exists(self._runtime_config_path):
            return ["--mcp-config", self._runtime_config_path, "--strict-mcp-config"]
        return []

    def status(self):
        result = {}
        with self._lock:
            for name, info in self._servers.items():
                running = info["proc"].poll() is None
                result[name] = {
                    "running": running,
                    "port": info["port"],
                    "pid": info["proc"].pid
                }
        return result

    def stop(self):
        with self._lock:
            for name, info in self._servers.items():
                try:
                    info["proc"].terminate()
                    log.info(f"MCP server '{name}' stopped")
                except Exception as e:
                    log.warning(f"Failed to stop MCP server '{name}': {e}")
            self._servers.clear()
