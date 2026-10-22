"""Fictional runtime metadata and real tempfile trust checks; never execute a runtime."""

import copy
import hashlib
import importlib
import json
import os
import stat
from pathlib import Path

import pytest

COMMIT = "a" * 40
PREFIX = "/opt/hybrid-stock-research/maintenance/" + COMMIT
LOCK = b"fictional immutable source lock\n"
REQUIREMENTS = b"fictional hashed production export plus pinned pip\n"
CONFIG = "c" * 64
ARCHIVE = "d" * 64


def module():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_maintenance_runtime.py"
    assert path.is_file(), "Independent maintenance runtime receipt verification is not implemented"
    return importlib.import_module("infra.hybrid.stock_maintenance_runtime")


def distribution(name, version):
    return {"name": name, "version": version, "direct_url_present": False, "editable": False}


def facts():
    packages = [distribution("pip", "26.2.1"), distribution("PyNaCl", "1.6.2")]
    return {
        "source_commit": COMMIT,
        "source_archive_sha256": ARCHIVE,
        "uv_lock_sha256": hashlib.sha256(LOCK).hexdigest(),
        "requirements_sha256": hashlib.sha256(REQUIREMENTS).hexdigest(),
        "config_hash": CONFIG,
        "python_implementation": "cpython",
        "python_version": "3.12.3",
        "platform": "linux",
        "architecture": "x86_64",
        "include_system_site_packages": False,
        "sys_prefix": PREFIX,
        "site_packages": PREFIX + "/lib/python3.12/site-packages",
        "distributions": copy.deepcopy(packages),
        "expected_distributions": copy.deepcopy(packages),
        "hashed_install_verified": True,
        "pip_check_verified": True,
    }


def expected():
    source = facts()
    return {
        key: source[key]
        for key in (
            "source_commit",
            "source_archive_sha256",
            "uv_lock_sha256",
            "requirements_sha256",
            "config_hash",
        )
    }


def test_pure_receipt_builder_normalizes_unique_packages_and_emits_closed_canonical_bytes():
    api = module()
    source = facts()
    body = api.build_runtime_receipt(source)
    value = json.loads(body)
    assert value == source | {
        "schema_version": 1,
        "kind": "stock_maintenance_runtime",
        "distributions": [distribution("pip", "26.2.1"), distribution("pynacl", "1.6.2")],
        "expected_distributions": [distribution("pip", "26.2.1"), distribution("pynacl", "1.6.2")],
    }
    assert body == (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    assert source["distributions"][1]["name"] == "PyNaCl"
    source["distributions"].reverse()
    assert api.build_runtime_receipt(source) == body


@pytest.fixture
def setup(tmp_path):
    api = module()
    anchor = tmp_path.resolve()
    anchor.chmod(0o755)
    runtime_root, source_root = anchor / "maintenance", anchor / "source"
    runtime, checkout = runtime_root / COMMIT, source_root / COMMIT
    trusted = anchor / "trusted"
    for path in (
        runtime_root,
        source_root,
        runtime,
        checkout,
        trusted,
        runtime / "bin",
        runtime / "lib",
    ):
        path.mkdir(mode=0o755)
    site = runtime / "lib/python3.12/site-packages"
    site.mkdir(mode=0o755, parents=True)
    (site / "fictional.py").write_bytes(b"# never imported or executed\n")
    (site / "fictional.py").chmod(0o644)
    interpreter = trusted / "python3.12"
    interpreter.write_bytes(b"fictional file, never executed\n")
    interpreter.chmod(0o755)
    (runtime / "bin/python").symlink_to("python3")
    (runtime / "bin/python3").symlink_to("python3.12")
    (runtime / "bin/python3.12").symlink_to(interpreter)
    (runtime / "lib64").symlink_to("lib", target_is_directory=True)
    (runtime / "requirements.txt").write_bytes(REQUIREMENTS)
    (runtime / "requirements.txt").chmod(0o400)
    (checkout / "uv.lock").write_bytes(LOCK)
    (checkout / "uv.lock").chmod(0o644)
    (checkout / "src").mkdir(mode=0o755)
    (checkout / "src/helper.py").write_bytes(b"# fictional source, never executed\n")
    (checkout / "src/helper.py").chmod(0o644)
    (runtime / "pyvenv.cfg").write_text(
        "home = /usr/bin\ninclude-system-site-packages = false\nversion = 3.12.3\n"
        "executable = /usr/bin/python3.12\ncommand = fictional initialization\n"
    )
    (runtime / "pyvenv.cfg").chmod(0o644)
    receipt = runtime / "runtime-receipt.json"
    receipt.write_bytes(api.build_runtime_receipt(facts()))
    receipt.chmod(0o400)
    return api, anchor, runtime_root, source_root, interpreter, receipt


def verify(setup, *, actual=None, **changes):
    api, anchor, runtime_root, source_root, interpreter, receipt = setup
    return api._verify_runtime_receipt(
        receipt,
        **(expected() | changes),
        actual_facts=facts() if actual is None else actual,
        trusted_uid=os.geteuid(),
        runtime_root=runtime_root,
        source_root=source_root,
        interpreter_target=interpreter,
        trusted_anchor=anchor,
    )


def test_private_fixture_verifier_checks_retained_bytes_and_trusted_standard_venv_links(setup):
    assert verify(setup) == json.loads(setup[-1].read_bytes())


@pytest.mark.parametrize(
    "selected,mode",
    [
        ("anchor", 0o700),
        ("runtime_root", 0o700),
        ("source_root", 0o700),
        ("runtime", 0o700),
        ("checkout", 0o700),
        ("runtime_bin", 0o700),
        ("runtime_lib", 0o700),
        ("dependency_dir", 0o700),
        ("source_dir", 0o700),
        ("interpreter_parent", 0o700),
        ("runtime", 0o711),
        ("dependency_dir", 0o744),
        ("source_file", 0o600),
        ("source_file", 0o640),
        ("dependency_file", 0o600),
        ("configuration", 0o600),
        ("lock", 0o600),
        ("interpreter", 0o700),
        ("interpreter", 0o744),
        ("interpreter", 0o711),
    ],
)
def test_reduced_helper_has_deterministic_read_traverse_and_execution_permissions(
    setup, selected, mode
):
    _, anchor, runtime_root, source_root, interpreter, _ = setup
    runtime, checkout = runtime_root / COMMIT, source_root / COMMIT
    path = {
        "anchor": anchor,
        "runtime_root": runtime_root,
        "source_root": source_root,
        "runtime": runtime,
        "checkout": checkout,
        "runtime_bin": runtime / "bin",
        "runtime_lib": runtime / "lib",
        "dependency_dir": runtime / "lib/python3.12/site-packages",
        "source_dir": checkout / "src",
        "interpreter_parent": interpreter.parent,
        "source_file": checkout / "src/helper.py",
        "dependency_file": runtime / "lib/python3.12/site-packages/fictional.py",
        "configuration": runtime / "pyvenv.cfg",
        "lock": checkout / "uv.lock",
        "interpreter": interpreter,
    }[selected]
    path.chmod(mode)
    with pytest.raises(ValueError, match=r"^stock_maintenance_runtime_unavailable$"):
        verify(setup)


def test_immutable_readable_source_and_dependencies_accept_root_only_recipe_metadata(setup):
    _, _, runtime_root, source_root, _, _ = setup
    runtime, checkout = runtime_root / COMMIT, source_root / COMMIT
    (runtime / "lib/python3.12/site-packages/fictional.py").chmod(0o444)
    (checkout / "src/helper.py").chmod(0o444)
    assert (runtime / "runtime-receipt.json").stat().st_mode & 0o777 == 0o400
    assert (runtime / "requirements.txt").stat().st_mode & 0o777 == 0o400
    assert verify(setup)["source_commit"] == COMMIT


@pytest.mark.parametrize("directory,mode", [(False, 0o604), (True, 0o705)])
def test_primary_helper_group_must_not_shadow_required_other_access(setup, directory, mode):
    values = list(setup[1].stat())
    values[0] = (stat.S_IFDIR if directory else stat.S_IFREG) | mode
    values[5] = 10001
    metadata = os.stat_result(values)
    with pytest.raises(ValueError, match=r"^stock_maintenance_runtime_unavailable$"):
        setup[0]._trusted(metadata, os.geteuid(), directory=directory)


def test_primary_helper_group_requires_execute_on_interpreter_target(setup, monkeypatch):
    api, _, runtime_root, _, interpreter, _ = setup
    original = api._path

    def group_owned(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == interpreter:
            values = list(info)
            values[0] = stat.S_IFREG | 0o745
            values[5] = 10001
            return os.stat_result(values)
        return info

    monkeypatch.setattr(api, "_path", group_owned)
    with pytest.raises(ValueError, match=r"^stock_maintenance_runtime_unavailable$"):
        api._python_link(
            runtime_root / COMMIT / "bin/python",
            runtime_root / COMMIT,
            interpreter,
            os.geteuid(),
            setup[1],
        )


def test_public_verifier_cannot_select_fixture_namespaces_or_owner(setup):
    with pytest.raises(ValueError, match=r"^stock_maintenance_runtime_unavailable$"):
        setup[0].verify_runtime_receipt(setup[-1], **expected(), actual_facts=facts())


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_commit", "A" * 40),
        ("source_commit", "a" * 39),
        ("source_archive_sha256", True),
        ("uv_lock_sha256", "z" * 64),
        ("requirements_sha256", "f" * 63),
        ("config_hash", None),
        ("python_implementation", "pypy"),
        ("python_version", "3.14.6"),
        ("python_version", "3.12.3rc1"),
        ("python_version", "3.12.03"),
        ("platform", "darwin"),
        ("architecture", "aarch64"),
        ("include_system_site_packages", True),
        ("include_system_site_packages", 0),
        ("sys_prefix", "/tmp/runtime"),
        ("site_packages", PREFIX + "/external"),
        ("hashed_install_verified", False),
        ("hashed_install_verified", 1),
        ("pip_check_verified", False),
        ("distributions", ()),
        ("expected_distributions", []),
    ],
)
def test_builder_rejects_wrong_source_python_isolation_or_install_facts(field, value):
    with pytest.raises(ValueError, match=r"^stock_maintenance_runtime_unavailable$"):
        module().build_runtime_receipt(facts() | {field: value})


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "missing",
        "actual_extra",
        "expected_extra",
        "no_pip",
        "duplicate",
        "normalized_duplicate",
        "url",
        "editable",
        "bool_flag",
        "bad_name",
        "bad_version",
        "too_many",
    ],
)
def test_distribution_inventory_is_closed_unique_frozen_and_has_no_direct_or_editable_inputs(
    mutation,
):
    value = facts()
    if mutation == "extra":
        value["unknown"] = True
    elif mutation == "missing":
        del value["config_hash"]
    elif mutation == "actual_extra":
        value["distributions"].append(distribution("pytest", "9.1.1"))
    elif mutation == "expected_extra":
        value["expected_distributions"].append(distribution("pytest", "9.1.1"))
    elif mutation == "no_pip":
        value["distributions"] = value["expected_distributions"] = [distribution("pynacl", "1.6.2")]
    elif mutation == "duplicate":
        value["distributions"].append(distribution("PIP", "26.2.1"))
    elif mutation == "normalized_duplicate":
        value["distributions"] += [distribution("some_pkg", "1"), distribution("some.pkg", "1")]
    elif mutation == "too_many":
        value["distributions"] += [distribution(f"package-{n}", "1") for n in range(257)]
    else:
        field, replacement = {
            "url": ("direct_url_present", True),
            "editable": ("editable", True),
            "bool_flag": ("editable", 0),
            "bad_name": ("name", "../../outside"),
            "bad_version": ("version", "1.0 @ https://private.example"),
        }[mutation]
        value["distributions"][0][field] = replacement
    with pytest.raises(ValueError, match=r"^stock_maintenance_runtime_unavailable$"):
        module().build_runtime_receipt(value)


@pytest.mark.parametrize("field", list(expected()))
def test_verification_binds_every_independently_expected_source_hash(setup, field):
    changed = "1" * (40 if field == "source_commit" else 64)
    with pytest.raises(ValueError, match=r"^stock_maintenance_runtime_unavailable$"):
        verify(setup, **{field: changed})


def test_current_python_or_installed_distribution_drift_denies_even_with_original_receipt(setup):
    for changed in [
        facts() | {"python_version": "3.12.4"},
        facts() | {"distributions": [distribution("pip", "26.2.1")]},
    ]:
        with pytest.raises(ValueError, match=r"^stock_maintenance_runtime_unavailable$"):
            verify(setup, actual=changed)


@pytest.mark.parametrize(
    "mutation",
    ["mode", "symlink", "hardlink", "oversize", "noncanonical", "duplicate", "unknown", "non_utf8"],
)
def test_receipt_is_root_policy_private_single_link_bounded_closed_canonical_json(setup, mutation):
    receipt = setup[-1]
    original = receipt.read_bytes()
    receipt.chmod(0o600)
    if mutation == "mode":
        receipt.chmod(0o444)
    elif mutation == "symlink":
        receipt.unlink()
        receipt.symlink_to(receipt.parent / "requirements.txt")
    elif mutation == "hardlink":
        os.link(receipt, receipt.with_name("alias"))
        receipt.chmod(0o400)
    else:
        body = {
            "oversize": b"x" * 65537,
            "noncanonical": original + b" ",
            "duplicate": b'{"schema_version":1,"schema_version":1}\n',
            "unknown": original.replace(b'"schema_version":1', b'"unknown":1,"schema_version":1'),
            "non_utf8": b"\xff\n",
        }[mutation]
        receipt.write_bytes(body)
        receipt.chmod(0o400)
    with pytest.raises(ValueError, match=r"^stock_maintenance_runtime_unavailable$"):
        verify(setup)


@pytest.mark.parametrize(
    "selected",
    [
        "lock",
        "requirements",
        "source_dir",
        "dependency_dir",
        "dependency_file",
        "interpreter",
        "interpreter_parent",
    ],
)
def test_current_recipe_bytes_and_all_trusted_code_metadata_are_checked(setup, selected):
    _, _, runtime_root, source_root, interpreter, _ = setup
    runtime = runtime_root / COMMIT
    if selected == "lock":
        (source_root / COMMIT / "uv.lock").write_bytes(b"changed")
    elif selected == "requirements":
        path = runtime / "requirements.txt"
        path.chmod(0o600)
        path.write_bytes(b"changed")
    else:
        path = {
            "source_dir": source_root / COMMIT,
            "dependency_dir": runtime / "lib/python3.12/site-packages",
            "dependency_file": runtime / "lib/python3.12/site-packages/fictional.py",
            "interpreter": interpreter,
            "interpreter_parent": interpreter.parent,
        }[selected]
        path.chmod(0o777)
    with pytest.raises(ValueError, match=r"^stock_maintenance_runtime_unavailable$"):
        verify(setup)


@pytest.mark.parametrize(
    "mutation",
    ["external_dependency", "external_source", "python_escape", "python_cycle", "lib64_escape"],
)
def test_only_closed_trusted_venv_symlinks_are_accepted(setup, mutation):
    _, _, runtime_root, source_root, _, _ = setup
    runtime = runtime_root / COMMIT
    if mutation == "external_dependency":
        (runtime / "lib/python3.12/site-packages/outside").symlink_to("/etc/passwd")
    elif mutation == "external_source":
        (source_root / COMMIT / "outside").symlink_to("/etc/passwd")
    else:
        path, target = {
            "python_escape": (runtime / "bin/python", "/usr/bin/other-python"),
            "python_cycle": (runtime / "bin/python3", "python"),
            "lib64_escape": (runtime / "lib64", "/usr/lib"),
        }[mutation]
        path.unlink()
        path.symlink_to(target)
    with pytest.raises(ValueError, match=r"^stock_maintenance_runtime_unavailable$"):
        verify(setup)


@pytest.mark.parametrize(
    "change",
    [
        "include-system-site-packages = true",
        "version = 3.12.4",
        "executable = /usr/bin/other-python",
        "home = /tmp",
        "include-system-site-packages = false\ninclude-system-site-packages = true",
    ],
)
def test_actual_venv_configuration_cannot_import_unrecorded_system_environment(setup, change):
    path = setup[2] / COMMIT / "pyvenv.cfg"
    body = path.read_text()
    key = change.split(" = ", 1)[0]
    body = (
        "\n".join(change if line.startswith(key + " = ") else line for line in body.splitlines())
        + "\n"
    )
    path.write_text(body)
    with pytest.raises(ValueError, match=r"^stock_maintenance_runtime_unavailable$"):
        verify(setup)


def test_runtime_inventory_count_is_bounded(setup, monkeypatch):
    monkeypatch.setattr(setup[0], "_MAX_TREE_ENTRIES", 3)
    with pytest.raises(ValueError, match=r"^stock_maintenance_runtime_unavailable$"):
        verify(setup)


@pytest.mark.parametrize("replacement", ["missing", "wrapper"])
def test_runtime_python_entrypoint_must_be_a_trusted_distro_interpreter_link(setup, replacement):
    path = setup[2] / COMMIT / "bin/python"
    path.unlink()
    if replacement == "wrapper":
        path.write_bytes(b"# fictional wrapper, never executed\n")
        path.chmod(0o755)
    with pytest.raises(ValueError, match=r"^stock_maintenance_runtime_unavailable$"):
        verify(setup)


@pytest.mark.parametrize("field", ["python_implementation", "platform", "architecture"])
def test_builder_requires_plain_fixed_string_facts(field):
    class UnsafeString(str):
        pass

    value = facts()
    value[field] = UnsafeString(value[field])
    with pytest.raises(ValueError, match=r"^stock_maintenance_runtime_unavailable$"):
        module().build_runtime_receipt(value)
