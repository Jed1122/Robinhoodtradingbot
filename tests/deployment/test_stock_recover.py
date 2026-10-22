"""Recovery-only post-stop boundary through real receipts and fictional Engine."""

import importlib
import signal
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest
from test_stock_prestart import policy as policy
from test_stock_release import release as release
from test_stock_research_cycle import cycle as cycle
from test_stock_research_cycle import opened, run

from infra.hybrid import stock_launcher


def recovery():
    operation = getattr(stock_launcher, "recover_research_cycle", None)
    assert callable(operation), "Recovery-only post-stop operation is missing"
    return operation


def test_empty_namespace_never_loads_a_release_or_calls_daemon(cycle, monkeypatch):
    _, _, _, daemon, _ = cycle
    monkeypatch.setattr(stock_launcher, "load_release", lambda _: pytest.fail("release loaded"))
    with opened(cycle) as store:
        assert recovery()(store).status == "recovery_only"
        assert store.snapshot() is None
    assert daemon.requests == []


def test_completed_attempt_is_reconfirmed_without_new_create_or_start(cycle):
    _, manifest, _, daemon, _ = cycle
    with opened(cycle) as store:
        run(store, manifest)
        before = store.snapshot()
    daemon.requests.clear()
    with opened(cycle) as store:
        assert recovery()(store).status == "recovery_only"
        assert store.snapshot() == before
    assert len(daemon.requests) == 1 and daemon.requests[0][0] == "GET"


def test_undispatched_intent_is_abandoned_without_creation(cycle):
    _, _, release, daemon, _ = cycle
    with opened(cycle) as store:
        store.begin(release)
    with opened(cycle) as store:
        assert recovery()(store).status == "recovery_only"
        assert store.snapshot().abandoned_sha256 is not None
    assert daemon.requests == []


def test_unresolved_create_is_preserved_and_never_retried(cycle):
    _, manifest, _, daemon, _ = cycle
    daemon.fault = "create_ack"
    with opened(cycle) as store, pytest.raises(ValueError):
        run(store, manifest)
    daemon.requests.clear()
    with opened(cycle) as store:
        result = recovery()(store)
        assert result.status == "recovery_only"
        assert store.snapshot().stopped_sha256 is not None
    assert len(daemon.requests) == 1 and daemon.requests[0][0] == "GET"


def test_fixed_production_guard_precedes_any_recovery(cycle, monkeypatch):
    _, _, _, daemon, _ = cycle

    def denied(_):
        raise ValueError("private failure")

    monkeypatch.setattr(stock_launcher, "_production_store", denied)
    with opened(cycle) as store, pytest.raises(ValueError, match=r"^stock_launcher_unavailable$"):
        recovery()(store)
    assert not daemon.requests


def test_recovery_requests_immediate_cleanup_and_restores_signal_handlers(cycle, monkeypatch):
    before = tuple(signal.getsignal(n) for n in (signal.SIGTERM, signal.SIGINT))
    seen = []

    def recover(store, reader, shutdown):
        seen.append(shutdown[:])
        return stock_launcher.StockCycleResult("recovery_only", None)

    monkeypatch.setattr(stock_launcher, "_recover", recover)
    with opened(cycle) as store:
        recovery()(store)
    assert seen == [[True]]
    assert tuple(signal.getsignal(n) for n in (signal.SIGTERM, signal.SIGINT)) == before


def cli():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_recover.py"
    assert path.is_file(), "Recovery-only CLI is missing"
    return importlib.import_module("infra.hybrid.stock_recover")


@pytest.mark.parametrize("args", [["arbitrary-release"], ["--cid", "a" * 64]])
def test_cli_has_no_release_cid_or_policy_overrides(monkeypatch, capsys, args):
    api = cli()
    monkeypatch.setattr(sys, "argv", ["stock_recover", *args])
    monkeypatch.setattr(api, "operations", lambda: pytest.fail("namespace opened"))
    assert api.main() == 1
    assert "unavailable" in capsys.readouterr().err


def test_cli_recovers_fixed_namespace_once(cycle, monkeypatch, capsys):
    api = cli()
    monkeypatch.setattr(sys, "argv", ["stock_recover"])
    with opened(cycle) as store:
        monkeypatch.setattr(api, "operations", lambda: nullcontext(store))
        assert api.main() == 0
    assert capsys.readouterr().out == '{"status": "recovery_only"}\n'


def test_cli_sanitizes_busy_or_failed_namespace(monkeypatch, capsys):
    api = cli()
    monkeypatch.setattr(sys, "argv", ["stock_recover"])

    def denied():
        raise OSError("private host path")

    monkeypatch.setattr(api, "operations", denied)
    assert api.main() == 1
    result = capsys.readouterr()
    assert result.out == "" and result.err == '{"status": "unavailable"}\n'
