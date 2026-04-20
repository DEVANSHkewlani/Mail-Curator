#!/usr/bin/env bash
# run.sh — Start The Curator Mail backend
# Usage: bash run.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
VENV_DIR="$PROJECT_DIR/.venv"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║      The Curator Mail — API Server       ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Virtual environment ───────────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
  echo "▸ Creating Python virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# ── 2. Install dependencies (skip pip self-upgrade) ──────────────────────────
echo "▸ Checking dependencies..."
pip install -q -r "$BACKEND_DIR/requirements.txt"

# ── 3. Launch Uvicorn ─────────────────────────────────────────────────────────
echo ""
echo "▸ Starting API server on http://localhost:8000"
echo "▸ API docs available at http://localhost:8000/docs"
echo "▸ Press Ctrl+C to stop"
echo ""

# Run from project root so 'backend.*' imports resolve correctly
cd "$PROJECT_DIR"
exec uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
