"""The HTTP layer: whose cookies go out, and which come back."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from vinted_sniper.vinted.transport import HttpxTransport, MockTransport, TransportError

Handler = Callable[[httpx.Request], httpx.Response]


def httpx_transport(handler: Handler) -> HttpxTransport:
    """The real transport, with only the network swapped for an in-process handler."""
    transport = HttpxTransport()
    transport._client._transport = httpx.MockTransport(handler)
    return transport


def cookie_header(request: httpx.Request) -> str:
    return str(request.headers.get("cookie", ""))


async def test_cookies_set_on_one_request_never_ride_along_on_the_next() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(cookie_header(request))
        return httpx.Response(200, headers={"set-cookie": "access_token_web=OLD; Path=/"})

    transport = httpx_transport(handler)
    await transport.get("https://www.vinted.fr/", headers={})
    await transport.get("https://www.vinted.fr/", headers={}, cookies={"access_token_web": "NEW"})

    assert seen == ["", "access_token_web=NEW"]


async def test_a_response_reports_the_cookies_it_set() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"set-cookie": "anon_id=abc; Path=/"})

    response = await httpx_transport(handler).get("https://www.vinted.fr/", headers={})

    assert response.cookies == {"anon_id": "abc"}


async def test_cookies_set_on_a_redirect_hop_are_sent_onward_and_kept() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.path] = cookie_header(request)
        if request.url.path == "/":
            return httpx.Response(
                302,
                headers={"location": "/home", "set-cookie": "access_token_web=T; Path=/"},
            )
        return httpx.Response(200, headers={"set-cookie": "anon_id=A; Path=/"})

    response = await httpx_transport(handler).get(
        "https://www.vinted.fr/", headers={}, cookies={"v_udt": "U"}
    )

    assert seen["/home"] == "v_udt=U; access_token_web=T"
    assert response.cookies == {"access_token_web": "T", "anon_id": "A"}


async def test_redirects_are_left_alone_when_asked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(307, headers={"location": "/items/1-slug"})

    response = await httpx_transport(handler).get(
        "https://www.vinted.fr/items/1", headers={}, follow_redirects=False
    )

    assert response.status_code == 307


async def test_a_redirect_loop_is_an_error_not_a_hang() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    with pytest.raises(TransportError, match="redirects"):
        await httpx_transport(handler).get("https://www.vinted.fr/", headers={})


@pytest.mark.parametrize(
    ("url", "scenario"),
    [
        ("https://api.vinted.fr/svc-catalogue/items", "catalog"),
        ("https://api.vinted.fr/svc-filters/filters/facets", "filters"),
        ("https://www.vinted.fr/api/v2/users/7", "user"),
        ("https://www.vinted.fr/api/v2/wardrobe/7/items", "wardrobe"),
        ("https://www.vinted.fr/items/42", "item"),
        ("https://www.vinted.fr/", "root"),
    ],
)
async def test_mock_mode_answers_each_kind_of_request_from_its_own_file(
    tmp_path: Path, url: str, scenario: str
) -> None:
    (tmp_path / f"{scenario}.json").write_text(json.dumps({"body": {"from": scenario}}))

    response = await MockTransport(scenario_dir=tmp_path).get(url, headers={})

    assert response.json() == {"from": scenario}
