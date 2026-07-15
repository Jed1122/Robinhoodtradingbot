"""AST and export boundaries for persistence transaction ownership."""

import ast
from pathlib import Path

from trading_bot.persistence import audit, repositories

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "trading_bot"


def test_sqlalchemy_imports_are_confined_to_persistence() -> None:
    violations: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        relative = path.relative_to(PACKAGE_ROOT)
        if relative.parts[0] == "persistence":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                if module == "sqlalchemy" or module.startswith("sqlalchemy."):
                    violations.append(f"{relative}:{node.lineno}: {module}")

    assert violations == []


def test_persistence_exports_protocols_not_raw_session_writers() -> None:
    assert repositories.__all__ == [
        "AuditRepository",
        "AuthorizationRepository",
        "DataQualityRepository",
        "EvidenceRepository",
        "FillRepository",
        "OrderRepository",
        "ReconciliationRepository",
        "SubmissionAttemptRepository",
    ]
    assert audit.__all__ == ["serialize_audit_details"]
