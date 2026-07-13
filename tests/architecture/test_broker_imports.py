"""AST-enforced broker capability boundaries."""

import ast
import re
from dataclasses import dataclass
from enum import Enum, auto
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
CURRENT_PLACE_ORDER_DEFINITION_ALLOWLIST = frozenset(
    {(Path("brokers/protocols.py"), "BrokerPlace")}
)

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


class _Identity(Enum):
    IMPORTLIB_MODULE = auto()
    BUILTINS_MODULE = auto()
    DYNAMIC_IMPORT = auto()
    GETATTR = auto()
    VARS = auto()


type _Binding = ast.expr | _Identity | None
type _Resolved = str | _Identity | None


@dataclass(slots=True)
class _ScopeFacts:
    kind: str
    parent: "_ScopeFacts | None"
    writes: dict[str, list[_Binding]]
    global_names: set[str]
    nonlocal_names: set[str]


@dataclass(frozen=True, slots=True)
class _ReflectionLookup:
    name: str | None


class _LexicalFacts(ast.NodeVisitor):
    """Collect direct writes and resolve only unambiguous lexical bindings."""

    def __init__(self, tree: ast.Module) -> None:
        self.module_scope = _ScopeFacts("module", None, {}, set(), set())
        self.current_scope = self.module_scope
        self.node_scopes: dict[ast.AST, _ScopeFacts] = {}
        self.visit(tree)

    def visit(self, node: ast.AST) -> None:
        self.node_scopes[node] = self.current_scope
        super().visit(node)

    def _record(self, name: str, value: _Binding) -> None:
        self._record_in_scope(self.current_scope, name, value)

    def _record_in_scope(self, scope: _ScopeFacts, name: str, value: _Binding) -> None:
        scope.writes.setdefault(name, []).append(value)

    def _record_unknown_target(self, target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            self._record(target.id, None)
        elif isinstance(target, (ast.List, ast.Tuple)):
            for element in target.elts:
                self._record_unknown_target(element)
        elif isinstance(target, ast.Starred):
            self._record_unknown_target(target.value)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        self._record(node.name, None)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ):
            if argument.annotation is not None:
                self.visit(argument.annotation)
        if node.args.vararg is not None and node.args.vararg.annotation is not None:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg is not None and node.args.kwarg.annotation is not None:
            self.visit(node.args.kwarg.annotation)
        if node.returns is not None:
            self.visit(node.returns)

        lexical_parent = self.current_scope
        if lexical_parent.kind == "class":
            assert lexical_parent.parent is not None
            lexical_parent = lexical_parent.parent
        function_scope = _ScopeFacts("function", lexical_parent, {}, set(), set())
        previous = self.current_scope
        self.current_scope = function_scope
        arguments = (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        )
        for argument in arguments:
            self._record(argument.arg, None)
            self.node_scopes[argument] = function_scope
        for optional_argument in (node.args.vararg, node.args.kwarg):
            if optional_argument is not None:
                self._record(optional_argument.arg, None)
                self.node_scopes[optional_argument] = function_scope
        for statement in node.body:
            self.visit(statement)
        self.current_scope = previous

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        lexical_parent = self.current_scope
        if lexical_parent.kind == "class":
            assert lexical_parent.parent is not None
            lexical_parent = lexical_parent.parent
        lambda_scope = _ScopeFacts("lambda", lexical_parent, {}, set(), set())
        previous = self.current_scope
        self.current_scope = lambda_scope
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ):
            self._record(argument.arg, None)
            self.node_scopes[argument] = lambda_scope
        for optional_argument in (node.args.vararg, node.args.kwarg):
            if optional_argument is not None:
                self._record(optional_argument.arg, None)
                self.node_scopes[optional_argument] = lambda_scope
        self.visit(node.body)
        self.current_scope = previous

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._record(node.name, None)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        class_scope = _ScopeFacts("class", self.current_scope, {}, set(), set())
        previous = self.current_scope
        self.current_scope = class_scope
        for statement in node.body:
            self.visit(statement)
        self.current_scope = previous

    def _visit_comprehension(
        self,
        generators: list[ast.comprehension],
        values: tuple[ast.expr, ...],
    ) -> None:
        first, *remaining = generators
        self.visit(first.iter)
        lexical_parent = self.current_scope
        if lexical_parent.kind == "class":
            assert lexical_parent.parent is not None
            lexical_parent = lexical_parent.parent
        comprehension_scope = _ScopeFacts("comprehension", lexical_parent, {}, set(), set())
        previous = self.current_scope
        self.current_scope = comprehension_scope
        self._record_unknown_target(first.target)
        self.visit(first.target)
        for condition in first.ifs:
            self.visit(condition)
        for generator in remaining:
            self.visit(generator.iter)
            self._record_unknown_target(generator.target)
            self.visit(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        for value in values:
            self.visit(value)
        self.current_scope = previous

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node.generators, (node.key, node.value))

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._record(target.id, node.value)
            else:
                self._record_unknown_target(target)
            self.visit(target)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
        self.visit(node.annotation)
        if isinstance(node.target, ast.Name):
            self._record(node.target.id, node.value)
        else:
            self._record_unknown_target(node.target)
        self.visit(node.target)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)
        self._record_unknown_target(node.target)
        self.visit(node.target)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        if isinstance(node.target, ast.Name):
            binding_scope = self.current_scope
            while binding_scope.kind == "comprehension":
                assert binding_scope.parent is not None
                binding_scope = binding_scope.parent
            self._record_in_scope(binding_scope, node.target.id, node.value)
            self.node_scopes[node.target] = binding_scope
        else:
            self._record_unknown_target(node.target)
            self.visit(node.target)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.pattern is not None:
            self.visit(node.pattern)
        if node.name is not None:
            self._record(node.name, None)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self._record(node.name, None)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        for key in node.keys:
            self.visit(key)
        for pattern in node.patterns:
            self.visit(pattern)
        if node.rest is not None:
            self._record(node.rest, None)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self._record_unknown_target(target)
            self.visit(target)

    def _visit_for(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        self._record_unknown_target(node.target)
        self.visit(node.target)
        for statement in (*node.body, *node.orelse):
            self.visit(statement)

    def visit_For(self, node: ast.For) -> None:
        self._visit_for(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_for(node)

    def _visit_with(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._record_unknown_target(item.optional_vars)
                self.visit(item.optional_vars)
        for statement in node.body:
            self.visit(statement)

    def visit_With(self, node: ast.With) -> None:
        self._visit_with(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._visit_with(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:
            self.visit(node.type)
        if node.name is not None:
            self._record(node.name, None)
        for statement in node.body:
            self.visit(statement)

    def visit_Global(self, node: ast.Global) -> None:
        self.current_scope.global_names.update(node.names)
        for name in node.names:
            self._record(name, None)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.current_scope.nonlocal_names.update(node.names)
        for name in node.names:
            self._record(name, None)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            bound_name = alias.asname or alias.name.split(".", maxsplit=1)[0]
            identity: _Identity | None = None
            if alias.name == "importlib" or (
                alias.asname is None and alias.name.startswith("importlib.")
            ):
                identity = _Identity.IMPORTLIB_MODULE
            elif alias.name == "builtins":
                identity = _Identity.BUILTINS_MODULE
            self._record(bound_name, identity)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if node.level == 0 and node.module == "importlib" and alias.name == "*":
                self._record("import_module", _Identity.DYNAMIC_IMPORT)
                continue
            identity: _Identity | None = None
            if node.level == 0 and node.module == "importlib" and alias.name == "import_module":
                identity = _Identity.DYNAMIC_IMPORT
            elif node.level == 0 and node.module == "builtins":
                identity = {
                    "__import__": _Identity.DYNAMIC_IMPORT,
                    "getattr": _Identity.GETATTR,
                    "vars": _Identity.VARS,
                }.get(alias.name)
            self._record(alias.asname or alias.name, identity)

    def scope_for(self, node: ast.AST) -> _ScopeFacts:
        return self.node_scopes[node]

    def resolve(self, node: ast.AST, scope: _ScopeFacts | None = None) -> _Resolved:
        return self._resolve(node, scope or self.scope_for(node), set())

    def _resolve(
        self,
        node: ast.AST,
        scope: _ScopeFacts,
        seen: set[tuple[int, str]],
    ) -> _Resolved:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return self._resolve_name(node.id, scope, seen)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self._resolve(node.left, scope, seen.copy())
            right = self._resolve(node.right, scope, seen.copy())
            if isinstance(left, str) and isinstance(right, str):
                return left + right
            return None
        if isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            for value in node.values:
                expression = value.value if isinstance(value, ast.FormattedValue) else value
                rendered = self._resolve(expression, scope, seen.copy())
                if not isinstance(rendered, str):
                    return None
                parts.append(rendered)
            return "".join(parts)
        if isinstance(node, ast.Attribute):
            owner = self._resolve(node.value, scope, seen)
            if owner is _Identity.IMPORTLIB_MODULE and node.attr == "import_module":
                return _Identity.DYNAMIC_IMPORT
            if owner is _Identity.BUILTINS_MODULE:
                return {
                    "__import__": _Identity.DYNAMIC_IMPORT,
                    "getattr": _Identity.GETATTR,
                    "vars": _Identity.VARS,
                }.get(node.attr)
        return None

    def _resolve_name(
        self,
        name: str,
        scope: _ScopeFacts,
        seen: set[tuple[int, str]],
    ) -> _Resolved:
        key = (id(scope), name)
        if key in seen:
            return None
        seen.add(key)
        if name in scope.global_names or name in scope.nonlocal_names:
            return None
        if name in scope.writes:
            values = scope.writes[name]
            if len(values) != 1 or values[0] is None:
                return None
            value = values[0]
            if isinstance(value, _Identity):
                return value
            return self._resolve(value, scope, seen)
        if scope.parent is not None:
            return self._resolve_name(name, scope.parent, seen)
        return {
            "__import__": _Identity.DYNAMIC_IMPORT,
            "getattr": _Identity.GETATTR,
            "vars": _Identity.VARS,
        }.get(name)


def _call_argument(node: ast.Call, position: int, keyword: str) -> ast.expr | None:
    if len(node.args) > position:
        return node.args[position]
    return next((item.value for item in node.keywords if item.arg == keyword), None)


def _dynamic_broker_import_violations(path: Path, package_root: Path) -> list[str]:
    tree = _parse(path)
    facts = _LexicalFacts(tree)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if facts.resolve(node.func, facts.scope_for(node)) is not _Identity.DYNAMIC_IMPORT:
            continue
        target = _call_argument(node, 0, "name")
        module = None if target is None else facts.resolve(target, facts.scope_for(node))
        if isinstance(module, str) and not _is_broker_module(module):
            continue
        relative = _relative_path(path, package_root)
        description = module if isinstance(module, str) else "unresolved target"
        violations.append(f"{relative}:{node.lineno}: dynamic broker import {description}")
    return violations


def _is_reflective_mapping(node: ast.AST, facts: _LexicalFacts, scope: _ScopeFacts) -> bool:
    return (isinstance(node, ast.Call) and facts.resolve(node.func, scope) is _Identity.VARS) or (
        isinstance(node, ast.Attribute) and node.attr == "__dict__"
    )


def _reflection_lookup(
    node: ast.AST,
    facts: _LexicalFacts,
) -> _ReflectionLookup | None:
    if not isinstance(node, (ast.Call, ast.Subscript)):
        return None
    scope = facts.scope_for(node)
    name_expression: ast.expr | None = None
    if isinstance(node, ast.Call):
        if facts.resolve(node.func, scope) is _Identity.GETATTR:
            name_expression = _call_argument(node, 1, "name")
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "__getattribute__":
            name_expression = _call_argument(node, 0, "name")
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and _is_reflective_mapping(node.func.value, facts, scope)
        ):
            name_expression = _call_argument(node, 0, "key")
        else:
            return None
    elif isinstance(node, ast.Subscript) and _is_reflective_mapping(node.value, facts, scope):
        name_expression = node.slice
    else:
        return None
    name = None if name_expression is None else facts.resolve(name_expression, scope)
    return _ReflectionLookup(name if isinstance(name, str) else None)


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
    facts = _LexicalFacts(tree)
    lines: set[int] = set()
    for node in ast.walk(tree):
        reflection = _reflection_lookup(node, facts)
        forbidden_reference = (
            (isinstance(node, ast.Name) and node.id in forbidden_names)
            or (isinstance(node, ast.Attribute) and node.attr in forbidden_names)
            or (
                reflection is not None
                and (reflection.name is None or reflection.name in forbidden_names)
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


def _class_place_order_members(tree: ast.Module) -> dict[str, list[tuple[str, ...]]]:
    classes: dict[str, list[tuple[str, ...]]] = {}

    def collect(body: list[ast.stmt], prefix: str = "") -> None:
        for statement in body:
            if not isinstance(statement, ast.ClassDef):
                continue
            qualified_name = f"{prefix}.{statement.name}" if prefix else statement.name
            kinds: list[str] = []
            for member in statement.body:
                if isinstance(member, ast.AsyncFunctionDef) and member.name == "place_order":
                    kinds.append("async")
                elif isinstance(member, ast.FunctionDef) and member.name == "place_order":
                    kinds.append("sync")
                elif isinstance(member, (ast.Assign, ast.AnnAssign)) and (
                    _assignment_defines_place_order(member)
                ):
                    kinds.append("assignment")
            classes.setdefault(qualified_name, []).append(tuple(kinds))
            collect(statement.body, qualified_name)

    collect(tree.body)
    return classes


def _is_broker_adapter_module(path: Path) -> bool:
    return (
        len(path.parts) >= 2
        and path.parts[0] == "brokers"
        and path.name not in {"__init__.py", "errors.py", "protocols.py"}
    )


def _place_order_use_sites(package_root: Path) -> set[Path]:
    sites: set[Path] = set()
    for path in _python_files(package_root):
        relative = _relative_path(path, package_root)
        tree = _parse(path)
        facts = _LexicalFacts(tree)
        unsafe = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "place_order":
                unsafe = True
                break
            reflection = _reflection_lookup(node, facts)
            if reflection is not None and (
                reflection.name == "place_order"
                or (reflection.name is None and _is_broker_adapter_module(relative))
            ):
                unsafe = True
                break
        if unsafe:
            sites.add(relative)
    return sites


def _definition_allowlist_violations(
    package_root: Path,
    allowlist: frozenset[tuple[Path, str]],
) -> set[Path]:
    allowed_paths = {path for path, _qualified_name in allowlist}
    violations = {
        path
        for path, kind in _place_order_definition_sites(package_root)
        if path not in allowed_paths or kind != "async"
    }
    definitions_by_path: dict[Path, list[str]] = {}
    for path, kind in _place_order_definition_sites(package_root):
        definitions_by_path.setdefault(path, []).append(kind)
    for path in allowed_paths:
        reviewed_names = {
            qualified_name for allowed_path, qualified_name in allowlist if allowed_path == path
        }
        source_path = package_root / path
        if not source_path.is_file():
            violations.add(path)
            continue
        class_members = _class_place_order_members(_parse(source_path))
        if any(class_members.get(name) != [("async",)] for name in reviewed_names):
            violations.add(path)
        definition_kinds = definitions_by_path.get(path, [])
        if len(definition_kinds) != len(reviewed_names) or any(
            kind != "async" for kind in definition_kinds
        ):
            violations.add(path)
    return violations


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
        ("forbidden", "risk/dynamic_alias.py"),
        ("cli", "cli/dynamic_alias.py"),
        ("recovery", "execution/recovery.py"),
    ),
)
@pytest.mark.parametrize(
    "source",
    (
        "import importlib\n"
        "loader = importlib.import_module\n"
        "module = loader(name=runtime_module_name())\n",
        "from importlib import import_module\n"
        "loader = import_module\n"
        "module = loader(name=runtime_module_name())\n",
        "loader = __import__\nmodule = loader(name=runtime_module_name())\n",
        "from builtins import __import__ as loader\nmodule = loader(name=runtime_module_name())\n",
        "import builtins\n"
        "loader = builtins.__import__\n"
        "module = loader(name=runtime_module_name())\n",
        "import importlib\nmodule = importlib.import_module(name=runtime_module_name())\n",
    ),
)
def test_dynamic_import_aliases_and_unresolved_keyword_targets_fail_closed(
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
        ("forbidden", "risk/dynamic_runtime.py"),
        ("cli", "cli/dynamic_runtime.py"),
        ("recovery", "execution/recovery.py"),
    ),
)
def test_direct_positional_unresolved_dynamic_import_fails_closed(
    tmp_path: Path,
    area: str,
    relative: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        relative,
        "import importlib\n"
        "MODULE = runtime_module_name()\n"
        "module = importlib.import_module(MODULE)\n",
    )
    assert _fixture_boundary_violations(package_root, area)


@pytest.mark.parametrize(
    ("area", "relative"),
    (
        ("forbidden", "risk/scoped_import.py"),
        ("cli", "cli/scoped_import.py"),
        ("recovery", "execution/recovery.py"),
    ),
)
def test_dynamic_import_constants_resolve_in_lexical_scope(
    tmp_path: Path,
    area: str,
    relative: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        relative,
        "import importlib\n"
        "def blocked():\n"
        "    TARGET = 'trading_bot.' + 'brokers'\n"
        "    return importlib.import_module(name=TARGET)\n"
        "def allowed():\n"
        "    TARGET = 'trading_bot.' + 'brokersafe'\n"
        "    return importlib.import_module(name=TARGET)\n",
    )
    violations = _fixture_boundary_violations(package_root, area)
    assert len(violations) == 1
    assert ":4:" in violations[0]


@pytest.mark.parametrize(
    ("area", "relative"),
    (
        ("forbidden", "risk/dynamic_alias.py"),
        ("cli", "cli/dynamic_alias.py"),
        ("recovery", "execution/recovery.py"),
    ),
)
def test_assigned_dynamic_import_alias_allows_proven_brokersafe_target(
    tmp_path: Path,
    area: str,
    relative: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        relative,
        "import importlib\n"
        "loader = importlib.import_module\n"
        "module = loader(name='trading_bot.' + 'brokersafe')\n",
    )
    assert _fixture_boundary_violations(package_root, area) == []


@pytest.mark.parametrize(
    ("area", "relative"),
    (
        ("forbidden", "risk/importlib_util.py"),
        ("cli", "cli/importlib_util.py"),
        ("recovery", "execution/recovery.py"),
    ),
)
def test_top_level_importlib_binding_from_submodule_import_is_recognized(
    tmp_path: Path,
    area: str,
    relative: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        relative,
        "import importlib.util\n"
        "module = importlib.import_module('trading_bot.brokers.protocols')\n",
    )
    assert _fixture_boundary_violations(package_root, area)


@pytest.mark.parametrize(
    ("area", "relative"),
    (
        ("forbidden", "risk/importlib_star.py"),
        ("cli", "cli/importlib_star.py"),
        ("recovery", "execution/recovery.py"),
    ),
)
def test_importlib_star_import_exposes_dynamic_import_callable(
    tmp_path: Path,
    area: str,
    relative: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        relative,
        "from importlib import *\nmodule = import_module(runtime_module_name())\n",
    )
    assert _fixture_boundary_violations(package_root, area)


@pytest.mark.parametrize(
    ("area", "relative", "import_source"),
    (
        ("forbidden", "risk/importlib_control.py", "import importlib.util"),
        ("cli", "cli/importlib_control.py", "import importlib.util"),
        ("recovery", "execution/recovery.py", "import importlib.util"),
        ("forbidden", "risk/importlib_control.py", "from importlib import *"),
        ("cli", "cli/importlib_control.py", "from importlib import *"),
        ("recovery", "execution/recovery.py", "from importlib import *"),
    ),
)
def test_new_importer_forms_preserve_exact_brokersafe_allowance(
    tmp_path: Path,
    area: str,
    relative: str,
    import_source: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        relative,
        f"{import_source}\nmodule = importlib.import_module('trading_bot.brokersafe')\n"
        if import_source == "import importlib.util"
        else f"{import_source}\nmodule = import_module('trading_bot.brokersafe')\n",
    )
    assert _fixture_boundary_violations(package_root, area) == []


@pytest.mark.parametrize(
    "source",
    (
        "import importlib\ndef load(TARGET):\n    return importlib.import_module(TARGET)\n",
        "import importlib\n"
        "TARGET = 'trading_bot.brokersafe'\n"
        "TARGET += runtime_suffix()\n"
        "module = importlib.import_module(TARGET)\n",
        "import importlib\n"
        "TARGET = 'trading_bot.brokersafe'\n"
        "del TARGET\n"
        "TARGET = runtime_module_name()\n"
        "module = importlib.import_module(TARGET)\n",
        "import importlib\n"
        "TARGET = 'trading_bot.brokersafe'\n"
        "modules = [importlib.import_module(TARGET) for TARGET in runtime_module_names()]\n",
    ),
)
def test_uncertain_lexical_import_targets_fail_closed(tmp_path: Path, source: str) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(package_root, "risk/uncertain_import.py", source)
    assert _forbidden_layer_import_violations(package_root)


def test_comprehension_walrus_writes_enclosing_scope(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        "risk/comprehension_walrus.py",
        "import importlib\n"
        "TARGET = 'trading_bot.brokersafe'\n"
        "[TARGET := runtime_module_name() for _ in values()]\n"
        "module = importlib.import_module(TARGET)\n",
    )
    assert _forbidden_layer_import_violations(package_root)


def test_match_capture_writes_enclosing_scope(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        "risk/match_capture.py",
        "import importlib\n"
        "TARGET = 'trading_bot.brokersafe'\n"
        "match runtime_module_name():\n"
        "    case TARGET:\n"
        "        pass\n"
        "module = importlib.import_module(TARGET)\n",
    )
    assert _forbidden_layer_import_violations(package_root)


@pytest.mark.parametrize(
    "pattern",
    (
        "[*TARGET]",
        "{**TARGET}",
    ),
)
def test_structural_pattern_capture_forms_are_unknown_writes(
    tmp_path: Path,
    pattern: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        "risk/structural_capture.py",
        "import importlib\n"
        "TARGET = 'trading_bot.brokersafe'\n"
        "match runtime_module_name():\n"
        f"    case {pattern}:\n"
        "        pass\n"
        "module = importlib.import_module(TARGET)\n",
    )
    assert _forbidden_layer_import_violations(package_root)


@pytest.mark.parametrize(
    "pattern",
    (
        "constants.TARGET",
        "models.TARGET()",
    ),
)
def test_pattern_value_and_class_attributes_are_not_capture_writes(
    tmp_path: Path,
    pattern: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        "risk/pattern_attribute.py",
        "import importlib\n"
        "TARGET = 'trading_bot.brokersafe'\n"
        "match runtime_module_name():\n"
        f"    case {pattern}:\n"
        "        pass\n"
        "module = importlib.import_module(TARGET)\n",
    )
    assert _forbidden_layer_import_violations(package_root) == []


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


@pytest.mark.parametrize(
    ("area", "relative"),
    (
        ("forbidden", "risk/reflection.py"),
        ("cli", "cli/reflection.py"),
        ("recovery", "execution/recovery.py"),
    ),
)
@pytest.mark.parametrize(
    "source",
    (
        "NAME = 'Broker' + 'Place'\ncapability = vars(module).get(NAME)\n",
        "NAME = 'BrokerPlace'\ncapability = module.__dict__.get(NAME)\n",
        "NAME = 'BrokerPlace'\ncapability = vars(module)[NAME]\n",
        "NAME = 'BrokerPlace'\ncapability = module.__dict__[NAME]\n",
        "NAME = 'BrokerPlace'\nlookup = getattr\ncapability = lookup(module, NAME)\n",
        "NAME = 'BrokerPlace'\nfields = vars\ncapability = fields(module).get(NAME)\n",
        "def blocked(module):\n"
        "    NAME = 'BrokerPlace'\n"
        "    return vars(module).get(NAME)\n"
        "def allowed(module):\n"
        "    NAME = 'health_check'\n"
        "    return vars(module).get(NAME)\n",
    ),
)
def test_reflective_mapping_get_rejects_scoped_broker_place_names(
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
        ("forbidden", "risk/unresolved_reflection.py"),
        ("cli", "cli/unresolved_reflection.py"),
        ("recovery", "execution/recovery.py"),
    ),
)
def test_unresolved_reflective_capability_lookup_fails_closed(
    tmp_path: Path,
    area: str,
    relative: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        relative,
        "NAME = runtime_name()\ncapability = vars(module).get(NAME)\n",
    )
    assert _fixture_boundary_violations(package_root, area)


def test_unresolved_reflection_outside_restricted_areas_remains_allowed(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        "config/loader.py",
        "NAME = runtime_name()\ncapability = vars(module).get(NAME)\n",
    )
    assert _forbidden_layer_import_violations(package_root) == []
    assert _cli_violations(package_root) == []
    assert _recovery_violations(package_root) == []


def test_ordinary_mapping_subscript_is_not_a_capability_lookup(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        "cli/labels.py",
        "labels = {'BrokerPlace': 'disabled'}\nlabel = labels['BrokerPlace']\n",
    )
    assert _cli_violations(package_root) == []


def test_ordinary_mapping_get_is_not_a_capability_lookup(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        "cli/labels.py",
        "labels = {'BrokerPlace': 'disabled'}\nlabel = labels.get('BrokerPlace')\n",
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
    assert (
        _definition_allowlist_violations(package_root, frozenset({(adapter, "ReviewedAdapter")}))
        == set()
    )
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
    assert _definition_allowlist_violations(
        package_root, frozenset({(adapter, "ReviewedAdapter")})
    ) == {adapter}


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
    assert _definition_allowlist_violations(
        package_root, frozenset({(adapter, "ReviewedAdapter")})
    ) == {adapter}


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
    assert _definition_allowlist_violations(
        package_root, frozenset({(adapter, "ReviewedAdapter")})
    ) == {adapter}


def test_allowlisted_adapter_rejects_imported_place_base_without_override(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    adapter = Path("brokers/reviewed_adapter.py")
    _write_module(
        package_root,
        str(adapter),
        "from provider import PlacementBase\nclass ReviewedAdapter(PlacementBase):\n    pass\n",
    )
    assert _definition_allowlist_violations(
        package_root, frozenset({(adapter, "ReviewedAdapter")})
    ) == {adapter}


def test_allowlisted_adapter_rejects_aliased_place_base_without_override(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    adapter = Path("brokers/reviewed_adapter.py")
    _write_module(
        package_root,
        str(adapter),
        "class PlacementBase:\n"
        "    async def place_order(self, submission: object) -> object:\n"
        "        return submission\n"
        "BaseAlias = PlacementBase\n"
        "class ReviewedAdapter(BaseAlias):\n"
        "    pass\n",
    )
    assert _definition_allowlist_violations(
        package_root, frozenset({(adapter, "ReviewedAdapter")})
    ) == {adapter}


def test_allowlisted_adapter_accepts_direct_async_override_of_imported_base(
    tmp_path: Path,
) -> None:
    package_root = _fixture_package(tmp_path)
    adapter = Path("brokers/reviewed_adapter.py")
    _write_module(
        package_root,
        str(adapter),
        "from provider import PlacementBase\n"
        "class ReviewedAdapter(PlacementBase):\n"
        "    async def place_order(self, submission: object) -> object:\n"
        "        return submission\n",
    )
    assert (
        _definition_allowlist_violations(package_root, frozenset({(adapter, "ReviewedAdapter")}))
        == set()
    )


def test_allowlisted_adapter_path_rejects_extra_place_capable_class(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    adapter = Path("brokers/reviewed_adapter.py")
    _write_module(
        package_root,
        str(adapter),
        "class ReviewedAdapter:\n"
        "    async def place_order(self, submission: object) -> object:\n"
        "        return submission\n"
        "class UnreviewedAdapter:\n"
        "    async def place_order(self, submission: object) -> object:\n"
        "        return submission\n",
    )
    assert _definition_allowlist_violations(
        package_root, frozenset({(adapter, "ReviewedAdapter")})
    ) == {adapter}


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


@pytest.mark.parametrize(
    "source",
    (
        "NAME = resolve_operation_name()\ncallback = getattr(broker, NAME)\n",
        "NAME = resolve_operation_name()\ncallback = broker.__getattribute__(NAME)\n",
        "NAME = resolve_operation_name()\ncallback = vars(broker)[NAME]\n",
        "NAME = resolve_operation_name()\ncallback = vars(broker).get(NAME)\n",
        "NAME = resolve_operation_name()\ncallback = broker.__dict__[NAME]\n",
        "NAME = resolve_operation_name()\ncallback = broker.__dict__.get(NAME)\n",
    ),
)
def test_adapter_unresolved_reflection_fails_closed_as_possible_place_use(
    tmp_path: Path,
    source: str,
) -> None:
    package_root = _fixture_package(tmp_path)
    adapter = Path("brokers/reviewed_adapter.py")
    _write_module(package_root, str(adapter), source)
    assert _place_order_use_sites(package_root) == {adapter}


def test_adapter_reflection_resolves_same_name_in_each_function_scope(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    adapter = Path("brokers/reviewed_adapter.py")
    _write_module(
        package_root,
        str(adapter),
        "def place_callback(broker):\n"
        "    NAME = 'place_' + 'order'\n"
        "    return getattr(broker, NAME)\n"
        "def health_callback(broker):\n"
        "    NAME = 'health_' + 'check'\n"
        "    return getattr(broker, NAME)\n",
    )
    assert _place_order_use_sites(package_root) == {adapter}


def test_known_safe_adapter_reflection_and_ordinary_mapping_access_are_allowed(
    tmp_path: Path,
) -> None:
    package_root = _fixture_package(tmp_path)
    adapter = Path("brokers/reviewed_adapter.py")
    _write_module(
        package_root,
        str(adapter),
        "NAME = 'health_' + 'check'\n"
        "callback = getattr(broker, NAME)\n"
        "health = vars(broker).get(NAME)\n"
        "labels = {'place_order': 'disabled'}\n"
        "label = labels['place_order']\n"
        "other = labels.get('place_order')\n",
    )
    assert _place_order_use_sites(package_root) == set()


def test_unresolved_config_getattr_is_not_treated_as_adapter_place_use(tmp_path: Path) -> None:
    package_root = _fixture_package(tmp_path)
    _write_module(
        package_root,
        "config/loader.py",
        "NAME = resolve_field_name()\nvalue = getattr(settings, NAME)\n",
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
