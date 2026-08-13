import hashlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import Header, HTTPException

from app.db import get_db


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def require_scope(scope: str):
    """
    Returns a FastAPI dependency that checks the caller's API key grants
    `scope` (e.g. "text", "stt", "tts", "image"), isn't revoked, and hasn't
    expired. Attach with Depends(require_scope("text")) on any route.
    """

    async def _check(authorization: Optional[str] = Header(default=None)):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Missing API key. Send it as: Authorization: Bearer <api-key>",
            )
        raw_key = authorization[len("Bearer "):].strip()
        key_hash = _hash_key(raw_key)

        db = get_db()
        try:
            row = db.execute(
                "SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)
            ).fetchone()

            if row is None:
                raise HTTPException(status_code=401, detail="Invalid API key")
            if row["revoked"]:
                raise HTTPException(status_code=403, detail="This API key has been revoked")

            expires_at = datetime.fromisoformat(row["expires_at"])
            if datetime.now(timezone.utc) > expires_at:
                raise HTTPException(status_code=403, detail="This API key has expired")

            allowed_scopes = row["scopes"].split(",")
            if scope not in allowed_scopes:
                raise HTTPException(
                    status_code=403,
                    detail=f"This API key doesn't have '{scope}' access (has: {row['scopes']})",
                )

            db.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), row["id"]),
            )
            db.commit()
        finally:
            db.close()

    return _check
