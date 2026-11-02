"""Live evaluations are explicit opt-in and never part of the default suite."""

import os
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-live-nasal",
        action="store_true",
        help="Send the 63-case gold sample to Gemini.",
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
    correct = sum(row["actual"] == row["expected"] for row in rows)
    lines = [
        "# Native Gemini Nasal Evaluation",
        "",
        f"Configured model: `{os.environ.get('CE_TRANSLIT_MODEL')}`. This is not proof of backend model identity.",
        f"Scored: **{correct}/{len(rows)}**. Gold: 63 native-speaker-reviewed positions in eight excerpts.",
        "This small, previously reviewed sample is not a general accuracy estimate.",
        "",
    ]
    for record in records:
        lines += [f"## {record['id']}", "", record["context"], ""]
        if "error" in record:
            lines += [f"Evaluation failed: {record['error']}", ""]
            continue
        lines += [
            "| Gold ID | Word | Source span | Gemini | Gold | Verdict | Reason |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in record["rows"]:
            reason = row["reason"].replace("|", "\\|").replace("\n", " ")
            verdict = "correct" if row["actual"] == row["expected"] else "INCORRECT"
            lines.append(
                f"| {row['id']} | {row['word']} | {row['start']}:{row['end']} | {row['actual']} | {row['expected']} | {verdict} | {reason} |"
            )
        lines.append("")
    path = Path(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
