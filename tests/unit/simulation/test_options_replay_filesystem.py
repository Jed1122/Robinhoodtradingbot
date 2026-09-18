"""Options artifacts inherit private, bounded, no-follow storage protections."""

import os
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from tests.unit.config.test_options_config import load_options
from trading_bot.risk.options_economics import TrialEpisode, TrialLossState
from trading_bot.simulation.options_fixtures import synthetic_options_request
from trading_bot.simulation.options_replay import replay_options
from trading_bot.simulation.options_replay_io import (
    read_options_replay_file,
    replay_options_report,
    write_options_replay_input,
)
from trading_bot.simulation.options_replay_wire import (
    OptionsReplayFileError,
    decode_options_replay,
    encode_options_replay,
)

ROOT = Path(__file__).resolve().parents[3]


def fixture_file(root: Path):
    root.chmod(0o700)
    request = synthetic_options_request(load_options(), Decimal("2500"))
    digest = write_options_replay_input(root, request, repository_root=ROOT)
    return request, root / "inputs" / f"{digest}.json"


def test_private_input_is_idempotent_and_null_values_roundtrip(tmp_path: Path) -> None:
    request, path = fixture_file(tmp_path)
    assert write_options_replay_input(tmp_path, request, repository_root=ROOT) == path.stem
    assert read_options_replay_file(path, request.loaded, repository_root=ROOT) == request
    nullable = replace(
        request,
        initial_quote=replace(request.initial_quote, bid_size=None, ask_size=None),
        history=replace(request.history, spread_percentage=None),
        trial=TrialLossState((TrialEpisode("pending", Decimal("5"), None, False, False, False),)),
    )
    assert decode_options_replay(encode_options_replay(nullable), nullable.loaded) == nullable
    report = replay_options_report(request, report_dir=None, repository_root=ROOT)
    assert report["schema"] == "synthetic-options-replay-report-v1"


@pytest.mark.parametrize(
    "mutation", ["public_file", "public_parent", "symlink_file", "fifo", "missing"]
)
def test_unsafe_input_files_are_rejected_without_context(tmp_path: Path, mutation: str) -> None:
    request, path = fixture_file(tmp_path)
    if mutation == "public_file":
        path.chmod(0o644)
    elif mutation == "public_parent":
        path.parent.chmod(0o755)
    else:
        original = path.with_suffix(".original")
        path.rename(original)
        if mutation == "symlink_file":
            path.symlink_to(original)
        elif mutation == "fifo":
            os.mkfifo(path, 0o600)
    with pytest.raises(OptionsReplayFileError) as caught:
        read_options_replay_file(path, request.loaded, repository_root=ROOT)
    assert caught.value.__context__ is None


def test_symlink_parent_relative_path_and_traversal_are_rejected(tmp_path: Path) -> None:
    request, path = fixture_file(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(path.parent, target_is_directory=True)
    for invalid in (alias / path.name, Path("inputs") / path.name, path.parent / ".." / path.name):
        with pytest.raises(OptionsReplayFileError):
            read_options_replay_file(invalid, request.loaded, repository_root=ROOT)


def test_repository_local_and_public_artifact_destinations_are_rejected(tmp_path: Path) -> None:
    request, _ = fixture_file(tmp_path)
    for invalid in (ROOT, Path(".")):
        with pytest.raises(OptionsReplayFileError):
            write_options_replay_input(invalid, request, repository_root=ROOT)
    tmp_path.chmod(0o755)
    with pytest.raises(OptionsReplayFileError):
        replay_options_report(request, report_dir=tmp_path, repository_root=ROOT)


def test_changed_existing_input_and_symlink_report_directory_are_not_overwritten(
    tmp_path: Path,
) -> None:
    request, path = fixture_file(tmp_path)
    path.write_bytes(b"preserve me")
    with pytest.raises(OptionsReplayFileError):
        write_options_replay_input(tmp_path, request, repository_root=ROOT)
    assert path.read_bytes() == b"preserve me"
    (tmp_path / "reports").symlink_to(path.parent, target_is_directory=True)
    with pytest.raises(OptionsReplayFileError):
        replay_options_report(request, report_dir=tmp_path, repository_root=ROOT)


def test_oversized_input_is_rejected_before_decoding(tmp_path: Path) -> None:
    request, path = fixture_file(tmp_path)
    loaded = load_options({"TRADING_BOT__OPTIONS__REPLAY_MAX_BYTES": "1024"})
    assert path.stat().st_size > 1024
    with pytest.raises(OptionsReplayFileError):
        read_options_replay_file(path, loaded, repository_root=ROOT)
    assert path.read_bytes() == encode_options_replay(request)


def test_forged_config_or_non_request_cannot_be_encoded(tmp_path: Path) -> None:
    request, _ = fixture_file(tmp_path)
    forged = replace(request, loaded=replace(request.loaded, canonical_json=b"forged"))
    with pytest.raises(OptionsReplayFileError):
        encode_options_replay(forged)
    with pytest.raises(OptionsReplayFileError):
        encode_options_replay(None)  # type: ignore[arg-type]
    with pytest.raises(OptionsReplayFileError):
        decode_options_replay(b"{}", None)  # type: ignore[arg-type]
    with pytest.raises(OptionsReplayFileError):
        read_options_replay_file(Path("/"), request.loaded, repository_root=ROOT)


def test_oversized_engine_output_is_denied_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _ = fixture_file(tmp_path)
    # Fault-inject expansion at the engine boundary. Current ordinary one-unit
    # reports are smaller than inputs; future diagnostic growth must remain bounded.
    oversized = replace(
        replay_options(request),
        reason_codes=("x" * request.loaded.config.options.replay_max_bytes,),
    )
    monkeypatch.setattr(
        "trading_bot.simulation.options_replay_io.replay_options",
        lambda _: oversized,
    )
    with pytest.raises(OptionsReplayFileError) as caught:
        replay_options_report(request, report_dir=tmp_path, repository_root=ROOT)
    assert caught.value.__context__ is None
    assert not (tmp_path / "reports").exists()
