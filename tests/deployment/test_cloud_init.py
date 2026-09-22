from pathlib import Path


def test_cloud_init_hardens_ssh() -> None:
    text = Path("infra/digitalocean/cloud-init.yaml.tftpl").read_text()
    assert "PermitRootLogin no" in text and "PasswordAuthentication no" in text
    assert "uid: 10001" in text and "gid: 10001" in text
