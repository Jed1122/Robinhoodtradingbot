"""AST-enforced broker capability boundaries."""

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "trading_bot"

FORBIDDEN_BROKER_IMPORT_LAYERS = (
    "strategies",
    "portfolio",
    "risk",
    "research",
    "reporting",
    "llm",
    "monitoring",
)
PROTOCOL_NAMES = frozenset({"BrokerRead", "BrokerReview", "BrokerPlace", "BrokerCancelOnly"})
ERROR_NAMES = frozenset(
    {
        "UnsupportedCapabilityError",
        "BrokerUnavailable",
        "BrokerSubmissionAmbiguous",
        "SchemaDriftError",
    }
)
CLI_ALLOWED_PROTOCOLS = PROTOCOL_NAMES - {"BrokerPlace"}
RECOVERY_ALLOWED_PROTOCOLS = frozenset({"BrokerRead", "BrokerCancelOnly"})
PLACE_ORDER_USE_ALLOWLIST = frozenset({Path("execution/service.py")})
CURRENT_PLACE_ORDER_DEFINITION_ALLOWLIST = frozenset({Path("brokers/protocols.py")})

EXPECTED_PROTOCOL_IMPORTS = {
    "datetime": frozenset({"datetime"}),
    "decimal": frozenset({"Decimal"}),
    "typing": frozenset({"Protocol"}),
    "trading_bot.domain": frozenset(
        {
            "AccountId",
            "AccountSnapshot",
            "AssetClass",
            "BrokerHealth",
            "BrokerOrder",
            "BrokerOrderId",
            "BrokerOrderReview",
            "CancelReceipt",
            "Fill",
            "OrderIntent",
            "PersistedReviewedOrder",
            "Position",
        }
    ),
}


@dataclass(frozen=True, slots=True)
class ImportUse:
    path: Path
    module: str
    name: str | None
    lineno: int
    whole_module: bool


def _python_files(root: Path) -> tuple[Path, ...]:
    if not root.exists():
        return ()
    return tuple(sorted(root.rglob("*.py")))


def _area_python_files(package_root: Path, area: str) -> tuple[Path, ...]:
    paths = list(_python_files(package_root / area))
    root_module = package_root / f"{area}.py"
    if root_module.is_file():
        paths.append(root_module)
    return tuple(sorted(paths))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _relative_path(path: Path, package_root: Path) -> Path:
    return path.relative_to(package_root)


def _current_package_parts(path: Path, package_root: Path) -> tuple[str, ...]:
    relative = path.relative_to(package_root).with_suffix("")
    module_parts = (package_root.name, *relative.parts)
    if module_parts[-1] == "__init__":
        return module_parts[:-1]
    return module_parts[:-1]


def _resolve_import_from_module(
    node: ast.ImportFrom,
    path: Path,
    package_root: Path,
) -> str:
    if node.level == 0:
        return node.module or ""
    current_package = _current_package_parts(path, package_root)
    parents_to_remove = node.level - 1
    if parents_to_remove > len(current_package):
        return ""
    base = current_package[: len(current_package) - parents_to_remove]
    suffix = tuple(node.module.split(".")) if node.module else ()
    return ".".join((*base, *suffix))


def _is_broker_module(module: str) -> bool:
    return module == "trading_bot.brokers" or module.startswith("trading_bot.brokers.")


def _broker_imports_in_file(path: Path, package_root: Path) -> tuple[ImportUse, ...]:
    uses: list[ImportUse] = []
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_broker_module(alias.name):
                    uses.append(
                        ImportUse(
                            path=path,
                            module=alias.name,
                            name=None,
                            lineno=node.lineno,
                            whole_module=True,
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            base_module = _resolve_import_from_module(node, path, package_root)
            for alias in node.names:
                if _is_broker_module(base_module):
                    uses.append(
                        ImportUse(
                            path=path,
                            module=base_module,
                            name=alias.name,
                            lineno=node.lineno,
                            whole_module=False,
                        )
                    )
                    continue
                imported_module = ".".join(part for part in (base_module, alias.name) if part)
                if _is_broker_module(imported_module):
                    uses.append(
                        ImportUse(
                            path=path,
                            module=imported_module,
                            name=None,
                            lineno=node.lineno,
                            whole_module=True,
                        )
                    )
    return tuple(uses)


def _format_import_use(use: ImportUse, package_root: Path) -> str:
    imported = use.module if use.name is None else f"{use.module}:{use.name}"
    return f"{_relative_path(use.path, package_root)}:{use.lineno}: {imported}"


def _forbidden_layer_import_violations(package_root: Path) -> list[str]:
    violations: list[str] = []
    for layer in FORBIDDEN_BROKER_IMPORT_LAYERS:
        for path in _area_python_files(package_root, layer):
            violations.extend(
                _format_import_use(use, package_root)
                for use in _broker_imports_in_file(path, package_root)
            )
            violations.extend(_dynamic_broker_import_violations(path, package_root))
            violations.extend(_forbidden_reference_violations(path, package_root, PROTOCOL_NAMES))
    return sorted(violations)


def _restricted_import_violations(
    path: Path,
    package_root: Path,
    *,
    allowed_protocols: frozenset[str],
) -> list[str]:
    allowed_by_module = {
        "trading_bot.brokers": allowed_protocols | ERROR_NAMES,
        "trading_bot.brokers.protocols": allowed_protocols,
        "trading_bot.brokers.errors": ERROR_NAMES,
    }
    violations: list[str] = []
    for use in _broker_imports_in_file(path, package_root):
        allowed_names = allowed_by_module.get(use.module, frozenset())
        if use.whole_module or use.name not in allowed_names:
            violations.append(_format_import_use(use, package_root))
    violations.extend(_dynamic_broker_import_violations(path, package_root))
    return violations


def _constant_string(node: ast.AST, constants: dict[str, str] | None = None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and constants is not None:
        return constants.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _constant_string(node.left, constants)
        right = _constant_string(node.right, constants)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                rendered = _constant_string(value.value, constants)
            else:
                rendered = _constant_string(value, constants)
            if rendered is None:
                return None
            parts.append(rendered)
        return "".join(parts)
    return None


def _constant_bindings(tree: ast.Module) -> dict[str, str]:
    assignments: dict[str, list[ast.AST | None]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assignments.setdefault(node.target.id, []).append(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            assignments.setdefault(node.target.id, []).append(None)
        elif isinstance(node, ast.arg) and node.arg in assignments:
            assignments[node.arg].append(None)

    constants: dict[str, str] = {}
    changed = True
    while changed:
        changed = False
        for name, values in assignments.items():
            if name in constants or len(values) != 1 or values[0] is None:
                continue
            value = _constant_string(values[0], constants)
            if value is not None:
                constants[name] = value
                changed = True
    return constants


def _dynamic_import_aliases(
    tree: ast.Module,
) -> tuple[set[str], set[str], set[str]]:
    importlib_modules: set[str] = set()
    builtins_modules: set[str] = set()
    import_functions = {"__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    importlib_modules.add(alias.asname or alias.name)
                elif alias.name == "builtins":
                    builtins_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            for alias in node.names:
                if (node.module == "importlib" and alias.name == "import_module") or (
                    node.module == "builtins" and alias.name == "__import__"
                ):
                    import_functions.add(alias.asname or alias.name)
    return importlib_modules, builtins_modules, import_functions


def _is_dynamic_import_call(
    node: ast.Call,
    importlib_modules: set[str],
    builtins_modules: set[str],
    import_functions: set[str],
) -> bool:
    if isinstance(node.func, ast.Name):
        return node.func.id in import_functions
    if not isinstance(node.func, ast.Attribute) or not isinstance(node.func.value, ast.Name):
        return False
    if node.func.attr == "import_module":
        return node.func.value.id in importlib_modules
    if node.func.attr == "__import__":
        return node.func.value.id in builtins_modules
    return False


def _dynamic_broker_import_violations(path: Path, package_root: Path) -> list[str]:
    tree = _parse(path)
    constants = _constant_bindings(tree)
    import_aliases = _dynamic_import_aliases(tree)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if not _is_dynamic_import_call(node, *import_aliases):
            continue
        module = _constant_string(node.args[0], constants)
        if module is not None and _is_broker_module(module):
            relative = _relative_path(path, package_root)
            violations.append(f"{relative}:{node.lineno}: dynamic broker import {module}")
    return violations


def _dynamic_lookup_name(node: ast.Call, constants: dict[str, str] | None = None) -> str | None:
    if isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2:
        return _constant_string(node.args[1], constants)
    if isinstance(node.func, ast.Attribute) and node.func.attr == "getattr" and len(node.args) >= 2:
        return _constant_string(node.args[1], constants)
    if isinstance(node.func, ast.Attribute) and node.func.attr == "__getattribute__":
        for argument in node.args:
            value = _constant_string(argument, constants)
            if value is not None:
                return value
    return None


def _reflective_subscript_name(
    node: ast.Subscript,
    constants: dict[str, str] | None = None,
) -> str | None:
    source = node.value
    is_vars_lookup = (
        isinstance(source, ast.Call)
        and isinstance(source.func, ast.Name)
        and source.func.id == "vars"
        and len(source.args) == 1
    )
    is_dict_lookup = isinstance(source, ast.Attribute) and source.attr == "__dict__"
    if not is_vars_lookup and not is_dict_lookup:
        return None
    return _constant_string(node.slice, constants)


def _annotation_values(tree: ast.Module) -> tuple[ast.expr, ...]:
    values: list[ast.expr] = []
    for node in ast.walk(tree):
        annotation: ast.expr | None = None
        if isinstance(node, (ast.arg, ast.AnnAssign)):
            annotation = node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            annotation = node.returns
        if annotation is not None:
            values.append(annotation)
    return tuple(values)


def _annotation_mentions(annotation: ast.AST, forbidden_names: frozenset[str]) -> bool:
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name) and node.id in forbidden_names:
            return True
        if isinstance(node, ast.Attribute) and node.attr in forbidden_names:
            return True
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and any(re.search(rf"\b{re.escape(name)}\b", node.value) for name in forbidden_names)
        ):
            return True
    return False


def _forbidden_reference_violations(
    path: Path,
    package_root: Path,
    forbidden_names: frozenset[str],
) -> list[str]:
    tree = _parse(path)
    constants = _constant_bindings(tree)
    lines: set[int] = set()
    for node in ast.walk(tree):
        forbidden_reference = (
            (isinstance(node, ast.Name) and node.id in forbidden_names)
            or (isinstance(node, ast.Attribute) and node.attr in forbidden_names)
            or (
                isinstance(node, ast.Call)
                and _dynamic_lookup_name(node, constants) in forbidden_names
            )
            or (
                isinstance(node, ast.Subscript)
                and _reflective_subscript_name(node, constants) in forbidden_names
            )
        )
        if forbidden_reference:
            assert isinstance(node, (ast.Name, ast.Attribute, ast.Call, ast.Subscript))
            lines.add(node.lineno)
    for annotation in _annotation_values(tree):
        if _annotation_mentions(annotation, forbidden_names):
            lines.add(annotation.lineno)
    relative = _relative_path(path, package_root)
    return [f"{relative}:{line}: forbidden capability reference" for line in sorted(lines)]


def _cli_violations(package_root: Path) -> list[str]:
    violations: list[str] = []
    for path in _area_python_files(package_root, "cli"):
        violations.extend(
            _restricted_import_violations(
                path,
                package_root,
                allowed_protocols=CLI_ALLOWED_PROTOCOLS,
            )
        )
        violations.extend(
            _forbidden_reference_violations(
                path,
                package_root,
                frozenset({"BrokerPlace"}),
            )
        )
    return sorted(set(violations))


def _recovery_files(package_root: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in _python_files(package_root)
        if path.stem == "recovery" or "recovery" in path.relative_to(package_root).parts[:-1]
    )


def _recovery_violations(package_root: Path) -> list[str]:
    violations: list[str] = []
    for path in _recovery_files(package_root):
        violations.extend(
            _restricted_import_violations(
                path,
                package_root,
                allowed_protocols=RECOVERY_ALLOWED_PROTOCOLS,
            )
        )
        violations.extend(
            _forbidden_reference_violations(
                path,
                package_root,
                frozenset({"BrokerReview", "BrokerPlace"}),
            )
        )
    return sorted(set(violations))


def _assignment_defines_place_order(node: ast.Assign | ast.AnnAssign) -> bool:
    if isinstance(node, ast.AnnAssign):
        return (
            node.value is not None
            and isinstance(node.target, ast.Name)
            and (node.target.id == "place_order")
        )
    return any(
        isinstance(target, ast.Name) and target.id == "place_order" for target in node.targets
    )


def _class_directly_exposes_place_order(node: ast.ClassDef) -> bool:
    return any(
        (
            isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            and statement.name == "place_order"
        )
        or (
            isinstance(statement, (ast.Assign, ast.AnnAssign))
            and _assignment_defines_place_order(statement)
        )
        for statement in node.body
    )


def _base_class_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _place_order_definition_sites(package_root: Path) -> tuple[tuple[Path, str], ...]:
    sites: list[tuple[Path, int, str]] = []
    for path in _python_files(package_root):
        relative = _relative_path(path, package_root)
        tree = _parse(path)
        class_nodes = tuple(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "place_order":
                sites.append((relative, node.lineno, "async"))
            elif isinstance(node, ast.FunctionDef) and node.name == "place_order":
                sites.append((relative, node.lineno, "sync"))
        for class_node in class_nodes:
            for statement in class_node.body:
                if isinstance(statement, (ast.Assign, ast.AnnAssign)) and (
                    _assignment_defines_place_order(statement)
                ):
                    sites.append((relative, statement.lineno, "assignment"))

        capable_class_names = {
            node.name for node in class_nodes if _class_directly_exposes_place_order(node)
        }
        changed = True
        while changed:
            changed = False
            for class_node in class_nodes:
                if class_node.name in capable_class_names:
                    continue
                if any(_base_class_name(base) in capable_class_names for base in class_node.bases):
                    capable_class_names.add(class_node.name)
                    changed = True
        for class_node in class_nodes:
            if _class_directly_exposes_place_order(class_node):
                continue
            if any(_base_class_name(base) in capable_class_names for base in class_node.bases):
                sites.append((relative, class_node.lineno, "inherited"))
    return tuple((path, kind) for path, _lineno, kind in sorted(sites))


def _place_order_use_sites(package_root: Path) -> set[Path]:
    sites: set[Path] = set()
    for path in _python_files(package_root):
        tree = _parse(path)
        constants = _constant_bindings(tree)
        unsafe = any(
            (isinstance(node, ast.Attribute) and node.attr == "place_order")
            or (
                isinstance(node, ast.Call)
                and _dynamic_lookup_name(node, constants) == "place_order"
            )
            or (
                isinstance(node, ast.Subscript)
                and _reflective_subscript_name(node, constants) == "place_order"
            )
            for node in ast.walk(tree)
        )
        if unsafe:
            sites.add(_relative_path(path, package_root))
    return sites


def _definition_allowlist_violations(
    package_root: Path,
    allowlist: frozenset[Path],
) -> set[Path]:
    return {
        path
        for path, kind in _place_order_definition_sites(package_root)
        if path not in allowlist or kind != "async"
    }


def _write_module(package_root: Path, relative: str, source: str) -> Path:
    path = package_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _fixture_package(tmp_path: Path) -> Path:
    package_root = tmp_path / "trading_bot"
    _write_module(package_root, "__init__.py", "")
    return package_root


def _fixture_boundary_violations(package_root: Path, area: str) -> list[str]:
    if area == "forbidden":
        return _forbidden_layer_import_violations(package_root)
    if area == "cli":
        return _cli_violations(package_root)
    if area == "recovery":
        return _recovery_violations(package_root)
    raise AssertionError(f"unknown fixture area: {area}")


def test_production_paths_are_derived_from_this_test_file() -> None:
    assert Path(__file__).resolve().parents[2] == PROJECT_ROOT
    assert PACKAGE_ROOT == PROJECT_ROOT / "src" / "trading_bot"
    assert PACKAGE_ROOT.is_dir()


def test_production_forbidden_layers_do_not_import_brokers() -> None:
    assert _forbidden_layer_import_violations(PACKAGE_ROOT) == []


@pytest.mark.parametrize("layer", FORBIDDEN_BROKER_IMPORT_LAYERS)
def test_forbidden_layer_rule_is_non_vacuous(tmp_path: Path, layer: str) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        f"{layer}/consumer.py",
        "from trading_bot.brokers import BrokerRead\n",
    )
    violations = _forbidden_layer_import_violations(package_root)
    assert len(violations) == 1
    assert violations[0].startswith(f"{layer}/consumer.py:1:")


@pytest.mark.parametrize("layer", FORBIDDEN_BROKER_IMPORT_LAYERS)
def test_forbidden_root_modules_are_scanned(tmp_path: Path, layer: str) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        f"{layer}.py",
        "from trading_bot.brokers import BrokerRead\n",
    )
    violations = _forbidden_layer_import_violations(package_root)
    assert len(violations) == 1
    assert violations[0].startswith(f"{layer}.py:1:")


def test_type_checking_imports_are_scanned(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        "strategies/typed.py",
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from trading_bot.brokers import BrokerRead\n",
    )
    assert len(_forbidden_layer_import_violations(package_root)) == 1


@pytest.mark.parametrize(
    "source",
    (
        "def consume(broker: BrokerRead) -> None:\n    pass\n",
        "def consume(broker: 'BrokerReview') -> None:\n    pass\n",
        "capability = contracts.BrokerCancelOnly\n",
        "capability = getattr(registry, 'Broker' + 'Place')\n",
    ),
)
def test_forbidden_layers_reject_injected_protocol_references(
    tmp_path: Path,
    source: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(package_root, "risk/injected.py", source)
    assert _forbidden_layer_import_violations(package_root)


@pytest.mark.parametrize(
    "source",
    (
        "import trading_bot.brokers\n",
        "from trading_bot.brokers import BrokerPlace\n",
        "from trading_bot import brokers\n",
        "from ..brokers import BrokerPlace\n",
        "from .. import brokers\n",
    ),
)
def test_absolute_and_relative_broker_imports_are_canonicalized(
    tmp_path: Path,
    source: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    path = _write_module(package_root, "strategies/consumer.py", source)
    uses = _broker_imports_in_file(path, package_root)
    assert len(uses) == 1
    assert _is_broker_module(uses[0].module)


def test_exact_broker_module_boundary_does_not_match_brokersafe(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        "strategies/consumer.py",
        "import trading_bot.brokersafe\n"
        "from trading_bot import brokersafe\n"
        "from ..brokersafe import PublicRecord\n",
    )
    assert _forbidden_layer_import_violations(package_root) == []


@pytest.mark.parametrize(
    ("area", "relative"),
    (
        ("forbidden", "risk/dynamic_import.py"),
        ("cli", "cli/dynamic_import.py"),
        ("recovery", "execution/recovery.py"),
    ),
)
@pytest.mark.parametrize(
    "source",
    (
        "import importlib\nmodule = importlib.import_module('trading_bot.' + 'brokers')\n",
        "from importlib import import_module\n"
        "module = import_module('trading_bot.brokers.protocols')\n",
        "module = __import__('trading_bot.' + 'brokers')\n",
    ),
)
def test_constant_dynamic_broker_imports_are_rejected(
    tmp_path: Path,
    area: str,
    relative: str,
    source: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(package_root, relative, source)
    assert _fixture_boundary_violations(package_root, area)


@pytest.mark.parametrize(
    ("area", "relative"),
    (
        ("forbidden", "risk/dynamic_import.py"),
        ("cli", "cli/dynamic_import.py"),
        ("recovery", "execution/recovery.py"),
    ),
)
@pytest.mark.parametrize(
    "source",
    (
        "import importlib\nmodule = importlib.import_module('trading_bot.brokersafe')\n",
        "from importlib import import_module\n"
        "module = import_module('trading_bot.brokersafe.tools')\n",
        "module = __import__('trading_bot.' + 'brokersafe')\n",
    ),
)
def test_constant_dynamic_imports_respect_exact_broker_boundary(
    tmp_path: Path,
    area: str,
    relative: str,
    source: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(package_root, relative, source)
    assert _fixture_boundary_violations(package_root, area) == []


@pytest.mark.parametrize(
    ("area", "relative"),
    (
        ("forbidden", "risk/reflection.py"),
        ("cli", "cli/reflection.py"),
        ("recovery", "execution/recovery.py"),
    ),
)
def test_reflective_constant_broker_place_subscript_is_rejected(
    tmp_path: Path,
    area: str,
    relative: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        relative,
        "capability = vars(module)['Broker' + 'Place']\n",
    )
    assert _fixture_boundary_violations(package_root, area)


def test_ordinary_mapping_subscript_is_not_a_capability_lookup(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        "cli/labels.py",
        "labels = {'BrokerPlace': 'disabled'}\nlabel = labels['BrokerPlace']\n",
    )
    assert _cli_violations(package_root) == []


def test_production_cli_has_no_place_provider_or_whole_broker_import() -> None:
    assert _cli_violations(PACKAGE_ROOT) == []


def test_cli_allows_only_explicit_non_place_contract_names(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        "cli/status.py",
        "from ..brokers import (\n"
        "    BrokerCancelOnly,\n"
        "    BrokerRead,\n"
        "    BrokerReview,\n"
        "    BrokerUnavailable,\n"
        ")\n",
    )
    assert _cli_violations(package_root) == []


@pytest.mark.parametrize(
    "source",
    (
        "from trading_bot.brokers import BrokerPlace\n",
        "from trading_bot import brokers\n",
        "import trading_bot.brokers.protocols\n",
        "from trading_bot.brokers.robinhood_crypto_api import RobinhoodCryptoPlaceAdapter\n",
        "def command(place: 'BrokerPlace') -> None:\n    pass\n",
        "capability = getattr(object(), 'Broker' + 'Place')\n",
    ),
)
def test_cli_restrictions_are_non_vacuous(tmp_path: Path, source: str) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(package_root, "cli/live.py", source)
    assert _cli_violations(package_root)


def test_cli_root_module_is_scanned(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(package_root, "cli.py", "capability: 'BrokerPlace'\n")
    assert _cli_violations(package_root)


def test_production_recovery_has_only_read_cancel_and_narrow_errors() -> None:
    assert _recovery_violations(PACKAGE_ROOT) == []


def test_recovery_allows_exact_read_cancel_and_error_imports(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        "execution/recovery.py",
        "from ..brokers import (\n"
        "    BrokerCancelOnly,\n"
        "    BrokerRead,\n"
        "    BrokerUnavailable,\n"
        "    SchemaDriftError,\n"
        ")\n",
    )
    assert _recovery_violations(package_root) == []


@pytest.mark.parametrize(
    "source",
    (
        "from ..brokers import BrokerReview\n",
        "from ..brokers import BrokerPlace\n",
        "from .. import brokers\n",
        "from trading_bot.brokers.robinhood_crypto_api import RobinhoodCryptoPlaceAdapter\n",
        "def recover(place: 'BrokerPlace') -> None:\n    pass\n",
        "capability = getattr(object(), 'Broker' + 'Place')\n",
    ),
)
def test_recovery_restrictions_are_non_vacuous(tmp_path: Path, source: str) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(package_root, "execution/recovery.py", source)
    assert _recovery_violations(package_root)


def test_protocol_module_imports_only_canonical_broker_neutral_types() -> None:
    protocol_path = PACKAGE_ROOT / "brokers" / "protocols.py"
    tree = _parse(protocol_path)
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))

    actual: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        assert node.level == 0
        assert node.module is not None
        actual.setdefault(node.module, set()).update(alias.name for alias in node.names)
    actual_imports = {module: frozenset(names) for module, names in actual.items()}
    assert actual_imports == EXPECTED_PROTOCOL_IMPORTS


def test_current_production_has_one_protocol_definition_and_no_place_use() -> None:
    definitions = _place_order_definition_sites(PACKAGE_ROOT)
    assert definitions == ((Path("brokers/protocols.py"), "async"),)
    assert (
        _definition_allowlist_violations(
            PACKAGE_ROOT,
            CURRENT_PLACE_ORDER_DEFINITION_ALLOWLIST,
        )
        == set()
    )

    uses = _place_order_use_sites(PACKAGE_ROOT)
    assert uses == set()
    assert uses <= PLACE_ORDER_USE_ALLOWLIST
    assert {Path("execution/service.py")} == PLACE_ORDER_USE_ALLOWLIST


def test_reviewed_adapter_declaration_is_not_mistaken_for_invocation(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    adapter = Path("brokers/reviewed_adapter.py")
    _write_module(
        package_root,
        str(adapter),
        "class ReviewedAdapter:\n"
        "    async def place_order(self, submission: object) -> object:\n"
        "        return submission\n",
    )
    assert _place_order_definition_sites(package_root) == ((adapter, "async"),)
    assert _definition_allowlist_violations(package_root, frozenset({adapter})) == set()
    assert _place_order_use_sites(package_root) == set()


def test_allowlisted_adapter_path_still_rejects_sync_place_definition(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    adapter = Path("brokers/reviewed_adapter.py")
    _write_module(
        package_root,
        str(adapter),
        "class ReviewedAdapter:\n"
        "    def place_order(self, submission: object) -> object:\n"
        "        return submission\n",
    )
    assert _place_order_definition_sites(package_root) == ((adapter, "sync"),)
    assert _definition_allowlist_violations(package_root, frozenset({adapter})) == {adapter}


def test_allowlisted_adapter_rejects_class_callable_place_assignment(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    adapter = Path("brokers/reviewed_adapter.py")
    _write_module(
        package_root,
        str(adapter),
        "async def provider_submit(submission: object) -> object:\n"
        "    return submission\n"
        "class ReviewedAdapter:\n"
        "    place_order = provider_submit\n",
    )
    assert (adapter, "assignment") in _place_order_definition_sites(package_root)
    assert _definition_allowlist_violations(package_root, frozenset({adapter})) == {adapter}


def test_allowlisted_adapter_rejects_inherited_place_exposure(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    adapter = Path("brokers/reviewed_adapter.py")
    _write_module(
        package_root,
        str(adapter),
        "class PlacementMixin:\n"
        "    async def place_order(self, submission: object) -> object:\n"
        "        return submission\n"
        "class ReviewedAdapter(PlacementMixin):\n"
        "    pass\n",
    )
    assert _definition_allowlist_violations(package_root, frozenset({adapter})) == {adapter}


def test_definition_inventory_preserves_multiple_same_file_declarations(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    adapter = Path("brokers/reviewed_adapter.py")
    _write_module(
        package_root,
        str(adapter),
        "class FirstAdapter:\n"
        "    async def place_order(self, submission: object) -> object:\n"
        "        return submission\n"
        "class SecondAdapter:\n"
        "    async def place_order(self, submission: object) -> object:\n"
        "        return submission\n",
    )
    assert len(_place_order_definition_sites(package_root)) == 2


@pytest.mark.parametrize(
    "source",
    (
        "async def invoke(broker, order):\n    return await broker.place_order(order)\n",
        "async def invoke(broker, order):\n"
        "    submit = broker.place_order\n"
        "    return await submit(order)\n",
        "async def invoke(broker, order):\n"
        "    submit = getattr(broker, 'place_' + 'order')\n"
        "    return await submit(order)\n",
        "async def invoke(broker, order):\n"
        "    submit = broker.__getattribute__('place_' + 'order')\n"
        "    return await submit(order)\n",
        "NAME = 'place_' + 'order'\n"
        "async def invoke(broker, order):\n"
        "    submit = getattr(broker, NAME)\n"
        "    return await submit(order)\n",
        "async def invoke(broker, order):\n"
        "    submit = vars(broker)['place_' + 'order']\n"
        "    return await submit(order)\n",
    ),
)
def test_adapter_place_invocation_and_alias_bypasses_are_denied(
    tmp_path: Path,
    source: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    adapter = Path("brokers/reviewed_adapter.py")
    _write_module(package_root, str(adapter), source)
    assert _place_order_use_sites(package_root) == {adapter}
    assert _place_order_use_sites(package_root) - PLACE_ORDER_USE_ALLOWLIST == {adapter}


def test_unresolved_dynamic_and_ordinary_subscript_access_are_not_place_uses(
    tmp_path: Path,
) -> None:
    package_root = _fixture_package(tmp_path)
    adapter = Path("brokers/reviewed_adapter.py")
    _write_module(
        package_root,
        str(adapter),
        "NAME = resolve_operation_name()\n"
        "callback = getattr(broker, NAME)\n"
        "labels = {'place_order': 'disabled'}\n"
        "label = labels['place_order']\n",
    )
    assert _place_order_use_sites(package_root) == set()


def test_only_future_execution_service_is_reserved_for_place_invocation(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    service = Path("execution/service.py")
    adapter = Path("brokers/reviewed_adapter.py")
    invocation = "async def invoke(broker, order):\n    return await broker.place_order(order)\n"
    _write_module(package_root, str(service), invocation)
    _write_module(package_root, str(adapter), invocation)
    assert _place_order_use_sites(package_root) == {service, adapter}
    assert _place_order_use_sites(package_root) - PLACE_ORDER_USE_ALLOWLIST == {adapter}
