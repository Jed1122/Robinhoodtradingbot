"""Keep default verification on the stock bot and its real shared safeguards."""

import ast
import fnmatch
import tomllib
from pathlib import Path

from coverage import Coverage

ROOT = Path(__file__).parents[2]


def test_legacy_asset_suites_are_physically_retired() -> None:
    retired = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests").rglob("test_*.py")
        if any(word in path.name for word in ("etf", "options", "databento"))
    ]
    assert retired == []
    for relative in (
        "tests/unit/config/test_capital_research.py",
        "tests/unit/market_data/test_alpaca_capital_native.py",
        "tests/unit/research/test_equity_comparison.py",
        "tests/integration/runtime/test_connected_research.py",
        "tests/fixtures/etf",
        "tests/fixtures/robinhood_crypto",
    ):
        assert not (ROOT / relative).exists(), relative


def test_stock_and_shared_safety_tests_remain_in_the_default_test_root() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    settings = config["tool"]["pytest"]["ini_options"]
    assert settings["testpaths"] == ["tests"]
    assert settings["addopts"] == "-ra --strict-markers --strict-config -m 'not authenticated'"
    assert not {"norecursedirs", "python_files", "python_functions"} & settings.keys()
    for relative in (
        "unit/risk/test_trial_losses.py",
        "unit/risk/test_pretrade.py",
        "unit/accounting/test_owned_economics.py",
        "integration/persistence/test_owned_economic_journal.py",
        "integration/execution/test_service.py",
        "integration/capabilities/test_unsupported_asset_snapshot.py",
        "unit/research/test_hybrid_research.py",
        "unit/brokers/test_stock_research_mcp.py",
        "deployment/test_stock_release_producer.py",
        "deployment/test_stock_attempts.py",
    ):
        assert (ROOT / "tests" / relative).is_file(), relative


def test_configured_coverage_includes_whole_stock_and_shared_modules() -> None:
    coverage = Coverage(config_file=str(ROOT / "pyproject.toml"))
    assert coverage.get_option("run:source") == ["src/trading_bot", "infra/hybrid"]
    assert coverage.get_option("run:branch") is True
    assert coverage.get_option("report:fail_under") == 80
    omissions = coverage.get_option("run:omit")
    assert not coverage.get_option("run:include")
    protected = set((ROOT / "infra/hybrid").glob("stock_*.py"))
    for directory in ("risk", "authorization", "accounting", "execution", "hybrid"):
        protected.update((ROOT / "src/trading_bot" / directory).glob("*.py"))
    protected.update((ROOT / "src/trading_bot").rglob("stock_*.py"))
    for path in protected:
        if path.name.startswith(("etf_", "options")):
            continue
        assert not any(fnmatch.fnmatch(str(path), pattern) for pattern in omissions), path


def test_no_retained_test_imports_a_retired_test_helper() -> None:
    for path in (ROOT / "tests").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                if not module.startswith("tests."):
                    continue
                target = ROOT.joinpath(*module.split("."))
                assert target.with_suffix(".py").is_file() or target.is_dir(), (path, module)
