---
title: "Gratis Vinted bot: melding bij nieuwe items zonder abonnement"
description: "Gratis Vinted bot: krijg nieuwe items uit je zoekopdrachten op Discord, Telegram of je telefoon. Open source, geen abonnement, geen Vinted-login."
slug: vinted-bot-gratis
key: free-bot
date: 2026-10-30
updated: 2026-10-30
keywords:
  - vinted bot gratis
  - vinted bot free
  - vinted bot discord
  - vinted bot monitor
  - vinted bot app
  - vinted bot github
faq:
  - q: "Bestaat er een gratis Vinted bot?"
    a: "Ja. vinted-bot is gratis en open source (MIT-licentie), zonder betaalde versie. Het houdt je Vinted-zoekopdrachten in de gaten en stuurt nieuwe items naar Discord, Telegram, ntfy op je telefoon of een webhook. Het draait op je eigen computer, die daarvoor aan moet blijven."
  - q: "Heeft een Vinted bot mijn inloggegevens nodig?"
    a: "Een bot die alleen meldingen stuurt niet. Zoekresultaten kan iedereen zonder inloggen bekijken. Alleen tools die voor je kopen, berichten sturen of items opnieuw plaatsen hebben je account nodig, en juist die brengen het in gevaar."
  - q: "Is er een Vinted bot app?"
    a: "Er zijn betaalde apps, meestal een paar euro per maand. Gratis kan ook: laat vinted-bot op een computer draaien en ontvang de meldingen in de gratis app ntfy op je telefoon, zonder account."
  - q: "Kan een gratis Vinted bot automatisch kopen?"
    a: "Deze niet. Automatisch kopen kan alleen met je ingelogde account, en daar komen accountblokkades vandaan. vinted-bot zet in elke melding een Kopen-knop, zodat jij zelf koopt."
---

Ja, een Vinted bot kan gratis. vinted-bot is een gratis open-source app die je Vinted-zoekopdrachten in de gaten houdt en elk nieuw item naar Discord, Telegram of je telefoon stuurt, met de prijs die je echt betaalt. Het draait op je eigen computer in plaats van op de server van een ander bedrijf. Daarom kost het niets, en het vraagt nooit om je Vinted-login.

Hieronder: wat mensen bedoelen met "Vinted bot", welke gratis opties er zijn, hoe je in een minuut of tien begint, en de beperkingen die je moet kennen.

## Wat een "Vinted bot" meestal is

Onder dat woord vallen heel verschillende tools, en het verschil bepaalt zowel de prijs als het risico.

Een meldingsbot (ook wel monitor genoemd) houdt een zoekopdracht in de gaten en laat het weten zodra er iets nieuws verschijnt. Kopen doe je zelf. Dit is wat de meeste mensen zoeken als de meldingen van een opgeslagen zoekopdracht in Vinted niet betrouwbaar binnenkomen.

Een autobuy-bot logt in als jou en rekent af zodra een item past. Dat zijn de dure tools, en ze hebben je account en betaalgegevens nodig.

Relist-, like- en volgbots zijn voor verkopers. Ze zetten items opnieuw bovenaan of verzamelen aandacht, ook via je ingelogde account.

Deze gids gaat over meldingsbots.

## De gratis opties eerlijk vergeleken

### Opgeslagen zoekopdrachten in Vinted

Gratis en ingebouwd. Je slaat een zoekopdracht op en Vinted hoort je te laten weten wanneer er iets nieuws bij komt. In de praktijk krijgen veel mensen die melding laat of helemaal niet, en het prijsfilter negeert de kopersbescherming. Waarom dat zo is, lees je in [Vinted meldingen werken niet](/guides/vinted-meldingen-werken-niet/).

### Proefperiodes en gratis versies van betaalde bots

Verschillende Telegram-bots en apps laten je één zoekopdracht gratis proberen en vragen daarna ongeveer €5 tot €30 per maand (stand oktober 2026). Prima om te testen, beperkt voor echt gebruik.

### Gratis Discord-servers

Gedeelde kanalen die items uit populaire categorieën posten. Je ziet wat iedereen in de server ziet, op hetzelfde moment, zonder eigen filters.

### Open-source tools op je eigen computer

Gratis en zonder limiet op het aantal zoekopdrachten, maar er moet een computer aan blijven. vinted-bot is er zo een. Het is gemaakt om makkelijk te installeren en om te laten weten wanneer het niet meer werkt, de meest gehoorde klacht over gratis bots.

## Waarom vinted-bot gratis is

Er is geen server aan onze kant. De app draait op je laptop, pc, Raspberry Pi of NAS, controleert je zoekopdrachten via je eigen internetverbinding en stuurt de meldingen van daaruit. Geen serverkosten, dus niets te rekenen. De code staat onder de MIT-licentie op GitHub, iedereen kan nalezen wat hij doet.

Wat je krijgt:

- Meldingen via Discord, Telegram, ntfy (een gratis telefoonapp zonder account), RSS of je eigen webhook. E-mail, Slack of Pushover werken via een optionele uitbreiding.
- De totaalprijs in elke melding, kopersbescherming inbegrepen, en prijsgrenzen die met dat totaal rekenen. Het prijsfilter van Vinted negeert die toeslag.
- Woorden die in de titel moeten staan en woorden om over te slaan, zodat "defect" of "alleen doos" je nooit bereikt.
- Verkopersfilters: minimale beoordeling, minimaal aantal reviews, land van de verkoper en een knop om iemand te blokkeren.
- Een dealbadge als een item duidelijk onder de gebruikelijke prijs van die zoekopdracht zit.
- Eén zoekopdracht over meerdere Vinted-landen, stille uren en een dashboard met al je vondsten.
- Voor elke zoekopdracht een status in gewone taal, zodat je weet wanneer Vinted hem afremt of wanneer hij vastloopt.

## In vijf stappen aan de slag

1. Installeer het. Open op Windows PowerShell en plak de opdracht van de homepage, op een Mac of Linux de Terminal met de andere opdracht. Geen beheerdersrechten, geen Docker. Daarna opent het dashboard in je browser op `http://localhost:8000`.
2. Zoek op Vinted zoals je altijd doet (woorden, categorie, maat, merk, staat) en kopieer het adres uit de adresbalk, of deel de zoekopdracht vanuit de app en kopieer de link. Je kunt de zoekopdracht ook in het dashboard bouwen, met de categorieën en merken van Vinted.
3. Plak de link in het dashboard. Je ziet direct hoeveel huidige items passen en hoeveel elk filter eruit haalt. Vul de maximumprijs in als het totaalbedrag dat je wilt betalen.
4. Kies waar de meldingen heen gaan. Het snelst is een melding op je telefoon met de gratis app ntfy: installeren, de onderwerpnaam uit het dashboard toevoegen, klaar. Voor Discord heb je een webhooklink nodig uit de kanaalinstellingen (Kanaal bewerken, Integraties, Webhooks, Nieuwe webhook). Telegram werkt met een eigen bot die je bij BotFather aanmaakt. Druk daarna op "Send test" (test versturen).
5. Laat het draaien. De eerste controle is bewust stil, zodat je niet overspoeld wordt met items die er al stonden. Daarna komt elk nieuw item binnen als bericht met foto's, totaalprijs, maat, staat, beoordeling van de verkoper en knoppen om te kopen, de verkoper te berichten of het item te openen.

{{install}}

## De beperkingen, voordat je erop rekent

### De computer moet aan blijven

De meldingen komen van het apparaat waarop de app draait. Een laptop in slaapstand stuurt niets. Zet op Windows de slaapstand op "Nooit" als hij aan de stroom hangt; de Mac-installatie biedt aan om de Mac wakker te houden zolang hij is aangesloten. Voor meldingen dag en nacht werkt een Raspberry Pi, een NAS of een oude laptop aan de oplader prima, en dat kost weinig stroom.

### Direct kan niet, bij niemand

Vinted zet nieuwe items pas een paar minuten na het uploaden in de zoekresultaten. Elke tool die de zoekresultaten leest, betaald of gratis, ziet ze pas dan. vinted-bot controleert standaard elke minuut. Vaker controleren levert niets eerder op en zorgt er alleen voor dat Vinted je verbinding afremt. Tegen autobuy-bots die op goedkope consoles jagen wint geen meldingstool. Zoek je een bepaalde maat, een merk of een verzamelobject, dan is een minuut ruim voldoende.

### Je verbinding telt mee

Vinted controleert adressen van datacenters en VPN's veel strenger dan gewone thuisverbindingen. Thuis draait het meestal het betrouwbaarst. Remt Vinted je toch af, dan wacht de app vanzelf en zegt het dashboard dat.

### Het koopt niet voor je

Dat is bewust. Automatisch kopen vraagt om je ingelogde account, en zo raken accounts geblokkeerd. Meer daarover in [Is een Vinted bot toegestaan?](/guides/vinted-bot-toegestaan/).

## Gratis of betaald?

Heb je een computer die het grootste deel van de dag aan staat, of een Pi of NAS, dan doet de gratis route hetzelfde als een meldingsdienst van €5 tot €30 per maand. Heb je niets dat aan blijft en wil je niets installeren, dan is een betaalde dienst een eerlijke keuze, want die draait op hun servers. Kies dan wel een dienst die niet om je Vinted-login vraagt. Hoe je meldingen instelt met wat Vinted zelf biedt, lees je in [Vinted melding bij een nieuw artikel](/guides/vinted-melding-nieuw-artikel/).
