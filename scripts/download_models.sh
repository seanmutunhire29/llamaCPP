#!/usr/bin/env bash
# Downloads the small, CPU-friendly models used by default.
# Total download: ~2.5 GB (text) + ~150 MB (STT) + ~340 MB (TTS) = ~3.0 GB
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="$ROOT_DIR/models"
mkdir -p "$MODELS_DIR"

echo "== Text-gen: Qwen2.5-3B-Instruct, Q4_K_M quant (~2 GB) =="
hf download Qwen/Qwen2.5-3B-Instruct-GGUF \
    qwen2.5-3b-instruct-q4_k_m.gguf \
    --local-dir "$MODELS_DIR"

echo "== STT: whisper.cpp base.en (~150 MB) =="
curl -L "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin" \
    -o "$MODELS_DIR/ggml-base.en.bin"

echo "== TTS: Kokoro-82M ONNX + voices (~340 MB) =="
curl -L "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx" \
    -o "$MODELS_DIR/kokoro-v1.0.onnx"
curl -L "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin" \
    -o "$MODELS_DIR/voices-v1.0.bin"

echo "== Done. Models are in $MODELS_DIR =="