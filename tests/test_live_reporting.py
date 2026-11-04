"""Report formatting is tested without enabling live model requests."""

import socket
from types import SimpleNamespace

import conftest
import pytest


def write_report(path, records):
    config = SimpleNamespace(
        getoption=lambda name: str(path), _nasal_live_records=records
    )
    conftest.pytest_sessionfinish(SimpleNamespace(config=config), 0)


def record(mode, total_tokens):
    return {
        "id": "fixture",
        "mode": mode,
        "context": "Сан шун",
        "seconds": 1.25,
        "requests": 2,
        "batches": [{"context_chars": 7, "total_tokens": total_tokens}],
        "rows": [
            {
                "id": "labelled",
                "word": "Сан",
                "start": 0,
                "end": 3,
                "actual": "nasalization",
                "expected": "nasalization",
                "reason": "one|two\nline",
            },
            {
                "id": "unlabelled",
                "word": "шун",
                "start": 4,
                "end": 7,
                "actual": "consonant",
                "expected": None,
                "reason": "Pending human label",
            },
        ],
    }


def test_report_scores_only_gold_and_preserves_unknown_usage(tmp_path):
    path = tmp_path / "review.md"
    write_report(path, [record("sentence", None), record("adjacent", 123)])
    text = path.read_text()
    assert "Scored: **2/2**" in text
    assert "Provider total tokens: unknown" in text
    assert "Provider total tokens: 123" in text
    assert "HTTP attempts: 2" in text
    assert "unlabelled" in text
    assert "one\\|two line" in text


def test_report_does_not_overwrite_an_existing_review(tmp_path):
    path = tmp_path / "review.md"
    path.write_text("Keep the previous evaluation")
    with pytest.raises(FileExistsError):
        write_report(path, [])
    assert path.read_text() == "Keep the previous evaluation"


@pytest.mark.parametrize("host", ["example.invalid", "192.0.2.1", "172.16.10.10"])
def test_default_suite_blocks_external_dns_and_direct_sockets(host, request):
    if request.config.getoption("run_live_nasal"):
        pytest.skip("This assertion checks the default offline policy.")
    with pytest.raises(AssertionError, match="External network"):
        socket.getaddrinfo(host, 80)
    with socket.socket() as client:
        with pytest.raises(AssertionError, match="External network"):
            client.connect((host, 80))
