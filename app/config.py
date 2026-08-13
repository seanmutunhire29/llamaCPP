import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- llama.cpp (text generation) ---
# llama-server is expected to already be running persistently (see scripts/start_llm.sh)
# because it's the one model worth keeping warm on a RAM-constrained box.
LLAMA_SERVER_URL = os.getenv("LLAMA_SERVER_URL", "http://127.0.0.1:8080")

# --- whisper.cpp (speech-to-text) ---
WHISPER_CPP_BIN = os.getenv("WHISPER_CPP_BIN", str(BASE_DIR / "third_party/whisper.cpp/build/bin/whisper-cli"))
WHISPER_MODEL_PATH = os.getenv("WHISPER_MODEL_PATH", str(BASE_DIR / "models/ggml-base.en.bin"))

# --- Kokoro-82M (text-to-speech) ---
# Lazy-loaded in the hub process on first /v1/audio/speak (~1GB peak).
# There is no Piper-style CLI; reloading the ONNX every request is too slow.
KOKORO_MODEL_PATH = os.getenv("KOKORO_MODEL_PATH", str(BASE_DIR / "models/kokoro-v1.0.onnx"))
KOKORO_VOICES_PATH = os.getenv("KOKORO_VOICES_PATH", str(BASE_DIR / "models/voices-v1.0.bin"))
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "af_heart")

# --- scratch space for per-request temp audio files ---
TMP_DIR = Path(os.getenv("HUB_TMP_DIR", "/tmp/llm-api-hub"))
TMP_DIR.mkdir(parents=True, exist_ok=True)

# --- auth ---
DB_PATH = os.getenv("HUB_DB_PATH", str(BASE_DIR / "hub.db"))

# Required to use the admin panel / admin API. Set this before starting the hub:
#   export HUB_ADMIN_TOKEN=$(openssl rand -hex 24)
# Anyone with this token can mint or revoke API keys, so treat it like a root password.
ADMIN_TOKEN = os.getenv("HUB_ADMIN_TOKEN")

VALID_SCOPES = ["text", "stt", "tts", "image"]
