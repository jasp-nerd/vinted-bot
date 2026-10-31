"""The dashboard.

Worth testing properly because it is the part most people will actually touch, and because
it holds webhook URLs and chat ids, so "is it locked" is a correctness question. Pages are
driven through Starlette's test client against a real database; Vinted is a scripted
transport and outgoing alerts go to an httpx mock, so nothing reaches the network.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tests.conftest import LOCAL_CLIENT, ScriptedTransport
from vinted_bot.botctl.telegram_bot import claim_pairing
from vinted_bot.config import Settings
from vinted_bot.db import Database
from vinted_bot.db.repo import Repo
from vinted_bot.vinted.client import VintedClient
from vinted_bot.vinted.models import Item
from vinted_bot.vinted.session import SessionManager
from vinted_bot.vinted.taxonomy import Taxonomy
from vinted_bot.vinted.transport import Response
from vinted_bot.web import core, preview, security
from vinted_bot.web.routes import finds
from vinted_bot.web.server import SESSION_COOKIE, create_app

TOKEN = "test-token-please-ignore"
BASE = "http://127.0.0.1"
SEARCH_URL = "https://www.vinted.fr/catalog?search_text=nike"


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        db_path=tmp_path / "app.db",
        web_enabled=True,
        **overrides,
    )


class Outgoing:
    """Records what test sends would have posted, and answers with a chosen status."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={})


@pytest.fixture
def outgoing() -> Outgoing:
    return Outgoing()


@pytest.fixture
def make_client(
    tmp_path: Path, repo: Repo, outgoing: Outgoing
) -> Iterator[Callable[..., TestClient]]:
    """Builds a dashboard with the given settings and parts, signed in if it has a password."""
    opened: list[TestClient] = []

    def build(*, signed_in: bool = True, **kwargs: Any) -> TestClient:
        settings_kw = {k: v for k, v in kwargs.items() if k in Settings.model_fields}
        app_kw = {k: v for k, v in kwargs.items() if k not in Settings.model_fields}
        http = httpx.AsyncClient(transport=httpx.MockTransport(outgoing.handler))
        app = create_app(_settings(tmp_path, **settings_kw), repo, http=http, **app_kw)
        client = TestClient(app, base_url=BASE, client=LOCAL_CLIENT)
        client.__enter__()
        opened.append(client)
        token = settings_kw.get("web_auth_token")
        if signed_in and token is not None:
            client.post("/login", data={"password": token.get_secret_value()})
        return client

    yield build
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


@pytest.fixture
def locked(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client(web_auth_token=SecretStr(TOKEN), signed_in=False)


@pytest.fixture
def vinted(db: Database, transport: ScriptedTransport) -> VintedClient:
    return VintedClient(None, SessionManager(db, transport))


@pytest.fixture(autouse=True)
def _no_preview_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Previews space live requests out; tests make them back to back on purpose."""
    monkeypatch.setattr(preview, "MIN_GAP_S", 0.0)


def _item(item_id: int, *, title: str = "Nike Air Max", total: str = "25.90", **kw: Any) -> Item:
    return Item(
        item_id=item_id,
        tld="fr",
        title=title,
        url=f"https://www.vinted.fr/items/{item_id}",
        price=Decimal(total) - Decimal(2),
        total_price=Decimal(total),
        currency="EUR",
        photo_url=f"https://images.vinted.net/{item_id}.jpeg",
        seller_id=kw.pop("seller_id", 77),
        seller_login=kw.pop("seller_login", "seller77"),
        **kw,
    )


async def _search(repo: Repo, name: str = "Nike", **filters: Any) -> int:
    return await repo.add_query(
        name=name,
        url=f"{SEARCH_URL}&n={name}",
        tld="fr",
        params={"search_text": "nike", "order": "newest_first"},
        poll_interval_s=60,
        **filters,
    )


async def _found(repo: Repo, query_id: int, *items: Item) -> None:
    query = await repo.get_query(query_id)
    assert query is not None
    await repo.record_new_items(query, list(items), [])


async def _seed(repo: Repo) -> int:
    """A search with finds, a destination, a watch and a blocked seller."""
    query_id = await _search(repo)
    await _found(repo, query_id, _item(1), _item(2, title="Adidas Samba", total="40.00"))
    await repo.add_destination(kind="ntfy", name="My phone", config={"topic": "mags-test"})
    await repo.add_watch(kind="seller", tld="fr", target_id=77, label="seller77")
    await repo.block_seller(99, login="spammer", tld="fr")
    await repo.set_onboarded(True)
    return query_id


# --- Access ----------------------------------------------------------------------------


def test_a_locked_dashboard_sends_you_to_sign_in(locked: TestClient) -> None:
    response = locked.get("/searches", follow_redirects=False)

    assert response.headers["location"] == "/login?next=/searches"


def test_a_locked_api_answers_401_not_a_page(locked: TestClient) -> None:
    response = locked.get("/api/health")

    assert response.status_code == 401


def test_the_wrong_password_is_refused_on_the_page(locked: TestClient) -> None:
    response = locked.post("/login", data={"password": "nope"})

    assert response.status_code == 401
    assert "didn&#39;t match" in response.text


def test_signing_in_never_puts_the_password_in_the_cookie(locked: TestClient) -> None:
    response = locked.post("/login", data={"password": TOKEN}, follow_redirects=False)

    assert response.cookies[SESSION_COOKIE]
    assert TOKEN not in response.headers["set-cookie"]


def test_each_sign_in_gets_its_own_session(locked: TestClient) -> None:
    first = locked.post("/login", data={"password": TOKEN}, follow_redirects=False)
    second = locked.post("/login", data={"password": TOKEN}, follow_redirects=False)

    assert first.cookies[SESSION_COOKIE] != second.cookies[SESSION_COOKIE]


def test_signing_out_revokes_the_session_on_the_server(locked: TestClient) -> None:
    """A copied cookie stops working once its owner signs out."""
    locked.post("/login", data={"password": TOKEN})
    stolen = locked.cookies[SESSION_COOKIE]
    locked.post("/logout", headers={"Origin": BASE})
    locked.cookies.set(SESSION_COOKIE, stolen)

    assert locked.get("/api/health").status_code == 401


async def test_changing_the_password_signs_everyone_out(
    make_client: Callable[..., TestClient],
) -> None:
    before = make_client(web_auth_token=SecretStr(TOKEN))
    cookie = before.cookies[SESSION_COOKIE]
    after = make_client(web_auth_token=SecretStr("a-new-password"), signed_in=False)
    after.cookies.set(SESSION_COOKIE, cookie)

    assert after.get("/api/health").status_code == 401


def test_restarting_with_the_same_password_keeps_people_signed_in(
    make_client: Callable[..., TestClient],
) -> None:
    before = make_client(web_auth_token=SecretStr(TOKEN))
    cookie = before.cookies[SESSION_COOKIE]
    after = make_client(web_auth_token=SecretStr(TOKEN), signed_in=False)
    after.cookies.set(SESSION_COOKIE, cookie)

    assert after.get("/api/health").status_code == 200


def test_guessing_passwords_is_slowed_down(locked: TestClient) -> None:
    for _ in range(5):
        locked.post("/login", data={"password": "guess"})

    response = locked.post("/login", data={"password": TOKEN}, follow_redirects=False)

    assert response.status_code == 429


def test_signing_in_never_redirects_to_another_site(locked: TestClient) -> None:
    response = locked.post(
        "/login", data={"password": TOKEN, "next": "//evil.example"}, follow_redirects=False
    )

    assert response.headers["location"] == "/"


def test_the_health_check_needs_no_sign_in(locked: TestClient) -> None:
    response = locked.get("/healthz")

    assert response.status_code in (200, 503)


def test_a_change_from_another_site_is_refused(client: TestClient, repo: Repo) -> None:
    """CSRF: a page elsewhere posting through the browser carries its own Origin."""
    response = client.post(
        "/searches/bulk",
        data={"action": "delete", "ids": "1"},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403


def test_a_change_from_the_dashboard_itself_is_allowed(client: TestClient, repo: Repo) -> None:
    response = client.post(
        "/settings", data={"key": "theme", "value": "dark"}, headers={"Origin": BASE}
    )

    assert response.json() == {"ok": True}


def test_a_foreign_host_name_is_refused_on_loopback(client: TestClient) -> None:
    """DNS rebinding: another site's name pointed at 127.0.0.1 must not read the page."""
    response = client.get("/", headers={"Host": "attacker.example"})

    assert response.status_code == 400


def test_the_public_url_host_is_allowed(make_client: Callable[..., TestClient]) -> None:
    proxied = make_client(web_public_url="https://finds.example.org")

    assert proxied.get("/healthz", headers={"Host": "finds.example.org"}).status_code != 400


REBIND = "rebind.attacker.example:8000"


def test_a_rebinding_page_cannot_read_a_wildcard_bound_dashboard(
    make_client: Callable[..., TestClient],
) -> None:
    """The Docker image binds 0.0.0.0; that must not switch the Host check off."""
    docker = make_client(web_host="0.0.0.0")

    assert docker.get("/alerts", headers={"Host": REBIND}).status_code == 400


async def test_a_rebinding_page_cannot_add_a_destination(
    make_client: Callable[..., TestClient], repo: Repo
) -> None:
    """Host and Origin both carry the attacker's name, so matching them proves nothing."""
    docker = make_client(web_host="0.0.0.0")

    docker.post(
        "/destinations",
        data={"kind": "webhook", "webhook_url": "https://attacker.example/collect"},
        headers={"Host": REBIND, "Origin": f"http://{REBIND}", "Accept": "application/json"},
    )

    assert await repo.list_destinations() == []


def test_the_unknown_host_page_names_the_setting_to_use(
    make_client: Callable[..., TestClient],
) -> None:
    docker = make_client(web_host="0.0.0.0")

    page = docker.get("/", headers={"Host": "finds.example.net:8000"})

    assert "VINTED_BOT_WEB_ALLOWED_HOSTS" in page.text


def test_the_unknown_host_page_gets_its_styles(make_client: Callable[..., TestClient]) -> None:
    """Its stylesheet was refused by the same check, so it showed as bare text."""
    docker = make_client(web_host="0.0.0.0")

    page = docker.get("/", headers={"Host": "finds.example.net:8000"}).text
    stylesheet = page.split('rel="stylesheet" href="', 1)[1].split('"', 1)[0]

    assert docker.get(stylesheet, headers={"Host": "finds.example.net:8000"}).status_code == 200


def test_an_ip_address_always_reaches_the_dashboard(
    make_client: Callable[..., TestClient],
) -> None:
    """Opening it from a phone by the computer's address keeps working."""
    docker = make_client(web_host="0.0.0.0")

    assert docker.get("/searches", headers={"Host": "192.168.1.20:8000"}).status_code == 200


def test_names_in_allowed_hosts_reach_the_dashboard(
    make_client: Callable[..., TestClient],
) -> None:
    docker = make_client(web_host="0.0.0.0", web_allowed_hosts="nas.local, finds.example.org")

    assert docker.get("/searches", headers={"Host": "nas.local:8000"}).status_code == 200


def test_a_change_from_a_site_served_by_ip_address_is_refused(client: TestClient) -> None:
    """Any IP may open the dashboard, but only the dashboard's own address may change it."""
    response = client.post(
        "/settings",
        data={"key": "theme", "value": "dark"},
        headers={"Origin": "http://203.0.113.5"},
    )

    assert response.status_code == 403


def test_a_change_from_an_allowed_name_is_accepted(make_client: Callable[..., TestClient]) -> None:
    named = make_client(web_allowed_hosts="nas.local")

    response = named.post(
        "/settings",
        data={"key": "theme", "value": "dark"},
        headers={"Host": "nas.local:8000", "Origin": "http://nas.local:8000"},
    )

    assert response.json() == {"ok": True}


def test_an_exposed_dashboard_without_a_password_says_so(
    make_client: Callable[..., TestClient], repo: Repo
) -> None:
    exposed = make_client(web_host="0.0.0.0")

    assert "Anyone on your network can open this page" in exposed.get("/searches").text


# --- Pages -----------------------------------------------------------------------------

PAGES = [
    "/",
    "/searches",
    "/searches/new",
    "/searches/1",
    "/searches/1/edit",
    "/alerts",
    "/watchlist",
    "/stats",
    "/stats?days=7",
    "/settings",
    "/welcome",
    "/welcome/country",
    "/welcome/search",
    "/welcome/alerts",
]


@pytest.mark.parametrize("path", PAGES)
async def test_every_page_renders_with_data(client: TestClient, repo: Repo, path: str) -> None:
    await _seed(repo)

    response = client.get(path)

    assert response.status_code == 200


@pytest.mark.parametrize("path", [p for p in PAGES if not p.startswith("/searches/1")])
async def test_every_page_renders_with_nothing_in_it(
    client: TestClient, repo: Repo, path: str
) -> None:
    await repo.set_onboarded(True)

    response = client.get(path)

    assert response.status_code == 200


def test_a_fresh_install_opens_the_setup(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)

    assert response.headers["location"] == "/welcome"


def test_a_missing_search_is_a_friendly_page(client: TestClient) -> None:
    response = client.get("/searches/999")

    assert response.status_code == 404
    assert "Nothing here" in response.text


async def test_pages_escape_what_people_typed(client: TestClient, repo: Repo) -> None:
    await _search(repo, name="<script>alert(1)</script>")
    await repo.set_onboarded(True)

    page = client.get("/searches").text

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


async def test_static_files_carry_a_version_and_long_caching(client: TestClient) -> None:
    href = core.static("css/app.css")

    response = client.get(href)

    assert "?v=" in href
    assert "immutable" in response.headers["cache-control"]


def test_the_app_can_be_installed_on_a_phone(client: TestClient) -> None:
    manifest = client.get("/manifest.webmanifest").json()

    assert {icon["sizes"] for icon in manifest["icons"]} == {"192x192", "512x512"}


async def test_a_newer_release_shows_a_banner(client: TestClient, repo: Repo) -> None:
    await repo.set_onboarded(True)
    await repo.set_latest_version("99.0.0")

    assert "Version 99.0.0 is out" in client.get("/searches").text


async def test_a_refused_search_shows_the_slowed_down_banner(
    client: TestClient, repo: Repo
) -> None:
    query_id = await _seed(repo)
    await repo.record_failure(query_id, "http_403", "refused")

    assert "vinted.fr is slowing us down" in client.get("/alerts").text


# --- Searches --------------------------------------------------------------------------


def _form(**overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "tld": "fr",
        "search_text": "nike air",
        "interval": "60",
        "quiet_mode": "hold",
        "quiet_start": "23:00",
        "quiet_end": "07:00",
    }
    form.update(overrides)
    return form


async def test_building_a_search_stores_its_filters(client: TestClient, repo: Repo) -> None:
    client.post(
        "/searches",
        data=_form(max_total_price="12,50", banned_keywords="replica,fake", brand_ids="53"),
    )

    stored = (await repo.list_queries())[0]
    assert (stored.max_total_price, stored.banned_keywords, stored.params["brand_ids"]) == (
        Decimal("12.50"),
        ["replica", "fake"],
        "53",
    )


async def test_an_or_term_is_stored_as_alternatives(client: TestClient, repo: Repo) -> None:
    client.post("/searches", data=_form(include_terms="501|505"))

    assert (await repo.list_queries())[0].include_terms == ["501|505"]


async def test_a_bad_price_is_shown_beside_the_field(client: TestClient, repo: Repo) -> None:
    response = client.post("/searches", data=_form(max_total_price="about 20"))

    assert response.status_code == 400
    assert 'id="err-max_total_price"' in response.text
    assert await repo.list_queries() == []


async def test_every_wrong_field_is_reported_at_once(client: TestClient) -> None:
    response = client.post("/searches", data=_form(max_total_price="x", regex="(", interval="5"))

    assert all(
        f'id="err-{field}"' in response.text for field in ("max_total_price", "regex", "interval")
    )


async def test_an_empty_search_is_refused_with_advice(client: TestClient, repo: Repo) -> None:
    response = client.post("/searches", data=_form(search_text=""))

    assert "isn&#39;t all of Vinted" in response.text


async def test_a_link_without_https_is_accepted(client: TestClient, repo: Repo) -> None:
    client.post("/searches", data=_form(link="vinted.fr/catalog?search_text=levis"))

    assert (await repo.list_queries())[0].params["search_text"] == "levis"


async def test_a_listing_link_gets_its_own_explanation(client: TestClient) -> None:
    response = client.post("/searches", data=_form(link="vinted.fr/items/123-a-coat"))

    assert "single listing" in response.text


async def test_unknown_destinations_are_dropped_not_half_saved(
    client: TestClient, repo: Repo
) -> None:
    real = await repo.add_destination(kind="ntfy", name="Phone", config={"topic": "t"})

    response = client.post("/searches", data=_form(dest=[str(real), "999"]))

    query_id = (await repo.list_queries())[0].id
    assert response.status_code == 200
    assert await repo.explicit_routes(query_id) == [real]


async def test_a_minimum_margin_needs_a_resale_price(client: TestClient, repo: Repo) -> None:
    response = client.post("/searches", data=_form(min_margin="10"))

    assert 'id="err-min_margin"' in response.text


async def test_editing_keeps_the_search_and_its_routes_change(
    client: TestClient, repo: Repo
) -> None:
    query_id = await _search(repo)
    phone = await repo.add_destination(kind="ntfy", name="Phone", config={"topic": "t"})

    client.post(f"/searches/{query_id}", data=_form(name="Renamed", dest=[str(phone)]))

    stored = await repo.get_query(query_id)
    assert stored is not None
    assert (stored.name, await repo.explicit_routes(query_id)) == ("Renamed", [phone])


async def test_the_editor_shows_where_a_search_sends(client: TestClient, repo: Repo) -> None:
    query_id = await _search(repo)
    phone = await repo.add_destination(kind="ntfy", name="Phone", config={"topic": "t"})
    await repo.set_routes(query_id, [phone])

    page = client.get(f"/searches/{query_id}/edit").text

    assert f'name="dest" value="{phone}" checked' in page


async def test_bulk_pause_pauses_the_chosen_searches(client: TestClient, repo: Repo) -> None:
    first, second = await _search(repo, "A"), await _search(repo, "B")

    client.post("/searches/bulk", data={"action": "pause", "ids": [str(first)]})

    assert [q.paused for q in await repo.list_queries()] == [True, False]
    assert second


async def test_bulk_routing_sets_where_alerts_go(client: TestClient, repo: Repo) -> None:
    query_id = await _search(repo)
    phone = await repo.add_destination(kind="ntfy", name="Phone", config={"topic": "t"})

    client.post(
        "/searches/bulk", data={"action": "routes", "ids": [str(query_id)], "dest": [str(phone)]}
    )

    assert await repo.explicit_routes(query_id) == [phone]


async def test_deleting_a_search_removes_it(client: TestClient, repo: Repo) -> None:
    query_id = await _search(repo)

    client.post(f"/searches/{query_id}/delete")

    assert await repo.get_query(query_id) is None


async def test_duplicating_opens_the_paused_copy(client: TestClient, repo: Repo) -> None:
    query_id = await _search(repo)

    response = client.post(f"/searches/{query_id}/duplicate", follow_redirects=False)

    copy = (await repo.list_queries())[-1]
    assert response.headers["location"] == f"/searches/{copy.id}/edit?copy=1"
    assert copy.paused


async def test_a_change_confirms_itself_on_the_next_page(client: TestClient, repo: Repo) -> None:
    query_id = await _search(repo)

    page = client.post(f"/searches/{query_id}/pause", data={"paused": "1"})

    assert "Paused. No checks and no alerts" in page.text


async def test_unmuting_ends_a_mute(client: TestClient, repo: Repo) -> None:
    query_id = await _search(repo)
    await repo.mute_query(query_id, int(time.time()) + 3600)

    client.post(f"/searches/{query_id}/unmute")

    stored = await repo.get_query(query_id)
    assert stored is not None
    assert not stored.is_muted(int(time.time()))


def test_the_bookmarklet_link_prefills_the_editor(client: TestClient) -> None:
    page = client.get(
        "/searches/new",
        params={"url": "https://www.vinted.nl/catalog?search_text=regenjas&brand_ids[]=53"},
    )

    assert 'value="regenjas"' in page.text
    assert 'name="brand_ids" value="53"' in page.text


def test_the_searches_page_offers_the_bookmarklet(client: TestClient) -> None:
    page = client.get("/searches").text

    assert "javascript:(function(){window.open(&#39;http://127.0.0.1/searches/new?url=" in page


async def test_the_not_sent_tab_says_why_in_words(client: TestClient, repo: Repo) -> None:
    from vinted_bot.db.repo import RejectedListing  # noqa: PLC0415

    query_id = await _search(repo)
    query = await repo.get_query(query_id)
    assert query is not None
    await repo.record_new_items(
        query, [], [], rejected=[RejectedListing(_item(5), "over_budget", "too much")]
    )

    assert "Too expensive" in client.get(f"/searches/{query_id}").text


async def _turned_away(repo: Repo, *reasons: str) -> int:
    from vinted_bot.db.repo import RejectedListing  # noqa: PLC0415

    query_id = await _search(repo)
    query = await repo.get_query(query_id)
    assert query is not None
    await repo.record_new_items(
        query,
        [],
        [],
        rejected=[
            RejectedListing(_item(100 + n), reason, "why") for n, reason in enumerate(reasons)
        ],
    )
    return query_id


async def test_a_reason_chip_shows_only_the_listings_turned_away_for_it(
    client: TestClient, repo: Repo
) -> None:
    """The chips looked like buttons and did nothing."""
    query_id = await _turned_away(repo, "over_budget", "promoted", "promoted")

    page = client.get(f"/searches/{query_id}", params={"reason": "over_budget"}).text

    assert page.count('class="rej"') == 1


async def test_the_not_sent_tab_counts_everything_not_just_what_it_lists(
    client: TestClient, repo: Repo
) -> None:
    """It said 60, the length of the list, with 398 turned away."""
    query_id = await _turned_away(repo, *["promoted"] * 65)

    page = client.get(f"/searches/{query_id}").text

    assert 'Not sent <span class="badge">65</span>' in page


async def test_the_recent_finds_tab_counts_every_find(client: TestClient, repo: Repo) -> None:
    query_id = await _search(repo)
    await _found(repo, query_id, *(_item(n) for n in range(1, 31)))

    page = client.get(f"/searches/{query_id}").text

    assert 'Recent finds <span class="badge">30</span>' in page


# --- Finds -----------------------------------------------------------------------------


async def test_saving_a_find_shows_it_under_saved(client: TestClient, repo: Repo) -> None:
    query_id = await _seed(repo)
    assert query_id

    client.post("/api/items/1/mark", data={"mark": "saved"})

    saved = client.get("/", params={"show": "saved"}).text
    assert ('data-item-id="1"' in saved, 'data-item-id="2"' in saved) == (True, False)


async def test_hiding_a_find_takes_it_off_the_feed(client: TestClient, repo: Repo) -> None:
    await _seed(repo)

    client.post("/api/items/2/mark", data={"mark": "hidden"})

    assert 'data-item-id="2"' not in client.get("/").text


async def test_a_mark_on_a_missing_listing_is_a_404(client: TestClient) -> None:
    assert client.post("/api/items/12345/mark", data={"mark": "saved"}).status_code == 404


async def test_blocking_from_a_find_blocks_its_seller(client: TestClient, repo: Repo) -> None:
    await _seed(repo)

    client.post("/api/items/1/block-seller")

    assert 77 in await repo.blocked_seller_ids()


async def test_watching_a_find_adds_an_item_watch(client: TestClient, repo: Repo) -> None:
    await _seed(repo)

    client.post("/api/items/1/watch")

    assert [(w.kind, w.target_id) for w in await repo.list_watches()][-1] == ("item", 1)


async def test_watching_twice_says_so(client: TestClient, repo: Repo) -> None:
    await _seed(repo)
    client.post("/api/items/1/watch")

    response = client.post("/api/items/1/watch")

    assert response.status_code == 409


async def test_older_finds_page_backwards(
    client: TestClient, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(finds, "PAGE_SIZE", 1)
    await _seed(repo)
    newest = await repo.latest_seq()

    older = client.get("/api/finds", params={"before": newest}).json()

    assert 'data-item-id="1"' in older["html"]


async def test_the_live_stream_sends_new_finds(
    client: TestClient, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(finds, "LIVE_MAX_S", 0.2)
    monkeypatch.setattr(finds, "LIVE_POLL_S", 0.05)
    query_id = await _seed(repo)
    cursor = await repo.latest_seq()
    await _found(repo, query_id, _item(3, title="Fresh find"))

    body = client.get("/api/live", params={"after": cursor}).text

    assert "event: item" in body
    assert "Fresh find" in body


async def test_the_live_stream_resumes_from_the_last_event(
    client: TestClient, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(finds, "LIVE_MAX_S", 0.2)
    await _seed(repo)
    latest = await repo.latest_seq()

    body = client.get("/api/live", headers={"Last-Event-ID": str(latest - 1)}).text

    assert body.count("event: item") == 1


# --- Previews --------------------------------------------------------------------------


@pytest.fixture
def previewing(make_client: Callable[..., TestClient], vinted: VintedClient) -> TestClient:
    return make_client(client=vinted)


def test_a_preview_counts_what_the_filters_keep(
    previewing: TestClient,
    transport: ScriptedTransport,
    make_item: Callable[..., dict[str, Any]],
) -> None:
    now = int(time.time())
    transport.queue_catalog(
        [make_item(1, photo_ts=now, price="10.0"), make_item(2, photo_ts=now, price="90.0")]
    )

    result = previewing.post("/api/preview", data=_form(max_total_price="30")).json()

    assert (result["count"], result["seen"]) == (1, 2)
    assert result["receipt"] == [{"label": "Too expensive", "icon": "badge-percent", "removed": 1}]


def test_the_same_preview_is_answered_from_memory(
    previewing: TestClient, transport: ScriptedTransport, make_item: Callable[..., dict[str, Any]]
) -> None:
    transport.queue_catalog([make_item(1, photo_ts=int(time.time()))])
    previewing.post("/api/preview", data=_form())
    asked = len(transport.requests)

    previewing.post("/api/preview", data=_form())

    assert len(transport.requests) == asked


def test_previews_too_close_together_are_asked_to_wait(
    previewing: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(preview, "MIN_GAP_S", 60.0)
    previewing.post("/api/preview", data=_form(search_text="first"))

    response = previewing.post("/api/preview", data=_form(search_text="second"))

    assert response.status_code == 429
    assert response.json()["wait"] > 0


def test_without_a_vinted_client_the_preview_says_why(client: TestClient) -> None:
    response = client.post("/api/preview", data=_form())

    assert response.status_code == 503


def test_a_preview_reports_field_problems(previewing: TestClient) -> None:
    result = previewing.post("/api/preview", data=_form(search_text="")).json()

    assert "search_text" in result["errors"]


# --- Where alerts go -------------------------------------------------------------------


def test_a_discord_channel_link_gets_specific_advice(client: TestClient) -> None:
    response = client.post(
        "/destinations",
        data={"kind": "discord", "discord_url": "https://discord.com/channels/1/2"},
    )

    assert "link to the channel itself" in response.json()["error"]


async def test_a_discord_link_without_https_is_accepted(client: TestClient, repo: Repo) -> None:
    client.post(
        "/destinations",
        data={"kind": "discord", "discord_url": "discord.com/api/webhooks/123/abc-DEF"},
    )

    stored = (await repo.list_destinations())[0]
    assert stored.config["url"] == "https://discord.com/api/webhooks/123/abc-DEF"


async def test_an_ntfy_topic_with_spaces_is_refused(client: TestClient, repo: Repo) -> None:
    response = client.post("/destinations", data={"kind": "ntfy", "ntfy_topic": "my topic"})

    assert response.json()["field"] == "ntfy_topic"
    assert await repo.list_destinations() == []


async def test_tier_choices_are_saved(client: TestClient, repo: Repo) -> None:
    phone = await repo.add_destination(kind="ntfy", name="Phone", config={"topic": "t"})

    client.post(
        f"/destinations/{phone}/options",
        data={"tiers": ["steal", "deal"], "silent_tiers": ["deal"], "priority": "4"},
    )

    stored = await repo.get_destination(phone)
    assert stored is not None
    assert (stored.config["tiers"], stored.config["silent_tiers"]) == (["steal", "deal"], ["deal"])


async def test_receiving_nothing_is_refused(client: TestClient, repo: Repo) -> None:
    phone = await repo.add_destination(kind="ntfy", name="Phone", config={"topic": "t"})

    response = client.post(f"/destinations/{phone}/options", data={"priority": "3"})

    assert response.json()["field"] == "tiers"


async def test_a_discord_mention_takes_a_role_id(client: TestClient, repo: Repo) -> None:
    hook = await repo.add_destination(
        kind="discord", name="D", config={"url": "https://discord.com/api/webhooks/1/a"}
    )

    client.post(
        f"/destinations/{hook}/options", data={"tiers": ["steal"], "mention": "123456789012345678"}
    )

    stored = await repo.get_destination(hook)
    assert stored is not None
    assert stored.config["mention"] == "<@&123456789012345678>"


async def test_a_test_send_reports_what_happened(
    client: TestClient, repo: Repo, outgoing: Outgoing
) -> None:
    phone = await repo.add_destination(kind="ntfy", name="Phone", config={"topic": "t"})

    result = client.post(f"/destinations/{phone}/test").json()

    assert result["ok"] is True
    assert len(outgoing.requests) == 1


async def test_removing_a_destination_takes_it_off_the_page(client: TestClient, repo: Repo) -> None:
    phone = await repo.add_destination(kind="ntfy", name="Old phone", config={"topic": "t"})

    client.post(f"/destinations/{phone}/delete")

    assert "Old phone" not in client.get("/alerts").text.split("Removed")[-1]


def test_pairing_telegram_without_a_bot_asks_for_its_token(client: TestClient) -> None:
    response = client.post("/destinations/telegram/pair")

    assert "Paste the token BotFather gave you" in response.json()["error"]


async def test_pairing_telegram_finishes_when_the_bot_claims_the_code(
    make_client: Callable[..., TestClient], repo: Repo
) -> None:
    paired = make_client(telegram_bot_token=SecretStr("1:abc"))
    started = paired.post("/destinations/telegram/pair").json()
    await claim_pairing(repo, started["code"], chat_id=42, thread_id=None)

    status = paired.get(f"/destinations/telegram/pair/{started['id']}").json()

    assert status == {"connected": True, "chat": "42"}


# --- Watchlist, settings, data ---------------------------------------------------------


async def test_pasting_a_member_link_follows_the_seller(client: TestClient, repo: Repo) -> None:
    client.post("/watchlist", data={"url": "vinted.nl/member/12345-kasia"})

    assert [(w.kind, w.target_id, w.label) for w in await repo.list_watches()] == [
        ("seller", 12345, "kasia")
    ]


def test_pasting_a_search_link_on_the_watchlist_explains(client: TestClient) -> None:
    response = client.post("/watchlist", data={"url": SEARCH_URL})

    assert response.status_code == 400
    assert "not to a listing or a member" in response.text


async def test_a_time_zone_is_saved(client: TestClient, repo: Repo) -> None:
    client.post("/settings", data={"key": "timezone", "value": "Europe/Amsterdam"})

    assert (await repo.app_settings(default_timezone="UTC")).timezone == "Europe/Amsterdam"


def test_a_wrong_time_zone_is_explained(client: TestClient) -> None:
    response = client.post("/settings", data={"key": "timezone", "value": "Mars/Base"})

    assert "not a time zone" in response.json()["error"]


async def test_a_health_check_link_without_https_is_accepted(
    client: TestClient, repo: Repo
) -> None:
    client.post("/settings", data={"key": "healthcheck_url", "value": "hc-ping.com/abc"})

    assert (await repo.app_settings(default_timezone="UTC")).healthcheck_url == (
        "https://hc-ping.com/abc"
    )


async def test_unblocking_a_seller(client: TestClient, repo: Repo) -> None:
    await repo.block_seller(99, login="spammer")

    client.post("/settings/blocked/99/unblock")

    assert await repo.blocked_seller_ids() == set()


async def test_finds_download_as_a_spreadsheet(client: TestClient, repo: Repo) -> None:
    await _seed(repo)

    response = client.get("/export.csv")

    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.text.removeprefix("\ufeff").startswith("item_id,site,title")


async def test_finds_download_as_json(client: TestClient, repo: Repo) -> None:
    await _seed(repo)

    rows = client.get("/export.json").json()

    assert {row["item_id"] for row in rows} == {1, 2}


async def test_a_feed_reader_needs_the_feed_key(
    make_client: Callable[..., TestClient], repo: Repo
) -> None:
    query_id = await _seed(repo)
    reader = make_client(web_auth_token=SecretStr(TOKEN), signed_in=False)
    key = await security.feed_key(repo)

    assert reader.get(f"/rss/{query_id}.xml").status_code == 401
    assert reader.get(f"/rss/{query_id}.xml", params={"key": key}).status_code == 200


async def test_the_password_is_not_a_feed_key(
    make_client: Callable[..., TestClient], repo: Repo
) -> None:
    """Feed addresses end up in reader settings and proxy logs; the password must not."""
    query_id = await _seed(repo)
    reader = make_client(web_auth_token=SecretStr(TOKEN), signed_in=False)

    assert reader.get(f"/rss/{query_id}.xml", params={"key": TOKEN}).status_code == 401


async def test_a_search_page_links_its_feed_with_the_key(
    make_client: Callable[..., TestClient], repo: Repo
) -> None:
    query_id = await _seed(repo)
    owner = make_client(web_auth_token=SecretStr(TOKEN))

    page = owner.get(f"/searches/{query_id}").text

    assert f"/rss/{query_id}.xml?key={await security.feed_key(repo)}" in page


async def test_a_feed_lists_only_its_own_search(client: TestClient, repo: Repo) -> None:
    mine = await _seed(repo)
    other = await _search(repo, "Other")
    await _found(repo, other, _item(9, title="Someone else's find"))

    feed = client.get(f"/rss/{mine}.xml").text

    assert "Someone else" not in feed
    assert "<pubDate>" in feed


# --- First-run setup -------------------------------------------------------------------


async def test_the_setup_end_to_end(
    make_client: Callable[..., TestClient],
    repo: Repo,
    vinted: VintedClient,
    transport: ScriptedTransport,
    make_item: Callable[..., dict[str, Any]],
) -> None:
    """Country, a pasted link with a live preview, a phone, a test that arrives, done."""
    setup = make_client(client=vinted)
    transport.queue_catalog([make_item(1, photo_ts=int(time.time()))])

    page = setup.post("/welcome/search", data={"state": "{}", "tld": "fr"})
    state = _state_of(page.text)
    assert (
        setup.post(
            "/api/preview",
            data={"tld": "fr", "mode": "paste", "link": "vinted.fr/catalog?search_text=nike"},
        ).json()["count"]
        == 1
    )
    page = setup.post(
        "/welcome/search",
        data={
            "state": state,
            "submitted": "1",
            "mode": "paste",
            "link": "vinted.fr/catalog?search_text=nike",
        },
    )
    page = setup.post(
        "/welcome/alerts",
        data={
            "state": _state_of(page.text),
            "submitted": "1",
            "kind": "ntfy",
            "ntfy_topic": "mags-abc",
        },
    )
    assert "Did it arrive?" in page.text
    page = setup.post("/welcome/test", data={"state": _state_of(page.text), "next": "ready"})
    setup.post("/welcome/finish", data={"state": _state_of(page.text)})

    query = (await repo.list_queries())[0]
    destination = (await repo.list_destinations())[0]
    assert (query.params["search_text"], destination.config["topic"]) == ("nike", "mags-abc")
    assert await repo.explicit_routes(query.id) == [destination.id]
    assert (await repo.app_settings(default_timezone="UTC")).onboarded


def _state_of(html: str) -> str:
    marker = 'name="state" value="'
    start = html.index(marker) + len(marker)
    raw = html[start : html.index('"', start)]
    return (
        raw.replace("&#34;", '"').replace("&quot;", '"').replace("&#39;", "'").replace("&amp;", "&")
    )


async def test_setup_stores_the_search_and_phone_when_the_test_is_sent(
    client: TestClient, repo: Repo
) -> None:
    """The last screen says the tab can be closed, so by then everything must be stored."""
    page = client.post(
        "/welcome/search",
        data={
            "state": json.dumps({"tld": "fr"}),
            "submitted": "1",
            "mode": "paste",
            "link": SEARCH_URL,
        },
    )
    client.post(
        "/welcome/alerts",
        data={"state": _state_of(page.text), "submitted": "1", "kind": "ntfy", "ntfy_topic": "x1"},
    )

    (query,) = await repo.list_queries()
    (destination,) = await repo.list_destinations()
    assert await repo.explicit_routes(query.id) == [destination.id]


def test_a_failed_test_send_offers_the_fix(client: TestClient, outgoing: Outgoing) -> None:
    outgoing.status = 404
    page = client.post(
        "/welcome/search",
        data={
            "state": json.dumps({"tld": "fr"}),
            "submitted": "1",
            "mode": "paste",
            "link": SEARCH_URL,
        },
    )

    result = client.post(
        "/welcome/alerts",
        data={
            "state": _state_of(page.text),
            "submitted": "1",
            "kind": "discord",
            "discord_url": "discord.com/api/webhooks/1/abc",
        },
    )

    assert "That didn't arrive" in result.text


def test_a_missing_link_in_setup_is_shown_beside_the_field(client: TestClient) -> None:
    page = client.post(
        "/welcome/search", data={"state": "{}", "submitted": "1", "mode": "paste", "link": ""}
    )

    assert page.status_code == 400
    assert 'id="err-link"' in page.text


async def test_skipping_setup_remembers_it(client: TestClient, repo: Repo) -> None:
    client.post("/welcome/skip")

    assert (await repo.app_settings(default_timezone="UTC")).onboarded


# --- The search builder's filter data --------------------------------------------------


@pytest.fixture
def builder_client(
    make_client: Callable[..., TestClient], db: Database, repo: Repo, transport: ScriptedTransport
) -> TestClient:
    """A dashboard wired to a taxonomy service that talks to a scripted Vinted."""
    return make_client(taxonomy=Taxonomy(SessionManager(db, transport), repo))


def _page_with_tree() -> Response:
    payload = {
        "CSRF_TOKEN": "11112222-3333-4444",
        "catalogTree": [{"id": 1904, "title": "Women", "catalogs": []}],
    }
    html = f"<script>self.__next_f.push([1,{json.dumps(json.dumps(payload))}])</script>"
    return Response(status_code=200, text=html, headers={}, cookies={"access_token_web": "t"})


def test_the_filter_endpoints_need_a_sign_in(locked: TestClient) -> None:
    assert locked.get("/api/filters/fr/brands?q=nike").status_code == 401


def test_without_the_service_the_builder_answers_503(client: TestClient) -> None:
    assert client.get("/api/filters/fr/categories").status_code == 503


def test_categories_come_back_as_a_tree(
    builder_client: TestClient, transport: ScriptedTransport
) -> None:
    transport.queue_root(_page_with_tree())  # session bootstrap
    transport.queue_root(_page_with_tree())  # the page that carries the tree

    response = builder_client.get("/api/filters/fr/categories")

    assert response.json() == {"categories": [{"id": 1904, "title": "Women", "children": []}]}


def test_an_unknown_site_is_refused_before_talking_to_vinted(
    builder_client: TestClient, transport: ScriptedTransport
) -> None:
    assert builder_client.get("/api/filters/xx/categories").status_code == 404
    assert transport.requests == []


def test_a_short_brand_query_is_answered_locally(
    builder_client: TestClient, transport: ScriptedTransport
) -> None:
    response = builder_client.get("/api/filters/fr/brands?q=n")

    assert response.json() == {"brands": []}
    assert transport.requests == []


def test_brands_pass_through_with_ids_and_counts(
    builder_client: TestClient, transport: ScriptedTransport
) -> None:
    transport.queue(
        Response(
            status_code=200,
            text=json.dumps({"brands": [{"id": 53, "title": "Nike", "item_count": 9}]}),
            headers={},
            cookies={},
        )
    )

    response = builder_client.get("/api/filters/fr/brands?q=nike")

    assert response.json() == {"brands": [{"id": 53, "title": "Nike", "count": 9}]}


def test_junk_in_catalog_ids_never_reaches_vinted(
    builder_client: TestClient, transport: ScriptedTransport
) -> None:
    transport.queue_root(_page_with_tree())
    transport.queue_root(_page_with_tree())
    transport.queue(
        Response(status_code=200, text=json.dumps({"options": []}), headers={}, cookies={})
    )

    builder_client.get("/api/filters/fr/brands?q=nike&catalog_ids=12,drop%20table,34")

    assert transport.requests[-1]["params"]["attribute_ids[catalog]"] == "12,34"


def test_an_unknown_facet_is_a_404(builder_client: TestClient) -> None:
    assert builder_client.get("/api/filters/fr/facets/shoe_smell").status_code == 404


def test_a_refusal_from_vinted_surfaces_as_a_502_with_the_reason(
    builder_client: TestClient, transport: ScriptedTransport
) -> None:
    transport.queue_root(_page_with_tree())
    transport.queue_root(_page_with_tree())
    transport.queue_status(403, "blocked")

    response = builder_client.get("/api/filters/fr/facets/status")

    assert response.status_code == 502


# --- Script safety ---------------------------------------------------------------------


def test_chart_tooltips_never_parse_page_data_as_markup() -> None:
    """Stored XSS: a tooltip carries a search name, and a name is whatever was pasted.

    The browser decodes a data attribute's escaping before the script reads it, so
    anything read from `dataset` and handed to innerHTML runs as markup.
    """
    script = (core.STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")

    assert not re.search(r"innerHTML\s*=[^;]*dataset", script)


# --- Asking for support ----------------------------------------------------------------

SUPPORT_HEADING = "Did it find you something good?"


async def _delivered(repo: Repo) -> int:
    """A search with one find whose alert reached a phone."""
    query_id = await _search(repo)
    phone = await repo.add_destination(kind="ntfy", name="Phone", config={"topic": "t"})
    query = await repo.get_query(query_id)
    assert query is not None
    await repo.record_new_items(query, [_item(1)], [phone])
    (pending,) = await repo.claim_batch(phone, 1)
    await repo.mark_sent([pending.outbox_id])
    await repo.set_onboarded(True)
    return query_id


async def test_finds_asks_for_support_once_an_alert_has_reached_someone(
    client: TestClient, repo: Repo
) -> None:
    await _delivered(repo)

    page = client.get("/").text

    assert SUPPORT_HEADING in page


async def test_the_support_card_links_to_ko_fi_tagged_with_where_it_was(
    client: TestClient, repo: Repo
) -> None:
    await _delivered(repo)

    page = client.get("/").text

    kofi = "https://ko-fi.com/jaspnerd?utm_source=vinted-bot&amp;utm_medium=support-card"
    assert f'href="{kofi}"' in page


async def test_finds_doesnt_ask_before_any_alert_was_delivered(
    client: TestClient, repo: Repo
) -> None:
    await _seed(repo)

    assert "Buy me a coffee" not in client.get("/").text


async def test_the_support_card_doesnt_come_back_the_same_week(
    client: TestClient, repo: Repo
) -> None:
    await _delivered(repo)
    client.get("/")

    assert "Buy me a coffee" not in client.get("/").text


async def test_finds_doesnt_ask_while_a_search_waits_on_vinted(
    client: TestClient, repo: Repo
) -> None:
    query_id = await _delivered(repo)
    await repo.record_failure(query_id, "http_403", "refused")

    assert "Buy me a coffee" not in client.get("/").text


async def test_dont_show_again_stops_the_card_for_good(client: TestClient, repo: Repo) -> None:
    await _delivered(repo)
    client.post("/support/hide", headers={"Origin": BASE, "Accept": "application/json"})
    # A week later, after another alert, it would otherwise ask again.
    await repo.record_support_card_shown(1, int(time.time()) - 8 * 24 * 3600)

    assert "Buy me a coffee" not in client.get("/").text


def test_dont_show_again_works_without_the_page_script(client: TestClient) -> None:
    response = client.post("/support/hide", headers={"Origin": BASE}, follow_redirects=False)

    assert response.headers["location"] == "/"


async def test_settings_offers_one_off_gifts_that_open_ko_fi(
    client: TestClient, repo: Repo
) -> None:
    await repo.set_onboarded(True)

    page = client.get("/settings").text

    assert page.count("ko-fi.com/jaspnerd?utm_source=vinted-bot&amp;utm_medium=settings") == 3


async def test_setup_never_asks_for_support(client: TestClient, repo: Repo) -> None:
    """Asking before it has found anything is asking for nothing in return."""
    await _delivered(repo)

    assert "ko-fi.com" not in client.get("/welcome/ready").text


async def _refused_since(repo: Repo, db: Database, seconds_ago: int) -> None:
    query_id = await _search(repo)
    await repo.record_failure(query_id, "http_403", "Forbidden")
    await db.execute(
        "UPDATE query_state SET last_success_at = ? WHERE query_id = ?",
        (int(time.time()) - seconds_ago, query_id),
    )


async def test_a_fresh_block_is_expected_to_clear_within_an_hour(
    client: TestClient, repo: Repo, db: Database
) -> None:
    await _refused_since(repo, db, 600)

    assert "within an hour" in client.get("/searches").text


async def test_a_block_past_an_hour_says_how_long_it_has_lasted(
    client: TestClient, repo: Repo, db: Database
) -> None:
    """The banner still said "clears up within an hour" an hour and a half in."""
    await _refused_since(repo, db, 90 * 60)

    page = client.get("/searches").text

    assert ("going on for 1 hour" in page, "within an hour" in page) == (True, False)
