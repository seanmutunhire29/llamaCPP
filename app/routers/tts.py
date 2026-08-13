import asyncio
import struct
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app.config import KOKORO_MODEL_PATH, KOKORO_VOICE, KOKORO_VOICES_PATH, TMP_DIR
from app.auth import require_scope

router = APIRouter()

_kokoro = None
_kokoro_lock = threading.Lock()


class SpeakRequest(BaseModel):
    text: str
    voice: str = Field(default=KOKORO_VOICE, description="Kokoro voice id, e.g. af_heart")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


def _espeak_config():
    """Prefer the distro espeak-ng over the pip wheel's broken bundled paths."""
    candidates = [
        ("/usr/lib/x86_64-linux-gnu/libespeak-ng.so.1", "/usr/share/espeak-ng-data"),
        ("/usr/lib/libespeak-ng.so.1", "/usr/share/espeak-ng-data"),
    ]
    for lib, data in candidates:
        if Path(lib).exists() and Path(data).exists():
            from kokoro_onnx import EspeakConfig
            return EspeakConfig(lib_path=lib, data_path=data)
    return None


def get_kokoro():
    global _kokoro
    if _kokoro is None:
        with _kokoro_lock:
            if _kokoro is None:
                from kokoro_onnx import Kokoro

                kwargs = {}
                cfg = _espeak_config()
                if cfg is not None:
                    kwargs["espeak_config"] = cfg
                _kokoro = Kokoro(KOKORO_MODEL_PATH, KOKORO_VOICES_PATH, **kwargs)
    return _kokoro


def _synthesize(text: str, voice: str, speed: float, out_path: Path):
    import soundfile as sf

    samples, sample_rate = get_kokoro().create(text, voice=voice, speed=speed)
    sf.write(str(out_path), samples, sample_rate)


def _cleanup(path: Path):
    path.unlink(missing_ok=True)


def _wav_header(sample_rate: int, channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """Streaming WAV header: unknown data size (0xFFFFFFFF)."""
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    data_size = 0xFFFFFFFF
    riff_size = 0xFFFFFFFF
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        riff_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )


def _pcm16(samples) -> bytes:
    import numpy as np

    pcm = np.clip(samples, -1.0, 1.0)
    return (pcm * 32767.0).astype("<i2").tobytes()


@router.post(
    "/speak",
    summary="Text-to-speech",
    response_class=FileResponse,
    responses={200: {"content": {"audio/wav": {}}, "description": "Complete WAV file"}},
)
async def speak(req: SpeakRequest, _: None = Depends(require_scope("tts"))):
    """
    Text-to-speech via Kokoro-82M (ONNX). The model is lazy-loaded into the
    hub process on first use (~1GB) and reused after that — there is no CLI
    to spawn, and reloading the ONNX per request is too slow on CPU.
    """
    if not Path(KOKORO_MODEL_PATH).exists() or not Path(KOKORO_VOICES_PATH).exists():
        raise HTTPException(
            status_code=503,
            detail="Kokoro model files not found — run scripts/download_models.sh",
        )

    req_id = uuid.uuid4().hex
    out_path = TMP_DIR / f"{req_id}.wav"

    try:
        await asyncio.wait_for(
            asyncio.to_thread(_synthesize, req.text, req.voice, req.speed, out_path),
            timeout=60,
        )
    except asyncio.TimeoutError:
        _cleanup(out_path)
        raise HTTPException(status_code=504, detail="kokoro timed out")
    except ImportError as e:
        _cleanup(out_path)
        raise HTTPException(
            status_code=503,
            detail=f"Kokoro Python deps missing — pip install -r requirements.txt ({e})",
        )
    except HTTPException:
        raise
    except Exception as e:
        _cleanup(out_path)
        raise HTTPException(status_code=500, detail=f"kokoro failed: {e}")

    if not out_path.exists():
        raise HTTPException(status_code=500, detail="kokoro produced no audio")

    return FileResponse(
        out_path,
        media_type="audio/wav",
        filename="speech.wav",
        background=BackgroundTask(_cleanup, out_path),
    )


@router.post(
    "/speak/stream",
    summary="Text-to-speech (WAV stream)",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Streaming WAV: 16-bit PCM mono at 24 kHz. Header first, then audio as each phrase is synthesized.",
            "content": {"audio/wav": {}},
        },
        503: {"description": "Kokoro model files or Python deps missing"},
    },
)
async def speak_stream(req: SpeakRequest, _: None = Depends(require_scope("tts"))):
    """
    Same JSON body as /v1/audio/speak, but streams a WAV as Kokoro synthesizes
    each phoneme batch. Header is 16-bit PCM mono at Kokoro's 24 kHz.
    """
    if not Path(KOKORO_MODEL_PATH).exists() or not Path(KOKORO_VOICES_PATH).exists():
        raise HTTPException(
            status_code=503,
            detail="Kokoro model files not found — run scripts/download_models.sh",
        )

    try:
        get_kokoro()
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Kokoro Python deps missing — pip install -r requirements.txt ({e})",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"kokoro failed: {e}")

    async def iter_wav():
        yield _wav_header(24000)
        stream = get_kokoro().create_stream(req.text, voice=req.voice, speed=req.speed)
        async for samples, _sample_rate in stream:
            yield _pcm16(samples)

    return StreamingResponse(iter_wav(), media_type="audio/wav")
