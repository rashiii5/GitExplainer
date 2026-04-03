"""
MCP Client - bridges Flask app to MCP server tools
Provides a synchronous wrapper around async MCP calls.
"""

import asyncio
import json
import subprocess
import sys
import os
from typing import Any, Optional


class MCPClient:
    """
    Lightweight MCP client that spawns the MCP server as a subprocess
    and communicates over stdio using the MCP JSON-RPC protocol.
    """

    def __init__(self, server_script: str):
        self.server_script = server_script
        self._tools_cache = None

    def _run(self, coro):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)

    async def _call_async(self, tool_name: str, arguments: dict) -> Any:
        """Send a tool call to the MCP server via subprocess stdio."""
        proc = await asyncio.create_subprocess_exec(
            sys.executable, self.server_script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ},
        )

        # MCP JSON-RPC: initialize
        init_msg = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "repo-explainer", "version": "1.0"},
            },
        }
        # tool call message
        call_msg = {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        messages = (
            json.dumps(init_msg) + "\n" +
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}) + "\n" +
            json.dumps(call_msg) + "\n"
        )

        stdout, stderr = await proc.communicate(messages.encode())
        lines = [l.strip() for l in stdout.decode().splitlines() if l.strip()]

        result = None
        for line in lines:
            try:
                obj = json.loads(line)
                if obj.get("id") == 2 and "result" in obj:
                    content = obj["result"].get("content", [])
                    if content:
                        result = content[0].get("text", "")
                    break
            except json.JSONDecodeError:
                continue

        return result

    def call_tool(self, tool_name: str, arguments: dict) -> Any:
        result = self._run(self._call_async(tool_name, arguments))
        if result:
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                return result
        return None

    def fetch_repository(self, url: str) -> dict:
        return self.call_tool("fetch_repository", {"url": url})

    def list_files(self, url: str, extension_filter: Optional[list] = None) -> list:
        args = {"url": url}
        if extension_filter:
            args["extension_filter"] = extension_filter
        return self.call_tool("list_files", args) or []

    def read_file(self, owner: str, repo: str, file_path: str) -> str:
        return self.call_tool("read_file", {"owner": owner, "repo": repo, "file_path": file_path}) or ""
