"""Thin PostgREST + Storage client.

Every call carries the *end user's* access token, so Postgres Row Level Security
is what actually enforces data isolation — the API layer never has to remember
to filter by ``user_id``. We still pass the filter explicitly for index use and
as defence in depth.

Deliberately dependency-light (httpx only) instead of pulling in supabase-py:
we need a handful of verbs and predictable error surfaces.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import httpx

from .config import settings
from .errors import NotFoundError, UpstreamError
from .http import get_http_client

log = logging.getLogger(__name__)

Row = dict[str, Any]
ReturnPref = Literal["representation", "minimal"]
# PostgREST needs repeated keys for range filters (logged_at=gte.X&logged_at=lt.Y),
# which a dict cannot express — so params may also be a list of pairs.
Params = dict[str, Any] | list[tuple[str, Any]]


def build_params(base: dict[str, Any], *extra: tuple[str, Any]) -> list[tuple[str, Any]]:
    """Flatten a dict plus repeated-key pairs into an httpx-friendly param list."""
    params: list[tuple[str, Any]] = [(k, v) for k, v in base.items() if v is not None]
    params.extend(p for p in extra if p[1] is not None)
    return params


def with_limit(params: Params, limit: int) -> Params:
    if isinstance(params, dict):
        return {**params, "limit": limit}
    return [*params, ("limit", limit)]


class SupabaseREST:
    """PostgREST wrapper bound to a single user's JWT."""

    def __init__(self, access_token: str) -> None:
        self._token = access_token

    # -- internals ---------------------------------------------------------
    @property
    def _headers(self) -> dict[str, str]:
        return {
            "apikey": settings.supabase_anon_key,
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        table: str,
        *,
        params: Params | None = None,
        json: Any = None,
        prefer: str | None = None,
    ) -> Any:
        headers = self._headers
        if prefer:
            headers["Prefer"] = prefer

        client = get_http_client()
        try:
            resp = await client.request(
                method,
                f"{settings.rest_url}/{table}",
                params=params,
                json=json,
                headers=headers,
            )
        except httpx.HTTPError as exc:  # network-level
            raise UpstreamError(f"Database request failed: {exc}") from exc

        if resp.status_code >= 400:
            body = resp.text[:500]
            log.error("PostgREST %s %s -> %s %s", method, table, resp.status_code, body)
            if resp.status_code in (401, 403):
                raise UpstreamError(
                    "Database rejected the request (check RLS policies and token)."
                )
            raise UpstreamError(f"Database error {resp.status_code}: {body}")

        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # -- verbs -------------------------------------------------------------
    async def select(self, table: str, params: Params) -> list[Row]:
        data = await self._request("GET", table, params=params)
        return data or []

    async def select_one(self, table: str, params: Params) -> Row | None:
        rows = await self.select(table, with_limit(params, 1))
        return rows[0] if rows else None

    async def insert(
        self,
        table: str,
        rows: Row | list[Row],
        *,
        returning: ReturnPref = "representation",
    ) -> list[Row]:
        data = await self._request(
            "POST", table, json=rows, prefer=f"return={returning}"
        )
        return data or []

    async def insert_one(self, table: str, row: Row) -> Row:
        rows = await self.insert(table, row)
        if not rows:
            raise UpstreamError(f"Insert into {table} returned no row")
        return rows[0]

    async def upsert(
        self,
        table: str,
        rows: Row | list[Row],
        *,
        on_conflict: str,
        returning: ReturnPref = "representation",
    ) -> list[Row]:
        data = await self._request(
            "POST",
            table,
            params={"on_conflict": on_conflict},
            json=rows,
            prefer=f"resolution=merge-duplicates,return={returning}",
        )
        return data or []

    async def update(self, table: str, patch: Row, params: Params) -> list[Row]:
        data = await self._request(
            "PATCH", table, params=params, json=patch, prefer="return=representation"
        )
        return data or []

    async def update_one(self, table: str, patch: Row, params: Params) -> Row:
        rows = await self.update(table, patch, params)
        if not rows:
            raise NotFoundError(f"No matching row in {table}")
        return rows[0]

    async def delete(self, table: str, params: Params) -> list[Row]:
        data = await self._request(
            "DELETE", table, params=params, prefer="return=representation"
        )
        return data or []

    async def delete_one(self, table: str, params: Params) -> Row:
        rows = await self.delete(table, params)
        if not rows:
            raise NotFoundError(f"No matching row in {table}")
        return rows[0]

    # -- storage -----------------------------------------------------------
    async def upload_image(
        self, path: str, content: bytes, content_type: str
    ) -> str | None:
        """Upload to the private food-photos bucket; returns the object path."""
        bucket = settings.supabase_storage_bucket
        client = get_http_client()
        try:
            resp = await client.post(
                f"{settings.storage_url}/object/{bucket}/{path}",
                content=content,
                headers={
                    "apikey": settings.supabase_anon_key,
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": content_type,
                    "x-upsert": "true",
                    "Cache-Control": "3600",
                },
            )
        except httpx.HTTPError as exc:
            log.warning("Storage upload failed: %s", exc)
            return None

        if resp.status_code >= 400:
            log.warning("Storage upload rejected: %s %s", resp.status_code, resp.text[:300])
            return None
        return f"{bucket}/{path}"

    async def signed_url(self, object_path: str, expires_in: int = 3600) -> str | None:
        """Create a short-lived signed URL for a private object."""
        bucket, _, key = object_path.partition("/")
        if not key:
            bucket, key = settings.supabase_storage_bucket, object_path
        client = get_http_client()
        try:
            resp = await client.post(
                f"{settings.storage_url}/object/sign/{bucket}/{key}",
                json={"expiresIn": expires_in},
                headers={
                    "apikey": settings.supabase_anon_key,
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError:
            return None
        if resp.status_code >= 400:
            return None
        signed = resp.json().get("signedURL") or resp.json().get("signedUrl")
        if not signed:
            return None
        return f"{settings.storage_url}{signed}" if signed.startswith("/") else signed


def eq(value: Any) -> str:
    return f"eq.{value}"


def gte(value: Any) -> str:
    return f"gte.{value}"


def lte(value: Any) -> str:
    return f"lte.{value}"


def lt(value: Any) -> str:
    return f"lt.{value}"
