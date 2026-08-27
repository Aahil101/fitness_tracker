"""Supabase access-token verification.

Supports both signing systems:

* **Asymmetric (current default)** — tokens are signed with ES256/RS256 and the
  public keys are published at ``{SUPABASE_URL}/auth/v1/.well-known/jwks.json``.
  Verification is local and needs no network round trip after the first fetch.
* **Legacy HS256** — projects created before JWT signing keys sign with the
  shared ``SUPABASE_JWT_SECRET``.

If neither can verify the token we fall back to asking the Auth server directly
(``GET /auth/v1/user``), which always works but costs a request.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .errors import AuthError, ConfigurationError

log = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

# JWKS cache: Supabase rotates keys rarely, so a 10 minute TTL is plenty.
_JWKS_TTL_S = 600
_jwks_cache: dict[str, Any] = {"fetched_at": 0.0, "keys": {}}


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None
    access_token: str
    claims: dict[str, Any]


async def _fetch_jwks() -> dict[str, Any]:
    now = time.monotonic()
    if _jwks_cache["keys"] and now - _jwks_cache["fetched_at"] < _JWKS_TTL_S:
        return _jwks_cache["keys"]

    url = f"{settings.auth_url}/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers={"apikey": settings.supabase_anon_key})
    if resp.status_code != 200:
        log.warning("JWKS fetch failed: %s %s", resp.status_code, resp.text[:200])
        return _jwks_cache["keys"]

    keys: dict[str, Any] = {}
    for jwk in resp.json().get("keys", []):
        kid = jwk.get("kid")
        if not kid:
            continue
        try:
            keys[kid] = jwt.PyJWK(jwk)
        except Exception as exc:  # pragma: no cover - malformed key
            log.warning("Skipping unusable JWK %s: %s", kid, exc)

    _jwks_cache["keys"] = keys
    _jwks_cache["fetched_at"] = now
    return keys


def _decode_with_secret(token: str) -> dict[str, Any] | None:
    if not settings.supabase_jwt_secret:
        return None
    try:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"verify_aud": False},
        )
    except jwt.PyJWTError:
        return None


async def _decode_with_jwks(token: str) -> dict[str, Any] | None:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        return None

    kid, alg = header.get("kid"), header.get("alg", "")
    if not kid or alg == "HS256":
        return None

    keys = await _fetch_jwks()
    signing_key = keys.get(kid)
    if signing_key is None:
        # Possible rotation: force one refresh before giving up.
        _jwks_cache["fetched_at"] = 0.0
        keys = await _fetch_jwks()
        signing_key = keys.get(kid)
    if signing_key is None:
        return None

    try:
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=[alg],
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        log.debug("JWKS decode failed: %s", exc)
        return None


async def _verify_remotely(token: str) -> dict[str, Any] | None:
    """Last resort: let the Auth server validate the token."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{settings.auth_url}/user",
            headers={
                "apikey": settings.supabase_anon_key,
                "Authorization": f"Bearer {token}",
            },
        )
    if resp.status_code != 200:
        return None
    user = resp.json()
    return {"sub": user.get("id"), "email": user.get("email"), "_remote": True}


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if not settings.supabase_configured:
        raise ConfigurationError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY."
        )

    token = credentials.credentials if credentials else None
    if not token:
        # Allow ?access_token= for EventSource / <img> style requests.
        token = request.query_params.get("access_token")
    if not token:
        raise AuthError("Missing bearer token")

    claims = _decode_with_secret(token)
    if claims is None:
        claims = await _decode_with_jwks(token)
    if claims is None:
        claims = await _verify_remotely(token)
    if claims is None:
        raise AuthError("Invalid or expired token")

    user_id = claims.get("sub")
    if not user_id:
        raise AuthError("Token is missing a subject claim")

    return CurrentUser(
        id=user_id,
        email=claims.get("email"),
        access_token=token,
        claims=claims,
    )
