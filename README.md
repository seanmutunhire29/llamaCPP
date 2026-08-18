# llm-api-hub

A local API hub for small, CPU-friendly open models. It supports text generation, speech-to-text, and text-to-speech. You can use it for internal testing to avoid burning API credits on other projects during development. When you are ready for production, you can swap the base URL for a hosted API like Claude or OpenAI.

**Live Demo / Hosted App:** [https://sean.tail15fdf0.ts.net/](https://sean.tail15fdf0.ts.net/)

**Backend engines:**

* llama.cpp (Text)
* whisper.cpp (Speech-to-Text)
* Kokoro-82M (Text-to-Speech)

## Architecture and Resource Budget

This project is built for a 10GB RAM, CPU-only environment. Loading all models into memory at once will cause an Out of Memory (OOM) error. The design works around this constraint:

* **Text generation (llama.cpp):** The `llama-server` runs persistently. Text generation is queried most often and is the slowest to load, so it stays warm in memory. It uses about 2.5GB resident memory with a 3B Q4 model and 4k context.
* **Speech-to-Text (whisper.cpp):** This runs per-request. It is spawned as a subprocess by FastAPI and torn down immediately after completion. It loads in under a second and uses about 150MB of RAM, so there is no cost to keeping it cold.
* **Text-to-Speech (Kokoro-82M):** This is lazy-loaded in the hub on the first `/v1/audio/speak` request. It peaks at about 1GB of RAM and is reused after that. There is no CLI to spawn, and reloading the ONNX model every request is too slow. It fits comfortably within the RAM budget.
* **Image generation (Phase 2):** Image generation is not implemented yet. Diffusion models are heavy and slow on a CPU. The planned implementation will mirror STT: spawn on demand and never keep it warm.

**Rough RAM budget:** OS and FastAPI (1GB) + llama-server (2.5GB) + Kokoro after first TTS (1GB). This leaves about 5.5GB of headroom for the OS cache, STT memory spikes, and future additions.

## Setup

Clone the repository and run the setup scripts:

```bash
git clone <this repo> && cd llm-api-hub
bash scripts/setup.sh            # builds llama.cpp + whisper.cpp, installs espeak-ng
bash scripts/download_models.sh  # ~3.0GB of model downloads

```

## Running

You need to run two processes:

```bash
# Terminal 1: keep this warm
bash scripts/start_llm.sh

# Terminal 2: the actual API your other projects call
bash scripts/start_hub.sh

```

The hub listens on `http://localhost:9000`. Open that URL in a browser for the in-app guide, which includes an overview and full curl, Python, and JavaScript examples. The interactive OpenAPI documentation is at `/docs`. The API key management panel is at `/admin/`.

For always-on use, you should wrap both scripts in systemd services or a process manager like pm2 or supervisord rather than leaving them running in active terminals.

## Authentication

Every `/v1/...` endpoint requires an API key with the correct scope (text, stt, tts, or image). You must send it in the headers:

```text
Authorization: Bearer sk-hub-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

```

Keys are managed through an admin panel. The panel is gated behind a separate admin token. Anyone with that token can mint or revoke keys. You should treat it like a root password.

```bash
export HUB_ADMIN_TOKEN=$(openssl rand -hex 24)
echo $HUB_ADMIN_TOKEN   # save this somewhere safe to paste into the panel

```

With the hub running, open `[https://sean.tail15fdf0.ts.net/admin/](https://sean.tail15fdf0.ts.net/admin/)` in a browser and paste the admin token. You can:

* Generate a key. You can name it, pick which scopes it can use, and set an expiration date between 1 day and 1 year.
* View all keys. You can see their scopes, status, expiration date, and last used time.
* Revoke a key instantly.

The full key is shown exactly once right after creation. Only the hash is stored in the database. If you lose the key, you must revoke it and create a new one.

You can also manage keys directly via the admin API. This is useful for scripting:

```bash
# Create a key
curl -X POST https://sean.tail15fdf0.ts.net/admin/keys \
  -H "Authorization: Bearer $HUB_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "eventer-dev", "scopes": ["text", "stt"], "expires_in_days": 30}'

# List keys
curl https://sean.tail15fdf0.ts.net/admin/keys \
  -H "Authorization: Bearer $HUB_ADMIN_TOKEN"

# Revoke a key
curl -X POST https://sean.tail15fdf0.ts.net/admin/keys/3/revoke \
  -H "Authorization: Bearer $HUB_ADMIN_TOKEN"

```

Keys and their hashes are stored in `hub.db`, an SQLite database created automatically on the first run. Back it up if you want to keep your keys after a reinstall.

## Endpoints

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/health` | GET | Checks whether llama-server is reachable |
| `/v1/text/generate` | POST | Chat-style text generation (returns complete JSON) |
| `/v1/text/generate/stream` | POST | Same body, OpenAI-style SSE token stream |
| `/v1/audio/transcribe` | POST | Speech-to-text (upload 16kHz mono WAV) |
| `/v1/audio/transcribe/stream` | POST | Same upload, SSE stream of each transcript segment |
| `/v1/audio/speak` | POST | Text-to-speech (returns a complete WAV file) |
| `/v1/audio/speak/stream` | POST | Same body, WAV streamed as it is synthesized |
| `/v1/image/generate` | POST | Not implemented yet (returns 501) |

Text, STT, and TTS each have two routes: a complete-response endpoint and a `/stream` sibling. The stream endpoint takes the same body and requires the same API key scope, but returns data as it is produced. The standard `/generate` endpoint always returns JSON even if you send `"stream": true`. You must use `/v1/text/generate/stream` for tokens.

### Example: Text Generation

```bash
curl -X POST https://sean.tail15fdf0.ts.net/v1/text/generate \
  -H "Authorization: Bearer sk-hub-..." \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Summarize what a Bloom filter is in 2 sentences."}]}'

```

Streaming (OpenAI-style SSE). Use `curl -N` so curl does not buffer the output:

```bash
curl -N -X POST https://sean.tail15fdf0.ts.net/v1/text/generate/stream \
  -H "Authorization: Bearer sk-hub-..." \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Summarize what a Bloom filter is in 2 sentences."}]}'

```

### Example: Transcription

Convert your file first, as whisper.cpp requires 16kHz mono audio:

```bash
ffmpeg -i input.mp3 -ar 16000 -ac 1 input.wav

```

Send the file:

```bash
curl -X POST https://sean.tail15fdf0.ts.net/v1/audio/transcribe \
  -H "Authorization: Bearer sk-hub-..." \
  -F "file=@input.wav"

```

Streaming (one SSE event per whisper.cpp segment):

```bash
curl -N -X POST https://sean.tail15fdf0.ts.net/v1/audio/transcribe/stream \
  -H "Authorization: Bearer sk-hub-..." \
  -F "file=@input.wav"

```

### Example: Speech Synthesis

```bash
curl -X POST https://sean.tail15fdf0.ts.net/v1/audio/speak \
  -H "Authorization: Bearer sk-hub-..." \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello from your local model."}' \
  --output speech.wav

```

Streaming WAV. The body is 16-bit PCM mono at 24 kHz. It sends a WAV header followed by chunks as Kokoro finishes each phrase. Audio players that need a known file size in the header may wait until the stream ends.

```bash
curl -N -X POST https://sean.tail15fdf0.ts.net/v1/audio/speak/stream \
  -H "Authorization: Bearer sk-hub-..." \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello from your local model."}' \
  --output speech.wav

```

Optional JSON fields for TTS include `voice` (default is `af_heart`) and `speed` (default is `1.0`).

## Swapping Models

* **Text:** Change `models/qwen2.5-3b-instruct-q4_k_m.gguf` in `scripts/start_llm.sh` to another GGUF file. A 7B Q4 model needs about 4.5GB resident memory, which leaves less room for STT and TTS spikes.
* **STT:** Change `ggml-base.en.bin` to `ggml-tiny.en.bin` (faster, ~75MB) or `ggml-small.en.bin` (slower, ~465MB) in `app/config.py`.
* **TTS:** Change `KOKORO_VOICE` or point to another Kokoro ONNX/voices pair via `KOKORO_MODEL_PATH` and `KOKORO_VOICES_PATH`.

## Adding Image Generation (Phase 2)

To add image generation:

1. Build `stable-diffusion.cpp` the same way `setup.sh` builds the other engines.
2. Select an SD-Turbo-class model (1-step or few-step). Full multi-step SDXL on a CPU with 10GB RAM will be too slow.
3. Mirror the STT/TTS pattern in `app/routers/image.py`. Spawn the binary per request, write the output to a temporary directory, return the file, and clean up. Do not run it as a persistent server.

## Using with Production Code

Point your other projects' development config to `http://<this-box>:9000/v1/...` while working. For production, swap the base URL and auth tokens for a hosted API. The endpoint shapes in this hub loosely mirror common API conventions, making the transition a configuration change rather than a code rewrite.