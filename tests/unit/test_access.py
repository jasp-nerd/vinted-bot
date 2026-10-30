"""Who can open the dashboard: the rule behind the "no password" warning."""

from __future__ import annotations

from vinted_bot.web import core
from vinted_bot.web.security import Access


def _access(**overrides: object) -> Access:
    values: dict[str, object] = {
        "host": "127.0.0.1",
        "host_from_env": False,
        "password": False,
        "password_from_env": False,
        "container": False,
    }
    values.update(overrides)
    return Access(**values)  # type: ignore[arg-type]


def test_no_password_is_fine_on_localhost() -> None:
    """Anyone who can reach localhost is already on the machine."""
    assert _access().exposed_without_password is False


def test_a_passwordless_dashboard_on_every_interface_is_flagged() -> None:
    assert _access(host="0.0.0.0").exposed_without_password is True


def test_a_password_clears_the_warning() -> None:
    assert _access(host="0.0.0.0", password=True).exposed_without_password is False


def test_a_container_is_not_flagged() -> None:
    """Not fatal and not flagged: a container always binds 0.0.0.0, the port mapping decides."""
    assert _access(host="0.0.0.0", container=True).exposed_without_password is False


def test_every_interface_is_not_loopback() -> None:
    assert _access(host="0.0.0.0").loopback is False


def test_addresses_a_phone_cannot_use_are_left_out() -> None:
    offered = core._usable(["127.0.0.1", "169.254.10.2", "0.0.0.0", "192.168.1.20"])

    assert offered == ["192.168.1.20"]


def test_a_public_address_on_the_local_network_is_kept() -> None:
    """Universities and offices often give every computer a public address."""
    assert core._usable(["130.37.84.245"]) == ["130.37.84.245"]


def test_the_same_address_is_offered_once() -> None:
    assert core._usable(["192.168.1.20", "192.168.1.20"]) == ["192.168.1.20"]
