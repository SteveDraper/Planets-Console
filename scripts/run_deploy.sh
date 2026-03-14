#!/usr/bin/env bash
# Run single server with built frontend. Build first: cd packages/frontend && npm run build
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export FRONTEND_DIST="$ROOT/packages/frontend/dist"
exec uv run serve "$@"
