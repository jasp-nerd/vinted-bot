---
title: "Vinted Bot kostenlos: Benachrichtigung bei neuen Artikeln ohne Abo"
description: "Vinted Bot kostenlos: neue Artikel deiner Suchen per Discord, Telegram oder aufs Handy. Open Source, ohne Abo, ohne Vinted-Login. Einrichtung und Grenzen."
slug: vinted-bot-kostenlos
key: free-bot
date: 2026-10-30
updated: 2026-10-30
keywords:
  - vinted bot kostenlos
  - vinted snipe bot kostenlos
  - vinted bot free
  - vinted bot discord
  - vinted bot github
  - vinted bot erstellen
faq:
  - q: "Gibt es einen kostenlosen Vinted Bot?"
    a: "Ja. vinted-bot ist kostenlos und Open Source (MIT-Lizenz), ohne Bezahlversion. Es beobachtet deine Vinted-Suchen und schickt neue Artikel an Discord, Telegram, ntfy auf dem Handy oder einen Webhook. Es läuft auf deinem eigenen Rechner, der dafür eingeschaltet bleiben muss."
  - q: "Braucht ein Vinted Bot meine Vinted-Zugangsdaten?"
    a: "Ein Benachrichtigungs-Bot nicht. Suchergebnisse kann jeder ohne Anmeldung lesen. Nur Tools, die für dich kaufen, Nachrichten schreiben oder Artikel neu einstellen, brauchen dein Konto, und genau die gefährden es."
  - q: "Kann ich mir einen Vinted Bot selbst erstellen?"
    a: "Du musst nichts programmieren. vinted-bot installierst du mit einem einzigen Befehl, danach richtest du alles im Browser ein: Vinted-Suchlink einfügen, Ziel wählen, Testnachricht schicken."
  - q: "Kann ein kostenloser Vinted Bot automatisch kaufen?"
    a: "Dieser nicht. Automatisches Kaufen braucht dein angemeldetes Konto, und daher kommen Kontosperren. vinted-bot legt stattdessen einen Kaufen-Button in jede Benachrichtigung, der Kauf bleibt bei dir."
---

Ja, einen Vinted Bot gibt es kostenlos. vinted-bot ist eine kostenlose Open-Source-App, die deine Vinted-Suchen beobachtet und jeden neuen Artikel an Discord, Telegram oder dein Handy schickt, mit dem Preis, den du wirklich zahlst. Sie läuft auf deinem eigenen Rechner statt auf fremden Servern. Deshalb kostet sie nichts, und sie fragt nie nach deinem Vinted-Login.

Hier steht, was mit "Vinted Bot" meistens gemeint ist, welche kostenlosen Wege es gibt, wie du in etwa zehn Minuten startest und welche Grenzen du kennen solltest.

## Was mit "Vinted Bot" gemeint ist

Unter dem Wort laufen sehr unterschiedliche Tools, und der Unterschied entscheidet über Preis und Risiko.

Ein Benachrichtigungs-Bot (auch Monitor oder Snipe Bot genannt) beobachtet eine Suche und meldet sich, sobald etwas Neues auftaucht. Kaufen tust du selbst. Das wollen die meisten, wenn die Benachrichtigungen der gespeicherten Suche bei Vinted nicht zuverlässig kommen.

Ein Autobuy-Bot meldet sich mit deinem Konto an und kauft, sobald ein Artikel passt. Das sind die teuren Tools, und sie brauchen dein Konto samt Zahlungsdaten.

Relist-, Like- und Follow-Bots sind für Verkäufer. Sie schieben Artikel nach oben oder sammeln Aufmerksamkeit, ebenfalls über dein angemeldetes Konto.

In diesem Ratgeber geht es um Benachrichtigungs-Bots.

## Die kostenlosen Möglichkeiten im Vergleich

### Die gespeicherte Suche von Vinted

Kostenlos und eingebaut. Du speicherst eine Suche, und Vinted soll dich über neue Treffer benachrichtigen. In der Praxis bekommen viele die Benachrichtigung spät oder gar nicht, und der Preisfilter ignoriert den Käuferschutz. Woran das liegt, steht in [Vinted Benachrichtigung funktioniert nicht](/guides/vinted-benachrichtigung-funktioniert-nicht/).

### Testphasen und Gratis-Stufen bezahlter Bots

Mehrere Telegram-Bots und Apps lassen dich eine Suche kostenlos testen und verlangen danach grob 5 bis 30 € im Monat (Stand Oktober 2026). Zum Ausprobieren gut, für den Alltag knapp.

### Kostenlose Discord-Server

Gemeinsame Kanäle, in denen Artikel aus beliebten Kategorien gepostet werden. Du siehst, was alle anderen im Server sehen, im selben Moment und ohne eigene Filter.

### Open-Source-Tools auf dem eigenen Rechner

Kostenlos und ohne Limit bei der Zahl der Suchen, aber ein Rechner muss eingeschaltet bleiben. vinted-bot gehört dazu. Der Schwerpunkt liegt auf einfacher Installation und darauf, dass es dir sagt, wenn es nicht mehr funktioniert. Das ist die häufigste Beschwerde über kostenlose Bots.

## Warum vinted-bot kostenlos ist

Es gibt bei uns keinen Server. Die App läuft auf deinem Laptop, PC, Raspberry Pi oder NAS, prüft deine Suchen über deine eigene Internetverbindung und verschickt die Benachrichtigungen von dort. Keine Serverkosten, also nichts zu berechnen. Der Code liegt unter MIT-Lizenz auf GitHub, jeder kann nachlesen, was er tut.

Was du bekommst:

- Benachrichtigungen per Discord, Telegram, ntfy (kostenlose Handy-App ohne Konto), RSS oder eigenem Webhook. E-Mail, Slack und Pushover gehen auch.
- Den Endpreis in jeder Nachricht, Käuferschutz inklusive, und Preisgrenzen, die mit diesem Endpreis rechnen. Der Preisfilter von Vinted ignoriert die Gebühr.
- Wörter, die im Titel stehen müssen, und Wörter, die rausfliegen, damit "defekt" oder "nur Karton" gar nicht erst ankommt.
- Verkäuferfilter: Mindestbewertung, Mindestanzahl an Bewertungen, Land des Verkäufers und ein Button zum Blockieren.
- Ein Deal-Hinweis, wenn ein Artikel deutlich unter dem üblichen Preis dieser Suche liegt.
- Eine Suche über mehrere Vinted-Länder, Ruhezeiten und ein Dashboard mit allen Funden.
- Für jede Suche einen Status in klaren Worten, damit du weißt, wenn Vinted sie bremst oder sie hängt.

## In fünf Schritten eingerichtet

1. Installieren. Unter Windows öffnest du PowerShell und fügst den Einzeiler von der Startseite ein, auf dem Mac oder unter Linux das Terminal und den anderen Befehl. Keine Adminrechte, kein Docker. Danach öffnet sich das Dashboard im Browser unter `http://localhost:8000`.
2. Such auf Vinted wie immer (Begriff, Kategorie, Größe, Marke, Zustand) und kopier die Adresse aus der Browserzeile, oder teil die Suche in der App und kopier den Link. Du kannst die Suche auch direkt im Dashboard bauen, mit den Kategorien und Marken von Vinted.
3. Füg den Link im Dashboard ein. Du siehst live, wie viele aktuelle Artikel passen und wie viele jeder Filter aussortiert. Den Höchstpreis gibst du als Endpreis an, den du zahlen willst.
4. Wähl das Ziel. Telegram und Discord schlägt die App als Erstes vor. Für Telegram gibt es eine eigene Anleitung: [Vinted Bot auf Telegram](/guides/vinted-bot-telegram/). Für Discord brauchst du einen Webhook-Link aus den Kanaleinstellungen (Kanal bearbeiten, Integrationen, Webhooks, Neuer Webhook). Unter "More options" (Weitere Optionen) gibt es außerdem die Handy-App ntfy, E-Mail und Webhooks. Drück danach "Send a test" (Test senden).
5. Laufen lassen. Die erste Prüfung ist absichtlich still, damit du nicht mit Artikeln überflutet wirst, die schon da waren. Ab dann kommt jeder neue Treffer als Nachricht mit Fotos, Endpreis, Größe, Zustand, Verkäuferbewertung und Buttons zum Kaufen, Schreiben und Öffnen.

{{install}}

## Die Grenzen, bevor du dich darauf verlässt

### Der Rechner muss an bleiben

Die Benachrichtigungen kommen von dem Gerät, auf dem die App läuft. Ein Laptop im Ruhezustand schickt nichts. Unter Windows stellst du den Energiesparmodus im Netzbetrieb auf "Nie", der Mac-Installer bietet an, den Mac wach zu halten, solange er am Strom hängt. Für Benachrichtigungen rund um die Uhr eignet sich ein Raspberry Pi, ein NAS oder ein alter Laptop am Netzteil, alles mit wenig Stromverbrauch.

### Sofort geht es nicht, bei niemandem

Vinted nimmt neue Artikel erst einige Minuten nach dem Hochladen in die Suche auf. Jedes Tool, das die Suche liest, ob bezahlt oder kostenlos, sieht sie erst dann. vinted-bot prüft standardmäßig jede Minute. Häufiger zu prüfen bringt nichts und sorgt nur dafür, dass Vinted deine Verbindung bremst. Gegen Autobuy-Bots bei günstigen Konsolen gewinnt kein Benachrichtigungs-Tool. Wer eine bestimmte Größe, Marke oder ein Sammlerstück sucht, ist mit einer Minute gut bedient.

### Deine Verbindung zählt

Vinted prüft Rechenzentrums- und VPN-Adressen deutlich strenger als normale Anschlüsse zu Hause. Daheim läuft es meist am zuverlässigsten. Bremst Vinted dich doch einmal aus, wartet die App von selbst und das Dashboard zeigt es an.

### Es kauft nicht für dich

Das ist Absicht. Automatisches Kaufen braucht dein angemeldetes Konto, und genau so werden Konten gesperrt. Mehr dazu in [Ist ein Vinted Bot erlaubt?](/guides/vinted-bot-erlaubt/).

## Kostenlos oder bezahlt?

Hast du einen Rechner, der die meiste Zeit läuft, oder einen Pi oder ein NAS, dann macht die kostenlose Lösung dasselbe wie ein Benachrichtigungsdienst für 5 bis 30 € im Monat. Hast du nichts, was eingeschaltet bleibt, und willst nichts installieren, ist ein bezahlter Dienst eine faire Wahl, weil er auf dessen Servern läuft. Achte dann darauf, dass er keinen Vinted-Login verlangt. Wie du ganz ohne Tool und mit Bordmitteln an Benachrichtigungen kommst, steht in [Vinted Benachrichtigung bei neuen Artikeln](/guides/vinted-benachrichtigung-neue-artikel/).
