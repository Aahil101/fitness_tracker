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
    """Swap the shared httpx client for a scripted transport, recording requests.

    Exactly one fake key is set. Two reasons it is explicit. Inheriting one from
    backend/.env made these tests pass locally and fail in CI, where no key
    exists and _post bails out with ConfigurationError before the transport is
    ever reached. And the count of requests is what several of these tests
    assert: _post now walks a pool of keys, so a five-key pool turns "a 403 is
    not retried, so one request" into five.
    """
    monkeypatch.setattr(settings, "gemini_api_key", "test-key-not-a-real-one")
    monkeypatch.setattr(settings, "gemini_api_keys", "")

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



OVERLOADED = {
    "error": {
        "code": 503,
        "message": "The model is overloaded. Please try again later.",
        "status": "UNAVAILABLE",
    }
}


async def test_503_overloaded_is_retried_and_then_succeeds(mock_gemini, monkeypatch):
    """Photo recognition failed outright on Gemini's 'high demand' 503."""
    monkeypatch.setattr(gemini, "RETRY_DELAY_S", 0)
    queue = [
        httpx.Response(503, json=OVERLOADED),
        httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": '{"items": []}'}]}}]},
        ),
    ]
    seen = mock_gemini(lambda _: queue.pop(0))

    result = await gemini.recognise_food(b"\xff\xd8\xff jpeg bytes")

    assert len(seen) == 2, "should have retried the 503 exactly once"
    assert result == {"items": []}


async def test_persistent_503_explains_itself_without_leaking_json(mock_gemini, monkeypatch):
    monkeypatch.setattr(gemini, "RETRY_DELAY_S", 0)
    seen = mock_gemini(lambda _: httpx.Response(503, json=OVERLOADED))

    with pytest.raises(UpstreamError) as caught:
        await gemini.recognise_food(b"\xff\xd8\xff jpeg bytes")

    assert len(seen) == gemini.MAX_ATTEMPTS, "should stop after the attempt budget"
    message = str(caught.value)
    assert "overloaded" in message.lower()
    assert "try again" in message.lower()
    assert "manually" in message.lower(), "offer the manual path when AI is unavailable"
    assert "candidates" not in message and "{" not in message


async def test_real_errors_are_not_retried(mock_gemini, monkeypatch):
    """A rejected key is final — retrying wastes the user's time."""
    monkeypatch.setattr(gemini, "RETRY_DELAY_S", 0)
    seen = mock_gemini(lambda _: httpx.Response(403, json={"error": {"message": "bad key"}}))

    with pytest.raises(UpstreamError, match="rejected the API key"):
        await gemini.recognise_food(b"\xff\xd8\xff jpeg bytes")

    assert len(seen) == 1, "403 must not be retried"
