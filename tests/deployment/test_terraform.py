from pathlib import Path


def test_ssh_has_no_public_default() -> None:
    variables = Path("infra/digitalocean/variables.tf").read_text()
    firewall = Path("infra/digitalocean/firewall.tf").read_text()
    assert 'variable "trusted_ssh_cidrs" { type = list(string) }' in variables
    inbound = firewall.split("outbound_rule", 1)[0]
    assert "0.0.0.0/0" not in inbound and "::/0" not in inbound
