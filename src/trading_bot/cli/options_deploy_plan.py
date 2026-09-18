"""Static, credential-free options deployment preparation report."""

import json

import typer

app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
    pretty_exceptions_show_locals=False,
)


def _report() -> dict[str, object]:
    return {
        "schema": "options-deployment-preparation-report-v1",
        "source_kind": "repository-declarations-only",
        "verdicts": {
            "technical_operational": "NOT_READY",
            "economic": "ECONOMIC_NO_GO",
            "capability": "UNVERIFIED",
            "operator_authorization": "NOT_AUTHORIZED",
        },
        "live_deployment_ready": False,
        "live_trading_enabled": False,
        "cost_evidence": {
            "status": "MISSING",
            "values": [],
            "reason": "current_cost_evidence_required",
        },
        "paused_deployment": {
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
        },
        "required_evidence": [
            {"id": "durable_options_state_and_restart_reconstruction", "status": "MISSING"},
            {"id": "options_runtime_capability_evidence", "status": "MISSING"},
            {"id": "options_process_benchmark", "status": "MISSING"},
            {
                "id": "current_hosting_storage_data_monitoring_costs",
                "status": "MISSING",
            },
            {"id": "encrypted_restore_and_schema_rollback_drill", "status": "MISSING"},
            {"id": "external_heartbeat_and_alert_delivery", "status": "MISSING"},
            {"id": "options_health_readiness_and_metrics", "status": "MISSING"},
            {"id": "complete_options_operator_commands_and_runbook", "status": "MISSING"},
        ],
        "limitations": [
            "repository_declarations_are_not_runtime_evidence",
            "resource_limits_are_not_benchmark_results",
            "no_cloud_or_service_state_was_probed",
            "no_costs_were_estimated",
            "no_live_order_was_placed",
        ],
    }


@app.callback()
def options_deploy_plan() -> None:
    """Render a static preparation report; never deploy, authenticate, or trade."""

    typer.echo(json.dumps(_report(), ensure_ascii=True, separators=(",", ":"), sort_keys=True))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
