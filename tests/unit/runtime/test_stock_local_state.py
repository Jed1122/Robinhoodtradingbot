"""Local observation has no ledger, provider or execution side effects."""

import hashlib
import json
from datetime import timedelta

import pytest

from tests.unit.runtime.test_stock_dashboard_export import NOW
from tests.unit.runtime.test_stock_dashboard_export import data as _data
from trading_bot.runtime import stock_local_state as module
from trading_bot.runtime.stock_dashboard_export import publish_stock_dashboard
from trading_bot.runtime.stock_research_controls import StockResearchControls

data = _data


@pytest.fixture
def local(data, tmp_path):
    export, loaded, projection = data
    control = tmp_path.resolve() / "controls"
    control.mkdir(mode=0o700)
    controls = StockResearchControls(control, clock=lambda: NOW)
    state = controls.initialize()
    publish_stock_dashboard(root=export, export=projection)
    return export, loaded, projection, control, controls, state


def test_observe_retains_original_times_and_control_identity(local):
    export, loaded, projection, control, _, state = local
    before = (export / "stock-research.json").read_bytes()
    result = module.read_local_stock_state(
        loaded=loaded, control_dir=control, export_dir=export, now=NOW + timedelta(hours=4)
    )
    assert result["projection"] == projection.model_dump(mode="json")
    assert result["control"] == state.record.model_dump(mode="json")
    assert result["control_sha256"] == state.sha256
    assert before == (export / "stock-research.json").read_bytes()
    assert result["projection"]["generated_at"] == projection.generated_at.isoformat().replace(
        "+00:00", "Z"
    )


def test_missing_projection_remains_missing_not_fabricated(local):
    export, loaded, _, control, _, _ = local
    (export / "stock-research.json").unlink()
    assert (
        module.read_local_stock_state(
            loaded=loaded, control_dir=control, export_dir=export, now=NOW
        )["projection"]
        is None
    )


@pytest.mark.parametrize("failure", ["future", "corrupt", "public", "symlink", "extra"])
def test_invalid_observation_fails_without_repair(local, failure):
    export, loaded, _, control, _, _ = local
    file = export / "stock-research.json"
    now = NOW
    if failure == "future":
        now -= timedelta(seconds=1)
    elif failure == "corrupt":
        file.write_bytes(b"secret fixture invalid")
    elif failure == "public":
        file.chmod(0o644)
    elif failure == "symlink":
        file.rename(export / "forensic")
        file.symlink_to(export / "forensic")
    else:
        other = export / "unknown"
        other.write_bytes(b"preserve")
        other.chmod(0o600)
    with pytest.raises(ValueError, match="stock_local_state_unavailable"):
        module.read_local_stock_state(
            loaded=loaded, control_dir=control, export_dir=export, now=now
        )


def test_control_permission_gate_requires_current_exact_grant(local):
    _, loaded, _, control, controls, state = local
    code = "b" * 64
    with pytest.raises(ValueError):
        module.check_local_research_authority(loaded=loaded, code_hash=code, control_dir=control)
    running = controls.change(
        "resume", expected_sha256=state.sha256, config_hash=str(loaded.config_hash), code_hash=code
    )
    receipt = module.check_local_research_authority(
        loaded=loaded, code_hash=code, control_dir=control
    )
    assert receipt == {
        "status": "running",
        "control_sha256": running.sha256,
        "control_id": running.record.control_id,
        "generation": 1,
    }
    assert (
        hashlib.sha256((control / "stock-control.json").read_bytes()).hexdigest() == running.sha256
    )
    with pytest.raises(ValueError):
        module.check_local_research_authority(
            loaded=loaded, code_hash="c" * 64, control_dir=control
        )
    controls.change("kill", expected_sha256=running.sha256)
    with pytest.raises(ValueError):
        module.check_local_research_authority(loaded=loaded, code_hash=code, control_dir=control)


def test_cli_requires_fixed_host_owner_and_sanitizes_error(capsys):
    assert module.main(["observe", "a" * 64, "b" * 64]) == 2
    assert json.loads(capsys.readouterr().out) == {"status": "stock_local_state_unavailable"}
