"""Which host names the dashboard answers to."""

from __future__ import annotations

import pytest

from vinted_bot.web.security import host_allowed

TOLD = frozenset({"localhost", "finds.example.org"})


@pytest.mark.parametrize("host", ["umbrel.local", "nas.local", "nas", "umbrel", "UMBREL.LOCAL"])
def test_names_only_the_local_network_resolves_are_answered(host: str) -> None:
    """Opening a NAS app as umbrel.local or http://nas/ gave a 400."""
    assert host_allowed(host.lower(), TOLD)


@pytest.mark.parametrize("host", ["attacker.example", "evil.local.example.com", "nas.example."])
def test_public_names_are_still_refused_unless_listed(host: str) -> None:
    assert not host_allowed(host, TOLD)


def test_a_listed_public_name_is_answered() -> None:
    assert host_allowed("finds.example.org", TOLD)
