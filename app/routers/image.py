from fastapi import APIRouter, Depends, HTTPException
from app.auth import require_scope

router = APIRouter()


@router.post("/generate")
async def generate_image(_: None = Depends(require_scope("image"))):
    """
    Placeholder. Phase 2 plan: stable-diffusion.cpp with an SD-Turbo-class
    model, spawned on demand like STT/TTS (image gen is memory-hungry and
    slow on CPU, so it should never be the "always warm" model on a 10GB box).
    Wire this up once you're ready — see README's "Adding image generation" section.
    """
    raise HTTPException(status_code=501, detail="Image generation not implemented yet")
