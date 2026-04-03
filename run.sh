#!/bin/bash
# ─── RepoExplainer Startup Script ───────────────────────────────

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  RepoExplainer — AI GitHub Code Intelligence"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check .env
if [ ! -f .env ]; then
  echo "⚠  No .env file found. Copying from .env.example..."
  cp .env.example .env
  echo "   Please edit .env and add your GROQ_API_KEY, then re-run."
  exit 1
fi

# Load env vars
export $(grep -v '^#' .env | xargs)

# Install dependencies
echo ""
echo "📦 Installing dependencies..."
pip install -r requirements.txt -q

echo ""
echo "✅ Starting RepoExplainer on http://localhost:5000"
echo ""

python app.py
