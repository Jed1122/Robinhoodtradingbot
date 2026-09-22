"""Local setup never prints credentials; estimation requires explicit network opt-in."""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

KEY = "db-" + "a" * 29


@pytest.mark.skipif(sys.platform != "darwin", reason="native macOS dialog compiler required")
def test_native_dialog_compiles_without_opening_ui(cli, tmp_path):
    result = subprocess.run(
        ["/usr/bin/osacompile", "-o", str(tmp_path / "dialog.scpt"), "-e", cli._DIALOG],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def cli():
    return importlib.import_module("trading_bot.cli.databento_preflight")


@pytest.fixture
def private(tmp_path):
    root = tmp_path.resolve() / "private"
    root.mkdir(mode=0o700)
    return root


def test_preview_does_not_read_key_or_connect(cli, private, capsys):
    code = cli.main(
        [
            "estimate",
            "--credential-directory",
            str(private),
            "--symbol",
            "SPY",
            "--schema",
            "definition",
            "--start",
            "2025-01-02",
            "--end",
            "2025-01-03",
        ]
    )
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "offline_preview"
    assert result["request"]["symbols"] == "SPY.OPT"
    assert result["request"]["schema"] == "definition"
    assert result["network_used"] is False
    assert result["download_authorized"] is False
    assert list(private.iterdir()) == []


def test_raw_preview_never_loads_credentials(cli, private, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("preview must not load credentials or call the provider")

    monkeypatch.setattr(cli, "load_credential", forbidden)
    monkeypatch.setattr(cli, "estimate_cost", forbidden)
    symbol = "SPY   250117C00500000"
    code = cli.main(
        [
            "estimate",
            "--credential-directory",
            str(private),
            "--symbol",
            symbol,
            "--stype-in",
            "raw_symbol",
            "--schema",
            "cbbo-1m",
            "--start",
            "2025-01-02",
            "--end",
            "2025-01-03",
        ]
    )
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "offline_preview"
    assert result["request"]["symbols"] == symbol
    assert result["request"]["stype_in"] == "raw_symbol"
    assert result["network_used"] is False
    assert result["download_authorized"] is False
    assert result["download_entitlement_verified"] is False
    assert result["economic_evidence"] is False
    assert result["credits_remaining"] is None
    assert list(private.iterdir()) == []


def test_invalid_raw_cli_denies_before_key_loading(cli, private, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid scope must not load credentials")

    monkeypatch.setattr(cli, "load_credential", forbidden)
    code = cli.main(
        [
            "estimate",
            "--credential-directory",
            str(private),
            "--symbol",
            KEY,
            "--stype-in",
            "raw_symbol",
            "--schema",
            "cbbo-1m",
            "--start",
            "2025-01-02",
            "--end",
            "2025-01-03",
            "--allow-metadata-network",
        ]
    )
    assert code == 2
    output = capsys.readouterr()
    assert KEY not in output.out + output.err
    result = json.loads(output.out)
    assert result["status"] == "denied"
    assert result["reason_code"] == "scope_invalid"
    assert result["network_used"] is False


def test_terminal_prompt_is_hidden_and_never_echoes_key(cli, private, monkeypatch, capsys):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: KEY)
    assert cli.main(["store-key", "--credential-directory", str(private)]) == 0
    output = capsys.readouterr()
    assert KEY not in output.out + output.err
    assert (private / "databento.key").read_text() == KEY


def test_pipe_cannot_be_used_to_enter_key(cli, private, monkeypatch, capsys):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    assert cli.main(["store-key", "--credential-directory", str(private)]) == 2
    assert "terminal_required" in capsys.readouterr().out
    assert list(private.iterdir()) == []


def test_getpass_echo_fallback_is_refused(cli, private, monkeypatch, capsys):
    import warnings

    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)

    def unsafe_prompt(prompt):
        warnings.warn("cannot hide input", cli.getpass.GetPassWarning, stacklevel=1)
        return KEY

    monkeypatch.setattr(cli.getpass, "getpass", unsafe_prompt)
    assert cli.main(["store-key", "--credential-directory", str(private)]) == 2
    assert KEY not in capsys.readouterr().out
    assert list(private.iterdir()) == []


def test_native_dialog_captures_only_in_process_not_argv(cli, private, monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "platform", "darwin")

    def native(args, **kwargs):
        assert args[0] == "/usr/bin/osascript"
        assert KEY not in repr(args)
        assert "with hidden answer" in args[2]
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["timeout"] == 120
        return subprocess.CompletedProcess(args, 0, KEY + "\n")

    monkeypatch.setattr(cli.subprocess, "run", native)
    assert cli.main(["store-key", "--native-dialog", "--credential-directory", str(private)]) == 0
    output = capsys.readouterr()
    assert KEY not in output.out + output.err
    assert (private / "databento.key").read_text() == KEY


@pytest.mark.parametrize("case", ["cancel", "timeout", "wrong_platform"])
def test_native_dialog_failures_never_print_output(cli, private, monkeypatch, capsys, case):
    monkeypatch.setattr(cli.sys, "platform", "darwin" if case != "wrong_platform" else "linux")

    def failed(args, **kwargs):
        if case == "timeout":
            raise subprocess.TimeoutExpired(args, 120, output=KEY)
        return subprocess.CompletedProcess(args, 1, KEY)

    monkeypatch.setattr(cli.subprocess, "run", failed)
    assert cli.main(["store-key", "--native-dialog", "--credential-directory", str(private)]) == 2
    assert KEY not in capsys.readouterr().out
    assert list(private.iterdir()) == []


@pytest.mark.parametrize("args", [["--key", KEY], ["nonsense", KEY]])
def test_bad_cli_arguments_are_not_echoed(cli, capsys, args):
    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert KEY not in output.out + output.err


def test_connected_estimate_without_key_fails_locally(cli, private, capsys):
    assert (
        cli.main(
            [
                "estimate",
                "--credential-directory",
                str(private),
                "--symbol",
                "SPY",
                "--schema",
                "cbbo-1m",
                "--start",
                "2025-01-02",
                "--end",
                "2025-01-03",
                "--allow-metadata-network",
            ]
        )
        == 2
    )
    assert "credential_invalid" in capsys.readouterr().out
    assert list(private.iterdir()) == []


def test_module_entrypoint_is_offline_and_rejects_unknown_arguments():
    result = subprocess.run(
        [__import__("sys").executable, "-m", "trading_bot.cli.databento_preflight", "--key", KEY],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parents[3],
    )
    assert result.returncode == 2
    assert KEY not in result.stdout + result.stderr
    assert "command_invalid" in result.stdout
