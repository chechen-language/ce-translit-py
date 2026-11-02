"""Gemini SDK adapter; the model never writes the transliterated text."""

import asyncio
import json
import math
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from importlib import resources
from typing import Any, NoReturn
from urllib.parse import urlsplit

from ce_translit._models import NasalDecision, NasalTarget
from ce_translit.ai._blocks import _iter_blocks
from ce_translit.errors import (
    MissingAIDependencyError,
    NasalAPIError,
    NasalResponseError,
)

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


def _load_sdk() -> tuple[Any, Any, Any, Any]:
    try:
        import httpx
        from google import genai
        from google.genai import errors, types
    except ImportError:
        raise MissingAIDependencyError(
            "Install optional AI support: pip install 'ce-translit[ai]'."
        ) from None
    return genai, types, errors, httpx


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field.")
        result[key] = value
    return result


def _parse_response(
    response: Any, targets: Sequence[NasalTarget]
) -> tuple[NasalDecision, ...]:
    candidates = response.candidates
    if not candidates or len(candidates) != 1:
        raise NasalResponseError("Gemini did not return exactly one candidate.")
    finish = getattr(candidates[0].finish_reason, "value", candidates[0].finish_reason)
    if finish != "STOP":
        raise NasalResponseError(
            "Gemini response was blocked or did not finish normally."
        )
    try:
        payload = json.loads(response.text, object_pairs_hook=_unique_object)
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


def _retry_delay(error: Exception, attempt: int) -> float:
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
                seconds = float(2**attempt)
        if math.isfinite(seconds):
            return min(60.0, max(0.0, seconds))
    return float(2**attempt)


class GeminiNasalResolver:
    """Reusable sync/async Gemini resolver, activated only by explicit wiring.

    api_key and model are required. base_url is a Gemini-protocol service root,
    not an OpenAI /v1 URL. timeout is in seconds, for each request attempt.
    Use aclose/async with if any asynchronous request has been made.
    """

    def __init__(
        self, api_key: str, model: str, base_url: str | None = None, timeout: float = 60
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be explicitly provided.")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be explicitly provided.")
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
        self._genai, self._types, self._errors, self._httpx = _load_sdk()
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._prompt = (
            resources.files("ce_translit.ai")
            .joinpath("_prompt.txt")
            .read_text(encoding="utf-8")
        )
        self._client: Any = None
        self._async_used = False
        self._closed = False

    def _get_client(self) -> Any:
        if self._closed:
            raise NasalAPIError("Gemini resolver is closed.")
        if self._client is None:
            options = self._types.HttpOptions(
                base_url=self._base_url,
                api_version="v1beta",
                timeout=max(1, int(self._timeout * 1000)),
                retry_options=self._types.HttpRetryOptions(attempts=1),
                # Force the same HTTPX error contract even if aiohttp is installed.
                async_client_args={"transport": self._httpx.AsyncHTTPTransport()},
            )
            self._client = self._genai.Client(
                api_key=self._api_key, enterprise=False, http_options=options
            )
        return self._client

    def _request_args(self, block: Any) -> dict[str, Any]:
        return {
            "model": self._model,
            "contents": json.dumps(
                {
                    "context": block.text,
                    "targets": [
                        {
                            "id": t.id,
                            "word": t.word,
                            "start": t.start - block.start,
                            "end": t.end - block.start,
                        }
                        for t in block.targets
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
        if isinstance(error, (ValueError, self._errors.UnknownApiResponseError)):
            raise NasalResponseError(
                "Gemini returned a response the SDK could not decode."
            ) from None
        code = error.code if isinstance(error, self._errors.APIError) else None
        raise NasalAPIError("Gemini request failed.", status_code=code) from None

    def _request(self, block: Any) -> Any:
        client = self._get_client()
        args = self._request_args(block)
        for attempt in range(3):
            try:
                return client.models.generate_content(**args)
            except Exception as error:
                if attempt < 2 and self._retryable(error):
                    time.sleep(_retry_delay(error, attempt))
                else:
                    self._raise_request_error(error)

    async def _arequest(self, block: Any) -> Any:
        client = self._get_client()
        self._async_used = True
        args = self._request_args(block)
        for attempt in range(3):
            try:
                return await client.aio.models.generate_content(**args)
            except Exception as error:
                if attempt < 2 and self._retryable(error):
                    await asyncio.sleep(_retry_delay(error, attempt))
                else:
                    self._raise_request_error(error)

    def resolve(
        self, text: str, targets: Sequence[NasalTarget]
    ) -> tuple[NasalDecision, ...]:
        if self._closed:
            raise NasalAPIError("Gemini resolver is closed.")
        blocks = tuple(_iter_blocks(text, targets))
        decisions: list[NasalDecision] = []
        for block in blocks:
            decisions.extend(_parse_response(self._request(block), block.targets))
        return tuple(decisions)

    async def aresolve(
        self, text: str, targets: Sequence[NasalTarget]
    ) -> tuple[NasalDecision, ...]:
        if self._closed:
            raise NasalAPIError("Gemini resolver is closed.")
        blocks = tuple(_iter_blocks(text, targets))
        decisions: list[NasalDecision] = []
        for block in blocks:
            decisions.extend(
                _parse_response(await self._arequest(block), block.targets)
            )
        return tuple(decisions)

    def close(self) -> None:
        """Close sync resources. Async use requires await aclose()."""
        if self._closed:
            return
        if self._async_used:
            raise RuntimeError(
                "An asynchronously used resolver requires await aclose()."
            )
        if self._client is not None:
            self._client.close()
        self._closed = True

    async def aclose(self) -> None:
        if self._closed:
            return
        if self._client is not None:
            try:
                await self._client.aio.aclose()
            finally:
                self._client.close()
        self._closed = True

    def __enter__(self) -> "GeminiNasalResolver":
        if self._closed:
            raise NasalAPIError("Gemini resolver is closed.")
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    async def __aenter__(self) -> "GeminiNasalResolver":
        return self.__enter__()

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()
