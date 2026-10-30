"""host/systemd/ci-nat.service: isolation rules must exist before any guest starts on vmbr9."""
from pathlib import Path

UNIT = Path(__file__).resolve().parents[3] / "host" / "systemd" / "ci-nat.service"


def _unit_values(key):
    vals = []
    for line in UNIT.read_text().splitlines():
        if line.startswith(key + "="):
            vals += line.split("=", 1)[1].split()
    return vals


def test_ci_nat_runs_before_guests_and_after_network():
    assert "pve-guests.service" in _unit_values("Before")
    after = _unit_values("After")
    assert "network-online.target" in after and "pve-firewall.service" in after
