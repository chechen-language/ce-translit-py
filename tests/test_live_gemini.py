import json
import os
from pathlib import Path

import pytest

from ce_translit import Transliterator

GOLD = json.loads(
    (Path(__file__).parent / "fixtures/nasal_gold.json").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
def live_transliterator():
    from ce_translit.ai import GeminiNasalResolver

    with GeminiNasalResolver(
        api_key=os.environ["CE_TRANSLIT_API_KEY"],
        model=os.environ["CE_TRANSLIT_MODEL"],
        base_url=os.environ.get("CE_TRANSLIT_BASE_URL"),
    ) as resolver:
        yield Transliterator(nasal_resolver=resolver)


@pytest.mark.live
@pytest.mark.parametrize("passage", GOLD["texts"], ids=[p["id"] for p in GOLD["texts"]])
def test_live_human_reviewed_passage(passage, live_transliterator, request):
    record = {"id": passage["id"], "context": passage["text"], "rows": []}
    request.config._nasal_live_records.append(record)
    try:
        result = live_transliterator.transliterate_detailed(passage["text"])
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
        raise
    assert len(result.decisions) == len(passage["targets"])
    for decision, gold in zip(result.decisions, passage["targets"], strict=True):
        assert (decision.word, decision.start, decision.end) == (
            gold["word"],
            gold["start"],
            gold["end"],
        )
        record["rows"].append(
            {
                "id": gold["id"],
                "word": decision.word,
                "start": decision.start,
                "end": decision.end,
                "actual": decision.kind,
                "expected": gold["kind"],
                "reason": decision.reason,
            }
        )
    errors = [row for row in record["rows"] if row["actual"] != row["expected"]]
    assert not errors, json.dumps(errors, ensure_ascii=False, indent=2)
