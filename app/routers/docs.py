from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.config import BASE_DIR

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def docs_page():
    """Serves the in-app documentation / landing page."""
    html_path = Path(BASE_DIR) / "static" / "docs.html"
    return HTMLResponse(html_path.read_text())
