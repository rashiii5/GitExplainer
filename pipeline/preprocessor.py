"""
Pipeline Step 1: Preprocessing
Cleans and filters repository files, removing noise.
"""

import os
import re
from typing import List, Dict, Any

# Files/dirs to skip
SKIP_DIRS = {
    ".git", ".github", "__pycache__", "node_modules", ".venv", "venv",
    "env", "dist", "build", ".next", ".nuxt", "coverage", ".pytest_cache",
    ".mypy_cache", ".tox", "eggs", ".eggs", "*.egg-info",
}

SKIP_EXTENSIONS = {
    # Binaries
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp",
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z",
    # Compiled
    ".pyc", ".pyo", ".class", ".o", ".so", ".dll", ".exe", ".whl",
    # Locks & generated
    ".lock", ".sum",
    # Media
    ".mp4", ".mp3", ".wav", ".mov", ".avi",
    # Fonts
    ".ttf", ".woff", ".woff2", ".eot",
}

PRIORITY_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cpp", ".c", ".h",
    ".go", ".rs", ".rb", ".php", ".cs", ".scala", ".kt", ".swift",
    ".r", ".m", ".sh", ".bash",
}

CONFIG_EXTENSIONS = {
    ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".env.example",
    ".dockerfile", "dockerfile", ".md", ".txt", ".rst",
}

MAX_FILE_SIZE = 200_000  # 200KB max per file


def should_skip(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    for part in parts:
        if part in SKIP_DIRS or part.startswith("."):
            return True
    _, ext = os.path.splitext(path.lower())
    return ext in SKIP_EXTENSIONS


def classify_file(path: str) -> str:
    _, ext = os.path.splitext(path.lower())
    name = os.path.basename(path).lower()
    if ext in PRIORITY_EXTENSIONS:
        return "source"
    if ext in CONFIG_EXTENSIONS or name in {"makefile", "dockerfile", "procfile"}:
        return "config"
    return "other"


def clean_content(content: str, file_path: str) -> str:
    """Remove excessive blank lines and normalize whitespace."""
    lines = content.splitlines()
    cleaned = []
    blank_count = 0
    for line in lines:
        stripped = line.rstrip()
        if not stripped:
            blank_count += 1
            if blank_count <= 2:
                cleaned.append("")
        else:
            blank_count = 0
            cleaned.append(stripped)
    return "\n".join(cleaned)


def preprocess_repository(
    files: List[Dict[str, Any]],
    mcp_client,
    owner: str,
    repo: str,
    max_files: int = 150,
) -> List[Dict[str, Any]]:
    """
    Filter, prioritize, fetch, and clean repository files.
    Returns a list of cleaned file dicts ready for parsing.
    """
    # Filter out noise
    filtered = [f for f in files if not should_skip(f["path"])]

    # Sort: source files first, then configs
    def priority(f):
        cls = classify_file(f["path"])
        if cls == "source":
            return 0
        if cls == "config":
            return 1
        return 2

    filtered.sort(key=priority)

    # Cap file count
    filtered = filtered[:max_files]

    cleaned_files = []
    for f in filtered:
        size = f.get("size", 0)
        if size > MAX_FILE_SIZE:
            continue

        try:
            content = mcp_client.read_file(owner, repo, f["path"])
            if not content or not isinstance(content, str):
                continue
            content = clean_content(content, f["path"])
            if not content.strip():
                continue

            cleaned_files.append({
                "path": f["path"],
                "content": content,
                "size": len(content),
                "type": classify_file(f["path"]),
                "extension": os.path.splitext(f["path"])[1].lower(),
                "filename": os.path.basename(f["path"]),
            })
        except Exception:
            continue

    return cleaned_files


def detect_tech_stack(files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Detect languages, frameworks, and tools from files."""
    extensions = {}
    frameworks = set()
    tools = set()

    config_contents = {}
    for f in files:
        ext = f.get("extension", "")
        if ext:
            extensions[ext] = extensions.get(ext, 0) + 1
        fname = f["filename"].lower()
        content = f.get("content", "")

        # Store config contents for analysis
        if fname in {"package.json", "requirements.txt", "pyproject.toml",
                     "pom.xml", "build.gradle", "go.mod", "cargo.toml"}:
            config_contents[fname] = content

    # Detect frameworks from package.json
    if "package.json" in config_contents:
        pkg = config_contents["package.json"]
        if "react" in pkg:
            frameworks.add("React")
        if "vue" in pkg:
            frameworks.add("Vue.js")
        if "next" in pkg:
            frameworks.add("Next.js")
        if "express" in pkg:
            frameworks.add("Express.js")
        if "typescript" in pkg:
            frameworks.add("TypeScript")

    # Detect from requirements.txt
    if "requirements.txt" in config_contents:
        req = config_contents["requirements.txt"].lower()
        if "flask" in req:
            frameworks.add("Flask")
        if "django" in req:
            frameworks.add("Django")
        if "fastapi" in req:
            frameworks.add("FastAPI")
        if "torch" in req or "pytorch" in req:
            frameworks.add("PyTorch")
        if "tensorflow" in req:
            frameworks.add("TensorFlow")
        if "streamlit" in req:
            frameworks.add("Streamlit")

    # Primary language
    lang_map = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".java": "Java", ".go": "Go", ".rs": "Rust", ".rb": "Ruby",
        ".cpp": "C++", ".c": "C", ".cs": "C#", ".kt": "Kotlin",
    }
    languages = {
        lang_map[ext]: count
        for ext, count in extensions.items()
        if ext in lang_map
    }

    return {
        "languages": languages,
        "frameworks": list(frameworks),
        "file_types": extensions,
        "total_files": len(files),
    }
