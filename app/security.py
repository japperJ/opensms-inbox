"""Signature verification and optional HTTP Basic auth."""

import hashlib
import hmac

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

basic_auth = HTTPBasic(auto_error=False)


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def require_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(basic_auth),
):
    settings = request.app.state.settings
    if not settings.user and not settings.password:
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    user_ok = hmac.compare_digest(credentials.username, settings.user)
    password_ok = hmac.compare_digest(credentials.password, settings.password)
    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
