"""The real SDK speaks Gemini protocol to loopback servers, never a provider."""

import asyncio
import json
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from ce_translit import Transliterator
from ce_translit.ai import GeminiNasalResolver
from ce_translit.errors import NasalAPIError, NasalLifecycleError, NasalResponseError

pytest.importorskip("google.genai")
pytest.importorskip("uniseg")


@pytest.fixture(autouse=True)
def clean_proxy_environment(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


@pytest.fixture
def http_stub():
    servers = []

    def create():
        state = SimpleNamespace(
            requests=[],
            replies=deque(),
            received=threading.Event(),
            release=threading.Event(),
            hold=False,
        )
        lock = threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with lock:
                    state.requests.append(
                        {"path": self.path, "headers": dict(self.headers), "body": body}
                    )
                    planned = state.replies.popleft() if state.replies else None
                state.received.set()
                if state.hold:
                    state.release.wait(5)
                if planned is None:
                    payload = json.loads(body["contents"][0]["parts"][0]["text"])
                    decisions = [
                        {
                            "id": t["id"],
                            "kind": "nasalization",
                            "reason": "Local fixture.",
                        }
                        for item in payload["contexts"]
                        for t in item["targets"]
                    ]
                    if (
                        "reason"
                        not in body["generationConfig"]["responseJsonSchema"][
                            "properties"
                        ]["decisions"]["items"]["properties"]
                    ):
                        for decision in decisions:
                            del decision["reason"]
                    status, headers, result = (
                        200,
                        {},
                        {
                            "candidates": [
                                {
                                    "content": {
                                        "role": "model",
                                        "parts": [
                                            {
                                                "text": json.dumps(
                                                    {"decisions": decisions}
                                                )
                                            }
                                        ],
                                    },
                                    "finishReason": "STOP",
                                }
                            ]
                        },
                    )
                else:
                    status, headers, result = planned
                output = (
                    result if isinstance(result, bytes) else json.dumps(result).encode()
                )
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(output)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    self.wfile.write(output)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        state.url = f"http://127.0.0.1:{server.server_port}"
        servers.append((server, thread, state))
        return state

    yield create
    for server, thread, state in servers:
        state.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def convert(resolver, mode, text="сан"):
    if mode == "sync":
        with resolver:
            return Transliterator(nasal_resolver=resolver).transliterate_detailed(text)

    async def run():
        async with resolver:
            return await Transliterator(
                nasal_resolver=resolver
            ).atransliterate_detailed(text)

    return asyncio.run(run())


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_native_wire_payload_and_owned_clients_close(http_stub, mode):
    server = http_stub()
    resolver = GeminiNasalResolver("dummy-key", "test-model", server.url + "/gateway")
    text = "Начало. Сан ду. Шун ду! Конец."
    result = convert(resolver, mode, text)
    assert len(result.decisions) == 2
    assert len(server.requests) == 1
    request = server.requests[0]
    assert request["path"] == "/gateway/v1beta/models/test-model:generateContent"
    assert request["headers"]["x-goog-api-key"] == "dummy-key"
    data = json.loads(request["body"]["contents"][0]["parts"][0]["text"])
    assert [item["text"] for item in data["contexts"]] == ["Сан ду.", "Шун ду!"]
    for item in data["contexts"]:
        for target in item["targets"]:
            assert item["text"][target["start"] : target["end"]] == target["word"]
    assert request["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert request["body"]["generationConfig"]["candidateCount"] == 1
    assert "systemInstruction" in request["body"]
    assert "thinkingConfig" not in request["body"]["generationConfig"]
    assert resolver._closed
    http = resolver._http if mode == "sync" else resolver._ahttp
    assert http.is_closed


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("level", ["minimal", "low", "medium", "high", "xhigh"])
def test_reasoning_level_reaches_native_gemini_wire_config(http_stub, mode, level):
    server = http_stub()
    resolver = GeminiNasalResolver(
        "dummy", "chosen-model", server.url, thinking_level=level
    )
    assert convert(resolver, mode).text == "saŋ"
    generation = server.requests[0]["body"]["generationConfig"]
    thinking = generation["thinkingConfig"]
    assert set(thinking) in ({"thinkingLevel"}, {"thinking_level"})
    assert next(iter(thinking.values())) == level.upper()
    assert generation["responseMimeType"] == "application/json"
    assert generation["candidateCount"] == 1
    assert "responseJsonSchema" in generation


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_custom_gateway_uses_explicit_sdk_placeholder_not_environment_credentials(
    http_stub, monkeypatch, mode
):
    server = http_stub()
    monkeypatch.setenv("GOOGLE_API_KEY", "must-not-leak")
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-leak-either")
    resolver = GeminiNasalResolver(
        "local-gateway", "gateway-model", server.url, thinking_level="LOW"
    )
    assert convert(resolver, mode).text == "saŋ"
    request = server.requests[0]
    assert request["headers"]["x-goog-api-key"] == "local-gateway"
    assert request["path"] == "/v1beta/models/gateway-model:generateContent"
    assert "must-not-leak" not in json.dumps(request)


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_env_proxy_used_without_direct_dns_or_endpoint_access(
    http_stub, monkeypatch, mode
):
    proxy = http_stub()
    monkeypatch.setenv("HTTP_PROXY", proxy.url)
    resolver = GeminiNasalResolver("dummy", "m", "http://gemini.invalid")
    assert convert(resolver, mode).text == "saŋ"
    assert len(proxy.requests) == 1
    assert (
        proxy.requests[0]["path"]
        == "http://gemini.invalid/v1beta/models/m:generateContent"
    )


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("mode", ["sync", "async"])
def test_redirect_never_forwards_key_or_text(http_stub, mode, status):
    origin, other = http_stub(), http_stub()
    origin.replies.append((status, {"Location": other.url + "/leak"}, b""))
    resolver = GeminiNasalResolver("dummy-secret", "m", origin.url)
    with pytest.raises(NasalAPIError) as caught:
        convert(resolver, mode)
    assert caught.value.status_code == status
    assert len(origin.requests) == 1
    assert other.requests == []
    assert "dummy-secret" not in str(caught.value)


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_real_sdk_retries_recover_with_exact_attempt_count(
    http_stub, monkeypatch, mode
):
    server = http_stub()
    server.replies.extend(
        [(503, {"Retry-After": "0"}, {"error": {"code": 503, "message": "private"}})]
        * 2
    )
    resolver = GeminiNasalResolver("dummy", "m", server.url)
    assert convert(resolver, mode).text == "saŋ"
    assert len(server.requests) == 3


@pytest.mark.parametrize("status", [400, 401, 403, 429, 503])
@pytest.mark.parametrize("mode", ["sync", "async"])
def test_http_error_status_and_no_sensitive_message(http_stub, mode, status):
    server = http_stub()
    count = 3 if status in (429, 503) else 1
    server.replies.extend(
        [
            (
                status,
                {"Retry-After": "0"},
                {"error": {"code": status, "message": "private text"}},
            )
        ]
        * count
    )
    with pytest.raises(NasalAPIError) as caught:
        convert(GeminiNasalResolver("dummy", "m", server.url), mode)
    assert caught.value.status_code == status
    assert len(server.requests) == count
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_retry_after_does_not_retry_early(http_stub, mode):
    server = http_stub()
    server.replies.append((429, {"Retry-After": "1000"}, {"error": {"code": 429}}))
    with pytest.raises(NasalAPIError) as caught:
        convert(GeminiNasalResolver("dummy", "m", server.url), mode)
    assert caught.value.retry_after == 1000
    assert len(server.requests) == 1


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "body",
    [
        b'{"candidates":[',
        {"candidates": []},
        {"candidates": [{"content": "private invalid response"}]},
        {"candidates": [{"finishReason": "MAX_TOKENS"}]},
    ],
)
def test_invalid_sdk_response_is_not_retried(http_stub, mode, body):
    server = http_stub()
    server.replies.append((200, {}, body))
    with pytest.raises(NasalResponseError):
        convert(GeminiNasalResolver("dummy", "m", server.url), mode)
    assert len(server.requests) == 1


def test_cross_loop_use_rejected_before_request_and_owner_can_still_close(http_stub):
    server = http_stub()
    resolver = GeminiNasalResolver("dummy", "m", server.url)
    transliterator = Transliterator(nasal_resolver=resolver)
    owner = asyncio.new_event_loop()
    try:
        assert owner.run_until_complete(transliterator.atransliterate("сан")) == "saŋ"
        with pytest.raises(NasalLifecycleError, match="same event loop"):
            asyncio.run(transliterator.atransliterate("сан"))
        with pytest.raises(NasalLifecycleError, match="same event loop"):
            asyncio.run(resolver.aclose())
        assert len(server.requests) == 1
        assert not resolver._closed
        owner.run_until_complete(resolver.aclose())
        assert resolver._ahttp.is_closed
    finally:
        owner.close()


def test_async_inside_sync_context_does_not_mask_error_or_create_clients(http_stub):
    resolver = GeminiNasalResolver("dummy", "m", http_stub().url)
    with pytest.raises(NasalLifecycleError, match="async with"), resolver:
        asyncio.run(Transliterator(nasal_resolver=resolver).atransliterate("сан"))
    assert resolver._client is None and resolver._aclient is None
    assert resolver._closed


def test_concurrent_sync_first_use_creates_one_client(http_stub):
    server = http_stub()
    resolver = GeminiNasalResolver("dummy", "m", server.url)
    original = resolver._genai.Client
    created = []

    def slow(**kwargs):
        time.sleep(0.02)
        client = original(**kwargs)
        created.append(client)
        return client

    resolver._genai = SimpleNamespace(Client=slow)
    with resolver, ThreadPoolExecutor(max_workers=4) as pool:
        assert (
            list(
                pool.map(
                    lambda _: Transliterator(nasal_resolver=resolver).transliterate(
                        "сан"
                    ),
                    range(4),
                )
            )
            == ["saŋ"] * 4
        )
    assert len(created) == 1
    assert len(server.requests) == 4
    assert resolver._http.is_closed


def test_cancel_request_then_close_resources_and_reject_active_close(http_stub):
    server = http_stub()
    server.hold = True

    async def run():
        resolver = GeminiNasalResolver("dummy", "m", server.url)
        task = asyncio.create_task(
            Transliterator(nasal_resolver=resolver).atransliterate("сан")
        )
        try:
            assert await asyncio.to_thread(server.received.wait, 3)
            with pytest.raises(NasalLifecycleError, match="active"):
                await resolver.aclose()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            server.release.set()
            await resolver.aclose()
        assert resolver._ahttp.is_closed

    asyncio.run(run())


def test_async_and_sync_modes_share_one_public_resolver(http_stub):
    server = http_stub()
    resolver = GeminiNasalResolver("dummy", "m", server.url)

    async def run():
        async with resolver:
            assert (
                await Transliterator(nasal_resolver=resolver).atransliterate("сан")
                == "saŋ"
            )
            assert (
                await asyncio.to_thread(
                    Transliterator(nasal_resolver=resolver).transliterate, "сан"
                )
                == "saŋ"
            )

    asyncio.run(run())
    assert resolver._http.is_closed and resolver._ahttp.is_closed


def test_close_cancellation_finishes_cleanup_before_propagating():
    async def run():
        resolver = GeminiNasalResolver("dummy", "m")
        started, release = asyncio.Event(), asyncio.Event()
        closed = []

        async def slow_close():
            started.set()
            await release.wait()
            closed.append(True)

        resolver._ahttp = SimpleNamespace(aclose=slow_close)
        task = asyncio.create_task(resolver.aclose())
        await started.wait()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed and resolver._closed

    asyncio.run(run())


def test_repeated_close_cancellation_never_cancels_the_cleanup_task():
    async def run():
        resolver = GeminiNasalResolver("dummy", "m")
        started, release = asyncio.Event(), asyncio.Event()
        completed = []

        async def slow_close():
            started.set()
            await release.wait()
            completed.append(True)

        resolver._ahttp = SimpleNamespace(aclose=slow_close)
        task = asyncio.create_task(resolver.aclose())
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert completed and resolver._cleanup_complete
        await resolver.aclose()

    asyncio.run(run())


def test_failed_cleanup_can_be_retried_but_closed_resolver_cannot_be_reused():
    async def run():
        resolver = GeminiNasalResolver("dummy", "m")
        calls = []

        async def close_once_fails():
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError("Cleanup failed")

        resolver._ahttp = SimpleNamespace(aclose=close_once_fails)
        with pytest.raises(RuntimeError, match="Cleanup failed"):
            await resolver.aclose()
        assert resolver._closed and not resolver._cleanup_complete
        with pytest.raises(NasalLifecycleError):
            await resolver.aresolve("", ())
        await resolver.aclose()
        assert len(calls) == 2 and resolver._cleanup_complete

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_retry_after_metadata_survives_the_last_allowed_attempt(http_stub, mode):
    server = http_stub()
    server.replies.extend(
        [
            (429, {"Retry-After": "0"}, {"error": {"code": 429}}),
            (429, {"Retry-After": "0"}, {"error": {"code": 429}}),
            (429, {"Retry-After": "3600"}, {"error": {"code": 429}}),
        ]
    )
    with pytest.raises(NasalAPIError) as caught:
        convert(GeminiNasalResolver("dummy", "m", server.url), mode)
    assert caught.value.retry_after == 3600
    assert len(server.requests) == 3


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("include_reasons", [False, True])
def test_reason_mode_reaches_native_schema_without_affecting_low_thinking(
    http_stub, mode, include_reasons
):
    server = http_stub()
    resolver = GeminiNasalResolver(
        "dummy",
        "test-model",
        server.url,
        thinking_level="low",
        include_reasons=include_reasons,
    )
    source = "са\u0301н\u0301"
    result = convert(resolver, mode, source)
    assert result.text == "saŋ"
    assert result.decisions[0].word == source
    assert (result.decisions[0].reason is not None) == include_reasons
    body = server.requests[0]["body"]
    generation = body["generationConfig"]
    assert list(generation["thinkingConfig"].values()) == ["LOW"]
    fields = generation["responseJsonSchema"]["properties"]["decisions"]["items"]
    assert ("reason" in fields["required"]) == include_reasons
    assert ("reason" in fields["properties"]) == include_reasons
    prompt = body["systemInstruction"]["parts"][0]["text"]
    assert ("Объяснение каждого решения" in prompt) == include_reasons
