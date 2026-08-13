import asyncio
import json
import re
import subprocess
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from app.config import WHISPER_CPP_BIN, WHISPER_MODEL_PATH, TMP_DIR
from app.auth import require_scope

router = APIRouter()

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

# whisper.cpp prints each finished segment as:
# [00:00:00.000 --> 00:00:02.000]  Hello from
_SEGMENT_RE = re.compile(
    r"^\s*\[(\d{2}:\d{2}:\d{2}[.,]\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}[.,]\d{3})\]\s*(.*)$"
)
_STT_TIMEOUT_S = 60.0


def _sse(data: dict) -> bytes:
    return f"data: {json.dumps(data)}\n\n".encode()


@router.post(
    "/transcribe",
    summary="Speech-to-text",
    response_description="JSON with the full transcript",
)
async def transcribe(file: UploadFile = File(...), _: None = Depends(require_scope("stt"))):
    """
    Speech-to-text via whisper.cpp. Spawns a short-lived process per request
    instead of a daemon — whisper.cpp loads base.en in well under a second
    and frees its RAM the moment it's done, which matters on a 10GB box.

    Expects 16kHz mono WAV. If your source audio isn't already in that
    format, convert with ffmpeg before uploading (see README).
    """
    if not Path(WHISPER_CPP_BIN).exists():
        raise HTTPException(status_code=503, detail="whisper.cpp binary not found — run scripts/setup.sh")

    req_id = uuid.uuid4().hex
    in_path = TMP_DIR / f"{req_id}.wav"
    out_prefix = TMP_DIR / req_id

    with open(in_path, "wb") as f:
        f.write(await file.read())

    try:
        result = subprocess.run(
            [
                WHISPER_CPP_BIN,
                "-m", WHISPER_MODEL_PATH,
                "-f", str(in_path),
                "-otxt",
                "-of", str(out_prefix),
                "-nt",  # no timestamps in output text
            ],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"whisper.cpp failed: {result.stderr[-500:]}")

        txt_path = out_prefix.with_suffix(".txt")
        text = txt_path.read_text().strip() if txt_path.exists() else ""
        return {"text": text}
    finally:
        in_path.unlink(missing_ok=True)
        out_prefix.with_suffix(".txt").unlink(missing_ok=True)


@router.post(
    "/transcribe/stream",
    summary="Speech-to-text (SSE stream)",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "SSE: one event per whisper.cpp segment (`done: false`), then a final event with the full transcript (`done: true`).",
            "content": {"text/event-stream": {}},
        },
        503: {"description": "whisper.cpp binary not found"},
    },
)
async def transcribe_stream(file: UploadFile = File(...), _: None = Depends(require_scope("stt"))):
    """
    Same 16 kHz mono WAV upload as /v1/audio/transcribe, but streams each
    whisper.cpp segment as SSE. The last event has done=true and the
    concatenated full transcript.
    """
    if not Path(WHISPER_CPP_BIN).exists():
        raise HTTPException(status_code=503, detail="whisper.cpp binary not found — run scripts/setup.sh")

    req_id = uuid.uuid4().hex
    in_path = TMP_DIR / f"{req_id}.wav"

    with open(in_path, "wb") as f:
        f.write(await file.read())

    async def iter_sse():
        proc = None
        segments = []
        try:
            proc = await asyncio.create_subprocess_exec(
                WHISPER_CPP_BIN,
                "-m", WHISPER_MODEL_PATH,
                "-f", str(in_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None
            deadline = time.monotonic() + _STT_TIMEOUT_S
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    proc.kill()
                    await proc.wait()
                    yield _sse({"error": "whisper.cpp timed out", "done": True})
                    return
                try:
                    line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    yield _sse({"error": "whisper.cpp timed out", "done": True})
                    return
                if not line_bytes:
                    break
                line = line_bytes.decode(errors="replace").rstrip("\n")
                match = _SEGMENT_RE.match(line)
                if not match:
                    continue
                text = match.group(3).strip()
                if not text:
                    continue
                segments.append(text)
                yield _sse({"text": text, "done": False})

            await proc.wait()
            if proc.returncode != 0:
                yield _sse({"error": "whisper.cpp failed", "done": True})
                return
            yield _sse({"text": " ".join(segments), "done": True})
        finally:
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
            in_path.unlink(missing_ok=True)

    return StreamingResponse(
        iter_sse(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
