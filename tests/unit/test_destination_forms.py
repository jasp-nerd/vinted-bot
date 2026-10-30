"""Turning the email form into an Apprise address.

Each test hands the result to Apprise itself, so a link Apprise would read differently
from what the form meant fails here rather than in someone's inbox.
"""

from __future__ import annotations

from typing import Any

import apprise
import pytest

from vinted_bot.engine.validation import InvalidInputError
from vinted_bot.web.destinations import email_url


def _parsed(url: str) -> Any:
    service = apprise.Apprise.instantiate(url)
    assert service is not None, f"Apprise could not read {url}"
    return service


def _custom(**fields: str) -> dict[str, str]:
    return {
        "email_address": "me@example.org",
        "email_provider": "custom",
        "email_smtp": "mail.example.org",
        **fields,
    }


def test_a_known_provider_signs_in_with_the_app_password() -> None:
    url = email_url(
        {"email_address": "me@gmail.com", "email_provider": "gmail", "email_password": "abcd efgh"}
    )

    assert _parsed(url).password == "abcd efgh"


def test_a_known_provider_needs_an_app_password() -> None:
    with pytest.raises(InvalidInputError) as raised:
        email_url({"email_address": "me@gmail.com", "email_provider": "gmail"})

    assert raised.value.field == "email_password"


def test_an_unknown_provider_is_refused() -> None:
    with pytest.raises(InvalidInputError) as raised:
        email_url({"email_address": "a@b.org", "email_provider": "aol", "email_password": "x"})

    assert raised.value.field == "email_provider"


def test_a_custom_server_is_where_the_mail_goes() -> None:
    service = _parsed(email_url(_custom(email_port="2525", email_security="none")))

    assert (service.smtp_host, service.port) == ("mail.example.org", 2525)


def test_a_custom_server_without_encryption_says_so() -> None:
    service = _parsed(email_url(_custom(email_security="none")))

    assert service.secure_mode == "insecure"


def test_a_custom_server_defaults_to_starttls_on_587() -> None:
    service = _parsed(email_url(_custom()))

    assert (service.secure_mode, service.port) == ("starttls", 587)


def test_ssl_picks_its_own_usual_port() -> None:
    service = _parsed(email_url(_custom(email_security="ssl")))

    assert service.port == 465


def test_a_custom_server_without_a_password_does_not_sign_in() -> None:
    service = _parsed(email_url(_custom(email_security="none")))

    assert not service.password


def test_a_custom_server_signs_in_as_the_address_by_default() -> None:
    service = _parsed(email_url(_custom(email_password="pw")))

    assert service.user == "me@example.org"


def test_a_custom_user_name_is_used_to_sign_in() -> None:
    service = _parsed(email_url(_custom(email_user="relay", email_password="p@ss/word")))

    assert (service.user, service.password) == ("relay", "p@ss/word")


def test_mail_from_a_custom_server_comes_from_the_address() -> None:
    service = _parsed(email_url(_custom(email_security="none")))

    assert service.from_addr[1] == "me@example.org"


def test_a_custom_server_needs_its_address() -> None:
    with pytest.raises(InvalidInputError) as raised:
        email_url(_custom(email_smtp=""))

    assert raised.value.field == "email_smtp"


@pytest.mark.parametrize("server", ["https://mail.example.org", "mail.example.org:587", "a b"])
def test_a_custom_server_is_only_a_name(server: str) -> None:
    with pytest.raises(InvalidInputError) as raised:
        email_url(_custom(email_smtp=server))

    assert raised.value.field == "email_smtp"


@pytest.mark.parametrize("port", ["0", "70000", "smtp"])
def test_a_port_out_of_range_is_refused(port: str) -> None:
    with pytest.raises(InvalidInputError) as raised:
        email_url(_custom(email_port=port))

    assert raised.value.field == "email_port"


def test_an_unknown_encryption_is_refused() -> None:
    with pytest.raises(InvalidInputError) as raised:
        email_url(_custom(email_security="tls13"))

    assert raised.value.field == "email_security"


def test_a_user_name_without_a_password_is_refused() -> None:
    with pytest.raises(InvalidInputError) as raised:
        email_url(_custom(email_user="relay"))

    assert raised.value.field == "email_password"
