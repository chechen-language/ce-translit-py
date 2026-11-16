# Contextual Nasalization Reference

For installation, the linguistic distinction and a first working conversion, start with the [README example](../README.md#contextual-nasalization). This page covers configuration and integration of `ce_translit.ai.GeminiNasalResolver`, which uses the [Google GenAI SDK](https://github.com/googleapis/python-genai).

## Configuration

Pass options directly to `GeminiNasalResolver`:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `api_key` | Required | Non-empty service API key. |
| `model` | Required | Non-empty model name available on the service. |
| `base_url` | `None` | Gemini service root; `None` selects Google's API. |
| `context` | `"sentence"` | Complete sentence per occurrence; `"adjacent"` also includes the previous and next sentence. |
| `thinking_level` | `None` | Provider default; otherwise `"minimal"`, `"low"`, `"medium"`, `"high"` or `"xhigh"`. |
| `include_reasons` | `True` | Request a visible explanation for each decision. |
| `timeout` | `60` | HTTP timeout in seconds; a finite positive number. Retries can extend total conversion time. |
| `max_targets_per_request` | `64` | Maximum target occurrences in a request; a positive integer. |
| `max_context_chars` | `12000` | Maximum sum of source-context characters in a request; a positive integer. |

### Gemini-Compatible Gateways

For a gateway such as CLIProxyAPI, set `base_url` to its HTTP(S) service root. The endpoint must implement Gemini's `generateContent` protocol under `/v1beta`. Do not append `/v1beta`, `/v1` or `/openai` to the root, or include credentials, query parameters or fragments in the URL.

Use the same resolver class for Google and a compatible gateway, changing `base_url`, `model` and `api_key`. Google's API requires a valid key. For a gateway without client authentication, pass a non-empty placeholder such as `local-gateway`.

### Reasoning And Explanations

Set `thinking_level` independently of the model name; supported levels depend on the selected model and service. Omitting it or passing `None` leaves internal reasoning to the provider.

With `include_reasons=False`, the prompt and response schema request only occurrence IDs and classifications. Returned decisions have `reason=None`. This controls visible explanations independently of internal reasoning. It can change classification accuracy as well as token use and latency; evaluate it on your own texts.

## Async And Resource Lifetime

The asynchronous equivalent of the README conversion is:

```python
import os

from ce_translit import Transliterator
from ce_translit.ai import GeminiNasalResolver


async def transliterate_texts(texts: list[str]) -> list[str]:
    async with GeminiNasalResolver(
        api_key=os.environ["GEMINI_API_KEY"],
        model=os.environ["GEMINI_MODEL"],
        base_url=os.environ.get("GEMINI_BASE_URL") or None,
        context="adjacent",
        thinking_level=os.environ.get("GEMINI_THINKING_LEVEL") or "low",
    ) as resolver:
        transliterator = Transliterator(nasal_resolver=resolver)
        return [await transliterator.atransliterate(text) for text in texts]
```

For a long-running application, keep one resolver open for its lifecycle and close it during shutdown. In an async server or bot, use `atransliterate()` or `atransliterate_detailed()` so provider requests do not block the event loop. Synchronous applications can use the corresponding sync methods. Asynchronous use requires `async with` or `await resolver.aclose()` in the same event loop that uses the resolver. Finish or cancel and await pending conversions before closing. Synchronous conversions can share a resolver across threads; a resolver used asynchronously must be closed asynchronously.

## Decisions And Source Spans

Each `NasalDecision` contains `id`, `word`, `start`, `end`, `kind` and `reason`. A supplied reason is a nonempty string. Source spans are half-open Python code-point offsets:

```python
# Using source and result from the README example:
for decision in result.decisions:
    assert source[decision.start:decision.end] == decision.word
```

Repeated words have separate IDs, local to the conversion. Decisions are returned in source order.

| `kind` | Rendering |
| --- | --- |
| `consonant` | `n/N` |
| `nasalization` | `ŋ/Ŋ` |
| `undetermined` | `n/N`, with the unresolved reading recorded. |

Use detailed results to inspect uncertainty. An unresolved reading does not trigger hidden follow-up requests.

## Contexts And Request Limits

In `sentence` mode, only sentences containing target occurrences are sent. In `adjacent` mode, their previous and next sentences are included even if those sentences contain no targets. Input without targets makes no provider requests. Multiple sentence contexts can share one request.

Sentence boundaries use Unicode UAX #29 with tailoring for single-line wraps, paragraph breaks, initials, common Russian abbreviations and web addresses. Single line breaks may remain inside a sentence; blank lines separate fragments. Unpunctuated input is treated as a fragment. Plain-text boundaries can be ambiguous; the library does not infer missing punctuation.

Requests are packed and sent sequentially. The character limit counts source contexts, excluding JSON overhead; it is not a provider token limit. If a target list exceeds the per-request limit, its full context is repeated with disjoint target lists. If a complete context exceeds the character limit, conversion raises `NasalInputError` before any request; increase the limit for that input. Contexts are never truncated.

Temporary network and API failures receive up to two retries. Provider `Retry-After` delays are honoured; delays above the 60-second automatic wait limit raise `NasalAPIError` with `retry_after` instead of retrying early. HTTPX environment proxy settings apply to both sync and async calls. HTTP redirects are rejected without forwarding credentials or text to another address.

## Errors

Import exceptions from `ce_translit.errors`:

| Exception | Meaning |
| --- | --- |
| `NasalAPIError` | A network or provider request failed; `status_code` and `retry_after` are available when known. |
| `NasalResponseError` | The response was blocked, truncated or failed decision validation. |
| `NasalInputError` | A complete context exceeds the configured limit or occurrence spans are invalid. |
| `NasalLifecycleError` | The resolver is closed, used from a different event loop, or closed with operations still running. |

These inherit from `NasalResolutionError`. A failed conversion raises an exception rather than returning partially processed text.

Invalid constructor options raise `ValueError`. A missing optional dependency raises `MissingAIDependencyError`, an `ImportError`, as described in the [README contextual example](../README.md#contextual-nasalization). Neither inherits from `NasalResolutionError`.

## Live Evaluation

Live evaluation sends the test fixtures to the configured Gemini service and compares the returned decisions with reviewed labels. It consumes API quota and runs only when explicitly enabled. With the environment variables from the README configured, run:

```bash
CE_TRANSLIT_API_KEY="$GEMINI_API_KEY" \
CE_TRANSLIT_MODEL="$GEMINI_MODEL" \
CE_TRANSLIT_BASE_URL="${GEMINI_BASE_URL:-}" \
CE_TRANSLIT_THINKING_LEVEL="${GEMINI_THINKING_LEVEL:-low}" \
uv run --extra ai --with pytest pytest \
  tests/test_live_gemini.py --run-live-nasal \
  --nasal-report "/tmp/nasal-review-$(date +%s).md" -v
```

Reports compare `sentence` and `adjacent` modes on 93 previously native-speaker-reviewed positions, recording every detected occurrence, per-class results, HTTP attempts, elapsed time and provider-reported token usage. They include source context, model decisions, reference labels and explanations. Unlabelled occurrences are shown but not scored; missing usage is reported as unknown. These previously reviewed samples are not an independent estimate of linguistic accuracy.
