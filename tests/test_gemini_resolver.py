import asyncio
import json
from types import SimpleNamespace

import pytest

from ce_translit import Transliterator
from ce_translit.ai import GeminiNasalResolver, _gemini
from ce_translit.errors import (
    NasalAPIError,
    NasalInputError,
    NasalLifecycleError,
    NasalResponseError,
)

httpx = pytest.importorskip("httpx")
errors = pytest.importorskip("google.genai.errors")
types = pytest.importorskip("google.genai.types")


def response(payload, finish="STOP"):
    return SimpleNamespace(
        candidates=[SimpleNamespace(finish_reason=finish)], text=json.dumps(payload)
    )


def valid_response(kwargs):
    targets = request_targets(kwargs)
    return response(
        {
            "decisions": [
                {"id": t["id"], "kind": "nasalization", "reason": "Context."}
                for t in reversed(targets)
            ]
        }
    )


def request_targets(kwargs):
    return [
        target
        for item in json.loads(kwargs["contents"])["contexts"]
        for target in item["targets"]
    ]


@pytest.fixture
def sdk(monkeypatch):
    state = SimpleNamespace(
        clients=[], calls=[], outcomes=[], sync_closed=0, async_closed=0
    )

    def generate(**kwargs):
        state.calls.append(kwargs)
        outcome = state.outcomes.pop(0) if state.outcomes else valid_response
        if isinstance(outcome, Exception):
            raise outcome
        return outcome(kwargs) if callable(outcome) else outcome

    async def agenerate(**kwargs):
        await asyncio.sleep(0)
        return generate(**kwargs)

    def close():
        state.sync_closed += 1

    async def aclose():
        state.async_closed += 1

    def make_client(**kwargs):
        state.clients.append(kwargs)
        return SimpleNamespace(
            models=SimpleNamespace(generate_content=generate),
            close=close,
            aio=SimpleNamespace(
                models=SimpleNamespace(generate_content=agenerate), aclose=aclose
            ),
        )

    import google.genai

    monkeypatch.setattr(google.genai, "Client", make_client)
    return state


def resolver(**kwargs):
    return GeminiNasalResolver(
        api_key="explicit-secret", model="chosen-model", **kwargs
    )


def test_explicit_settings_schema_and_lazy_sdk(sdk, monkeypatch):
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_GEMINI_BASE_URL", "https://wrong.example")
    with resolver() as r:
        assert not sdk.clients
        result = Transliterator(nasal_resolver=r).transliterate_detailed("сан сан")
        assert result.text == "saŋ saŋ"
        assert [d.id for d in result.decisions] == ["N000001", "N000002"]
        kwargs = sdk.clients[0]
        assert kwargs["api_key"] == "explicit-secret"
        assert kwargs["enterprise"] is False
        options = kwargs["http_options"]
        assert options.base_url == "https://generativelanguage.googleapis.com"
        assert options.timeout == 60_000
        assert options.api_version == "v1beta"
        assert options.retry_options.attempts == 1
        assert isinstance(options.httpx_client, httpx.Client)
        assert options.httpx_client.follow_redirects is False
        assert "transport" not in options.async_client_args
        config = sdk.calls[0]["config"]
        assert config.response_mime_type == "application/json"
        assert config.response_json_schema == _gemini._SCHEMA
        assert config.automatic_function_calling.disable
    assert sdk.sync_closed == 1


def test_proxy_base_url_and_timeout_are_forwarded(sdk):
    with resolver(base_url="http://localhost:8317/", timeout=12.5) as r:
        assert Transliterator(nasal_resolver=r).transliterate("сан") == "saŋ"
    options = sdk.clients[0]["http_options"]
    assert options.base_url == "http://localhost:8317"
    assert options.timeout == 12_500


def test_thinking_level_uses_native_sdk_config_without_extra_body(sdk):
    with resolver(thinking_level=" high ") as r:
        Transliterator(nasal_resolver=r).transliterate("сан")
    config = sdk.calls[0]["config"]
    assert config.thinking_config.thinking_level == "HIGH"
    assert config.http_options is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"api_key": ""},
        {"api_key": None},
        {"model": " "},
        {"timeout": 0},
        {"timeout": float("nan")},
        {"timeout": float("inf")},
        {"timeout": True},
        {"base_url": "ftp://example.test"},
        {"base_url": "https://user:secret@example.test"},
        {"base_url": "http://example.test/v1"},
        {"base_url": "http://example.test/v1beta/"},
        {"base_url": "http://example.test?secret=key"},
        {"thinking_level": ""},
        {"thinking_level": "automatic"},
        {"thinking_level": 100},
        {"thinking_level": True},
    ],
)
def test_invalid_settings_fail_before_client_construction(sdk, kwargs):
    config = {"api_key": "key", "model": "model", **kwargs}
    with pytest.raises(ValueError):
        GeminiNasalResolver(**config)
    assert not sdk.clients


def test_no_targets_no_sdk_client_or_requests(sdk):
    with resolver() as r:
        assert Transliterator(nasal_resolver=r).transliterate("слово") == "slovo"
        assert r.resolve("", ()) == ()
    assert not sdk.clients
    assert not sdk.calls


def test_transport_retries_are_bounded_and_do_not_expose_provider_errors(
    sdk, monkeypatch
):
    sleeps = []
    monkeypatch.setattr(_gemini.time, "sleep", sleeps.append)
    sdk.outcomes = [httpx.ReadTimeout("sensitive text and key")] * 3
    with resolver() as r, pytest.raises(NasalAPIError) as caught:
        Transliterator(nasal_resolver=r).transliterate("сан")
    assert len(sdk.calls) == 3
    assert sleeps == [1, 2]
    assert "sensitive" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("code", [408, 429, 500, 503])
def test_retryable_api_statuses_can_recover(sdk, monkeypatch, code):
    sleeps = []
    monkeypatch.setattr(_gemini.time, "sleep", sleeps.append)
    sdk.outcomes = [
        errors.APIError(code, {"error": {"message": "private"}}),
        valid_response,
    ]
    with resolver() as r:
        assert Transliterator(nasal_resolver=r).transliterate("сан") == "saŋ"
    assert sleeps == [1]
    assert len(sdk.calls) == 2


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_nonretryable_api_errors_preserve_status_only(sdk, monkeypatch, code):
    monkeypatch.setattr(
        _gemini.time, "sleep", lambda value: pytest.fail("Unexpected retry.")
    )
    sdk.outcomes = [errors.ClientError(code, {"error": {"message": "private source"}})]
    with resolver() as r, pytest.raises(NasalAPIError) as caught:
        Transliterator(nasal_resolver=r).transliterate("сан")
    assert caught.value.status_code == code
    assert "private" not in str(caught.value)
    assert len(sdk.calls) == 1


@pytest.mark.parametrize(
    "value,expected", [("5", 5), ("-2", 0), ("garbage", 1), ("nan", 1)]
)
def test_retry_after_is_respected(sdk, monkeypatch, value, expected):
    sleeps = []
    monkeypatch.setattr(_gemini.time, "sleep", sleeps.append)
    sdk.outcomes = [
        errors.ClientError(
            429, {}, response=httpx.Response(429, headers={"Retry-After": value})
        )
    ]
    with resolver() as r:
        Transliterator(nasal_resolver=r).transliterate("сан")
    assert sleeps == [expected]


def test_long_retry_after_fails_without_retrying_early(sdk, monkeypatch):
    monkeypatch.setattr(
        _gemini.time, "sleep", lambda _: pytest.fail("Unexpected sleep.")
    )
    sdk.outcomes = [
        errors.ClientError(
            429, {}, response=httpx.Response(429, headers={"Retry-After": "1000"})
        )
    ]
    with resolver() as r, pytest.raises(NasalAPIError) as caught:
        Transliterator(nasal_resolver=r).transliterate("сан")
    assert caught.value.status_code == 429
    assert caught.value.retry_after == 1000
    assert len(sdk.calls) == 1


def test_http_date_retry_after():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    when = format_datetime(
        datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True
    )
    error = errors.ClientError(
        429, {}, response=httpx.Response(429, headers={"Retry-After": when})
    )
    assert 28 <= _gemini._retry_delay(error, 0) <= 30


@pytest.mark.parametrize(
    "bad",
    [
        response({"decisions": []}),
        response({"decisions": "wrong"}),
        response([]),
        response(
            {"decisions": [{"id": "N000001", "kind": "wrong", "reason": "reason"}]}
        ),
        response(
            {"decisions": [{"id": "N000001", "kind": "nasalization", "reason": " "}]}
        ),
        response(
            {
                "decisions": [
                    {"id": "unexpected", "kind": "nasalization", "reason": "reason"}
                ]
            }
        ),
        response(
            {
                "decisions": [
                    {
                        "id": "N000001",
                        "kind": "nasalization",
                        "reason": "reason",
                        "extra": 1,
                    }
                ]
            }
        ),
        response({"decisions": []}, finish="MAX_TOKENS"),
        response({}, finish="SAFETY"),
        SimpleNamespace(candidates=[], text="{}"),
        SimpleNamespace(
            candidates=[SimpleNamespace(finish_reason="STOP")], text="not JSON"
        ),
        SimpleNamespace(candidates=[SimpleNamespace(finish_reason="STOP")], text=None),
        SimpleNamespace(
            candidates=[SimpleNamespace(finish_reason="STOP")],
            text='{"decisions": [], "decisions": []}',
        ),
    ],
)
def test_invalid_responses_are_not_retried(sdk, bad):
    sdk.outcomes = [bad]
    with resolver() as r, pytest.raises(NasalResponseError):
        Transliterator(nasal_resolver=r).transliterate("сан")
    assert len(sdk.calls) == 1


def test_duplicate_ids_with_matching_count_are_rejected(sdk):
    row = {"id": "N000001", "kind": "nasalization", "reason": "reason"}
    sdk.outcomes = [response({"decisions": [row, row]})]
    with resolver() as r, pytest.raises(NasalResponseError):
        Transliterator(nasal_resolver=r).transliterate("сан сан")


def test_sdk_decode_errors_are_response_failures_not_retries(sdk):
    sdk.outcomes = [json.JSONDecodeError("Invalid JSON", "private response", 0)]
    with resolver() as r, pytest.raises(NasalResponseError):
        Transliterator(nasal_resolver=r).transliterate("сан")
    assert len(sdk.calls) == 1


@pytest.mark.parametrize(
    "error", [TypeError("Internal bug"), ValueError("Internal bug")]
)
def test_internal_programming_errors_are_not_masked_as_api_errors(sdk, error):
    sdk.outcomes = [error]
    with resolver() as r, pytest.raises(type(error), match="Internal bug"):
        Transliterator(nasal_resolver=r).transliterate("сан")
    assert len(sdk.calls) == 1


def test_multiple_blocks_processed_once_and_later_failure_returns_no_result(sdk):
    text = " ".join(["сан"] * 130)
    with resolver() as r:
        result = Transliterator(nasal_resolver=r).transliterate_detailed(text)
        assert len(result.decisions) == 130
    assert [len(request_targets(c)) for c in sdk.calls] == [64, 64, 2]
    sdk.calls.clear()
    sdk.outcomes = [valid_response, response({"decisions": []})]
    with resolver() as r, pytest.raises(NasalResponseError):
        Transliterator(nasal_resolver=r).transliterate(text)
    assert len(sdk.calls) == 2


def test_long_bad_input_rejected_before_any_api_request(sdk):
    with resolver() as r, pytest.raises(NasalInputError):
        Transliterator(nasal_resolver=r).transliterate("сан " + "а" * 12_000 + "н")
    assert not sdk.calls
    assert not sdk.clients


def test_sync_context_closes_after_failure_and_close_is_idempotent(sdk):
    r = resolver()
    with pytest.raises(RuntimeError), r:
        Transliterator(nasal_resolver=r).transliterate("сан")
        raise RuntimeError("Caller error.")
    r.close()
    assert sdk.sync_closed == 1
    with pytest.raises(NasalLifecycleError):
        r.resolve("сан", Transliterator()._targets("сан"))


def test_async_requests_use_async_path_and_close_both_clients(sdk):
    async def run():
        async with resolver() as r:
            result = await Transliterator(nasal_resolver=r).atransliterate_detailed(
                "сан сан"
            )
            assert result.text == "saŋ saŋ"
            with pytest.raises(RuntimeError, match="aclose"):
                r.close()
        await r.aclose()

    asyncio.run(run())
    assert sdk.async_closed == sdk.sync_closed == 1


def test_async_retry_sleep_does_not_block_or_use_sync_sleep(sdk, monkeypatch):
    sleeps = []
    original_sleep = asyncio.sleep

    async def sleep(value):
        if value:
            sleeps.append(value)
        await original_sleep(0)

    monkeypatch.setattr(_gemini.asyncio, "sleep", sleep)
    monkeypatch.setattr(
        _gemini.time, "sleep", lambda value: pytest.fail("Blocking sleep.")
    )
    sdk.outcomes = [httpx.ConnectError("private"), valid_response]

    async def run():
        async with resolver() as r:
            assert await Transliterator(nasal_resolver=r).atransliterate("сан") == "saŋ"

    asyncio.run(run())
    assert sleeps == [1]


def test_real_sdk_response_finish_enum_and_text_parts(sdk):
    sdk.outcomes = [
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    finish_reason=types.FinishReason.STOP,
                    content=types.Content(
                        parts=[
                            types.Part(
                                text=json.dumps(
                                    {
                                        "decisions": [
                                            {
                                                "id": "N000001",
                                                "kind": "undetermined",
                                                "reason": "Not enough context.",
                                            }
                                        ]
                                    }
                                )
                            )
                        ]
                    ),
                )
            ]
        )
    ]
    with resolver() as r:
        result = Transliterator(nasal_resolver=r).transliterate_detailed("шун")
    assert result.text == "şun"
    assert result.decisions[0].kind == "undetermined"


@pytest.mark.parametrize("asynchronous", [False, True])
def test_compact_resolver_omits_reasons_and_preserves_original_spans(sdk, asynchronous):
    def compact(kwargs):
        return response(
            {
                "decisions": [
                    {"id": t["id"], "kind": "nasalization"}
                    for t in reversed(request_targets(kwargs))
                ]
            }
        )

    sdk.outcomes = [compact]
    source = "са\u0301н\u0301 сан"
    if asynchronous:

        async def run():
            async with resolver(include_reasons=False, thinking_level="low") as r:
                return await Transliterator(nasal_resolver=r).atransliterate_detailed(
                    source
                )

        result = asyncio.run(run())
    else:
        with resolver(include_reasons=False, thinking_level="low") as r:
            converter = Transliterator(nasal_resolver=r)
            result = converter.transliterate_detailed(source)
    assert result.text == "saŋ saŋ"
    assert all(
        d.reason is None and source[d.start : d.end] == d.word for d in result.decisions
    )
    config = sdk.calls[0]["config"]
    item = config.response_json_schema["properties"]["decisions"]["items"]
    assert set(item["properties"]) == {"id", "kind"}
    assert item["required"] == ["id", "kind"]
    assert config.thinking_config.thinking_level == "LOW"
    assert "объяснен" not in config.system_instruction.lower()
    assert "Бен как ограничительная частица" in config.system_instruction
    assert "consonant противоречит указанному правилу" in config.system_instruction


@pytest.mark.parametrize("include_reasons", [True, False])
@pytest.mark.parametrize("asynchronous", [True, False])
def test_selected_reason_schema_is_enforced_without_retry(
    sdk, include_reasons, asynchronous
):
    row = {"id": "N000001", "kind": "nasalization"}
    if not include_reasons:
        row["reason"] = "Unexpected in compact mode."
    sdk.outcomes = [response({"decisions": [row]})]
    if asynchronous:

        async def run():
            async with resolver(include_reasons=include_reasons) as r:
                await Transliterator(nasal_resolver=r).atransliterate("сан")

        with pytest.raises(NasalResponseError):
            asyncio.run(run())
    else:
        with (
            resolver(include_reasons=include_reasons) as r,
            pytest.raises(NasalResponseError),
        ):
            Transliterator(nasal_resolver=r).transliterate("сан")
    assert len(sdk.calls) == 1


@pytest.mark.parametrize("value", [None, 0, 1, "false", []])
def test_reason_setting_requires_an_explicit_boolean(sdk, value):
    with pytest.raises(ValueError, match="include_reasons"):
        resolver(include_reasons=value)
    assert not sdk.clients


@pytest.mark.parametrize(
    "bad",
    [
        '{"decisions":[{"id":"N000001","id":"N000001","kind":"nasalization"}]}',
        '{"decisions":[{"id":"N000001","kind":"invalid"}]}',
        '{"decisions":[{"id":"N000001","kind":"nasalization","extra":1}]}',
        '{"decisions":[{"id":"WRONG","kind":"nasalization"}]}',
    ],
)
def test_compact_parser_rejects_ambiguous_or_invalid_rows(sdk, bad):
    sdk.outcomes = [
        SimpleNamespace(candidates=[SimpleNamespace(finish_reason="STOP")], text=bad)
    ]
    with resolver(include_reasons=False) as r, pytest.raises(NasalResponseError):
        Transliterator(nasal_resolver=r).transliterate("сан")
    assert len(sdk.calls) == 1


def test_reason_modes_share_all_linguistic_instructions_and_default_is_unchanged():
    from importlib import resources

    default = (
        resources.files("ce_translit.ai")
        .joinpath("_prompt.txt")
        .read_text(encoding="utf-8")
    )
    assert _gemini._system_prompt(True) == default
    assert _gemini._system_prompt(False) == default.replace(
        " Объяснение каждого решения - не более одного предложения по-русски.", ""
    ).replace(
        "Проверь согласованность каждого kind с объяснением:",
        "Проверь согласованность каждого kind:",
    )


def test_compact_mode_fails_before_requests_if_bundled_prompt_edits_drift(monkeypatch):
    resource = SimpleNamespace(read_text=lambda **kwargs: "Unexpected prompt contents.")
    package = SimpleNamespace(joinpath=lambda name: resource)
    monkeypatch.setattr(_gemini.resources, "files", lambda name: package)
    with pytest.raises(RuntimeError, match="explanation template"):
        _gemini._system_prompt(False)
