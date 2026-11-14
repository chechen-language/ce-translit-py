"""Live evaluations are explicit opt-in and never part of the default suite."""

import ipaddress
import os
import socket
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def offline_network(request, monkeypatch):
    """Default tests may use loopback servers, but never external endpoints."""
    if request.config.getoption("run_live_nasal"):
        return
    original = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def check_host(host):
        value = host.decode() if isinstance(host, bytes) else host
        if value in (None, "localhost"):
            return
        try:
            allowed = ipaddress.ip_address(value).is_loopback
        except ValueError:
            allowed = False
        if not allowed:
            raise AssertionError("External network is disabled in offline tests.")

    def local_only(host, *args, **kwargs):
        check_host(host)
        return original(host, *args, **kwargs)

    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            check_host(address[0])
        return original_connect(sock, address)

    def connect_ex(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            check_host(address[0])
        return original_connect_ex(sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", local_only)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)


def pytest_addoption(parser):
    parser.addoption(
        "--run-live-nasal",
        action="store_true",
        help="Compare sentence/adjacent contexts on 93 reviewed positions using Gemini.",
    )
    parser.addoption(
        "--nasal-report", help="Write a human-readable Markdown live evaluation report."
    )


def pytest_configure(config):
    config._nasal_live_records = []
    if config.getoption("run_live_nasal"):
        if not os.environ.get("CE_TRANSLIT_API_KEY") or not os.environ.get(
            "CE_TRANSLIT_MODEL"
        ):
            raise pytest.UsageError(
                "Live tests require CE_TRANSLIT_API_KEY and CE_TRANSLIT_MODEL."
            )
    if config.getoption("nasal_report"):
        if not config.getoption("run_live_nasal"):
            raise pytest.UsageError("--nasal-report requires --run-live-nasal.")
        if Path(config.getoption("nasal_report")).exists():
            raise pytest.UsageError(
                "The report path already exists; choose a new path to preserve prior evaluations."
            )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("run_live_nasal"):
        for item in items:
            if "live" in item.keywords:
                item.add_marker(
                    pytest.mark.skip(
                        reason="Use --run-live-nasal to explicitly enable Gemini requests."
                    )
                )


def pytest_sessionfinish(session, exitstatus):
    report = session.config.getoption("nasal_report")
    if not report:
        return
    records = session.config._nasal_live_records
    rows = [row for record in records for row in record.get("rows", [])]
    scored = [row for row in rows if row["expected"] is not None]
    correct = sum(row["actual"] == row["expected"] for row in scored)
    lines = [
        "# Native Gemini Nasal Evaluation",
        "",
        f"Configured model: `{os.environ.get('CE_TRANSLIT_MODEL')}`. This is not proof of backend model identity.",
        f"Configured thinking level: `{os.environ.get('CE_TRANSLIT_THINKING_LEVEL') or 'provider default'}`.",
        f"Scored: **{correct}/{len(scored)}**. Reference data: 93 previously reviewed positions, evaluated in two context modes.",
        "This small, previously reviewed sample is not a general accuracy estimate.",
        "All detected occurrences are shown; unlabelled positions are not scored. Missing provider usage is reported as unknown, not zero.",
        "",
    ]
    for mode in ("sentence", "adjacent"):
        selected = [record for record in records if record["mode"] == mode]
        predictions = [
            row
            for record in selected
            for row in record.get("rows", [])
            if row["expected"] is not None
        ]
        observations = [
            batch for record in selected for batch in record.get("batches", [])
        ]
        usage = [batch["total_tokens"] for batch in observations]
        tokens = (
            sum(usage)
            if usage and all(value is not None for value in usage)
            else "unknown"
        )
        correct_mode = sum(row["actual"] == row["expected"] for row in predictions)
        lines += [
            f"## {mode}",
            "",
            f"Correct: {correct_mode}/{len(predictions)}. HTTP attempts: {sum(record.get('requests', 0) for record in selected)}. Context characters sent in logical batches: {sum(batch['context_chars'] for batch in observations)}. Provider total tokens: {tokens}. Elapsed: {sum(record.get('seconds', 0) for record in selected):.3f} seconds.",
            "",
            "| Gold kind | Positions | Correct | Predicted undetermined |",
            "| --- | --- | --- | --- |",
        ]
        for kind in ("consonant", "nasalization", "undetermined"):
            subset = [row for row in predictions if row["expected"] == kind]
            lines.append(
                f"| {kind} | {len(subset)} | {sum(row['actual'] == kind for row in subset)} | {sum(row['actual'] == 'undetermined' for row in subset)} |"
            )
        lines.append("")
    for record in records:
        lines += [f"## {record['id']} ({record['mode']})", "", record["context"], ""]
        if "error" in record:
            lines += [f"Evaluation failed: {record['error']}", ""]
            continue
        lines += [
            "| Gold ID | Word | Source span | Gemini | Gold | Verdict | Reason |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in record["rows"]:
            reason = row["reason"].replace("|", "\\|").replace("\n", " ")
            verdict = (
                "unlabelled"
                if row["expected"] is None
                else "correct"
                if row["actual"] == row["expected"]
                else "INCORRECT"
            )
            lines.append(
                f"| {row['id']} | {row['word']} | {row['start']}:{row['end']} | {row['actual']} | {row['expected']} | {verdict} | {reason} |"
            )
        lines.append("")
    path = Path(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")
