from pathlib import Path


def test_live_cli_tests_do_not_import_network_clients() -> None:
    source = Path("tests/integration/cli/test_live_commands.py").read_text()
    assert "httpx" not in source
    assert "RobinhoodCryptoPlaceAdapter" not in source
