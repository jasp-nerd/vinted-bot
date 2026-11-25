"""Where this computer can be reached on the network, without the dashboard's code.

Used by the dashboard (phone access, the QR code), by alerts (the Dashboard button) and by
`vinted-bot address`, so none of them has to load FastAPI to know the answer.
"""

from __future__ import annotations

import contextlib
import ipaddress
import re
import socket
import sys
from pathlib import Path

from vinted_bot.engine import wakeups

# This computer, private networks, self-assigned addresses and Tailscale (CGNAT), in both
# IP versions. Spelled out rather than ipaddress's is_private, which also counts
# documentation and benchmarking ranges and leaves 100.64.0.0/10 out.
_LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "100.64.0.0/10",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)


def is_local_address(address: str) -> bool:
    """Whether a client address is this computer or a private network (see above).

    Anything that is not an IP address at all counts as not local, so an odd transport
    fails closed.
    """
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0].strip("[]"))
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in network for network in _LOCAL_NETWORKS)


# Where the probes below pretend to send: "the internet" (the default route) for the home
# network, and Tailscale's own resolver for its network when it runs.
_PROBES = (wakeups.INTERNET, "100.100.100.100")


def lan_addresses() -> list[str]:
    """This computer's private IPv4 addresses a phone can open the dashboard at.

    Asking the OS which interface it would send through (wakeups.local_address, which
    sends nothing) gives the address that matters: once towards the internet, for the
    home network, and once towards Tailscale's resolver, which only routes somewhere of
    its own while Tailscale runs. Only when neither helps, as on a computer with no route
    out, are the addresses its own name resolves to tried: that list also holds virtual
    machines' and containers' networks, which a phone can't reach.

    Only private addresses (is_local_address) are offered. Some networks
    (universities, offices) give every computer a public one, and offering that would
    send people to an address the dashboard refuses anyway, as it should: it would be
    on the internet.
    """
    found = [address for target in _PROBES if (address := wakeups.local_address(target))]
    if not _usable(found):
        with contextlib.suppress(OSError):
            for *_, sockaddr in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                found.append(str(sockaddr[0]))
    return _usable(found)


def _usable(addresses: list[str]) -> list[str]:
    usable: list[str] = []
    for address in addresses:
        ip = ipaddress.ip_address(address)
        unusable = ip.is_loopback or ip.is_link_local or ip.is_unspecified
        if not unusable and is_local_address(address) and address not in usable:
            usable.append(address)
    return usable


_HOST_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def local_name(platform: str = sys.platform) -> str | None:
    """This computer's name on the home network (raspberrypi.local), where the system
    announces one: macOS always, Linux when Avahi is installed (Raspberry Pi OS has it).
    Windows names don't reliably resolve from phones, so none is offered there."""
    host = socket.gethostname().split(".", 1)[0]
    if not _HOST_NAME.match(host) or host.lower() == "localhost":
        return None
    announced = platform == "darwin" or (
        platform.startswith("linux")
        and (Path("/usr/sbin/avahi-daemon").exists() or Path("/etc/avahi").is_dir())
    )
    return f"{host.lower()}.local" if announced else None
