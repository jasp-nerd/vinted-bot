---
title: "Bot Vinted na Discordzie: webhook w 2 minuty, za darmo"
description: "Darmowy bot Vinted na Discordzie: załóż serwer, skopiuj URL webhooka na komputerze lub telefonie i odbieraj nowe ogłoszenia. Bez abonamentu i logowania."
slug: vinted-bot-discord
key: discord
date: 2026-10-30
updated: 2026-10-30
keywords:
  - vinted bot discord
  - vinted bot discord polska
  - bot vinted discord
  - discord webhook url
  - vinted alert discord
  - vinted monitor discord
faq:
  - q: "Jak zdobyć URL webhooka na Discordzie?"
    a: "Na serwerze, na którym możesz zarządzać kanałami, otwórz ustawienia kanału (Edytuj kanał), wejdź w Integracje, potem Webhooki, Nowy webhook i kliknij Kopiuj URL webhooka. Na telefonie przytrzymaj nazwę kanału, żeby dojść do edycji kanału."
  - q: "Czy da się utworzyć webhook Discorda na telefonie?"
    a: "Tak. Przytrzymaj nazwę kanału, wybierz edycję kanału, Integracje, Webhooki, Nowy webhook, potem dotknij nowego webhooka i skopiuj jego URL."
  - q: "Czy muszę dodawać bota na swój serwer Discord, żeby dostawać ogłoszenia z Vinted?"
    a: "Nie, jeśli używasz webhooka. Webhook pozwala tylko pisać na jednym kanale, więc nie ma czego zapraszać i nic nie ma dostępu do reszty serwera."
  - q: "Dlaczego nie mogę utworzyć webhooka na serwerze Discord?"
    a: "Potrzebujesz uprawnienia do zarządzania webhookami, co na cudzym serwerze zwykle oznacza bycie administratorem. Własny serwer jest darmowy i zakładasz go w niecałą minutę."
---

Żeby dostawać ogłoszenia z Vinted na Discordzie, potrzebujesz URL webhooka: prywatnego linku, przez który aplikacja może pisać na jednym kanale. Załóż serwer (za darmo), otwórz ustawienia kanału, wejdź w Integracje, potem Webhooki, Nowy webhook, i skopiuj URL. Wklej go do bota Vinted i wyślij test. Z vinted-sniper całość jest darmowa i zajmuje około dwóch minut.

## Dlaczego webhook, a nie bot na serwerze

Webhook to drzwi w jedną stronę do jednego kanału. Kto ma URL, może tam wysyłać wiadomości i nic więcej: nie czyta Twoich wiadomości, nie widzi innych kanałów, nie wchodzi na kanały głosowe. Niczego nie zapraszasz na serwer.

To najprostszy i najbezpieczniejszy sposób na powiadomienia. Jedna rzecz do zapamiętania: każdy, kto zna URL, może pisać na tym kanale, więc traktuj go jak hasło. Nie wklejaj go na czatach, zrzutach ekranu ani do asystentów AI.

## Krok 1: załóż własny serwer

Webhooki możesz tworzyć tylko tam, gdzie wolno Ci zarządzać kanałem. Na serwerze znajomego musiałby on dać Ci uprawnienia administratora, więc łatwiej mieć własny.

Na komputerze:

1. W Discordzie kliknij plus na dole listy serwerów po lewej.
2. Wybierz opcję utworzenia własnego serwera, a potem serwer dla siebie i znajomych.
3. Nadaj nazwę, na przykład "Znaleziska z Vinted", i utwórz serwer.

Na telefonie wygląda to tak samo: plus na liście serwerów, własny serwer, nazwa, utwórz.

Nowy serwer ma kanał #ogólny. Możesz go użyć albo założyć osobny kanał na każde wyszukiwanie, na przykład #kurtki i #pokemon, żeby wyciszać je osobno.

## Krok 2: utwórz webhook i skopiuj URL

### Na komputerze

1. Najedź na kanał, na który mają trafiać ogłoszenia, i kliknij ikonę zębatki obok nazwy (Edytuj kanał).
2. W menu po lewej kliknij Integracje.
3. Kliknij Webhooki, potem Nowy webhook. Discord utworzy go z losową nazwą.
4. Kliknij webhook, żeby go rozwinąć. Możesz zmienić nazwę, na przykład na "Ogłoszenia Vinted".
5. Kliknij Kopiuj URL webhooka.

### Na telefonie

1. Przytrzymaj nazwę kanału i wybierz edycję kanału.
2. Dotknij Integracje, potem Webhooki, potem Nowy webhook.
3. Dotknij nowego webhooka, żeby go otworzyć, i skopiuj jego URL.

URL zaczyna się od `https://discord.com/api/webhooks/`, a dalej są dwa długie kody. Jeśli skopiowany tekst zaczyna się inaczej, to skopiowałeś coś innego, najczęściej link do kanału.

Mała pułapka: Discord nie przyjmuje nazw webhooków zawierających słowo "discord". Jeśli zmiana nazwy się nie udaje, to dlatego.

## Krok 3: wklej go do vinted-sniper

vinted-sniper to darmowa aplikacja open source, która obserwuje Twoje wyszukiwania na Vinted i wysyła nowe ogłoszenia na przykład na Discorda. Nie wymaga abonamentu ani logowania do Vinted. Po instalacji panel otwiera się pod adresem `http://localhost:8000`.

1. Otwórz stronę "Alerts" (miejsca, do których trafiają powiadomienia) i dodaj nowe miejsce.
2. Wybierz Discorda i wklej URL webhooka.
3. Kliknij "Send test" (wyślij test). Po kilku sekundach na kanale powinna pojawić się wiadomość testowa.

Potem dodaj wyszukiwanie: wklej link z Vinted albo zbuduj je w panelu, ustaw limit ceny i słowa do pominięcia, i wybierz, na które miejsca ma wysyłać. Wyszukiwanie, którego nigdzie nie skierujesz, trafia do wszystkich dodanych miejsc.

{{install}}

## Jak wygląda ogłoszenie z Vinted na Discordzie

Każde nowe ogłoszenie przychodzi jako karta na kanale:

- Galeria zdjęć z ogłoszenia.
- Łączna cena, którą zapłacisz, z ochroną kupujących, a pod nią cena wystawienia.
- Oznaczenie okazji, gdy cena jest wyraźnie niższa niż zwykle w tym wyszukiwaniu.
- Rozmiar, stan, marka oraz ocena sprzedającego z liczbą opinii.
- Przyciski do kupna, wiadomości do sprzedającego i otwarcia na Vinted.

Jest też styl kompaktowy, jeśli wolisz widzieć więcej ogłoszeń na ekranie. Możesz też ustawić oznaczanie roli tylko przy najlepszych okazjach, żeby telefon głośno dzwonił tylko wtedy.

## Kilka kanałów, kilka wyszukiwań

Każde wyszukiwanie może wysyłać na inne miejsca. Jeśli utworzysz osobny webhook dla #kurtki i dla #pokemon, a potem dodasz oba w panelu, każde wyszukiwanie przypiszesz do jego kanału. Gdy dwa wyszukiwania znajdą to samo ogłoszenie, każdy kanał dostanie je tylko raz. Możesz też ustawić godziny ciszy: nocne ogłoszenia poczekają do rana, przyjdą bez dźwięku albo zostaną pominięte.

## Krok 4: powiadomienia na telefonie

Ustawienia powiadomień Discorda to najczęstsza przyczyna sytuacji "nic nie dostałem", więc warto poświęcić im dwie minuty.

1. W aplikacji Discord na telefonie przytrzymaj ikonę serwera, wejdź w powiadomienia i ustaw wszystkie wiadomości.
2. Jeśli masz osobny kanał na każde wyszukiwanie, możesz przytrzymać kanał i ustawić mu własny poziom powiadomień.
3. Na iPhonie zezwól Discordowi na powiadomienia w Ustawieniach i sprawdź, czy tryby skupienia go nie blokują.
4. Na Androidzie zezwól Discordowi na powiadomienia i ustaw zużycie baterii na bez ograniczeń.
5. Gdy jesteś jednocześnie aktywny na komputerze, Discord może wstrzymywać powiadomienia na telefon. W ustawieniach powiadomień Discorda zmienisz, po jakim czasie bezczynności wysyła je na telefon.

## Gdy wiadomości przestają przychodzić

### Webhook został usunięty

Jeśli ktoś usunie webhook albo kanał, Discord informuje vinted-sniper, że już nie istnieje, a aplikacja wyłącza to miejsce. To celowe: ciągłe wysyłanie do martwego webhooka sprawia, że sam Discord zaczyna ograniczać Twój adres. Utwórz nowy webhook i dodaj go ponownie.

### URL wyciekł

Jeśli URL trafił gdzieś publicznie, usuń ten webhook w Discordzie (edycja kanału, Integracje, Webhooki) i utwórz nowy. Stary URL od razu przestaje działać.

### Wyszukiwanie działa, ale nic nie przychodzi

Sprawdź limit ceny. Zawiera on ochronę kupujących, więc limit 80 zł odrzuci ogłoszenie za 77 zł, które z opłatą kosztuje więcej. Panel prowadzi listę pominiętych ogłoszeń z powodem, co odpowiada na większość pytań "dlaczego tego nie dostałem?". Pamiętaj też, że Vinted dodaje nowe ogłoszenia do wyszukiwarki kilka minut po wystawieniu, więc żadne powiadomienie nie jest natychmiastowe.

## Wolisz coś innego niż Discord?

Jeśli nie używasz Discorda, vinted-sniper wysyła też na Telegrama (przez własnego bota z BotFather) albo jako zwykłe powiadomienie na telefon przez darmową aplikację ntfy, bez zakładania konta. Pełną konfigurację opisuje poradnik o [darmowym bocie Vinted](/guides/darmowy-bot-vinted/), a ustawienia samego Vinted poradnik o [powiadomieniach Vinted](/guides/powiadomienia-vinted/).
