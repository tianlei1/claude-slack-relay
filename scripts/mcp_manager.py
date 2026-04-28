import os
import json

from logger import get_logger

log = get_logger(__name__)

RUNTIME_CONFIG_FILENAME = ".mcp.runtime.json"


class MCPServerManager:
    def __init__(self, mcp_config_path):
        self.mcp_config_path = mcp_config_path
        self._runtime_config_path = None

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
        for name in servers:
            log.info(f"MCP server '{name}': stdio mode (per-request)")

        # Write runtime config identical to source (all stdio, no persistent servers)
        runtime_path = os.path.join(
            os.path.dirname(self.mcp_config_path), RUNTIME_CONFIG_FILENAME
        )
        try:
            with open(runtime_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            self._runtime_config_path = runtime_path
            log.info(f"MCP runtime config written: {runtime_path}")
        except Exception as e:
            log.error(f"Failed to write MCP runtime config: {e}")

    def get_mcp_args(self):
        if self._runtime_config_path and os.path.exists(self._runtime_config_path):
            return ["--mcp-config", self._runtime_config_path, "--strict-mcp-config"]
        return []

    def stop(self):
        pass  # nothing persistent to stop
