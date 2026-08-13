import httpx
from fastapi import APIRouter
from app.config import LLAMA_SERVER_URL

router = APIRouter()


@router.get("/health")
async def health():
    """Reports whether the persistent llama.cpp server is reachable.
    STT is spawned per request; TTS (Kokoro) is lazy-loaded in the hub."""
    llama_up = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{LLAMA_SERVER_URL}/health")
            llama_up = r.status_code == 200
    except Exception:
        pass

    return {
        "status": "ok",
        "text_backend_llama_cpp": "up" if llama_up else "down",
        "stt_backend": "on-demand (whisper.cpp)",
        "tts_backend": "kokoro-82m (lazy-loaded)",
        "image_backend": "not implemented yet",
    }
