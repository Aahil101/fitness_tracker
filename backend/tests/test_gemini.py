"""Gemini transport behaviour.

A coach reply that reasons over a full day's log can run past the 30s timeout
that suits Supabase and USDA. When it did, two things went wrong: the request
was aborted even though Gemini was healthy, and the log line read
``Could not reach Gemini:`` with nothing after it — because httpx timeout
exceptions stringify to the empty string, so the actual cause was invisible.
"""

import httpx
import pytest

from app import http as app_http
from app.config import settings
from app.errors import UpstreamError
from app.services import gemini


@pytest.fixture
def mock_gemini(monkeypatch: pytest.MonkeyPatch):
    """Swap the shared httpx client for a scripted transport, recording requests."""

    def install(handler):
        seen: list[httpx.Request] = []

        def wrapped(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        monkeypatch.setattr(
            app_http,
            "_client",
            httpx.AsyncClient(transport=httpx.MockTransport(wrapped)),
        )
        return seen

    return install


async def test_read_timeout_reports_the_exception_type_not_a_blank_reason(mock_gemini):
    """A timeout must name itself, otherwise the log says 'Gemini:' and nothing."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("", request=request)

    mock_gemini(handler)

    with pytest.raises(UpstreamError) as caught:
        await gemini.chat(
            [{"role": "user", "content": "How am I doing?"}], context_json="{}"
        )

    message = str(caught.value)
    assert "Could not reach Gemini: " in message
    reason = message.split("Could not reach Gemini: ", 1)[1]
    assert reason, "the reason must never be empty — that was the original bug"
    assert reason == "ReadTimeout"


async def test_gemini_gets_its_own_timeout_not_the_shared_one(mock_gemini):
    """The generous Gemini budget must actually reach the request."""
    assert settings.gemini_timeout_s > settings.request_timeout_s

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "You are on track."}]}}]},
        )

    seen = mock_gemini(handler)
    reply = await gemini.chat(
        [{"role": "user", "content": "How am I doing?"}], context_json="{}"
    )

    assert reply == "You are on track."
    assert len(seen) == 1
    timeout = seen[0].extensions.get("timeout") or {}
    assert timeout.get("read") == pytest.approx(settings.gemini_timeout_s)
