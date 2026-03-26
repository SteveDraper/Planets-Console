#!/usr/bin/env bash
# Start backend and frontend dev server. Ctrl+C stops both.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Run backend in its own process group so we can kill it and all children (e.g. uvicorn).
set -m
uv run serve &
BACKEND_PID=$!
set +m

cleanup() {
  # Kill backend process group (uv + uvicorn)
  kill -- -"$BACKEND_PID" 2>/dev/null || true
  # Fallback: kill anything still bound to port 8000 (e.g. if process group kill missed a child)
  lsof -t -i :8000 2>/dev/null | xargs kill -9 2>/dev/null || true
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

# So About shows e.g. 0.1 (a1b2c3d) in dev; same pattern as CI build-time injection.
if GIT_SHA_SHORT=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null); then
  export VITE_GIT_COMMIT_SHORT="$GIT_SHA_SHORT"
fi

cd packages/frontend && npm run dev
