"""Signed short-lived BFF -> API identity. No browser-supplied principals."""
import hashlib
import hmac
import re
import time

from fastapi import Header, HTTPException

from sentinela.config import get_settings


def verify_principal(
    x_sentinela_principal: str = Header(default=""),
    x_sentinela_timestamp: str = Header(default=""),
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
    payload = f"{x_sentinela_principal}\n{x_sentinela_timestamp}".encode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, x_sentinela_signature):
        raise HTTPException(status_code=401, detail="unauthorized")
    return x_sentinela_principal
