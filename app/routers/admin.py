import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.config import ADMIN_TOKEN, VALID_SCOPES, BASE_DIR
from app.db import get_db

router = APIRouter()


def require_admin(authorization: Optional[str] = Header(default=None)):
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="HUB_ADMIN_TOKEN isn't set on the server — export it before starting the hub.",
        )
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid admin token")


class CreateKeyRequest(BaseModel):
    name: str = Field(min_length=1, description="What this key is for, e.g. 'eventer-dev'")
    scopes: List[str]
    expires_in_days: int = Field(gt=0, le=3650)


@router.get("/", response_class=HTMLResponse)
async def admin_panel():
    """Serves the single-page admin panel."""
    html_path = Path(BASE_DIR) / "static" / "admin.html"
    return HTMLResponse(html_path.read_text())


@router.get("/keys")
async def list_keys(_: None = Depends(require_admin)):
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, name, key_prefix, scopes, created_at, expires_at, revoked, last_used_at "
            "FROM api_keys ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


@router.post("/keys")
async def create_key(req: CreateKeyRequest, _: None = Depends(require_admin)):
    unknown = [s for s in req.scopes if s not in VALID_SCOPES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown scopes {unknown}. Valid scopes: {VALID_SCOPES}")
    if not req.scopes:
        raise HTTPException(status_code=400, detail="At least one scope is required")

    raw_key = "sk-hub-" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=req.expires_in_days)

    db = get_db()
    try:
        db.execute(
            "INSERT INTO api_keys (name, key_hash, key_prefix, scopes, created_at, expires_at, revoked) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (req.name, key_hash, raw_key[:14], ",".join(req.scopes), now.isoformat(), expires_at.isoformat()),
        )
        db.commit()
    finally:
        db.close()

    return {
        "api_key": raw_key,
        "name": req.name,
        "scopes": req.scopes,
        "expires_at": expires_at.isoformat(),
        "warning": "This is the only time the full key is shown. Save it now.",
    }


@router.post("/keys/{key_id}/revoke")
async def revoke_key(key_id: int, _: None = Depends(require_admin)):
    db = get_db()
    try:
        cur = db.execute("UPDATE api_keys SET revoked = 1 WHERE id = ?", (key_id,))
        db.commit()
    finally:
        db.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"status": "revoked", "id": key_id}


@router.delete("/keys/{key_id}")
async def delete_key(key_id: int, _: None = Depends(require_admin)):
    db = get_db()
    try:
        cur = db.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        db.commit()
    finally:
        db.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"status": "deleted", "id": key_id}
