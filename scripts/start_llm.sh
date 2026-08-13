#!/usr/bin/env bash
# Starts the persistent llama.cpp server that backs /v1/text/generate.
# This is the one process worth keeping warm. STT is spawned per-request;
# TTS (Kokoro) is lazy-loaded inside the hub on first use.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$ROOT_DIR/third_party/llama.cpp/build/bin/llama-server" \
    --model "$ROOT_DIR/models/qwen2.5-3b-instruct-q4_k_m.gguf" \
    --ctx-size 4096 \
    --threads "$(nproc)" \
    --port 8080 \
    --host 127.0.0.1
