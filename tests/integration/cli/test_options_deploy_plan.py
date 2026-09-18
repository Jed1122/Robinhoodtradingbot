"""Credential-free deployment preparation reporting cannot probe or mutate anything."""

import ast
import json
import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("network forbidden in options deployment-plan tests")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def _app():  # type: ignore[no-untyped-def]
    try:
        from trading_bot.cli.options_deploy_plan import app
    except ModuleNotFoundError:
        pytest.fail("options deployment-plan command is not implemented")
    return app


def _run() -> dict[str, object]:
    result = runner.invoke(_app())
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_report_keeps_all_readiness_verdicts_independently_fail_closed() -> None:
    report = _run()

    assert report["schema"] == "options-deployment-preparation-report-v1"
    assert report["source_kind"] == "repository-declarations-only"
    assert report["verdicts"] == {
        "capability": "UNVERIFIED",
        "economic": "ECONOMIC_NO_GO",
        "operator_authorization": "NOT_AUTHORIZED",
        "technical_operational": "NOT_READY",
    }
    assert report["live_deployment_ready"] is False
    assert report["live_trading_enabled"] is False
    assert report["cost_evidence"] == {
        "status": "MISSING",
        "values": [],
        "reason": "current_cost_evidence_required",
    }


def test_report_lists_only_declared_paused_resources_and_required_evidence() -> None:
    report = _run()
    deployment = report["paused_deployment"]
    assert isinstance(deployment, dict)

    assert deployment == {
        "declaration_status": "NOT_RUNTIME_VERIFIED",
        "target": "digitalocean",
        "startup_mode": "paused_shadow",
        "live_flags": {
            "live_trading_enabled": False,
            "prediction_live_enabled": False,
        },
        "loopback_publish": "127.0.0.1:8080:8080",
        "resources": {"cpus": "0.75", "memory": "768m", "pids_limit": 256},
        "health_endpoints": ["/healthz", "/readyz", "/metrics"],
        "declared_controls": [
            "nonroot_read_only_container",
            "capabilities_dropped",
            "paused_startup",
            "loopback_monitoring",
            "transactional_release_rollback",
            "sqlite_online_backup",
            "age_encrypted_backup",
            "restore_integrity_verifier",
        ],
        "expected_manifests": [
            "Dockerfile",
            "docker-compose.yml",
            "infra/digitalocean/backup.sh",
            "infra/digitalocean/cloud-init.yaml.tftpl",
            "infra/digitalocean/deploy-remote.sh",
            "infra/digitalocean/deploy.sh",
            "infra/digitalocean/firewall.tf",
            "infra/digitalocean/main.tf",
            "infra/digitalocean/monitoring.tf",
            "infra/digitalocean/outputs.tf",
            "infra/digitalocean/restore.sh",
            "infra/digitalocean/variables.tf",
            "infra/digitalocean/versions.tf",
        ],
    }
    evidence = report["required_evidence"]
    assert isinstance(evidence, list)
    assert evidence == [
        {"id": "durable_options_state_and_restart_reconstruction", "status": "MISSING"},
        {"id": "options_runtime_capability_evidence", "status": "MISSING"},
        {"id": "options_process_benchmark", "status": "MISSING"},
        {"id": "current_hosting_storage_data_monitoring_costs", "status": "MISSING"},
        {"id": "encrypted_restore_and_schema_rollback_drill", "status": "MISSING"},
        {"id": "external_heartbeat_and_alert_delivery", "status": "MISSING"},
        {"id": "options_health_readiness_and_metrics", "status": "MISSING"},
        {"id": "complete_options_operator_commands_and_runbook", "status": "MISSING"},
    ]


def test_command_is_deterministic_and_ignores_environment_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(_app(), env={"TRADING_BOT_SECRET": "first-secret"})
    second = runner.invoke(_app(), env={"TRADING_BOT_SECRET": "different-secret"})

    assert first.exit_code == second.exit_code == 0
    assert first.stdout == second.stdout
    assert "secret" not in first.stdout.lower()
    assert not list(tmp_path.iterdir())


def test_module_has_no_broker_state_network_process_or_filesystem_dependencies() -> None:
    source = Path(__file__).parents[3] / "src/trading_bot/cli/options_deploy_plan.py"
    assert source.is_file(), "options deployment-plan command is not implemented"
    imported: list[str] = []
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)

    banned = (
        "trading_bot.authorization",
        "trading_bot.brokers",
        "trading_bot.execution",
        "trading_bot.persistence",
        "trading_bot.reconciliation",
        "trading_bot.risk",
        "httpx",
        "mcp",
        "os",
        "pathlib",
        "socket",
        "subprocess",
    )
    assert not any(
        name == prefix or name.startswith(prefix + ".") for name in imported for prefix in banned
    )
