# llm-api-hub

A single local API in front of small, CPU-friendly open models — text generation,
speech-to-text, and text-to-speech today; image generation planned. Built for
internal testing so you don't burn API credits on other projects during dev,
then swap the base URL for a real hosted API (Claude, etc.) for production.

Backend engines: **llama.cpp** (text), **whisper.cpp** (STT), **Kokoro-82M** (TTS).

## Why this architecture

You're on a 10GB RAM, CPU-only box, which is tight enough that "just load
everything" will OOM. The design:

- **llama-server runs persistently.** Text-gen is the thing you'll query
  most often and it's the slowest to load, so it stays warm (~2.5GB resident
  with a 3B Q4 model + 4k context).
- **whisper.cpp runs per-request**, spawned as a subprocess by FastAPI and
  torn down immediately after. It loads in well under a second (~150MB), so
  there's no real cost to not keeping it resident.
- **Kokoro-82M is lazy-loaded in the hub** on the first `/v1/audio/speak`
  (~1GB peak) and reused after that. There is no CLI to spawn, and reloading
  the ONNX every request is too slow — still well within the RAM budget.
- **Image generation is not implemented yet on purpose.** Even the smallest
  usable diffusion models are heavier and slower on CPU than the budget here
  comfortably allows alongside a warm LLM. Phase 2 (see below) handles it the
  same way as STT: spawn on demand, never keep it warm.

Rough RAM budget: OS + FastAPI (~1GB) + llama-server (~2.5GB) + Kokoro after
first TTS (~1GB) leaves ~5.5GB of headroom for OS cache, STT spikes, and
whatever you add later.

## Setup

```bash
git clone <this repo> && cd llm-api-hub
bash scripts/setup.sh            # builds llama.cpp + whisper.cpp, installs espeak-ng
bash scripts/download_models.sh  # ~3.0GB of model downloads
```

## Running

Two long-running processes:

```bash
# terminal 1 — keep this warm
bash scripts/start_llm.sh

# terminal 2 — the actual API your other projects call
bash scripts/start_hub.sh
```

The hub listens on `http://localhost:9000`. Open that URL in a browser for
the in-app guide (overview + full curl / Python / JavaScript examples).
Interactive OpenAPI is at `/docs`; the key panel is at `/admin/`.

For always-on use, wrap both scripts in systemd services or a process
manager (pm2, supervisord) rather than leaving them in terminals.

## Auth

Every `/v1/...` endpoint requires an API key with the right scope
(`text`, `stt`, `tts`, or `image`), sent as:

```
Authorization: Bearer sk-hub-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Keys are managed through a small admin panel, itself gated behind a
separate admin token — anyone with that token can mint or revoke keys,
so treat it like a root password:

```bash
export HUB_ADMIN_TOKEN=$(openssl rand -hex 24)
echo $HUB_ADMIN_TOKEN   # save this somewhere safe, you'll paste it into the panel
```

With the hub running, open `https://sean.tail15fdf0.ts.net/admin/` in a browser,
paste the admin token in, and you can:

- **Generate a key** — give it a name, pick which scopes it can use
  (text/STT/TTS/image), and set an expiry (1 day up to 1 year).
- **See all keys** at a glance — scopes, status (active/expired/revoked),
  when it expires, when it was last used.
- **Revoke a key** instantly, whether or not it's expired yet.

The full key is shown exactly once, right after creation — only its
hash is stored, so if you lose it, revoke it and make a new one.

You can also manage keys directly via the admin API (useful for scripting):

```bash
# create a key
curl -X POST https://sean.tail15fdf0.ts.net/admin/keys \
  -H "Authorization: Bearer $HUB_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "eventer-dev", "scopes": ["text", "stt"], "expires_in_days": 30}'

# list keys
curl https://sean.tail15fdf0.ts.net/admin/keys -H "Authorization: Bearer $HUB_ADMIN_TOKEN"

# revoke a key
curl -X POST https://sean.tail15fdf0.ts.net/admin/keys/3/revoke -H "Authorization: Bearer $HUB_ADMIN_TOKEN"
```

Keys and their hashes live in `hub.db` (SQLite, created automatically on
first run) — back it up if you don't want to regenerate keys after a
reinstall.

## Endpoints

| Endpoint                      | Method | Purpose                                      |
| ----------------------------- | ------ | -------------------------------------------- |
| `/health`                     | GET    | Checks whether llama-server is reachable     |
| `/v1/text/generate`           | POST   | Chat-style text generation (complete JSON)   |
| `/v1/text/generate/stream`    | POST   | Same body, OpenAI-style SSE token stream     |
| `/v1/audio/transcribe`        | POST   | Speech-to-text (upload 16kHz mono WAV)       |
| `/v1/audio/transcribe/stream` | POST   | Same upload, SSE of each transcript segment  |
| `/v1/audio/speak`             | POST   | Text-to-speech (returns a complete WAV)      |
| `/v1/audio/speak/stream`      | POST   | Same body, WAV streamed as it is synthesized |
| `/v1/image/generate`          | POST   | Not implemented yet — returns 501            |

Each of text, STT, and TTS has two routes: a complete-response endpoint and a
`/stream` sibling that takes the same body (and the same API-key scope) but
returns data as it is produced. `/generate` always returns JSON even if you
send `"stream": true` — use `/v1/text/generate/stream` for tokens.

### Example: text generation

```bash
curl -X POST https://sean.tail15fdf0.ts.net/v1/text/generate \
  -H "Authorization: Bearer sk-hub-..." \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Summarize what a Bloom filter is in 2 sentences."}]}'
```

Streaming (OpenAI-style SSE — use `curl -N` so curl does not buffer):

```bash
curl -N -X POST https://sean.tail15fdf0.ts.net/v1/text/generate/stream \
  -H "Authorization: Bearer sk-hub-..." \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Summarize what a Bloom filter is in 2 sentences."}]}'
```

Typical events:

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"A Bloom"},"finish_reason":null}]}

data: [DONE]
```

### Example: transcription

```bash
ffmpeg -i input.mp3 -ar 16000 -ac 1 input.wav   # whisper.cpp wants 16kHz mono
curl -X POST https://sean.tail15fdf0.ts.net/v1/audio/transcribe \
  -H "Authorization: Bearer sk-hub-..." \
  -F "file=@input.wav"
```

Streaming (one SSE event per whisper.cpp segment; last event has `"done": true`):

```bash
curl -N -X POST https://sean.tail15fdf0.ts.net/v1/audio/transcribe/stream \
  -H "Authorization: Bearer sk-hub-..." \
  -F "file=@input.wav"
```

Typical events:

```
data: {"text": "Hello from", "done": false}

data: {"text": "your local model.", "done": false}

data: {"text": "Hello from your local model.", "done": true}
```

### Example: speech synthesis

```bash
curl -X POST https://sean.tail15fdf0.ts.net/v1/audio/speak \
  -H "Authorization: Bearer sk-hub-..." \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello from your local model."}' \
  --output speech.wav
```

Streaming WAV (same JSON body; audio arrives as Kokoro finishes each phrase).
The body is 16-bit PCM mono at 24 kHz: a WAV header, then chunks. Players that
need a known file size in the header may wait until the stream ends.

```bash
curl -N -X POST https://sean.tail15fdf0.ts.net/v1/audio/speak/stream \
  -H "Authorization: Bearer sk-hub-..." \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello from your local model."}' \
  --output speech.wav
```

Optional JSON fields: `voice` (default `af_heart`) and `speed` (default `1.0`).
See [Kokoro voices](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md).

## Swapping in bigger/different models

- **Text**: change `models/qwen2.5-3b-instruct-q4_k_m.gguf` in
  `scripts/start_llm.sh` to any other GGUF file. Stay CPU-conscious: a 7B
  Q4 model needs ~4.5GB resident, which still fits but leaves much less
  headroom for concurrent STT/TTS spikes.
- **STT**: swap `ggml-base.en.bin` for `ggml-tiny.en.bin` (faster, less
  accurate, ~75MB) or `ggml-small.en.bin` (slower, more accurate, ~465MB)
  in `app/config.py`.
- **TTS**: change `KOKORO_VOICE` (e.g. `af_sarah`, `am_adam`) or drop in
  another Kokoro ONNX/voices pair via `KOKORO_MODEL_PATH` /
  `KOKORO_VOICES_PATH`. Voice list:
  [VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md).

## Adding image generation (phase 2)

When you're ready:

1. Build [`stable-diffusion.cpp`](https://github.com/leejet/stable-diffusion.cpp)
   the same way `setup.sh` builds llama.cpp/whisper.cpp.
2. Pick an SD-Turbo-class model (1-step/few-step) — full multi-step SDXL
   on CPU with 10GB RAM will be painfully slow.
3. Mirror the STT/TTS pattern in `app/routers/image.py`: spawn the binary
   per request, write output to `TMP_DIR`, return the file, clean up.
   Do **not** make it a persistent server — it's the heaviest single model
   here and shouldn't compete with the LLM for RAM at idle.

## Using this alongside production code

Point your other projects' dev/test config at `http://<this-box>:9000/v1/...`
during development. For production, swap the base URL and auth for a real
hosted API — the endpoint shapes here loosely mirror common API conventions
so the swap is mostly a config change, not a rewrite.
# llamaCPP
