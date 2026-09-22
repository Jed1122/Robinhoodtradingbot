import os
from dataclasses import replace
from pathlib import Path

import pytest

from tests.unit.research.test_validation import report
from trading_bot.domain import DataHash
from trading_bot.research.artifacts import (
    ResearchArtifactError,
    persist_research_report,
)
from trading_bot.research.report import build_research_report


def test_private_report_artifact_is_content_addressed_and_idempotent(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "research"
    first = persist_research_report(directory, report())
    second = persist_research_report(directory, report())

    assert first == second
    assert first.name == f"{report().report_hash}.json"
    assert first.stat().st_mode & 0o777 == 0o600


def test_existing_mismatched_artifact_fails_closed(tmp_path: Path) -> None:
    directory = tmp_path / "research"
    path = persist_research_report(directory, report())
    path.write_text("changed", encoding="utf-8")

    with pytest.raises(ResearchArtifactError):
        persist_research_report(directory, report())


def test_forged_report_hash_is_rejected_before_path_construction(
    tmp_path: Path,
) -> None:
    forged = replace(report(), report_hash="../outside")

    with pytest.raises(ResearchArtifactError):
        persist_research_report(tmp_path / "research", forged)

    assert not (tmp_path / "outside").exists()


def test_dataset_manifest_mismatch_is_rejected(tmp_path: Path) -> None:
    complete = report()
    assert complete.run.dataset_snapshot is not None
    altered_snapshot = replace(
        complete.run.dataset_snapshot,
        raw_hashes=(DataHash("f" * 64),),
    )
    altered = replace(complete.run, dataset_snapshot=altered_snapshot)
    mismatched = build_research_report(altered, attempts=complete.attempts)

    with pytest.raises(ResearchArtifactError):
        persist_research_report(tmp_path / "research", mismatched)


def test_short_writes_are_completed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_write = os.write

    def short_write(descriptor: int, value: object) -> int:
        view = memoryview(value)  # type: ignore[arg-type]
        return real_write(descriptor, view[: max(1, len(view) // 2)])

    monkeypatch.setattr(os, "write", short_write)
    path = persist_research_report(tmp_path / "research", report())

    assert path.read_text(encoding="utf-8").endswith("\n")
