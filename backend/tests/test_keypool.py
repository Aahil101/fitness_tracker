"""Failover across several API keys per provider.

One key per provider made every AI feature depend on a single credential staying
healthy, which on Gemini's free tier it does not: twenty generate_content calls a
day, shared between the coach, insights and food logging, and a model can be
withdrawn from one project while still serving another. When the key ran dry the
photo path returned an error and text logging fell to Groq for the rest of the
day.

So keys are a pool: a call takes a healthy key, and a failure that a different
key could survive moves on to the next one. The distinctions that matter, and
that these tests pin down, are which failures are worth another key (quota, auth,
a withdrawn model, a 5xx) and which are the request's own fault and would fail
identically on all of them.
"""

from __future__ import annotations

import httpx
import pytest

from app import http as app_http
from app.config import settings
from app.errors import UpstreamError
from app.services import gemini, groq, keypool
from app.services.keypool import KeyPool

OK = {"candidates": [{"content": {"parts": [{"text": '{"items": []}'}]}}]}
QUOTA = {"error": {"code": 429, "message": "Quota exceeded for this project."}}
REJECTED = {"error": {"code": 403, "message": "API key not valid."}}
WITHDRAWN = {
    "error": {
        "code": 404,
        "message": "models/gemini-2.5-flash is no longer available to new users.",
    }
}
OVERLOADED = {"error": {"code": 503, "message": "The model is overloaded."}}


@pytest.fixture
def five_keys(monkeypatch: pytest.MonkeyPatch):
    """Five Gemini keys and a transport that answers per key.

    The handler is given the key the request carried, so a test can say "the
    first two are exhausted, the third works" and then assert which keys were
    tried and in what order — which is the whole behaviour under test.
    """
    monkeypatch.setattr(settings, "gemini_api_key", "key-one")
    monkeypatch.setattr(settings, "gemini_api_keys", "key-two,key-three,key-four,key-five")
    monkeypatch.setattr(gemini, "RETRY_DELAY_S", 0)

    def install(reply):
        tried: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            key = request.headers.get("x-goog-api-key", "")
            tried.append(key)
            return reply(key)

        monkeypatch.setattr(
            app_http, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        return tried

    return install


# --- what deserves another key ---------------------------------------------


@pytest.mark.parametrize(
    ("status", "message", "reason_fragment"),
    [
        (429, "Quota exceeded for this project.", "quota"),
        (403, "API key not valid.", "auth"),
        (401, "Unauthorized", "auth"),
        (404, "is no longer available to new users", "model unavailable"),
        (503, "The model is overloaded.", "provider error"),
        (500, "Internal error", "provider error"),
    ],
)
def test_provider_side_failures_are_worth_trying_another_key(
    status: int, message: str, reason_fragment: str
) -> None:
    verdict = keypool.classify(status, message)
    assert verdict is not None, f"{status} should move to the next key"
    reason, seconds = verdict
    assert reason_fragment in reason
    assert seconds > 0


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (400, "Invalid JSON payload received."),
        (400, "Request contains an invalid argument."),
        (422, "Unprocessable content."),
        (None, "Gemini blocked the request (SAFETY)."),
        (None, "Gemini returned no candidates."),
        (200, "Gemini did not return valid JSON for the photo."),
    ],
)
def test_the_requests_own_faults_do_not_burn_the_pool(status: int | None, message: str) -> None:
    """A malformed or blocked request fails the same way on all five keys.

    Retrying it would spend the entire day's allowance on one bad request and
    still show the user the same error, five times slower.
    """
    assert keypool.classify(status, message) is None


def test_a_quota_refusal_benches_for_longer_than_a_blip() -> None:
    """The two are not the same kind of wait, and treating them alike is costly.

    A daily quota will not have reset in a minute, so re-checking that often
    spends a request per attempt to learn nothing. An overloaded model usually
    clears in seconds, so benching it for an hour throws away a working key.
    """
    quota = keypool.classify(429, "quota")
    transient = keypool.classify(503, "overloaded")
    auth = keypool.classify(403, "bad key")
    assert quota and transient and auth
    assert transient[1] < quota[1] < auth[1]


# --- the pool itself --------------------------------------------------------


def test_duplicate_and_blank_keys_are_dropped() -> None:
    """GEMINI_API_KEYS commonly repeats GEMINI_API_KEY; that is not two keys.

    A duplicate would be benched twice for the same quota and reported as two
    keys available when there is one.
    """
    pool = KeyPool.from_values("gemini", ["a", "  a  ", "", "   ", "b"])
    assert [key.value for key in pool.keys] == ["a", "b"]
    assert pool.size == 2


def test_load_moves_on_after_a_success_instead_of_hammering_the_first_key() -> None:
    """Always starting at key one exhausts it, then starts on key two.

    That wastes the pool's usefulness: the first key absorbs the whole daily
    allowance and its 429s are paid for in latency on every later request.
    """
    pool = KeyPool.from_values("gemini", ["a", "b", "c"])
    used = []
    for _ in range(4):
        key = pool.healthy()[0]
        used.append(key.value)
        pool.note_success(key)
    assert used == ["a", "b", "c", "a"]


def test_a_benched_key_is_skipped_until_its_cooldown_expires() -> None:
    pool = KeyPool.from_values("gemini", ["a", "b"])
    pool.bench(pool.keys[0], "quota reached", 3600)

    assert [key.value for key in pool.healthy()][0] == "b"
    assert pool.available == 1


def test_an_exhausted_pool_still_offers_its_least_bad_key() -> None:
    """Benched is a guess about the future, so a hopeless call beats a certain one.

    Every key benched on quota at 23:59 means every key is usable again at
    00:00, and the bench is an hour long. Refusing to call at all would keep the
    feature down until something re-checked; trying anyway costs one request and
    recovers by itself.
    """
    pool = KeyPool.from_values("gemini", ["a", "b"])
    for key in pool.keys:
        pool.bench(key, "quota reached", 3600)

    assert pool.available == 0
    assert len(pool.healthy()) == 2, "still returns candidates, worst-ranked"


def test_a_success_clears_an_earlier_bench() -> None:
    pool = KeyPool.from_values("gemini", ["a"])
    pool.bench(pool.keys[0], "quota reached", 3600)
    pool.note_success(pool.keys[0])
    assert pool.available == 1


def test_rebuilding_only_happens_when_the_configured_keys_change() -> None:
    """Health lives in the pool, so rebuilding it forgets which keys are spent.

    get_pool is called on every request. If it rebuilt each time, a key benched
    for the day would be retried on the next call, and the 429s would come back
    on every single request.
    """
    first = keypool.get_pool("gemini", ["a", "b"])
    keypool.get_pool("gemini", ["a", "b"]).bench(first.keys[0], "quota reached", 3600)

    assert keypool.get_pool("gemini", ["a", "b"]) is first, "same keys, same pool"
    assert keypool.get_pool("gemini", ["a", "b"]).available == 1, "bench survived"
    assert keypool.get_pool("gemini", ["a", "b", "c"]) is not first, "new key, new pool"


def test_status_identifies_keys_without_printing_them() -> None:
    """This is served over HTTP by /api/ai/status, so it must not carry secrets."""
    secret = "AQ.Ab8RN6ThisIsNotARealKeyButLooksLikeOne1234"
    pool = keypool.get_pool("gemini", [secret])
    pool.bench(pool.keys[0], "quota reached", 3600)

    rendered = repr(keypool.all_status())
    assert secret not in rendered
    assert secret[8:-8] not in rendered, "no long fragment of the key either"

    status = pool.status()
    assert status["keys"] == 1
    assert status["available"] == 0
    assert status["detail"][0]["state"] == "benched"
    assert status["detail"][0]["benched_for_s"] > 0


# --- the pool as the transport actually uses it -----------------------------


async def test_an_exhausted_key_hands_over_to_the_next_one(five_keys) -> None:
    """The point of the whole thing: a dry key must not surface to the user."""
    tried = five_keys(
        lambda key: httpx.Response(200, json=OK)
        if key == "key-three"
        else httpx.Response(429, json=QUOTA)
    )

    assert await gemini.recognise_food(b"\xff\xd8\xff jpeg") == {"items": []}
    assert tried == ["key-one", "key-two", "key-three"], "stops at the first that works"

    pool = keypool.get_pool("gemini", settings.gemini_key_list)
    assert pool.available == 3, "the two dry keys are benched, the rest untouched"


async def test_a_revoked_key_does_not_take_the_feature_down(five_keys) -> None:
    tried = five_keys(
        lambda key: httpx.Response(403, json=REJECTED)
        if key == "key-one"
        else httpx.Response(200, json=OK)
    )

    assert await gemini.recognise_food(b"\xff\xd8\xff jpeg") == {"items": []}
    assert tried == ["key-one", "key-two"]


async def test_a_model_withdrawn_from_one_project_is_tried_on_another(five_keys) -> None:
    """Not hypothetical: 2.5-flash answers older keys and 404s newer ones.

    Four keys added to this app hit "no longer available to new users" on a model
    the existing key served fine. A 404 that reads that way is about the project,
    not the request, so it is worth another key.
    """
    tried = five_keys(
        lambda key: httpx.Response(404, json=WITHDRAWN)
        if key in {"key-one", "key-two"}
        else httpx.Response(200, json=OK)
    )

    assert await gemini.recognise_food(b"\xff\xd8\xff jpeg") == {"items": []}
    assert tried == ["key-one", "key-two", "key-three"]


async def test_a_bad_request_is_refused_once_not_five_times(five_keys) -> None:
    tried = five_keys(
        lambda _: httpx.Response(400, json={"error": {"message": "Invalid argument."}})
    )

    with pytest.raises(UpstreamError):
        await gemini.recognise_food(b"\xff\xd8\xff jpeg")

    assert tried == ["key-one"], "the request was wrong; other keys cannot help"


async def test_every_key_dry_reports_the_provider_error_not_a_pool_error(five_keys) -> None:
    """The caller's own fallback — Groq, or the offline reply — has to still fire.

    That depends on the error looking like the provider being unavailable. An
    exception about key management would be shown to a user who cannot act on it.
    """
    tried = five_keys(lambda _: httpx.Response(429, json=QUOTA))

    with pytest.raises(UpstreamError) as caught:
        await gemini.recognise_food(b"\xff\xd8\xff jpeg")

    assert len(tried) == 5, "every key gets a turn before giving up"
    message = str(caught.value)
    assert "quota" in message.lower()
    assert "key-" not in message and "pool" not in message.lower()


async def test_the_bench_is_remembered_across_calls(five_keys) -> None:
    """Otherwise every request pays for the same 429s again.

    The second call does not simply repeat the first: a success advances the
    rotation, so it starts further along the pool. What must hold is that the
    key already known to be dry is not asked a second time.
    """
    tried = five_keys(
        lambda key: httpx.Response(200, json=OK)
        if key == "key-two"
        else httpx.Response(429, json=QUOTA)
    )

    await gemini.recognise_food(b"\xff\xd8\xff jpeg")
    assert tried == ["key-one", "key-two"]

    tried.clear()
    await gemini.recognise_food(b"\xff\xd8\xff jpeg")
    assert "key-one" not in tried, "already benched; asking again wastes a request"
    assert tried[-1] == "key-two", "and the working key is still found"

    # By the third call every dry key has been benched, so it goes straight there.
    tried.clear()
    await gemini.recognise_food(b"\xff\xd8\xff jpeg")
    assert tried == ["key-two"], "the pool has settled on the only key that works"


async def test_a_transient_503_is_retried_on_the_same_key_before_moving_on(five_keys) -> None:
    """Overload clears in seconds, so the cheap fix comes first.

    Moving to the next key immediately would burn the pool on a wobble that a
    0.8s wait fixes; never moving on would fail while four keys sat idle. So:
    retry in place, then hand over.
    """
    seen: dict[str, int] = {}

    def reply(key: str) -> httpx.Response:
        seen[key] = seen.get(key, 0) + 1
        if key == "key-two":
            return httpx.Response(200, json=OK)
        return httpx.Response(503, json=OVERLOADED)

    five_keys(reply)

    assert await gemini.recognise_food(b"\xff\xd8\xff jpeg") == {"items": []}
    assert seen["key-one"] == gemini.MAX_ATTEMPTS, "retried in place first"
    assert seen["key-two"] == 1


# --- Groq, which has its own pool ------------------------------------------


async def test_groq_keys_fail_over_independently_of_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Separate pools: a spent Gemini key must not bench a healthy Groq one."""
    monkeypatch.setattr(settings, "groq_api_key", "groq-one")
    monkeypatch.setattr(settings, "groq_api_keys", "groq-two")

    tried: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        tried.append(token)
        if token == "groq-one":
            return httpx.Response(429, json={"error": {"message": "Rate limit reached"}})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"items": []}'}}]}
        )

    monkeypatch.setattr(
        app_http, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    assert await groq.parse_meal_text("two rotis") == {"items": []}
    assert tried == ["groq-one", "groq-two"]

    pools = {status["provider"]: status for status in keypool.all_status()}
    assert pools["groq"]["available"] == 1
    assert "gemini" not in pools, "an unused provider has no pool to bench"



# --- the grounded brand lookup, which shares the same pool ------------------


async def test_a_brand_lookup_never_puts_the_key_in_the_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """httpx logs the full URL of every request at INFO level.

    This call used to pass the credential as ``?key=...``, so each Domino's
    lookup wrote a live API key into the Render log, in plain text, where anyone
    with log access could read it. Nothing about the call failed, which is why it
    went unnoticed. The key belongs in a header.
    """
    from app.services import restaurant

    monkeypatch.setattr(settings, "gemini_api_key", "secret-brand-key")

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": '{"found": false}'}]}},
                ]
            },
        )

    monkeypatch.setattr(
        app_http, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    await restaurant.lookup_published("dominos margherita", "Domino's")

    assert seen, "the lookup should have been attempted"
    assert "secret-brand-key" not in str(seen[0].url)
    assert seen[0].headers["x-goog-api-key"] == "secret-brand-key"


async def test_a_grounded_refusal_does_not_bench_a_key_for_ordinary_calls(
    five_keys,
) -> None:
    """Search grounding is not part of Gemini's free tier at all.

    Every key answers a grounded request with 429 RESOURCE_EXHAUSTED in about
    120ms while answering plain generateContent perfectly — verified against the
    live API on all five. So a grounded 429 says nothing about whether that key
    can still serve the coach, and treating it as if it did poisoned the pool:
    one Domino's lookup benched all five keys for an hour, and /api/ai/status
    then reported nothing available while every key was in fact working.
    """
    from app.services import restaurant

    five_keys(lambda _: httpx.Response(429, json=QUOTA))

    assert await restaurant.lookup_published("dominos farmhouse", "Domino's") is None

    pool = keypool.get_pool("gemini", settings.gemini_key_list)
    assert pool.available == 5, "the keys are fine for everything except grounding"


async def test_grounding_refused_by_the_whole_pool_stops_being_attempted(
    five_keys,
) -> None:
    """Otherwise every branded item costs five wasted calls and about 1.5s.

    Rediscovering a missing capability on each pizza is pure latency: the answer
    will not change until someone enables billing.
    """
    from app.services import restaurant

    tried = five_keys(lambda _: httpx.Response(429, json=QUOTA))

    assert await restaurant.lookup_published("dominos farmhouse", "Domino's") is None
    assert len(tried) == 5
    assert not restaurant.grounding_available()

    tried.clear()
    assert await restaurant.lookup_published("dominos peppy paneer", "Domino's") is None
    assert tried == [], "no further calls while grounding is known to be unavailable"

    restaurant.reset_grounding_backoff()
    assert await restaurant.lookup_published("dominos farmhouse", "Domino's") is None
    assert len(tried) == 5, "and it can be turned back on, for when billing is enabled"


async def test_one_bad_request_does_not_disable_grounding(five_keys) -> None:
    """A refused request is about the request, not about the capability.

    It stops after one key, because the other four would refuse it identically —
    but it must not conclude that grounding is gone, or a single malformed
    description would turn the feature off for six hours.
    """
    from app.services import restaurant

    tried = five_keys(
        lambda _: httpx.Response(400, json={"error": {"message": "Invalid argument."}})
    )

    assert await restaurant.lookup_published("dominos farmhouse", "Domino's") is None
    assert len(tried) == 1
    assert restaurant.grounding_available(), "one bad request is not a missing feature"


async def test_a_failed_brand_lookup_returns_none_rather_than_raising(five_keys) -> None:
    """The caller has better fallbacks than an error message.

    _resolve_branded has a checked menu table and a model estimate to fall back
    to, and an approximate pizza beats a failed meal log. This used to raise
    "Nutrition lookup limit reached for today", which the caller caught and
    logged — so the behaviour was already this, by accident, through an exception
    path that also read as if the user had done something wrong.
    """
    from app.services import restaurant

    five_keys(lambda _: httpx.Response(429, json=QUOTA))
    assert await restaurant.lookup_published("dominos farmhouse", "Domino's") is None
