# RepoExplainer — AI-Powered GitHub Repository Explainer

> Drop a GitHub link. Get architecture breakdowns, code explanations, dependency analysis, and an interactive Q&A — all powered by CodeBERT + FAISS + RAG + MCP.

---

## Architecture

```
GitHub URL
    │
    ▼
┌─────────────────────────────────────────────────────┐
│                   MCP Server                         │
│  fetch_repository() → list_files() → read_file()   │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│               Preprocessing Pipeline                 │
│  Filter noise → Fetch content → Detect tech stack  │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              AST Parser + Chunker                    │
│  Tree-sitter (Python/JS) → Regex fallback           │
│  → Functions / Classes / Segments                   │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│         CodeBERT Embeddings + FAISS Index            │
│  microsoft/codebert-base → 768-dim vectors          │
│  IndexFlatIP (cosine similarity)                    │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              RAG Query Engine (Groq)                 │
│  Query → embed → retrieve top-k → LLM explain      │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              Flask Frontend                          │
│  Dark UI · Project overview · Q&A chat              │
│  File explorer · Dependency graph · Tech stack      │
└─────────────────────────────────────────────────────┘
```

## Setup

### 1. Clone / navigate to the project
```bash
cd repo-explainer
```

### 2. Create virtual environment
```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env — add GROQ_API_KEY and optionally GITHUB_TOKEN
```

### 4. Run
```bash
chmod +x run.sh
./run.sh
```

Then open **http://localhost:5000**

---

## API Keys

| Key | Where to get | Required? |
|-----|-------------|-----------|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) | **Yes** |
| `GITHUB_TOKEN` | [github.com/settings/tokens](https://github.com/settings/tokens) | No (but raises rate limit 60→5000/hr) |

---

## Project Structure

```
repo-explainer/
├── app.py                    # Flask application + API routes
├── orchestrator.py           # Full pipeline coordinator + session cache
├── requirements.txt
├── run.sh
├── .env.example
│
├── mcp_server/
│   ├── github_tools.py       # MCP server: fetch_repository, list_files, read_file
│   └── client.py             # MCP client wrapper (sync)
│
├── pipeline/
│   ├── preprocessor.py       # Filter, clean, detect tech stack
│   ├── parser.py             # Tree-sitter AST + regex chunker
│   ├── embedder.py           # CodeBERT embeddings + FAISS index
│   └── rag_engine.py         # RAG query + Groq LLM generation
│
├── templates/
│   └── index.html            # Dark-themed frontend
│
└── static/
    ├── css/style.css
    └── js/app.js
```

## Features

- **MCP-based GitHub access** — structured tool calls via Model Context Protocol
- **Tree-sitter AST parsing** — semantically accurate code chunking for Python + JS
- **CodeBERT embeddings** — code-aware 768-dim vectors (not generic text embeddings)
- **FAISS cosine search** — sub-millisecond retrieval over thousands of chunks
- **RAG + Groq LLaMA** — grounded, citation-backed code explanations
- **Session caching** — re-analyzing the same repo loads from disk instantly
- **Interactive Q&A** — ask anything about the codebase
- **File-level explanation** — click any file for an LLM-generated module breakdown
- **Dependency analysis** — extracted import graphs across all source files
