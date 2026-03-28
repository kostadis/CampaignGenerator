#!/bin/bash
# Development server — runs FastAPI backend + Vite frontend in parallel.
# Usage: ./dev.sh [--session-dir /path/to/session]
#
# FastAPI runs on :8000, Vite dev server on :5173 (proxies /api/* to :8000).
# Open http://localhost:5173 in your browser.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Start FastAPI backend
echo "Starting FastAPI backend on :8000..."
uvicorn server.main:app --reload --port 8000 --app-dir "$SCRIPT_DIR" &
BACKEND_PID=$!

# Start Vite dev server
echo "Starting Vite dev server on :5173..."
cd "$SCRIPT_DIR/frontend" && npm run dev &
FRONTEND_PID=$!

# Clean up on exit
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT

echo ""
echo "  Open http://localhost:5173 in your browser"
echo "  Press Ctrl+C to stop both servers"
echo ""

wait
