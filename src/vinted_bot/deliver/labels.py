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
    # The relative-time label: "listed" when Vinted said when the listing went up,
    # "found" when all we know is when we saw it.
    listed: str
    found: str
    buy: str
    message: str
    open: str
    dashboard: str
    # eBay's sold listings for the title, and Google Lens on the photo.
    price_check: str
    photo_search: str
    # Telegram's action buttons, and what each says once pressed.
    block_seller: str
    mute: str
    hide: str
    blocked: str
    muted: str
    hidden: str
    plus_protection: str
    typical: str
    vs_typical: str
    steal: str
    good_deal: str
    # "{n}" is replaced with the count.
    new_matches: str
    new_seller: str
    margin: str


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
        found="found",
        buy="Buy",
        message="Message seller",
        open="Open on Vinted",
        dashboard="Dashboard",
        price_check="eBay sold",
        photo_search="Photo search",
        block_seller="Block seller",
        mute="Mute 1 h",
        hide="Hide",
        blocked="Seller blocked",
        muted="Muted 1 h",
        hidden="Hidden",
        plus_protection="+ buyer protection",
        typical="typical",
        vs_typical="vs typical",
        steal="Steal",
        good_deal="Good deal",
        new_matches="{n} new matches",
        new_seller="new seller",
        margin="margin",
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
        found="trouvé",
        buy="Acheter",
        message="Contacter",
        open="Voir sur Vinted",
        dashboard="Tableau de bord",
        price_check="eBay vendus",
        photo_search="Recherche photo",
        block_seller="Bloquer vendeur",
        mute="Silence 1 h",
        hide="Masquer",
        blocked="Vendeur bloqué",
        muted="En silence 1 h",
        hidden="Masqué",
        plus_protection="+ protection acheteurs",
        typical="habituel",
        vs_typical="vs habituel",
        steal="Super affaire",
        good_deal="Bonne affaire",
        new_matches="{n} nouvelles annonces",
        new_seller="nouveau vendeur",
        margin="marge",
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
        found="gefunden",
        buy="Kaufen",
        message="Nachricht",
        open="Auf Vinted öffnen",
        dashboard="Dashboard",
        price_check="eBay verkauft",
        photo_search="Bildersuche",
        block_seller="Verkäufer sperren",
        mute="1 Std. stumm",
        hide="Ausblenden",
        blocked="Verkäufer gesperrt",
        muted="1 Std. stumm",
        hidden="Ausgeblendet",
        plus_protection="+ Käuferschutz",
        typical="üblich",
        vs_typical="vs. üblich",
        steal="Schnäppchen",
        good_deal="Guter Deal",
        new_matches="{n} neue Treffer",
        new_seller="neuer Verkäufer",
        margin="Marge",
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
        found="gevonden",
        buy="Kopen",
        message="Bericht sturen",
        open="Open op Vinted",
        dashboard="Dashboard",
        price_check="eBay verkocht",
        photo_search="Zoek op foto",
        block_seller="Verkoper blokkeren",
        mute="1 uur stil",
        hide="Verbergen",
        blocked="Verkoper geblokkeerd",
        muted="1 uur stil",
        hidden="Verborgen",
        plus_protection="+ kopersbescherming",
        typical="normaal",
        vs_typical="t.o.v. normaal",
        steal="Topdeal",
        good_deal="Goede deal",
        new_matches="{n} nieuwe resultaten",
        new_seller="nieuwe verkoper",
        margin="marge",
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
        found="encontrado",
        buy="Comprar",
        message="Mensaje",
        open="Ver en Vinted",
        dashboard="Panel",
        price_check="eBay vendidos",
        photo_search="Buscar por foto",
        block_seller="Bloquear vendedor",
        mute="Silenciar 1 h",
        hide="Ocultar",
        blocked="Vendedor bloqueado",
        muted="Silenciado 1 h",
        hidden="Oculto",
        plus_protection="+ protección al comprador",
        typical="habitual",
        vs_typical="vs. habitual",
        steal="Chollo",
        good_deal="Buen precio",
        new_matches="{n} nuevos resultados",
        new_seller="vendedor nuevo",
        margin="margen",
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
        found="trovato",
        buy="Acquista",
        message="Messaggio",
        open="Apri su Vinted",
        dashboard="Dashboard",
        price_check="eBay venduti",
        photo_search="Cerca per foto",
        block_seller="Blocca venditore",
        mute="Silenzia 1 h",
        hide="Nascondi",
        blocked="Venditore bloccato",
        muted="Silenziato 1 h",
        hidden="Nascosto",
        plus_protection="+ protezione acquisti",
        typical="solito",
        vs_typical="vs. solito",
        steal="Affarone",
        good_deal="Buon affare",
        new_matches="{n} nuovi risultati",
        new_seller="nuovo venditore",
        margin="margine",
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
        found="znaleziono",
        buy="Kup",
        message="Napisz",
        open="Otwórz w Vinted",
        dashboard="Panel",
        price_check="eBay sprzedane",
        photo_search="Szukaj zdjęciem",
        block_seller="Zablokuj sprzedającego",
        mute="Wycisz 1 h",
        hide="Ukryj",
        blocked="Zablokowano",
        muted="Wyciszono 1 h",
        hidden="Ukryto",
        plus_protection="+ ochrona kupujących",
        typical="zwykle",
        vs_typical="vs zwykle",
        steal="Okazja",
        good_deal="Dobra cena",
        new_matches="Nowe oferty: {n}",
        new_seller="nowy sprzedający",
        margin="marża",
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
        found="rasta",
        buy="Pirkti",
        message="Rašyti",
        open="Atidaryti Vinted",
        dashboard="Skydelis",
        price_check="eBay parduota",
        photo_search="Ieškoti pagal nuotrauką",
        block_seller="Blokuoti pardavėją",
        mute="Nutildyti 1 val.",
        hide="Slėpti",
        blocked="Užblokuota",
        muted="Nutildyta 1 val.",
        hidden="Paslėpta",
        plus_protection="+ pirkėjo apsauga",
        typical="įprasta",
        vs_typical="nuo įprastos",
        steal="Super kaina",
        good_deal="Gera kaina",
        new_matches="Nauji skelbimai: {n}",
        new_seller="naujas pardavėjas",
        margin="marža",
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
        found="nalezeno",
        buy="Koupit",
        message="Napsat",
        open="Otevřít na Vinted",
        dashboard="Přehled",
        price_check="eBay prodané",
        photo_search="Hledat fotkou",
        block_seller="Blokovat prodejce",
        mute="Ztlumit 1 h",
        hide="Skrýt",
        blocked="Prodejce blokován",
        muted="Ztlumeno 1 h",
        hidden="Skryto",
        plus_protection="+ ochrana kupujících",
        typical="obvykle",
        vs_typical="oproti obvyklé",
        steal="Super cena",
        good_deal="Dobrá cena",
        new_matches="Nové inzeráty: {n}",
        new_seller="nový prodejce",
        margin="marže",
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

# A real minus sign: a hyphen in "-46%" reads as a dash, and wraps like one.
MINUS = "\u2212"


def labels_for(tld: str) -> Labels:
    """The labels for a listing on vinted.<tld>."""
    return _CATALOGUE[_LOCALE_BY_TLD.get(tld, "en")]


def money_text(amount: Decimal) -> str:
    """An amount with exactly two decimals, as the JSON contract documents it ("15.00")."""
    return str(amount.quantize(_CENT, rounding=ROUND_HALF_UP))


def format_rough_money(amount: Decimal, currency: str | None, locale: str) -> str:
    """A signed, whole-unit estimate such as "+€19", with a real minus sign when negative.

    Rounded because it is an estimate built on a guessed resale price, and cents would
    claim a precision it does not have.
    """
    whole = amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    text = format_money(abs(whole), currency, locale)
    for zeros in (".00", ",00"):
        text = text.replace(zeros, "")
    return f"{MINUS if whole < 0 else '+'}{text}"


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
