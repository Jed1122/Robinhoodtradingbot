"""Source-only negative-facts CLI; no native operation or result reconstruction."""

import importlib
from contextlib import contextmanager
from pathlib import Path

import pytest


def api():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_producer_reconcile.py"
    assert path.is_file(), "Negative-only public CLI is missing"
    return importlib.import_module("infra.hybrid.stock_producer_reconcile")


def test_success_requires_context_cleanup_and_post_output_window(monkeypatch, capsys):
    module = api()
    completed = []

    class Final:
        facts = Path("/fixture/failed-build-terminal.json")

        def check(self):
            completed.append("check")

    @contextmanager
    def owned(source):
        assert source == "a" * 64
        completed.append("enter")
        yield Final()
        completed.append("closed")

    monkeypatch.setattr(module, "_completed_reconciliation", owned)
    assert module.main(["a" * 64]) == 0
    assert completed == ["enter", "closed", "check", "check"]
    output = capsys.readouterr()
    assert output.out == (
        '{"facts":"/fixture/failed-build-terminal.json","status":"spent_failed_build_reconciled"}\n'
    )
    assert output.err == ""


@pytest.mark.parametrize("stage", ["enter", "close", "check", "write", "flush"])
def test_any_failure_never_returns_success(monkeypatch, capsys, stage):
    module = api()

    class Final:
        facts = Path("/fixture/failed-build-terminal.json")

        def check(self):
            if stage == "check":
                raise ValueError("fixture late failure")

    @contextmanager
    def owned(source):
        if stage == "enter":
            raise OSError("private path and token must not appear")
        yield Final()
        if stage == "close":
            raise OSError("fixture close failure")

    monkeypatch.setattr(module, "_completed_reconciliation", owned)
    if stage in {"write", "flush"}:

        class Sink:
            def write(self, text):
                if stage == "write":
                    raise OSError("fixture output failure")

            def flush(self):
                if stage == "flush":
                    raise OSError("fixture flush failure")

        with monkeypatch.context() as patch:
            patch.setattr(module.sys, "stdout", Sink())
            result = module.main(["a" * 64])
    else:
        result = module.main(["a" * 64])
    assert result == 1
    output = capsys.readouterr()
    assert "private" not in output.out + output.err


def test_cli_has_no_observation_path_or_namespace_override():
    with pytest.raises(SystemExit) as result:
        api().main(["a" * 64, "--observation", "untrusted.json"])
    assert result.value.code == 2


def test_module_entrypoint_preserves_failure_exit_without_native_io(monkeypatch, capsys):
    import runpy

    from infra.hybrid import stock_failed_build

    @contextmanager
    def denied(source):
        raise ValueError("fixture denial")
        yield

    monkeypatch.setattr(stock_failed_build, "_completed_reconciliation", denied)
    monkeypatch.setattr("sys.argv", ["stock_producer_reconcile", "a" * 64])
    monkeypatch.delitem(
        __import__("sys").modules, "infra.hybrid.stock_producer_reconcile", raising=False
    )
    with pytest.raises(SystemExit) as result:
        runpy.run_module("infra.hybrid.stock_producer_reconcile", run_name="__main__")
    assert result.value.code == 1
    assert capsys.readouterr().out == '{"reason":"stock_producer_unavailable","status":"blocked"}\n'
