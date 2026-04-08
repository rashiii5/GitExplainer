"""
Pipeline Step 4: RAG Query Engine
Retrieves relevant code chunks and generates explanations via LLM.
"""

import os
import json
import re
from typing import List, Dict, Any, Optional

# Use Groq (fast) or fallback to any OpenAI-compatible endpoint
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"


def _call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 1024) -> str:
    """Call Groq LLM API."""
    import requests

    if not GROQ_API_KEY:
        return "[Error: GROQ_API_KEY not set. Please add it to your .env file.]"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[LLM Error: {e}]"


# ─── Project Overview ─────────────────────────────────────────────────────────

def generate_project_overview(
    repo_meta: Dict,
    tech_stack: Dict,
    chunks: List[Dict],
) -> str:
    """Generate a high-level project summary."""
    # Pick a representative sample of chunks
    sample = chunks[:12]
    sample_text = "\n\n---\n\n".join(c["raw_code"][:400] for c in sample)

    system = (
        "You are an expert software engineer and technical writer. "
        "Analyze the repository information and generate a clear, concise overview."
    )
    user = f"""Repository: {repo_meta.get('name', 'Unknown')}
Description: {repo_meta.get('description', 'N/A')}
Languages: {json.dumps(tech_stack.get('languages', {}))}
Frameworks: {', '.join(tech_stack.get('frameworks', [])) or 'None detected'}
Total files: {tech_stack.get('total_files', 0)}

Sample code from the repository:
{sample_text}

Generate a structured overview with:
1. **What this project does** (2-3 sentences)
2. **Key features** (bullet points)
3. **Tech stack summary**
4. **Who would use this** (target users)
5. **Architecture summary** (how components fit together)

Be specific and grounded in the actual code shown."""

    return _call_llm(system, user, max_tokens=800)


# ─── RAG Query ────────────────────────────────────────────────────────────────

def answer_query(
    query: str,
    vector_store,
    repo_meta: Dict,
    top_k: int = 8,
) -> Dict[str, Any]:
    """
    Main RAG pipeline:
    1. Embed query
    2. Retrieve top-k chunks
    3. Generate grounded answer
    """
    retrieved = vector_store.query(query, top_k=top_k)

    if not retrieved:
        return {
            "answer": "No relevant code found for this query.",
            "sources": [],
        }

    # Build context from retrieved chunks
    context_parts = []
    for i, chunk in enumerate(retrieved):
        context_parts.append(
            f"[Source {i+1}: {chunk['file_path']} | {chunk['chunk_name']} "
            f"(lines {chunk['start_line']}-{chunk['end_line']})]\n"
            f"{chunk['raw_code'][:600]}"
        )
    context = "\n\n---\n\n".join(context_parts)

    system = (
        "You are a sharp, expert code analyst. Answer questions about a software repository "
        "based ONLY on the provided code context. "
        "Be extremely concise — 3 to 5 sentences max. No filler, no preamble. "
        "Lead with the direct answer. Use inline code names (file/function) only when essential. "
        "If context is insufficient, say so in one sentence."
    )
    user = f"""Repository: {repo_meta.get('name', 'Unknown')}

Question: {query}

Code context:
{context}

Answer in 3-5 sentences max. Be direct and specific."""

    answer = _call_llm(system, user, max_tokens=1024)

    sources = [
        {
            "file": c["file_path"],
            "name": c["chunk_name"],
            "type": c["node_type"],
            "lines": f"{c['start_line']}-{c['end_line']}",
            "score": round(c["score"], 3),
        }
        for c in retrieved[:5]
    ]

    return {"answer": answer, "sources": sources}


# ─── Module Explanation ───────────────────────────────────────────────────────

def explain_module(
    file_path: str,
    vector_store,
    repo_meta: Dict,
) -> str:
    """Explain a specific file/module."""
    # Get all chunks for this file
    file_chunks = [
        m for m in vector_store.metadata
        if m["file_path"] == file_path
    ]
    if not file_chunks:
        return f"No parsed chunks found for `{file_path}`."

    code_sample = "\n\n".join(c["raw_code"][:400] for c in file_chunks[:8])

    system = (
        "You are a sharp senior engineer. Given a source file, write a crisp summary "
        "in exactly 3-4 sentences. Cover: what the file does, its key functions/classes, "
        "and how it fits into the project. No bullet points, no headers, no filler. Plain prose only."
    )
    user = f"""File: {file_path}
Repository: {repo_meta.get('name')}

Code:
{code_sample}

Write a 3-4 sentence plain prose summary of this file."""

    return _call_llm(system, user, max_tokens=700)


# ─── Dependency Analysis ──────────────────────────────────────────────────────

def analyze_dependencies(files: List[Dict]) -> Dict[str, Any]:
    """Extract imports and build a dependency map."""
    dep_map = {}
    import_pattern = re.compile(
        r"^(?:import|from)\s+([\w.]+)|"
        r"^(?:const|let|var|import)\s+.*?(?:require\(['\"]|from\s+['\"])([\w./\-@]+)",
        re.MULTILINE,
    )

    for f in files:
        if f.get("type") != "source":
            continue
        path = f["path"]
        content = f.get("content", "")
        imports = set()
        for m in import_pattern.finditer(content):
            mod = m.group(1) or m.group(2)
            if mod:
                top = mod.split(".")[0].split("/")[0]
                if top and not top.startswith("."):
                    imports.add(top)
        if imports:
            dep_map[path] = sorted(imports)

    # Count most common dependencies
    freq = {}
    for deps in dep_map.values():
        for d in deps:
            freq[d] = freq.get(d, 0) + 1

    top_deps = sorted(freq.items(), key=lambda x: -x[1])[:20]

    return {
        "file_dependencies": dep_map,
        "top_dependencies": [{"name": k, "count": v} for k, v in top_deps],
    }
