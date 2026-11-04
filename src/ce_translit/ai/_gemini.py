"""Gemini SDK adapter; the model never writes the transliterated text."""

import asyncio
import json
import math
import time
import warnings
from collections.abc import Sequence
from contextlib import ExitStack
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from importlib import resources
from threading import RLock
from typing import TYPE_CHECKING, Any, NoReturn, TypedDict
from urllib.parse import urlsplit

from ce_translit._models import NasalDecision, NasalTarget
from ce_translit.ai._contexts import ContextMode, _Batch, _prepare_batches
from ce_translit.errors import (
    MissingAIDependencyError,
    NasalAPIError,
    NasalLifecycleError,
    NasalResponseError,
)

if TYPE_CHECKING:
    import httpx
    from google import genai
    from google.genai import types


class _RequestArgs(TypedDict):
    model: str
    contents: str
    config: "types.GenerateContentConfig"


def _reject_redirect(response: "httpx.Response") -> None:
    if 300 <= response.status_code < 400:
        raise NasalAPIError(
            "Gemini endpoint returned an HTTP redirect.",
            status_code=response.status_code,
        )


async def _areject_redirect(response: "httpx.Response") -> None:
    _reject_redirect(response)


_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["consonant", "nasalization", "undetermined"],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["id", "kind", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["decisions"],
    "additionalProperties": False,
}


def _load_sdk() -> tuple[Any, Any, Any, Any, Any]:
    try:
        import httpx
        import uniseg  # type: ignore[import-untyped]  # noqa: F401
        from google import genai
        from google.genai import errors, types
        from pydantic import ValidationError
    except ImportError:
        raise MissingAIDependencyError(
            "Install optional AI support: pip install 'ce-translit[ai]'."
        ) from None
    return genai, types, errors, httpx, ValidationError


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field.")
        result[key] = value
    return result


def _parse_response(
    response: "types.GenerateContentResponse", targets: Sequence[NasalTarget]
) -> tuple[NasalDecision, ...]:
    candidates = response.candidates
    if not candidates or len(candidates) != 1:
        raise NasalResponseError("Gemini did not return exactly one candidate.")
    finish = getattr(candidates[0].finish_reason, "value", candidates[0].finish_reason)
    if finish != "STOP":
        raise NasalResponseError(
            "Gemini response was blocked or did not finish normally."
        )
    body = response.text
    if not isinstance(body, str):
        raise NasalResponseError("Gemini did not return JSON text.")
    try:
        payload = json.loads(body, object_pairs_hook=_unique_object)
    except (TypeError, ValueError):
        raise NasalResponseError(
            "Gemini did not return valid, unambiguous JSON."
        ) from None
    if not isinstance(payload, dict) or set(payload) != {"decisions"}:
        raise NasalResponseError("Gemini returned an invalid response object.")
    rows = payload["decisions"]
    if not isinstance(rows, list) or len(rows) != len(targets):
        raise NasalResponseError("Gemini did not return one decision per target.")
    expected = {target.id: target for target in targets}
    found = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"id", "kind", "reason"}
            or not isinstance(row["id"], str)
            or row["id"] not in expected
            or row["id"] in found
            or row["kind"] not in ("consonant", "nasalization", "undetermined")
            or not isinstance(row["reason"], str)
            or not row["reason"].strip()
        ):
            raise NasalResponseError(
                "Gemini returned invalid, duplicate or unexpected decisions."
            )
        target = expected[row["id"]]
        found[target.id] = NasalDecision(
            target.id,
            target.word,
            target.start,
            target.end,
            row["kind"],
            row["reason"].strip(),
        )
    if found.keys() != expected.keys():
        raise NasalResponseError("Gemini omitted requested occurrences.")
    return tuple(found[target.id] for target in targets)


def _retry_after(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("Retry-After")
    if value:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            try:
                when = parsedate_to_datetime(value)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                seconds = (when - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return None
        if math.isfinite(seconds):
            return max(0.0, seconds)
    return None


def _retry_delay(error: Exception, attempt: int) -> float:
    value = _retry_after(error)
    return value if value is not None else float(2**attempt)


class GeminiNasalResolver:
    """Reusable sync/async Gemini resolver, activated only by explicit wiring.

    api_key and model are required. base_url is a Gemini-protocol service root,
    not an OpenAI /v1 URL. timeout is in seconds, for each request attempt.
    Use aclose/async with if any asynchronous request has been made.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        timeout: float = 60,
        *,
        context: ContextMode = "sentence",
        max_targets_per_request: int = 64,
        max_context_chars: int = 12_000,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be explicitly provided.")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be explicitly provided.")
        if context not in ("sentence", "adjacent"):
            raise ValueError("context must be 'sentence' or 'adjacent'.")
        for limit in (max_targets_per_request, max_context_chars):
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise ValueError("Request limits must be positive integers.")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be a finite positive number of seconds.")
        base_url = base_url or "https://generativelanguage.googleapis.com"
        parts = urlsplit(base_url)
        if (
            parts.scheme not in ("https", "http")
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path.rstrip("/").endswith(("/v1", "/v1beta", "/openai"))
        ):
            raise ValueError(
                "base_url must be an HTTP(S) Gemini service root, without API version or credentials."
            )
        self._genai, self._types, self._errors, self._httpx, validation_error = (
            _load_sdk()
        )
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._context = context
        self._max_targets = max_targets_per_request
        self._max_chars = max_context_chars
        self._prompt = (
            resources.files("ce_translit.ai")
            .joinpath("_prompt.txt")
            .read_text(encoding="utf-8")
        )
        self._client: genai.Client | None = None
        self._aclient: genai.Client | None = None
        self._http: httpx.Client | None = None
        self._ahttp: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = RLock()
        self._active = 0
        self._sync_context = False
        self._closing = False
        self._closed = False
        self._cleanup_complete = False
        self._request_errors = (
            self._httpx.TransportError,
            self._errors.APIError,
            self._errors.UnknownApiResponseError,
            json.JSONDecodeError,
            validation_error,
        )
        self._response_errors = (
            json.JSONDecodeError,
            self._errors.UnknownApiResponseError,
            validation_error,
        )

    def _check_open(self) -> None:
        if self._closed or self._closing:
            raise NasalLifecycleError("Gemini resolver is closed or closing.")

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._sync_context:
            raise NasalLifecycleError("Async use requires async with, not with.")
        if self._loop is not None and self._loop is not loop:
            raise NasalLifecycleError(
                "Use and close the async resolver in the same event loop."
            )
        self._loop = loop

    def _begin(self, *, asynchronous: bool = False) -> None:
        with self._lock:
            self._check_open()
            if asynchronous:
                self._bind_loop()
            self._active += 1

    def _end(self) -> None:
        with self._lock:
            self._active -= 1

    def _get_client(self, *, asynchronous: bool = False) -> "genai.Client":
        with self._lock:
            self._check_open()
            client = self._aclient if asynchronous else self._client
            if client is not None:
                return client
            # Public SDK client injection keeps HTTPX env-proxy discovery intact
            # and prevents an optional aiohttp install from changing behavior.
            if asynchronous:
                if self._ahttp is None:
                    self._ahttp = self._httpx.AsyncClient(
                        timeout=self._timeout,
                        follow_redirects=False,
                        event_hooks={"response": [_areject_redirect]},
                    )
            elif self._http is None:
                self._http = self._httpx.Client(
                    timeout=self._timeout,
                    follow_redirects=False,
                    event_hooks={"response": [_reject_redirect]},
                )
            options = self._types.HttpOptions(
                base_url=self._base_url,
                api_version="v1beta",
                timeout=max(1, int(self._timeout * 1000)),
                retry_options=self._types.HttpRetryOptions(attempts=1),
                httpx_client=None if asynchronous else self._http,
                httpx_async_client=self._ahttp if asynchronous else None,
                client_args={"follow_redirects": False},
                async_client_args={"follow_redirects": False},
            )
            client = self._genai.Client(
                api_key=self._api_key, enterprise=False, http_options=options
            )
            if asynchronous:
                self._aclient = client
            else:
                self._client = client
            return client

    def _request_args(self, batch: _Batch) -> _RequestArgs:
        return {
            "model": self._model,
            "contents": json.dumps(
                {
                    "contexts": [
                        {
                            "text": item.text,
                            "targets": [
                                {
                                    "id": t.id,
                                    "word": t.word,
                                    "start": t.start - item.start,
                                    "end": t.end - item.start,
                                }
                                for t in item.targets
                            ],
                        }
                        for item in batch.contexts
                    ],
                },
                ensure_ascii=False,
            ),
            "config": self._types.GenerateContentConfig(
                system_instruction=self._prompt,
                response_mime_type="application/json",
                response_json_schema=_SCHEMA,
                candidate_count=1,
                automatic_function_calling=self._types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
        }

    def _retryable(self, error: Exception) -> bool:
        if isinstance(
            error, (self._httpx.TransportError, TimeoutError, ConnectionError)
        ):
            return True
        return isinstance(error, self._errors.APIError) and (
            error.code in (408, 429) or 500 <= error.code < 600
        )

    def _raise_request_error(self, error: Exception) -> NoReturn:
        if isinstance(error, self._response_errors):
            raise NasalResponseError(
                "Gemini returned a response the SDK could not decode."
            ) from None
        code = error.code if isinstance(error, self._errors.APIError) else None
        raise NasalAPIError(
            "Gemini request failed.", status_code=code, retry_after=_retry_after(error)
        ) from None

    def _delay(self, error: Exception, attempt: int) -> float:
        delay = _retry_delay(error, attempt)
        if delay > 60:
            raise NasalAPIError(
                "Provider Retry-After exceeds the automatic wait limit.",
                status_code=getattr(error, "code", None),
                retry_after=delay,
            ) from None
        return delay

    def _request(self, batch: _Batch) -> "types.GenerateContentResponse":
        client = self._get_client()
        args = self._request_args(batch)
        for attempt in range(3):
            try:
                return client.models.generate_content(**args)
            except self._request_errors as error:
                if attempt < 2 and self._retryable(error):
                    time.sleep(self._delay(error, attempt))
                else:
                    self._raise_request_error(error)
        raise AssertionError("Unreachable retry state.")

    async def _arequest(self, batch: _Batch) -> "types.GenerateContentResponse":
        client = self._get_client(asynchronous=True)
        args = self._request_args(batch)
        for attempt in range(3):
            try:
                return await client.aio.models.generate_content(**args)
            except self._request_errors as error:
                if attempt < 2 and self._retryable(error):
                    await asyncio.sleep(self._delay(error, attempt))
                else:
                    self._raise_request_error(error)
        raise AssertionError("Unreachable retry state.")

    def resolve(
        self, text: str, targets: Sequence[NasalTarget]
    ) -> tuple[NasalDecision, ...]:
        self._begin()
        try:
            decisions: list[NasalDecision] = []
            for batch in self._batches(text, targets):
                decisions.extend(_parse_response(self._request(batch), batch.targets))
            return tuple(decisions)
        finally:
            self._end()

    def _batches(self, text: str, targets: Sequence[NasalTarget]) -> tuple[_Batch, ...]:
        return _prepare_batches(
            text,
            targets,
            context=self._context,
            max_targets_per_request=self._max_targets,
            max_context_chars=self._max_chars,
        )

    async def aresolve(
        self, text: str, targets: Sequence[NasalTarget]
    ) -> tuple[NasalDecision, ...]:
        self._begin(asynchronous=True)
        try:
            batches = await asyncio.to_thread(self._batches, text, tuple(targets))
            decisions: list[NasalDecision] = []
            for batch in batches:
                decisions.extend(
                    _parse_response(await self._arequest(batch), batch.targets)
                )
            return tuple(decisions)
        finally:
            self._end()

    def _start_close(self, *, asynchronous: bool = False) -> bool:
        with self._lock:
            if self._closed and self._cleanup_complete:
                return False
            if self._closing or self._active:
                raise NasalLifecycleError(
                    "Finish active resolver operations before closing."
                )
            if asynchronous:
                self._bind_loop()
            elif self._loop is not None:
                raise NasalLifecycleError(
                    "An async resolver requires await aclose() in its event loop."
                )
            self._closing = True
            return True

    def _finish_close(self, completed: bool) -> None:
        with self._lock:
            self._closed = True
            self._closing = False
            self._cleanup_complete = completed

    def _close_sync_resources(self) -> None:
        with ExitStack() as cleanup:
            if self._http is not None:
                cleanup.callback(self._http.close)
            if self._client is not None:
                cleanup.callback(self._client.close)
            if self._aclient is not None:
                cleanup.callback(self._aclient.close)

    def close(self) -> None:
        """Close sync resources. Async use requires await aclose()."""
        if self._start_close():
            completed = False
            try:
                self._close_sync_resources()
                completed = True
            except self._request_errors as error:
                self._raise_request_error(error)
            finally:
                self._finish_close(completed)

    async def aclose(self) -> None:
        if not self._start_close(asynchronous=True):
            return

        async def cleanup() -> None:
            try:
                try:
                    if self._aclient is not None:
                        await self._aclient.aio.aclose()
                finally:
                    if self._ahttp is not None:
                        await self._ahttp.aclose()
            finally:
                self._close_sync_resources()

        task = asyncio.create_task(cleanup())
        completed = cancelled = False
        try:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    cancelled = True
            task.result()
            completed = True
            if cancelled:
                raise asyncio.CancelledError
        except self._request_errors as error:
            self._raise_request_error(error)
        finally:
            self._finish_close(completed)

    def __enter__(self) -> "GeminiNasalResolver":
        with self._lock:
            self._check_open()
            if self._loop is not None or self._sync_context:
                raise NasalLifecycleError("Use a fresh sync context or async with.")
            self._sync_context = True
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        with self._lock:
            self._sync_context = False
        self._exit_cleanup(exc)

    def _exit_cleanup(self, exc: BaseException | None) -> None:
        try:
            self.close()
        except Exception:
            if exc is None:
                raise
            warnings.warn(
                "Resolver cleanup failed; close it after pending operations finish.",
                ResourceWarning,
                stacklevel=2,
            )

    async def __aenter__(self) -> "GeminiNasalResolver":
        with self._lock:
            self._check_open()
            self._bind_loop()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            await self.aclose()
        except Exception:
            if exc is None:
                raise
            warnings.warn(
                "Resolver cleanup failed; close it after pending operations finish.",
                ResourceWarning,
                stacklevel=2,
            )
