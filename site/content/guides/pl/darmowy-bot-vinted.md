---
title: "Darmowy bot Vinted: powiadomienia o nowych ogłoszeniach"
description: "Darmowy bot Vinted open source: nowe ogłoszenia z Twoich wyszukiwań na Discordzie, Telegramie lub telefonie. Bez abonamentu i bez logowania do Vinted."
slug: darmowy-bot-vinted
key: free-bot
date: 2026-10-30
updated: 2026-10-30
keywords:
  - bot vinted
  - bot vinted pl
  - darmowy bot vinted
  - vinted bot na telefon
  - vinted bot free
  - bot vinted discord
faq:
  - q: "Czy istnieje darmowy bot Vinted?"
    a: "Tak. vinted-sniper jest darmowy i open source (licencja MIT), bez płatnych planów. Obserwuje Twoje wyszukiwania na Vinted i wysyła nowe ogłoszenia na Discorda, Telegrama, telefon przez aplikację ntfy albo na webhook. Działa na Twoim komputerze, który musi być włączony."
  - q: "Czy bot Vinted potrzebuje mojego konta na Vinted?"
    a: "Bot do powiadomień nie. Wyniki wyszukiwania można czytać bez logowania. Konta potrzebują tylko narzędzia, które kupują, piszą wiadomości albo ponownie wystawiają za Ciebie, i to one narażają konto na blokadę."
  - q: "Czy mogę dostawać powiadomienia z bota Vinted na telefon?"
    a: "Tak. Najprościej przez darmową aplikację ntfy, bez zakładania konta. Możesz też odbierać powiadomienia w aplikacji Discord albo Telegram na telefonie."
  - q: "Czy darmowy bot Vinted może kupować za mnie?"
    a: "Ten nie. Automatyczne kupowanie wymaga zalogowanego konta, a stąd biorą się blokady kont. vinted-sniper dodaje do każdego powiadomienia przycisk kupna, więc zakup robisz Ty."
---

Tak, darmowy bot Vinted istnieje. vinted-sniper to darmowa aplikacja open source, która obserwuje Twoje wyszukiwania na Vinted i wysyła każde nowe ogłoszenie na Discorda, Telegrama albo telefon, razem z ceną, którą naprawdę zapłacisz. Działa na Twoim własnym komputerze, a nie na cudzym serwerze, dlatego nic nie kosztuje, i nigdy nie prosi o login do Vinted.

Poniżej: co zwykle oznacza "bot Vinted", jakie są darmowe opcje, jak go uruchomić w około dziesięć minut i jakie ma ograniczenia.

## Co to jest bot Vinted

To słowo obejmuje bardzo różne narzędzia, a różnica ma znaczenie i dla ceny, i dla ryzyka.

Bot do powiadomień (nazywany też monitorem albo snajperem) obserwuje wyszukiwanie i daje znać, gdy pojawi się coś nowego. Ogłoszenie otwierasz i kupujesz sam. Tego szuka większość osób, którym nie wystarczają powiadomienia z zapisanych wyszukiwań Vinted.

Bot do automatycznego kupowania (autobuy) loguje się na Twoje konto i kupuje, gdy tylko ogłoszenie pasuje. To te drogie, i potrzebują Twojego konta oraz danych płatności.

Boty do ponownego wystawiania, polubień i obserwowania są dla sprzedających. One też działają przez Twoje konto.

Ten poradnik dotyczy botów do powiadomień.

## Darmowe opcje, uczciwie porównane

### Zapisane wyszukiwania na Vinted

Darmowe i wbudowane w aplikację. Zapisujesz wyszukiwanie i Vinted powinien informować Cię o nowych przedmiotach. W praktyce wiele osób dostaje te powiadomienia z opóźnieniem albo wcale, a filtr ceny pomija opłatę za ochronę kupujących. Przyczyny i ustawienia opisujemy w poradniku o [powiadomieniach Vinted](/guides/powiadomienia-vinted/).

### Darmowe okresy próbne płatnych botów

Kilka botów na Telegramie i aplikacji pozwala przetestować jedno wyszukiwanie za darmo, a potem kosztuje mniej więcej od 5 do 30 euro miesięcznie (stan na październik 2026). Dobre do testu, za mało do codziennego używania.

### Darmowe serwery Discord

Wspólne kanały, które publikują ogłoszenia z popularnych kategorii. Widzisz to samo co wszyscy inni, w tym samym momencie, bez własnych filtrów.

### Narzędzia open source uruchamiane samodzielnie

Darmowe i bez limitu wyszukiwań, ale potrzebujesz komputera, który zostaje włączony. vinted-sniper jest jednym z nich. Stawia na prostą instalację i na to, żeby mówić Ci, kiedy przestaje działać, bo to najczęstsza skarga na darmowe boty.

## Dlaczego vinted-sniper jest darmowy

Po naszej stronie nie ma żadnego serwera. Aplikacja działa na Twoim laptopie, komputerze stacjonarnym, Raspberry Pi albo serwerze NAS, sprawdza wyszukiwania z Twojego łącza i stamtąd wysyła powiadomienia. Brak kosztów serwera oznacza, że nie ma za co pobierać opłat. Kod jest na GitHubie na licencji MIT, więc każdy może sprawdzić, co dokładnie robi.

Co dostajesz za darmo:

- Powiadomienia na Discordzie, Telegramie, w ntfy (darmowa aplikacja z powiadomieniami na telefon, bez konta), przez RSS albo na własny webhook. E-mail i usługi takie jak Slack czy Pushover działają przez opcjonalny dodatek.
- Pełną cenę w każdym powiadomieniu, z ochroną kupujących, i limity ceny liczone od tej kwoty. Filtr ceny na Vinted pomija tę opłatę.
- Słowa, które musi zawierać tytuł, i słowa do pominięcia, żeby "na części" czy "samo pudełko" nigdy do Ciebie nie trafiały.
- Filtry sprzedającego: minimalna ocena, minimalna liczba opinii, kraj i przycisk blokowania.
- Oznaczenie okazji, gdy ogłoszenie jest wyraźnie tańsze niż zwykle w danym wyszukiwaniu.
- Jedno wyszukiwanie na kilku krajowych stronach Vinted, godziny ciszy i panel z nowymi znaleziskami na żywo.
- Prosty opis stanu każdego wyszukiwania, więc wiesz, kiedy Vinted je spowalnia albo kiedy się zacięło.

## Konfiguracja w pięciu krokach

1. Zainstaluj. Na Windowsie otwórz PowerShell i wklej jednolinijkowe polecenie ze strony głównej; na Macu lub Linuksie otwórz Terminal i wklej drugie. Nie potrzebujesz uprawnień administratora ani Dockera. Na końcu przeglądarka otworzy panel pod adresem `http://localhost:8000`.
2. Wyszukaj na Vinted tak jak zawsze (słowa, kategoria, rozmiar, marka, stan) i skopiuj adres z paska przeglądarki albo udostępnij wyszukiwanie z aplikacji i skopiuj link. Wyszukiwanie możesz też zbudować w panelu, korzystając z kategorii i marek Vinted.
3. Wklej je do panelu. Zobaczysz na żywo, ile aktualnych ogłoszeń pasuje i ile odrzuca każdy filtr. Ustaw cenę maksymalną jako kwotę, którą chcesz zapłacić łącznie.
4. Wybierz, gdzie mają trafiać powiadomienia. Najszybciej jest na telefon przez darmową aplikację ntfy: instalujesz ją, dodajesz nazwę z panelu i gotowe. Dla Discorda jest osobny poradnik: [bot Vinted na Discordzie](/guides/vinted-bot-discord/). Telegram działa przez własnego bota założonego w BotFather. Zanim pójdziesz dalej, kliknij "Send test" (wyślij test).
5. Zostaw go włączonego. Pierwsze sprawdzenie jest celowo ciche, żeby nie zasypało Cię ogłoszeniami, które już były. Od tej chwili każde nowe ogłoszenie przychodzi ze zdjęciami, pełną ceną, rozmiarem, stanem, oceną sprzedającego i przyciskami do kupna, wiadomości do sprzedającego i otwarcia ogłoszenia.

{{install}}

## Ograniczenia, zanim mu zaufasz

### Komputer musi być włączony

Powiadomienia wychodzą z komputera, na którym działa aplikacja. Uśpiony laptop nic nie wyśle. Na Windowsie ustaw uśpienie na "Nigdy", gdy komputer jest podłączony do prądu; instalator na Maca proponuje, że Mac nie będzie zasypiał podczas ładowania. Jeśli chcesz powiadomień przez całą dobę, sprawdzi się Raspberry Pi, NAS albo stary laptop podłączony do prądu. Zużywają mało energii.

### To nie jest natychmiastowe, i nic nie jest

Vinted dodaje nowe ogłoszenia do wyszukiwarki kilka minut po ich wystawieniu. Każde narzędzie, które czyta wyszukiwarkę, darmowe czy płatne, widzi je dopiero wtedy. vinted-sniper sprawdza co minutę. Częstsze sprawdzanie nie znajdzie niczego wcześniej, a sprawi, że Vinted zacznie spowalniać Twoje łącze. Jeśli ścigasz się z botami do automatycznego kupowania o tanie konsole, żaden bot do powiadomień nie wygra. Jeśli szukasz konkretnego rozmiaru, marki albo przedmiotu kolekcjonerskiego, minuta w zupełności wystarczy.

### Łącze ma znaczenie

Vinted częściej blokuje adresy z centrów danych i niektórych VPN niż domowe łącza. Uruchomienie bota w domu jest zwykle najpewniejsze. Jeśli Vinted Cię spowolni, aplikacja sama odczeka, a panel Ci o tym powie.

### Nie kupuje za Ciebie

Celowo. Automatyczne kupowanie wymaga zalogowanego konta, a tak właśnie konta trafiają pod ograniczenia. Regulamin Vinted zabrania automatycznego dostępu: bot, który się nie loguje, nie ma konta do stracenia, a ten, który kupuje za Ciebie, ma.

## Darmowy czy płatny?

Jeśli masz komputer włączony przez dużą część dnia, albo Raspberry Pi czy NAS, darmowa droga robi to samo co usługa powiadomień za 5 do 30 euro miesięcznie. Jeśli nie masz nic, co zostaje włączone, i nie chcesz niczego instalować, płatna usługa jest rozsądnym wyborem, bo działa na jej serwerach. Wybierz wtedy taką, która nie prosi o login do Vinted.
