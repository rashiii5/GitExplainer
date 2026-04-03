"""
Orchestrator - coordinates the full RepoExplainer pipeline.
Manages state per repository session.
"""

import os
import json
import hashlib
from typing import Dict, Any, Optional

from pipeline.preprocessor import preprocess_repository, detect_tech_stack
from pipeline.parser import chunk_repository
from pipeline.embedder import FAISSVectorStore
from pipeline.rag_engine import (
    generate_project_overview,
    answer_query,
    explain_module,
    analyze_dependencies,
)


CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def _repo_hash(url: str) -> str:
    return hashlib.md5(url.strip().lower().encode()).hexdigest()[:12]


class RepoSession:
    """Holds all state for an analyzed repository."""

    def __init__(self, url: str):
        self.url = url
        self.repo_id = _repo_hash(url)
        self.repo_meta: Dict = {}
        self.tech_stack: Dict = {}
        self.files: list = []
        self.chunks: list = []
        self.vector_store = FAISSVectorStore()
        self.overview: str = ""
        self.dep_analysis: Dict = {}
        self.status: str = "idle"
        self.error: str = ""
        self.progress: int = 0

    def cache_path(self) -> str:
        return os.path.join(CACHE_DIR, self.repo_id)

    def is_cached(self) -> bool:
        cp = self.cache_path()
        return (
            os.path.exists(os.path.join(cp, "index.faiss")) and
            os.path.exists(os.path.join(cp, "session.json"))
        )

    def save_cache(self):
        cp = self.cache_path()
        os.makedirs(cp, exist_ok=True)
        self.vector_store.save(cp)
        meta = {
            "url": self.url,
            "repo_meta": self.repo_meta,
            "tech_stack": self.tech_stack,
            "overview": self.overview,
            "dep_analysis": self.dep_analysis,
            "file_list": [f["path"] for f in self.files],
        }
        with open(os.path.join(cp, "session.json"), "w") as f:
            json.dump(meta, f)

    def load_cache(self) -> bool:
        cp = self.cache_path()
        json_path = os.path.join(cp, "session.json")
        if not os.path.exists(json_path):
            return False
        with open(json_path) as f:
            meta = json.load(f)
        self.repo_meta = meta.get("repo_meta", {})
        self.tech_stack = meta.get("tech_stack", {})
        self.overview = meta.get("overview", "")
        self.dep_analysis = meta.get("dep_analysis", {})
        return self.vector_store.load(cp)


# Global session store (in-memory, keyed by repo_id)
_sessions: Dict[str, RepoSession] = {}


def get_session(url: str) -> RepoSession:
    repo_id = _repo_hash(url)
    if repo_id not in _sessions:
        _sessions[repo_id] = RepoSession(url)
    return _sessions[repo_id]


def analyze_repository(url: str, mcp_client, progress_cb=None) -> RepoSession:
    """
    Full pipeline: fetch → preprocess → parse → embed → overview.
    Returns the session object.
    """
    session = get_session(url)

    def update(pct, msg):
        session.progress = pct
        session.status = msg
        if progress_cb:
            progress_cb(pct, msg)
        print(f"[{pct}%] {msg}")

    # Check cache
    if session.is_cached():
        update(100, "Loaded from cache")
        session.load_cache()
        return session

    try:
        session.status = "running"
        session.error = ""

        # Step 1: Fetch repo metadata
        update(5, "Fetching repository metadata...")
        session.repo_meta = mcp_client.fetch_repository(url) or {}
        if not session.repo_meta:
            raise ValueError("Could not fetch repository. Check the URL or GitHub token.")

        owner = session.repo_meta.get("owner", "")
        repo = session.repo_meta.get("repo", "")

        # Step 2: List files
        update(15, "Listing repository files...")
        all_files = mcp_client.list_files(url)
        if not all_files:
            raise ValueError("Repository appears empty or inaccessible.")

        # Step 3: Preprocess (fetch + clean content)
        update(25, f"Fetching and cleaning {len(all_files)} files...")
        session.files = preprocess_repository(all_files, mcp_client, owner, repo)
        if not session.files:
            raise ValueError("No processable source files found.")

        session.tech_stack = detect_tech_stack(session.files)
        update(45, f"Processed {len(session.files)} files. Detecting tech stack...")

        # Step 4: Parse + chunk
        update(55, "Parsing code structure (AST / regex)...")
        session.chunks = chunk_repository(session.files)
        if not session.chunks:
            raise ValueError("Could not extract any code chunks.")

        # Step 5: Embed + index
        update(65, f"Embedding {len(session.chunks)} chunks with CodeBERT...")
        session.vector_store.build(session.chunks)

        # Step 6: Dependency analysis
        update(80, "Analyzing dependencies...")
        session.dep_analysis = analyze_dependencies(session.files)

        # Step 7: Generate overview
        update(90, "Generating project overview with LLM...")
        session.overview = generate_project_overview(
            session.repo_meta, session.tech_stack, session.chunks
        )

        # Step 8: Cache
        update(98, "Saving to cache...")
        session.save_cache()

        update(100, "Done")
        session.status = "done"

    except Exception as e:
        session.status = "error"
        session.error = str(e)
        print(f"[Orchestrator Error] {e}")

    return session


def query_repository(url: str, query: str) -> Dict[str, Any]:
    session = get_session(url)
    if not session.vector_store.is_ready:
        return {"error": "Repository not yet indexed. Please analyze it first."}
    return answer_query(query, session.vector_store, session.repo_meta)


def explain_file(url: str, file_path: str) -> str:
    session = get_session(url)
    if not session.vector_store.is_ready:
        return "Repository not yet indexed."
    return explain_module(file_path, session.vector_store, session.repo_meta)
