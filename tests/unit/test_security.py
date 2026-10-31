"""Which host names the dashboard answers to, and which devices it lets in."""

from __future__ import annotations

from typing import Any

import pytest

from vinted_bot.config import Settings
from vinted_bot.web.security import client_allowed, host_allowed, is_local_address

TOLD = frozenset({"localhost", "finds.example.org"})


@pytest.mark.parametrize("host", ["umbrel.local", "nas.local", "nas", "umbrel", "UMBREL.LOCAL"])
def test_names_only_the_local_network_resolves_are_answered(host: str) -> None:
    """Opening a NAS app as umbrel.local or http://nas/ gave a 400."""
    assert host_allowed(host.lower(), TOLD)


@pytest.mark.parametrize(
    "host",
    [
        "nas.lan",
        "nas.home",
        "nas.home.arpa",
        "nas.internal",
        "fritz.box",
        "nas.fritz.box",
        "laptop.tail1234.ts.net",
    ],
)
def test_names_routers_and_vpns_hand_out_are_answered(host: str) -> None:
    """A FRITZ!Box, a router's .lan or Tailscale's MagicDNS name got the unknown-address page."""
    assert host_allowed(host, TOLD)


@pytest.mark.parametrize(
    "host", ["attacker.example", "evil.local.example.com", "nas.example.", "lan.example.com"]
)
def test_public_names_are_still_refused_unless_listed(host: str) -> None:
    assert not host_allowed(host, TOLD)


def test_a_listed_public_name_is_answered() -> None:
    assert host_allowed("finds.example.org", TOLD)


# --- Devices ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "::1",
        "192.168.1.30",
        "10.0.0.7",
        "172.17.0.1",  # Docker's bridge, which port-mapped requests arrive from
        "169.254.10.2",
        "100.101.102.103",  # Tailscale
        "fd7a:115c:a1e0::1",  # Tailscale over IPv6, and any other ULA
        "fe80::1%en0",
        "::ffff:192.168.1.30",
    ],
)
def test_this_computer_and_private_networks_are_local(address: str) -> None:
    assert is_local_address(address)


@pytest.mark.parametrize(
    "address",
    ["130.37.84.245", "8.8.8.8", "2001:db8::1", "::ffff:130.37.84.245", "testclient", ""],
)
def test_internet_addresses_and_non_addresses_are_not(address: str) -> None:
    """130.37.84.245 is what a university network handed a tester's laptop."""
    assert not is_local_address(address)


def _settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_listening_on_loopback_lets_any_client_in() -> None:
    """Only this computer can connect then, whatever a proxy says it forwarded."""
    assert client_allowed(_settings(), False, "130.37.84.245")


def test_listening_beyond_loopback_refuses_the_internet() -> None:
    assert not client_allowed(_settings(), True, "130.37.84.245")


def test_a_public_address_in_the_public_url_lets_the_internet_in() -> None:
    """A reverse proxy that serves the internet: the operator said so by naming it."""
    settings = _settings(web_public_url="https://finds.example.org")

    assert client_allowed(settings, True, "130.37.84.245")


def test_a_public_name_in_the_allowed_hosts_lets_the_internet_in() -> None:
    settings = _settings(web_allowed_hosts="nas.local, finds.example.org")

    assert client_allowed(settings, True, "130.37.84.245")


@pytest.mark.parametrize(
    "values",
    [
        {"web_public_url": "http://nas.local:8000"},
        {"web_public_url": "http://192.168.1.20:8000"},
        {"web_allowed_hosts": "nas.lan,fritz.box"},
    ],
)
def test_naming_a_private_address_does_not_let_the_internet_in(values: dict[str, str]) -> None:
    assert not client_allowed(_settings(**values), True, "130.37.84.245")


def test_the_switch_for_it_lets_the_internet_in() -> None:
    assert client_allowed(_settings(web_allow_public=True), True, "130.37.84.245")
