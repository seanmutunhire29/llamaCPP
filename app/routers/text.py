import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List
from app.config import LLAMA_SERVER_URL
from app.auth import require_scope

router = APIRouter()

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


class ChatMessage(BaseModel):
    role: str
    content: str


class GenerateRequest(BaseModel):
    messages: List[ChatMessage]
    max_tokens: int = Field(default=512, le=4096)
    temperature: float = 0.7
    stream: bool = Field(
        default=False,
        description="Ignored. POST /v1/text/generate always returns a complete JSON body; "
        "use POST /v1/text/generate/stream for SSE.",
    )


def _payload(req: GenerateRequest, stream: bool) -> dict:
    return {
        "messages": [m.model_dump() for m in req.messages],
        "max_tokens": req.max_tokens,
        "temperature": req.temperature,
        "stream": stream,
    }


@router.post(
    "/generate",
    summary="Chat-style text generation",
    response_description="OpenAI-style chat.completion JSON",
)
async def generate(req: GenerateRequest, _: None = Depends(require_scope("text"))):
    """
    Thin proxy to llama-server's OpenAI-compatible /v1/chat/completions.
    Always returns a complete JSON body. Use /v1/text/generate/stream for SSE.
    """
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{LLAMA_SERVER_URL}/v1/chat/completions",
                json=_payload(req, stream=False),
            )
            r.raise_for_status()
            return r.json()
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="llama-server isn't reachable. Start it with scripts/start_llm.sh first.",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@router.post(
    "/generate/stream",
    summary="Chat-style text generation (SSE stream)",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "OpenAI-style SSE. Each event is a chat.completion.chunk; the stream ends with `data: [DONE]`.",
            "content": {"text/event-stream": {}},
        },
        503: {"description": "llama-server is not reachable"},
    },
)
async def generate_stream(req: GenerateRequest, _: None = Depends(require_scope("text"))):
    """
    Same JSON body as /v1/text/generate. Proxies llama-server's token stream as
    `text/event-stream`. The `stream` field on the body is ignored (always on).
    """
    client = httpx.AsyncClient(timeout=120.0)
    try:
        request = client.build_request(
            "POST",
            f"{LLAMA_SERVER_URL}/v1/chat/completions",
            json=_payload(req, stream=True),
        )
        response = await client.send(request, stream=True)
    except httpx.ConnectError:
        await client.aclose()
        raise HTTPException(
            status_code=503,
            detail="llama-server isn't reachable. Start it with scripts/start_llm.sh first.",
        )

    if response.is_error:
        body = (await response.aread()).decode(errors="replace")
        await response.aclose()
        await client.aclose()
        raise HTTPException(status_code=response.status_code, detail=body)

    async def iter_sse():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        iter_sse(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
