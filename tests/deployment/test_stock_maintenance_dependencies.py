"""Independently bind the offline host recipe to the frozen production lock graph."""

import hashlib
import importlib.metadata
import re
import tomllib
from pathlib import Path

import pytest
from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "infra/hybrid/stock-maintenance-requirements.txt"
RECIPE_SHA256 = "3750df43f52035f03b70669b1b7d1fcaf5e2b16a63e1fa7d8437ba40df292341"
LOCK_SHA256 = "d5b8a7dc41eba4badc9d1e0f70d340f65de776324ecfc47511bb0213fa2fe95d"


def _lock():
    return tomllib.loads((ROOT / "uv.lock").read_text())


def _requirements():
    assert RECIPE.is_file(), "The immutable offline maintenance recipe is missing"
    body = RECIPE.read_bytes()
    assert 0 < len(body) <= 524288 and body.endswith(b"\n")
    assert b"\r" not in body
    result = {}
    for line in body.decode("ascii").replace("\\\n", "").splitlines():
        if not line:
            continue
        definition, *hash_fields = line.split("--hash=")
        assert hash_fields, f"Unhashed requirement: {definition}"
        requirement = Requirement(definition.strip())
        assert requirement.url is None and not requirement.extras
        assert len(requirement.specifier) == 1
        pin = next(iter(requirement.specifier))
        assert pin.operator == "==" and "*" not in pin.version
        name = canonicalize_name(requirement.name)
        assert name not in result, f"Duplicate recipe distribution: {name}"
        hashes = [field.strip() for field in hash_fields]
        assert all(re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in hashes)
        assert len(hashes) == len(set(hashes))
        result[name] = (requirement, set(hashes))
    assert result
    return result


def _environment(version):
    # Fictional target facts, independent of the OS/Python executing these tests.
    return {
        "implementation_name": "cpython",
        "implementation_version": version,
        "os_name": "posix",
        "platform_machine": "x86_64",
        "platform_python_implementation": "CPython",
        "platform_release": "6.8.0",
        "platform_system": "Linux",
        "platform_version": "#1",
        "python_full_version": version,
        "python_version": "3.12",
        "sys_platform": "linux",
        "extra": "",
    }


def _closure(lock, environment):
    packages = {canonicalize_name(package["name"]): package for package in lock["package"]}
    assert len(packages) == len(lock["package"]), "Resolve lock variants explicitly if introduced"
    roots = [package for package in packages.values() if package["source"] == {"editable": "."}]
    assert len(roots) == 1
    pending = [*roots[0]["dependencies"], {"name": "pip"}]
    visited = set()
    selected = {}
    while pending:
        dependency = pending.pop()
        if (
            environment is not None
            and dependency.get("marker")
            and not Marker(dependency["marker"]).evaluate(environment=environment)
        ):
            continue
        name = canonicalize_name(dependency["name"])
        extras = tuple(sorted(dependency.get("extra", [])))
        if (name, extras) in visited:
            continue
        visited.add((name, extras))
        package = packages[name]
        assert package["source"] == {"registry": "https://pypi.org/simple"}
        selected[name] = package["version"]
        pending.extend(package.get("dependencies", []))
        optional = package.get("optional-dependencies", {})
        for extra in extras:
            assert extra in optional
            pending.extend(optional[extra])
    return selected


def test_maintenance_recipe_is_frozen_exactly_to_the_reviewed_lock_and_export_bytes():
    assert RECIPE.is_file(), "The immutable offline maintenance recipe is missing"
    assert hashlib.sha256(RECIPE.read_bytes()).hexdigest() == RECIPE_SHA256
    assert hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest() == LOCK_SHA256


def test_every_recipe_pin_and_hash_is_a_public_registry_artifact_in_uv_lock():
    lock = _lock()
    packages = {canonicalize_name(package["name"]): package for package in lock["package"]}
    assert importlib.metadata.version("packaging") == packages["packaging"]["version"]
    for name, (requirement, hashes) in _requirements().items():
        package = packages[name]
        assert package["source"] == {"registry": "https://pypi.org/simple"}
        assert str(requirement.specifier) == "==" + package["version"]
        artifacts = package.get("wheels", []) + ([package["sdist"]] if "sdist" in package else [])
        assert hashes <= {artifact["hash"] for artifact in artifacts}


def test_recipe_contains_only_the_production_graph_and_its_explicit_bootstrap_pip():
    lock = _lock()
    # Ignore platform markers only to include legitimate inactive Windows edges.
    # Optional dependencies are traversed only when an actual production edge requests them.
    assert set(_requirements()) == set(_closure(lock, None))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    root = next(package for package in lock["package"] if package["source"] == {"editable": "."})
    production = {canonicalize_name(Requirement(item).name) for item in project["dependencies"]}
    assert production == {canonicalize_name(edge["name"]) for edge in root["dependencies"]}
    assert canonicalize_name(project["name"]) not in _requirements()


@pytest.mark.parametrize("version", ["3.12.3", "3.12.13"])
def test_target_linux_cpython312_inventory_matches_the_exact_production_dependency_closure(version):
    environment = _environment(version)
    actual = {
        name: next(iter(requirement.specifier)).version
        for name, (requirement, _) in _requirements().items()
        if requirement.marker is None or requirement.marker.evaluate(environment=environment)
    }
    expected = _closure(_lock(), environment)
    assert actual == expected
    assert len(actual) == 49


def test_bootstrap_pip_is_pinned_to_its_same_lock_universal_wheel_only():
    lock = _lock()
    pip = next(package for package in lock["package"] if package["name"] == "pip")
    wheels = [wheel for wheel in pip["wheels"] if wheel["url"].endswith("-py3-none-any.whl")]
    assert len(wheels) == 1
    requirement, hashes = _requirements()["pip"]
    assert requirement.marker is None
    assert str(requirement.specifier) == "==" + pip["version"]
    assert hashes == {wheels[0]["hash"]}
