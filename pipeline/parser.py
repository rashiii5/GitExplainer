"""
Pipeline Step 2: AST Parsing + Chunking
Uses tree-sitter for Python/JS/TS; falls back to regex for other languages.
Each chunk = function / class / module segment.
"""

import re
from typing import List, Dict, Any

MAX_CHUNK_TOKENS = 400  # approx tokens per chunk
MIN_CHUNK_CHARS = 80


# ─── Tree-sitter AST Parser ───────────────────────────────────────────────────

def _try_treesitter_parse(content: str, language_name: str) -> List[Dict]:
    """Attempt tree-sitter parse; returns [] if unavailable."""
    try:
        import tree_sitter_python as tspython
        import tree_sitter_javascript as tsjavascript
        from tree_sitter import Language, Parser

        lang_map = {
            "python": (tspython, "python"),
            "javascript": (tsjavascript, "javascript"),
        }
        if language_name not in lang_map:
            return []

        mod, _ = lang_map[language_name]
        lang = Language(mod.language())
        parser = Parser(lang)
        tree = parser.parse(content.encode())

        chunks = []
        _walk_tree(tree.root_node, content, chunks)
        return chunks
    except Exception:
        return []


def _walk_tree(node, source: str, chunks: list, depth: int = 0):
    """Walk AST and extract function/class definitions."""
    target_types = {
        "function_definition", "async_function_definition",
        "class_definition", "function_declaration",
        "method_definition", "arrow_function",
    }
    if node.type in target_types:
        code = source[node.start_byte:node.end_byte]
        name = _extract_name(node, source)
        chunks.append({
            "code": code,
            "name": name,
            "node_type": node.type,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
        })
    else:
        for child in node.children:
            _walk_tree(child, source, chunks, depth + 1)


def _extract_name(node, source: str) -> str:
    for child in node.children:
        if child.type in ("identifier", "name"):
            return source[child.start_byte:child.end_byte]
    return "anonymous"


# ─── Regex-based fallback parser ─────────────────────────────────────────────

PATTERNS = {
    "python": [
        (r"((?:^[ \t]*(?:@\w+[^\n]*\n))*^[ \t]*(?:async\s+)?def\s+\w+.*?(?=\n(?:def|class|@|\Z)))", "function"),
        (r"(^class\s+\w+.*?(?=\nclass\s|\Z))", "class"),
    ],
    "javascript": [
        (r"((?:export\s+)?(?:async\s+)?function\s+\w+\s*\([^)]*\)\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})", "function"),
        (r"((?:export\s+)?class\s+\w+[^{]*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})", "class"),
        (r"((?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?\([^)]*\)\s*=>[^;]+;)", "arrow_fn"),
    ],
    "generic": [
        (r"((?:^[ \t]*(?:public|private|protected|static|async|def|func|fn|sub|function)\s+\w+[^\n]*\n(?:(?!(?:public|private|protected|static|def|func|fn|sub|function|class|end\b)).+\n?)*)+)", "function"),
    ],
}


def _regex_parse(content: str, lang: str) -> List[Dict]:
    patterns = PATTERNS.get(lang, PATTERNS["generic"])
    chunks = []
    seen = set()
    for pattern, node_type in patterns:
        for m in re.finditer(pattern, content, re.MULTILINE | re.DOTALL):
            code = m.group(1).strip()
            if len(code) < MIN_CHUNK_CHARS or code in seen:
                continue
            seen.add(code)
            start_line = content[:m.start()].count("\n") + 1
            name_match = re.search(r"(?:def|function|class|fn|func)\s+(\w+)", code)
            chunks.append({
                "code": code,
                "name": name_match.group(1) if name_match else "block",
                "node_type": node_type,
                "start_line": start_line,
                "end_line": start_line + code.count("\n"),
            })
    return chunks


# ─── Sliding window chunker (fallback for files with no clear structure) ──────

def _sliding_window_chunks(content: str, window_lines: int = 40, overlap: int = 10) -> List[Dict]:
    lines = content.splitlines()
    chunks = []
    step = window_lines - overlap
    for i in range(0, len(lines), step):
        block = "\n".join(lines[i : i + window_lines])
        if len(block.strip()) < MIN_CHUNK_CHARS:
            continue
        chunks.append({
            "code": block,
            "name": f"segment_{i // step}",
            "node_type": "segment",
            "start_line": i + 1,
            "end_line": min(i + window_lines, len(lines)),
        })
    return chunks


# ─── Main parse + chunk entry point ──────────────────────────────────────────

EXT_TO_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "javascript",
    ".tsx": "javascript",
    ".java": "generic",
    ".cpp": "generic",
    ".c": "generic",
    ".go": "generic",
    ".rs": "generic",
    ".rb": "generic",
    ".php": "generic",
    ".cs": "generic",
}


def parse_and_chunk(file: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse a file and return chunks, each with metadata.
    """
    path = file["path"]
    content = file["content"]
    ext = file.get("extension", "")
    lang = EXT_TO_LANG.get(ext, None)

    raw_chunks = []

    # 1. Try tree-sitter
    if lang in ("python", "javascript"):
        raw_chunks = _try_treesitter_parse(content, lang)

    # 2. Regex fallback
    if not raw_chunks and lang:
        raw_chunks = _regex_parse(content, lang)

    # 3. Config / markdown files → treat as single chunk
    if not raw_chunks and file.get("type") == "config":
        if len(content.strip()) > MIN_CHUNK_CHARS:
            raw_chunks = [{
                "code": content[:3000],  # cap config content
                "name": file["filename"],
                "node_type": "config",
                "start_line": 1,
                "end_line": content.count("\n") + 1,
            }]

    # 4. Sliding window as last resort
    if not raw_chunks:
        raw_chunks = _sliding_window_chunks(content)

    # Attach file metadata to each chunk
    result = []
    for i, chunk in enumerate(raw_chunks):
        code = chunk["code"]
        # Cap very large chunks
        if len(code) > MAX_CHUNK_TOKENS * 6:
            code = code[: MAX_CHUNK_TOKENS * 6]

        chunk_text = (
            f"File: {path}\n"
            f"Type: {chunk['node_type']} | Name: {chunk['name']} "
            f"(lines {chunk['start_line']}-{chunk['end_line']})\n\n"
            f"{code}"
        )

        result.append({
            "chunk_id": f"{path}::{chunk['name']}::{i}",
            "file_path": path,
            "chunk_name": chunk["name"],
            "node_type": chunk["node_type"],
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "text": chunk_text,
            "raw_code": code,
            "language": lang or "unknown",
        })

    return result


def chunk_repository(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Process all files and return all chunks."""
    all_chunks = []
    for f in files:
        try:
            chunks = parse_and_chunk(f)
            all_chunks.extend(chunks)
        except Exception:
            continue
    return all_chunks
