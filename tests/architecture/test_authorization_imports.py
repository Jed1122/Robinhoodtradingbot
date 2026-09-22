import ast
from pathlib import Path

PACKAGE = Path(__file__).parents[2] / "src" / "trading_bot"


def test_private_signing_key_is_confined_to_operator_signing_module() -> None:
    violations: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE)
        if relative in {
            Path("authorization/signing.py"),
            Path("brokers/robinhood_crypto_auth.py"),
        }:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "SigningKey" for alias in node.names
            ):
                violations.append(f"{relative}:{node.lineno}")
    assert violations == []


def test_runtime_authorization_does_not_import_operator_signing_module() -> None:
    for name in ("verifier.py", "preflight.py"):
        path = PACKAGE / "authorization" / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(
            isinstance(node, ast.ImportFrom) and node.module == "trading_bot.authorization.signing"
            for node in ast.walk(tree)
        )
