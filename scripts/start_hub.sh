#!/usr/bin/env bash
# Starts the FastAPI gateway. Run this in a second terminal/session
# after start_llm.sh is already running.
set -euo pipefail


ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

uvicorn app.main:app --host 0.0.0.0 --port 9000
