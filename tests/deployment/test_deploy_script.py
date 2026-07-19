from pathlib import Path


def test_deploy_never_enables_live() -> None:
    text = (
        Path("infra/digitalocean/deploy.sh").read_text()
        + Path("infra/digitalocean/deploy-remote.sh").read_text()
    )
    assert "enable-live" not in text and "--paused" in text
