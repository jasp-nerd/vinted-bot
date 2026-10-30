"""The few words an alert needs, in the language of the site the listing is on.

Vinted already localises what the seller typed and the condition ("Très bon état"), and the
chat apps localise relative times themselves. What is left is a dozen labels and the way a
price is written, so a small table does the job; Babel would be more correct and is a
ten-megabyte wheel for the sake of "4,90 €".

Strings stay short on purpose: they sit on buttons and in one-line headers on a phone.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True, slots=True)
class Labels:
    """Every piece of fixed text an alert can contain, for one language."""

    locale: str
    new_match: str
    price_drop: str
    sold: str
    reserved: str
    removed: str
    # "{seller}" is replaced with the seller's login.
    new_from: str
    size: str
    condition: str
    brand: str
    seller: str
    listed: str
    buy: str
    message: str
    open: str
    dashboard: str
    plus_protection: str
    typical: str
    vs_typical: str
    steal: str
    good_deal: str
    # "{n}" is replaced with the count.
    new_matches: str
    new_seller: str


_CATALOGUE: dict[str, Labels] = {
    "en": Labels(
        locale="en",
        new_match="New match",
        price_drop="Price drop",
        sold="Sold",
        reserved="Reserved",
        removed="No longer listed",
        new_from="New from {seller}",
        size="Size",
        condition="Condition",
        brand="Brand",
        seller="Seller",
        listed="listed",
        buy="Buy",
        message="Message seller",
        open="Open on Vinted",
        dashboard="Dashboard",
        plus_protection="+ buyer protection",
        typical="typical",
        vs_typical="vs typical",
        steal="Steal",
        good_deal="Good deal",
        new_matches="{n} new matches",
        new_seller="new seller",
    ),
    "fr": Labels(
        locale="fr",
        new_match="Nouvelle annonce",
        price_drop="Baisse de prix",
        sold="Vendu",
        reserved="Réservé",
        removed="Annonce retirée",
        new_from="Nouveau chez {seller}",
        size="Taille",
        condition="État",
        brand="Marque",
        seller="Vendeur",
        listed="publié",
        buy="Acheter",
        message="Contacter",
        open="Voir sur Vinted",
        dashboard="Tableau de bord",
        plus_protection="+ protection acheteurs",
        typical="habituel",
        vs_typical="vs habituel",
        steal="Super affaire",
        good_deal="Bonne affaire",
        new_matches="{n} nouvelles annonces",
        new_seller="nouveau vendeur",
    ),
    "de": Labels(
        locale="de",
        new_match="Neuer Treffer",
        price_drop="Preissenkung",
        sold="Verkauft",
        reserved="Reserviert",
        removed="Nicht mehr verfügbar",
        new_from="Neu von {seller}",
        size="Größe",
        condition="Zustand",
        brand="Marke",
        seller="Verkäufer",
        listed="eingestellt",
        buy="Kaufen",
        message="Nachricht",
        open="Auf Vinted öffnen",
        dashboard="Dashboard",
        plus_protection="+ Käuferschutz",
        typical="üblich",
        vs_typical="vs. üblich",
        steal="Schnäppchen",
        good_deal="Guter Deal",
        new_matches="{n} neue Treffer",
        new_seller="neuer Verkäufer",
    ),
    "nl": Labels(
        locale="nl",
        new_match="Nieuwe match",
        price_drop="Prijsdaling",
        sold="Verkocht",
        reserved="Gereserveerd",
        removed="Niet meer beschikbaar",
        new_from="Nieuw van {seller}",
        size="Maat",
        condition="Staat",
        brand="Merk",
        seller="Verkoper",
        listed="geplaatst",
        buy="Kopen",
        message="Bericht sturen",
        open="Open op Vinted",
        dashboard="Dashboard",
        plus_protection="+ kopersbescherming",
        typical="normaal",
        vs_typical="t.o.v. normaal",
        steal="Topdeal",
        good_deal="Goede deal",
        new_matches="{n} nieuwe resultaten",
        new_seller="nieuwe verkoper",
    ),
    "es": Labels(
        locale="es",
        new_match="Nuevo resultado",
        price_drop="Bajada de precio",
        sold="Vendido",
        reserved="Reservado",
        removed="Ya no disponible",
        new_from="Nuevo de {seller}",
        size="Talla",
        condition="Estado",
        brand="Marca",
        seller="Vendedor",
        listed="publicado",
        buy="Comprar",
        message="Mensaje",
        open="Ver en Vinted",
        dashboard="Panel",
        plus_protection="+ protección al comprador",
        typical="habitual",
        vs_typical="vs. habitual",
        steal="Chollo",
        good_deal="Buen precio",
        new_matches="{n} nuevos resultados",
        new_seller="vendedor nuevo",
    ),
    "it": Labels(
        locale="it",
        new_match="Nuovo risultato",
        price_drop="Prezzo ribassato",
        sold="Venduto",
        reserved="Riservato",
        removed="Non più disponibile",
        new_from="Novità da {seller}",
        size="Taglia",
        condition="Condizioni",
        brand="Brand",
        seller="Venditore",
        listed="pubblicato",
        buy="Acquista",
        message="Messaggio",
        open="Apri su Vinted",
        dashboard="Dashboard",
        plus_protection="+ protezione acquisti",
        typical="solito",
        vs_typical="vs. solito",
        steal="Affarone",
        good_deal="Buon affare",
        new_matches="{n} nuovi risultati",
        new_seller="nuovo venditore",
    ),
    "pl": Labels(
        locale="pl",
        new_match="Nowe ogłoszenie",
        price_drop="Obniżka ceny",
        sold="Sprzedane",
        reserved="Zarezerwowane",
        removed="Ogłoszenie usunięte",
        new_from="Nowe od {seller}",
        size="Rozmiar",
        condition="Stan",
        brand="Marka",
        seller="Sprzedający",
        listed="dodano",
        buy="Kup",
        message="Napisz",
        open="Otwórz w Vinted",
        dashboard="Panel",
        plus_protection="+ ochrona kupujących",
        typical="zwykle",
        vs_typical="vs zwykle",
        steal="Okazja",
        good_deal="Dobra cena",
        new_matches="Nowe oferty: {n}",
        new_seller="nowy sprzedający",
    ),
    "lt": Labels(
        locale="lt",
        new_match="Naujas skelbimas",
        price_drop="Kaina sumažinta",
        sold="Parduota",
        reserved="Rezervuota",
        removed="Skelbimas pašalintas",
        new_from="Nauja iš {seller}",
        size="Dydis",
        condition="Būklė",
        brand="Prekės ženklas",
        seller="Pardavėjas",
        listed="įkelta",
        buy="Pirkti",
        message="Rašyti",
        open="Atidaryti Vinted",
        dashboard="Skydelis",
        plus_protection="+ pirkėjo apsauga",
        typical="įprasta",
        vs_typical="nuo įprastos",
        steal="Super kaina",
        good_deal="Gera kaina",
        new_matches="Nauji skelbimai: {n}",
        new_seller="naujas pardavėjas",
    ),
    "cs": Labels(
        locale="cs",
        new_match="Nový inzerát",
        price_drop="Sleva",
        sold="Prodáno",
        reserved="Rezervováno",
        removed="Inzerát odstraněn",
        new_from="Nové od {seller}",
        size="Velikost",
        condition="Stav",
        brand="Značka",
        seller="Prodejce",
        listed="přidáno",
        buy="Koupit",
        message="Napsat",
        open="Otevřít na Vinted",
        dashboard="Přehled",
        plus_protection="+ ochrana kupujících",
        typical="obvykle",
        vs_typical="oproti obvyklé",
        steal="Super cena",
        good_deal="Dobrá cena",
        new_matches="Nové inzeráty: {n}",
        new_seller="nový prodejce",
    ),
}

# Which language each country site speaks. Sites missing here (the UK, Ireland, the US,
# and countries without a catalogue entry yet) get English.
_LOCALE_BY_TLD = {
    "fr": "fr",
    "be": "fr",
    "lu": "fr",
    "de": "de",
    "at": "de",
    "nl": "nl",
    "es": "es",
    "it": "it",
    "pl": "pl",
    "lt": "lt",
    "cz": "cs",
}

_SYMBOLS = {
    "EUR": "€",
    "GBP": "£",
    "USD": "$",
    "PLN": "zł",
    "CZK": "Kč",
    "SEK": "kr",
    "DKK": "kr",
    "HUF": "Ft",
    "RON": "lei",
}

# English writes these symbols in front of the number with no space; everything else
# goes after it.
_PREFIX_SYMBOLS = frozenset({"€", "£", "$"})

_CENT = Decimal("0.01")


def labels_for(tld: str) -> Labels:
    """The labels for a listing on vinted.<tld>."""
    return _CATALOGUE[_LOCALE_BY_TLD.get(tld, "en")]


def money_text(amount: Decimal) -> str:
    """An amount with exactly two decimals, as the JSON contract documents it ("15.00")."""
    return str(amount.quantize(_CENT, rounding=ROUND_HALF_UP))


def format_money(amount: Decimal, currency: str | None, locale: str) -> str:
    """A price the way someone reading `locale` writes it: "€4.90", "4,90 €", "€ 4,90"."""
    number = money_text(amount)
    symbol = _SYMBOLS.get((currency or "").upper(), currency or "")
    if locale == "en":
        if symbol in _PREFIX_SYMBOLS:
            return f"{symbol}{number}"
        return f"{number} {symbol}".strip()
    number = number.replace(".", ",")
    if locale == "nl" and symbol in _PREFIX_SYMBOLS:
        return f"{symbol} {number}"
    return f"{number} {symbol}".strip()
