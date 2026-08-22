#!/usr/bin/env bash
# One-time setup: builds llama.cpp and whisper.cpp from source (CPU-only),
# and installs espeak-ng (needed by Kokoro TTS). Run this once on the target machine.
#
# Usage: bash scripts/setup.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
THIRD_PARTY="$ROOT_DIR/third_party"
mkdir -p "$THIRD_PARTY"

echo "== Installing build dependencies =="
sudo apt-get update -y
sudo apt-get install -y build-essential cmake git curl ffmpeg python3-pip espeak-ng

echo "== Building llama.cpp (CPU-only) =="
if [ ! -d "$THIRD_PARTY/llama.cpp" ]; then
    git clone --depth 1 https://github.com/ggml-org/llama.cpp "$THIRD_PARTY/llama.cpp"
fi
cmake -B "$THIRD_PARTY/llama.cpp/build" -S "$THIRD_PARTY/llama.cpp"
cmake --build "$THIRD_PARTY/llama.cpp/build" --config Release -j"$(nproc)"

echo "== Building whisper.cpp (CPU-only) =="
if [ ! -d "$THIRD_PARTY/whisper.cpp" ]; then
    git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$THIRD_PARTY/whisper.cpp"
fi
cmake -B "$THIRD_PARTY/whisper.cpp/build" -S "$THIRD_PARTY/whisper.cpp"
cmake --build "$THIRD_PARTY/whisper.cpp/build" --config Release -j"$(nproc)"

echo "== Installing Python dependencies =="
pip install --break-system-packages -r "$ROOT_DIR/requirements.txt"
pip install --break-system-packages huggingface_hub

echo "== Done. Next: bash scripts/download_models.sh =="
