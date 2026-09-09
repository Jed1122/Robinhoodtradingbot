import hashlib
import re
import subprocess
from pathlib import Path


def test_deploy_never_enables_live() -> None:
    text = (
        Path("infra/digitalocean/deploy.sh").read_text()
        + Path("infra/digitalocean/deploy-remote.sh").read_text()
        + Path("docker-compose.yml").read_text()
        + Path("Dockerfile").read_text()
    )
    assert "enable-live" not in text and "--paused" in text
    assert "trading_bot_live_enabled 0.0" in text
    assert "ready_status" in text and '"503"' in text
    assert "flock -n" in text
    assert "/usr/bin/env -i" in text
    assert "export PATH" in text
    assert "--disable" in text and "--noproxy '*'" in text
    assert "started_image" in text
    assert "LAST_GOOD_POINTER" in text
    assert "LAST_GOOD_IMAGE" in text
    assert 'cmp -s "$release_env" -' in text
    assert "first no-volume release" in text
    assert "TRADING_BOT_STATE_DIR=/var/lib/trading-bot" in text
    assert 'write_last_good_pointer "$LAST_GOOD_RELEASE_KEY"' in text
    assert 'validate_resolved_images "$IMAGE" "$RESOLVED_IMAGES"' in text


def test_remote_deploy_attests_only_a_verified_paused_release() -> None:
    text = Path("infra/digitalocean/deploy-remote.sh").read_text()

    assert "TRADING_BOT_RUNTIME_ATTESTATION_FILE=$CANDIDATE_ATTESTATION" in text
    assert 'install -m 0444 -o root -g root "$ATTESTATION_TEMP"' in text
    assert 'validate_release_attestation "$CANDIDATE_ATTESTATION"' in text
    assert r'\"schema_version\":1}' in text
    assert text.index('verify_paused_service "$IMAGE"') < text.index(
        'write_release_attestation "$CANDIDATE_ATTESTATION"'
    )
    assert text.index('write_release_attestation "$CANDIDATE_ATTESTATION"') < text.index(
        'write_last_good_pointer "$RELEASE_KEY"'
    )
    assert 'rm -f -- "$CANDIDATE_ATTESTATION"' in text


def test_deploy_scripts_have_valid_shell_syntax() -> None:
    for path in ("infra/digitalocean/deploy.sh", "infra/digitalocean/deploy-remote.sh"):
        result = subprocess.run(["sh", "-n", path], check=False, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_remote_helper_pins_exact_compose_content() -> None:
    helper = Path("infra/digitalocean/deploy-remote.sh").read_text()
    match = re.search(r"^EXPECTED_COMPOSE_SHA256=([0-9a-f]{64})$", helper, re.MULTILINE)
    assert match is not None
    actual = hashlib.sha256(Path("docker-compose.yml").read_bytes()).hexdigest()
    assert match.group(1) == actual
