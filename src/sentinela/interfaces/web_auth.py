"""Authenticate BFF calls with signed method, URL, body and nonce."""
import hashlib
import hmac
import re
import time
from uuid import UUID

from fastapi import Header, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from sentinela.config import get_settings


async def verify_principal(
    request: Request,
    x_sentinela_principal: str = Header(default=""),
    x_sentinela_timestamp: str = Header(default=""),
    x_sentinela_nonce: str = Header(default=""),
    x_sentinela_body_sha256: str = Header(default=""),
    x_sentinela_signature: str = Header(default=""),
) -> str:
    secret = get_settings().web_internal_key.get_secret_value()
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="web channel disabled")
    if not re.fullmatch(r"[a-f0-9]{64}", x_sentinela_principal):
        raise HTTPException(status_code=401, detail="unauthorized")
    if not re.fullmatch(r"[0-9]{10,11}", x_sentinela_timestamp):
        raise HTTPException(status_code=401, detail="unauthorized")
    if abs(time.time() - int(x_sentinela_timestamp)) > 60:
        raise HTTPException(status_code=401, detail="expired signature")
    try:
        nonce = UUID(x_sentinela_nonce)
        if str(nonce) != x_sentinela_nonce:
            raise ValueError("noncanonical nonce")
    except (ValueError, AttributeError):
        raise HTTPException(status_code=401, detail="unauthorized") from None
    if not re.fullmatch(r"[a-f0-9]{64}", x_sentinela_body_sha256):
        raise HTTPException(status_code=401, detail="unauthorized")
    body = await request.body()
    digest = hashlib.sha256(body).hexdigest()
    if not hmac.compare_digest(x_sentinela_body_sha256, digest):
        raise HTTPException(status_code=401, detail="unauthorized")
    path = request.url.path
    if request.url.query:
        path += "?" + request.url.query
    canonical = "\n".join((
        x_sentinela_principal, x_sentinela_timestamp, x_sentinela_nonce,
        request.method.upper(), path, digest,
    ))
    signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, x_sentinela_signature):
        raise HTTPException(status_code=401, detail="unauthorized")
    if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
        try:
            if not await run_in_threadpool(request.app.state.web_store.consume_nonce, nonce):
                raise HTTPException(status_code=401, detail="replayed request")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=503, detail="request authentication unavailable") from None
    return x_sentinela_principal
