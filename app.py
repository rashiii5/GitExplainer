"""
Flask App - RepoExplainer
Routes: /, /analyze, /query, /explain, /status
"""

import os
import sys
import threading
from flask import Flask, render_template, request, jsonify, session

sys.path.insert(0, os.path.dirname(__file__))

from mcp_server.client import MCPClient
from orchestrator import analyze_repository, query_repository, explain_file, get_session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "repo-explainer-secret-2024")

MCP_SERVER_SCRIPT = os.path.join(os.path.dirname(__file__), "mcp_server", "github_tools.py")
mcp_client = MCPClient(MCP_SERVER_SCRIPT)

# Background analysis tasks
_analysis_threads: dict = {}


def _run_analysis(url: str):
    analyze_repository(url, mcp_client)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url or "github.com" not in url:
        return jsonify({"error": "Please provide a valid GitHub URL."}), 400

    sess = get_session(url)

    # If cached or already running, don't re-launch
    if sess.status in ("running",):
        return jsonify({"status": "running", "progress": sess.progress, "message": sess.status})

    if sess.is_cached() and sess.status != "idle":
        return jsonify({"status": "done", "repo_id": sess.repo_id})

    # Launch background thread
    t = threading.Thread(target=_run_analysis, args=(url,), daemon=True)
    _analysis_threads[sess.repo_id] = t
    t.start()

    return jsonify({"status": "started", "repo_id": sess.repo_id})


@app.route("/api/status", methods=["GET"])
def api_status():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "Missing url parameter"}), 400

    sess = get_session(url)

    # If idle and cached, load it
    if sess.status == "idle" and sess.is_cached():
        sess.load_cache()
        sess.status = "done"

    response = {
        "status": sess.status,
        "progress": sess.progress,
        "error": sess.error,
    }

    if sess.status == "done":
        response["data"] = {
            "repo_meta": sess.repo_meta,
            "tech_stack": sess.tech_stack,
            "overview": sess.overview,
            "dep_analysis": {
                "top_dependencies": sess.dep_analysis.get("top_dependencies", []),
                "total_files_with_deps": len(sess.dep_analysis.get("file_dependencies", {})),
            },
            "files": [f["path"] for f in sess.files] if sess.files else [],
            "chunk_count": len(sess.chunks) if sess.chunks else 0,
        }

    return jsonify(response)


@app.route("/api/query", methods=["POST"])
def api_query():
    data = request.get_json()
    url = data.get("url", "").strip()
    query = data.get("query", "").strip()

    if not url or not query:
        return jsonify({"error": "Missing url or query"}), 400

    result = query_repository(url, query)
    return jsonify(result)


@app.route("/api/explain_file", methods=["POST"])
def api_explain_file():
    data = request.get_json()
    url = data.get("url", "").strip()
    file_path = data.get("file_path", "").strip()

    if not url or not file_path:
        return jsonify({"error": "Missing url or file_path"}), 400

    explanation = explain_file(url, file_path)
    return jsonify({"explanation": explanation, "file": file_path})


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "RepoExplainer"})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
