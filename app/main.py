"""
llm-api-hub
A single local API gateway in front of small, CPU-friendly models
(llama.cpp for text, whisper.cpp for STT, Kokoro-82M for TTS).

Run with: uvicorn app.main:app --host 0.0.0.0 --port 9000
"""
from fastapi import FastAPI
from app.routers import text, stt, tts, image, health, admin, docs
from app.db import init_db

app = FastAPI(
    title="llm-api-hub",
    description=(
        "Internal-use API hub over small local models (llama.cpp, whisper.cpp, Kokoro-82M). "
        "Not for production — swap to hosted APIs (Claude, etc.) for that. "
        "Text, STT, and TTS each have a complete-response route and a `/stream` sibling."
    ),
    version="0.1.0",
)


@app.on_event("startup")
async def _startup():
    init_db()


app.include_router(docs.router, tags=["docs"])
app.include_router(health.router, tags=["health"])
app.include_router(text.router, prefix="/v1/text", tags=["text"])
app.include_router(stt.router, prefix="/v1/audio", tags=["audio (speech-to-text)"])
app.include_router(tts.router, prefix="/v1/audio", tags=["audio (text-to-speech)"])
app.include_router(image.router, prefix="/v1/image", tags=["image (not yet implemented)"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
