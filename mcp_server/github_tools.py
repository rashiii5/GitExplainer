"""
MCP Server - GitHub Repository Tools
Exposes: fetch_repository, list_files, read_file
"""

import os
import base64
import requests
from typing import Optional
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import json

app = Server("github-repo-tools")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}" if GITHUB_TOKEN else "",
    "Accept": "application/vnd.github.v3+json",
}


def parse_github_url(url: str) -> tuple[str, str]:
    """Extract owner and repo from GitHub URL."""
    url = url.rstrip("/").replace("https://github.com/", "")
    parts = url.split("/")
    return parts[0], parts[1]


def fetch_tree(owner: str, repo: str, branch: str = "main") -> list:
    """Fetch full file tree from GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    r = requests.get(url, headers=HEADERS)
    if r.status_code == 404:
        # Try master branch
        url = url.replace(f"/{branch}?", "/master?")
        r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json().get("tree", [])


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="fetch_repository",
            description="Fetch metadata and file tree of a GitHub repository",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "GitHub repository URL"},
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="list_files",
            description="List all files in a GitHub repository with their paths and types",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "extension_filter": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by extensions e.g. ['.py', '.js']",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="read_file",
            description="Read the content of a specific file from a GitHub repository",
            inputSchema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "file_path": {"type": "string", "description": "Path within repo"},
                },
                "required": ["owner", "repo", "file_path"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "fetch_repository":
        url = arguments["url"]
        owner, repo = parse_github_url(url)
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        r = requests.get(api_url, headers=HEADERS)
        r.raise_for_status()
        data = r.json()
        result = {
            "name": data.get("name"),
            "description": data.get("description"),
            "language": data.get("language"),
            "stars": data.get("stargazers_count"),
            "forks": data.get("forks_count"),
            "default_branch": data.get("default_branch"),
            "owner": owner,
            "repo": repo,
        }
        tree = fetch_tree(owner, repo, data.get("default_branch", "main"))
        result["total_files"] = len([f for f in tree if f["type"] == "blob"])
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "list_files":
        url = arguments["url"]
        owner, repo = parse_github_url(url)
        ext_filter = arguments.get("extension_filter", [])
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        r = requests.get(api_url, headers=HEADERS)
        branch = r.json().get("default_branch", "main")
        tree = fetch_tree(owner, repo, branch)
        files = [
            {"path": f["path"], "size": f.get("size", 0), "sha": f["sha"]}
            for f in tree
            if f["type"] == "blob"
            and (not ext_filter or any(f["path"].endswith(e) for e in ext_filter))
        ]
        return [TextContent(type="text", text=json.dumps(files, indent=2))]

    elif name == "read_file":
        owner = arguments["owner"]
        repo = arguments["repo"]
        file_path = arguments["file_path"]
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"
        r = requests.get(url, headers=HEADERS)
        r.raise_for_status()
        data = r.json()
        if data.get("encoding") == "base64":
            content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        else:
            content = data.get("content", "")
        return [TextContent(type="text", text=content)]

    return [TextContent(type="text", text="Unknown tool")]


async def main():
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
