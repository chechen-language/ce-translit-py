"""Explicit live comparison; never enabled by normal tests or CI."""

import json
import os
import time
from pathlib import Path

import pytest

from ce_translit import Transliterator

FIXTURES = Path(__file__).parent / "fixtures"
GOLD = json.loads((FIXTURES / "nasal_gold.json").read_text(encoding="utf-8"))
POSITIONS = json.loads(
    (FIXTURES / "nasal_reviewed_positions.json").read_text(encoding="utf-8")
)
PASSAGES = GOLD["texts"] + [
    {
        "id": row["id"],
        "text": row["text"],
        "targets": [{"id": row["id"], **row["target"]}],
    }
    for row in POSITIONS["positions"]
]


@pytest.fixture
def live_transliterator(context_mode):
    from ce_translit.ai import GeminiNasalResolver

    class ObservedResolver(GeminiNasalResolver):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.observations = []
            self.http_requests = 0
            self.hooked = False

        def _get_client(self, **kwargs):
            client = super()._get_client(**kwargs)
            if not self.hooked:
                self._http.event_hooks["request"].append(self.count_request)
                self.hooked = True
            return client

        def count_request(self, request):
            self.http_requests += 1

        def _request(self, batch):
            started = time.perf_counter()
            response = None
            try:
                response = super()._request(batch)
                return response
            finally:
                usage = getattr(response, "usage_metadata", None)
                self.observations.append(
                    {
                        "seconds": time.perf_counter() - started,
                        "context_chars": sum(len(item.text) for item in batch.contexts),
                        "prompt_tokens": getattr(usage, "prompt_token_count", None),
                        "output_tokens": getattr(usage, "candidates_token_count", None),
                        "thinking_tokens": getattr(usage, "thoughts_token_count", None),
                        "total_tokens": getattr(usage, "total_token_count", None),
                    }
                )

    with ObservedResolver(
        api_key=os.environ["CE_TRANSLIT_API_KEY"],
        model=os.environ["CE_TRANSLIT_MODEL"],
        base_url=os.environ.get("CE_TRANSLIT_BASE_URL") or None,
        context=context_mode,
        thinking_level=os.environ.get("CE_TRANSLIT_THINKING_LEVEL") or None,
    ) as resolver:
        yield Transliterator(nasal_resolver=resolver), resolver


@pytest.mark.live
@pytest.mark.parametrize("context_mode", ["sentence", "adjacent"])
@pytest.mark.parametrize("passage", PASSAGES, ids=[p["id"] for p in PASSAGES])
def test_live_human_reviewed_passage(
    passage, context_mode, live_transliterator, request
):
    transliterator, resolver = live_transliterator
    record = {
        "id": passage["id"],
        "mode": context_mode,
        "context": passage["text"],
        "rows": [],
    }
    request.config._nasal_live_records.append(record)
    started = time.perf_counter()
    try:
        result = transliterator.transliterate_detailed(passage["text"])
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        record["seconds"] = time.perf_counter() - started
        record["requests"] = resolver.http_requests
        record["batches"] = resolver.observations
    assert len(result.decisions) == len(transliterator._targets(passage["text"]))
    references = {
        (gold["start"], gold["end"], gold["word"]): gold for gold in passage["targets"]
    }
    covered = set()
    for decision in result.decisions:
        key = decision.start, decision.end, decision.word
        gold = references.get(key)
        if gold is not None:
            covered.add(key)
        record["rows"].append(
            {
                "id": gold["id"] if gold else f"{passage['id']}:{decision.id}",
                "word": decision.word,
                "start": decision.start,
                "end": decision.end,
                "actual": decision.kind,
                "expected": gold["kind"] if gold else None,
                "reason": decision.reason,
            }
        )
    assert covered == references.keys()
    errors = [
        row
        for row in record["rows"]
        if row["expected"] is not None and row["actual"] != row["expected"]
    ]
    assert not errors, json.dumps(errors, ensure_ascii=False, indent=2)
