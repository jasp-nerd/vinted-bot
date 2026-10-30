---
title: "Vinted Bot auf Telegram: kostenlos einrichten, ohne Discord"
description: "Vinted Bot für Telegram auf Deutsch: eigenen Bot mit BotFather anlegen, Chat oder Gruppe verbinden und neue Artikel mit Foto und Endpreis bekommen."
slug: vinted-bot-telegram
key: telegram
date: 2026-10-30
updated: 2026-10-30
keywords:
  - vinted bot telegram
  - vinted bot telegram deutsch
  - vinted snipe bot telegram
  - vinted tracker bot telegram
  - vinted monitor bot telegram
  - telegram botfather token
faq:
  - q: "Gibt es einen kostenlosen Vinted Bot für Telegram?"
    a: "Ja. Mit vinted-bot legst du in etwa drei Minuten deinen eigenen privaten Telegram-Bot an, der dir neue Artikel aus deinen Vinted-Suchen schickt. Kostenlos, Open Source und ohne Begrenzung bei der Zahl der Suchen."
  - q: "Wie bekomme ich einen Telegram Bot Token?"
    a: "In Telegram nach BotFather suchen (der echte hat einen blauen Haken), /newbot senden, einen Anzeigenamen und einen Benutzernamen wählen, der auf bot endet. BotFather antwortet mit dem Token: Ziffern, ein Doppelpunkt, dann eine lange Zeichenfolge. Tipp ihn an, um ihn zu kopieren, und füg ihn im Dashboard von vinted-bot ein."
  - q: "Brauche ich meine Telegram Chat-ID?"
    a: "Nicht bei vinted-bot. Das Dashboard erzeugt einen Einmal-Code, du schickst ihn an deinen Bot, und die App findet den Chat selbst. Das klappt auch in Gruppen und Themen."
  - q: "Warum schickt mir mein Telegram-Bot nichts?"
    a: "Ein Telegram-Bot darf dir nicht als Erster schreiben, du musst den Chat starten. Prüf, dass das Dashboard nach Check and save den Namen deines Bots angezeigt hat, dass du im Chat mit deinem Bot auf Starten gedrückt hast und dass der Bot bei Gruppen Mitglied der Gruppe ist."
---

Vinted-Benachrichtigungen per Telegram bekommst du kostenlos und ohne Discord. Du legst bei Telegrams BotFather deinen eigenen privaten Bot an (rund drei Minuten), fügst seinen Token im Dashboard von vinted-bot ein und verbindest deinen Chat mit einem Einmal-Code. Danach landet jeder neue Artikel aus deinen Vinted-Suchen in Telegram, mit Foto, Endpreis, Größe, Zustand und Buttons zum Kaufen und Öffnen.

In Deutschland wird nach "Vinted Telegram" ungefähr so oft gesucht wie nach "Vinted Bot", und viele nutzen Discord schlicht nicht. Hier die komplette Einrichtung.

## Warum ein eigener Bot

Gemeinsame Telegram-Bots für Vinted laufen als ein Bot für alle Nutzer und verlangen Geld für mehr Suchen. Mit vinted-bot legst du einen Bot an, den nur du nutzt. Er ist kostenlos, gehört zu deinem Telegram-Konto, und nur die App, die du selbst betreibst, kann über ihn schreiben.

"Bot" ist hier einfach Telegrams Name für ein Konto, über das Programme Nachrichten verschicken. Einen anzulegen kostet nichts und braucht keine Programmierkenntnisse.

## Schritt 1: Bot bei BotFather anlegen

Dieselben Schritte zeigt dir auch das Dashboard, sobald du dort Telegram wählst. Du kannst also auch direkt dort mitlesen.

1. Öffne Telegram am Handy oder Rechner und such nach @BotFather. Nimm den mit dem blauen Haken, es gibt Nachahmer.
2. Tipp auf Starten und schick `/newbot`.
3. BotFather fragt nach einem Namen. Jeder Name geht. Den siehst du oben im Chat, etwa "Meine Vinted Funde".
4. Dann fragt er nach einem Benutzernamen. Der muss einmalig sein und auf "bot" enden, etwa `lena_vinted_funde_bot`. Ist er vergeben, häng ein paar Ziffern an.
5. BotFather antwortet mit "Done! Congratulations". Dein Token steht unter "Use this token to access the HTTP API". Er sieht aus wie `7123456789:AAH...` (Ziffern, ein Doppelpunkt, dann eine lange Folge aus Buchstaben und Ziffern). Tipp ihn einmal an, dann ist er kopiert.

Behalt den Token für dich. Wer ihn hat, kann als dein Bot Nachrichten schicken. Füg ihn nicht in Chats, Screenshots oder KI-Assistenten ein. Ist er doch rausgegangen, schick `/revoke` an BotFather und hol dir einen neuen.

{{install}}

## Schritt 2: Token im Dashboard einfügen

1. Wähl im Dashboard Telegram. Bei der ersten Einrichtung passiert das im Schritt "Where should we tell you?" (Wo sollen wir dir Bescheid geben?), später auf der Seite "Alerts" (Benachrichtigungen) über "Add a place" (Ziel hinzufügen).
2. Füg den Token ins Feld "Bot token" ein und drück "Check and save" (Prüfen und speichern).
3. vinted-bot prüft den Token sofort bei Telegram und zeigt den @Namen deines Bots. Ist der Token falsch oder nur halb kopiert, bekommst du stattdessen eine klare Fehlermeldung. Kopier ihn dann noch einmal bei BotFather und füg ihn neu ein.

Keine Einstellungsdatei, kein Neustart. (Auf einem Server oder mit Docker kannst du weiterhin `VINTED_BOT_TELEGRAM_BOT_TOKEN` in der Umgebung setzen, dieser Wert hat dann Vorrang.)

## Schritt 3: Chat verbinden

Ein Telegram-Bot darf dir nicht als Erster schreiben. Das ist eine Telegram-Regel gegen Spam, und deshalb verlangen die meisten Telegram-Anleitungen, dass du eine "Chat-ID" heraussuchst. vinted-bot spart dir das. Sobald der Token gespeichert ist, geht es auf demselben Bildschirm weiter:

1. Drück "Connect my chat" (Chat verbinden). Die App erzeugt einen Einmal-Code.
2. Drück "Open Telegram". Der Chat mit deinem Bot öffnet sich mit dem fertigen Code. Tipp auf Starten.
3. Das Dashboard zeigt "Connected". Drück "Send a test" (Test senden), und eine Testnachricht kommt in Telegram an.

Der Link läuft nach dreißig Minuten ab. Wenn du zwischendurch abgelenkt warst, drück einfach noch einmal auf "Connect my chat".

### In eine Gruppe oder ein Thema

Willst du die Funde mit Partner oder Partnerin oder einem Reselling-Kumpel teilen, nimm eine Gruppe:

1. Leg eine Telegram-Gruppe an und füg deinen Bot wie ein normales Mitglied hinzu.
2. Öffne den Verbindungslink aus der Gruppe heraus und tipp dort auf Starten.

Nutzt die Gruppe Themen, öffne den Link im gewünschten Thema, dann landen die Nachrichten nur dort. Praktisch für ein Thema pro Suche.

## So sehen die Nachrichten aus

Jeder neue Artikel kommt als Fotonachricht mit:

- dem Endpreis zuerst, Käuferschutz inklusive, und einem Deal-Hinweis, wenn er deutlich unter dem üblichen Preis dieser Suche liegt,
- Titel, Größe, Zustand, Marke und der Bewertung des Verkäufers,
- der Vinted-Länderseite und dem Zeitpunkt, an dem er gefunden wurde,
- einem grünen Kaufen-Button und einem Button "Open on Vinted".

Du kannst auf eine Galerie mit mehreren Fotos pro Artikel umstellen oder ein Ziel lautlos schalten und nur echte Schnäppchen mit Ton schicken lassen.

Einiges geht direkt aus dem Chat. `/list` zeigt deine Suchen und wie es ihnen geht, `/pause 3` und `/resume 3` halten Suche 3 an und starten sie wieder, und `/add` mit einem Vinted-Suchlink dahinter beobachtet eine neue Suche. Einfach einen Vinted-Link einfügen geht auch: Ein Suchlink legt die Suche an, ein Artikellink beobachtet dessen Preis, und ein Profillink folgt den neuen Artikeln dieses Mitglieds.

## Dann eine Suche anlegen

Füg im Dashboard einen Vinted-Suchlink ein (aus dem Browser oder über Teilen in der App) oder bau die Suche mit den Kategorien, Marken und Größen von Vinted. Setz den Höchstpreis als Endpreis, den du zahlst, und Wörter, die rausfliegen sollen, etwa "defekt" oder "nur Karton". Die erste Prüfung bleibt still, du hörst also nur von Artikeln, die ab jetzt erscheinen.

## Wenn es nicht klappt

### Der Chat verbindet sich nie

Die App muss laufen, wenn du in Telegram auf Starten tippst, und der Link darf nicht älter als dreißig Minuten sein. Bei einer Gruppe den Bot hinzufügen, bevor du den Link öffnest.

### Es lief und hat aufgehört

Hast du den Bot blockiert oder aus der Gruppe entfernt, meldet Telegram vinted-bot, dass der Chat weg ist, und die App schaltet dieses Ziel ab, statt es immer wieder zu versuchen. Verbinde den Chat auf der Seite "Alerts" neu.

### Die Suche läuft, aber nichts kommt an

Meist ist es die Preisgrenze. Sie enthält den Käuferschutz, ein Artikel für 19 € kostet also 20,65 € und fällt bei einer Grenze von 20 € heraus. Die Liste der übersprungenen Artikel im Dashboard nennt bei jedem den Grund.

### Zu viele Nachrichten

Mach die Suche enger, ergänz Wörter zum Ausschließen oder nutz den Deal-Filter, damit nur Artikel deutlich unter dem üblichen Preis durchkommen.

## Telegram oder Discord?

Telegram passt, wenn du es ohnehin nutzt und Funde weiterleiten oder in einer Gruppe teilen willst. Discord geht noch schneller, weil der Token-Schritt entfällt: In den Kanaleinstellungen unter Integrationen, Webhooks einen neuen Webhook anlegen und den Link kopieren. Diese beiden schlägt die App als Erstes vor. Unter "More options" (Weitere Optionen) findest du außerdem die Handy-App ntfy, E-Mail und Webhooks. Die ganze Einrichtung steht in [Vinted Bot kostenlos](/guides/vinted-bot-kostenlos/).
