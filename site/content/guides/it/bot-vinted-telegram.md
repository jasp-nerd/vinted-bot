---
title: "Bot Vinted Telegram gratis: notifiche dei nuovi articoli"
description: "Bot Vinted Telegram gratis e open source: crea il tuo bot con BotFather, collega la chat e ricevi i nuovi articoli delle tue ricerche. Senza abbonamento."
slug: bot-vinted-telegram
key: telegram
date: 2026-10-30
updated: 2026-10-30
keywords:
  - vinted bot telegram
  - vinted bot telegram italia
  - bot vinted gratis telegram
  - bot vinted telegram gratuito
  - vinted tracker bot telegram
  - notifiche vinted telegram
faq:
  - q: "Esiste un bot Vinted su Telegram gratis?"
    a: "Sì. Con vinted-sniper crei il tuo bot Telegram privato in circa tre minuti e ricevi i nuovi annunci delle tue ricerche Vinted. È gratuito e open source, senza abbonamento e senza limite di ricerche."
  - q: "Come ottengo il token di un bot Telegram?"
    a: "Apri Telegram, cerca BotFather (quello ufficiale ha la spunta blu), invia /newbot, scegli un nome e uno username che finisce con bot. BotFather risponde con il token: dei numeri, i due punti e un lungo codice."
  - q: "Mi serve il chat ID di Telegram?"
    a: "No. La dashboard di vinted-sniper ti dà un codice monouso, lo mandi al tuo bot e l'app trova la chat da sola. Funziona anche con i gruppi e con i topic dei gruppi forum."
  - q: "Il bot Vinted per Telegram mi chiede il login di Vinted?"
    a: "No. vinted-sniper legge gli annunci pubblici come un visitatore non loggato e non tocca mai il tuo account Vinted. Gli acquisti li fai tu, con il tuo account, dal pulsante nell'avviso."
---

Puoi ricevere gli annunci nuovi di Vinted su Telegram gratis. Crea il tuo bot privato con BotFather (circa tre minuti), dai il suo token a vinted-sniper e collega la chat con un codice monouso. Da quel momento ogni nuovo articolo delle tue ricerche Vinted arriva su Telegram con la foto, il prezzo totale, la taglia, le condizioni e i pulsanti per comprare o aprire l'annuncio.

In Italia Telegram è il modo più diffuso per ricevere avvisi da Vinted, più di Discord. Ecco come configurarlo dall'inizio alla fine.

## Perché un bot tutto tuo

Molti bot Vinted su Telegram sono servizi condivisi: un solo bot per tutti gli utenti, una ricerca gratis e poi un abbonamento, di solito da 5 a 30 euro al mese (a ottobre 2026). Con vinted-sniper crei un bot che usi solo tu. Non costa niente, vive nel tuo account Telegram e solo l'app che fai girare tu può scrivere tramite lui.

"Bot", qui, è solo il nome che Telegram dà a un account da cui un'app può inviare messaggi. Crearlo è gratis e non serve saper programmare.

vinted-sniper è un'app gratuita e open source (licenza MIT) che gira sul tuo computer, su un Raspberry Pi o su un NAS. Controlla le tue ricerche Vinted ogni minuto e non chiede mai il login di Vinted.

## Passo 1: crea il bot con BotFather

1. Apri Telegram sul telefono o sul computer e cerca BotFather. Scegli quello con la spunta blu: esistono delle copie.
2. Tocca Avvia (Start), poi invia `/newbot`.
3. BotFather ti chiede un nome. È quello che vedrai in cima alla chat, per esempio "I miei avvisi Vinted".
4. Poi ti chiede uno username. Deve essere unico e finire con "bot", per esempio `giulia_vinted_avvisi_bot`. Se è già preso, provane un altro.
5. BotFather risponde con un messaggio che contiene il token. Ha questa forma: `7123456789:AAH...` (dei numeri, i due punti, poi una lunga serie di lettere e numeri).

Tieni il token per te. Chi lo possiede può mandare messaggi a nome del tuo bot. Non incollarlo in chat, negli screenshot o negli assistenti AI. Se finisce in giro, invia `/revoke` a BotFather e ne ottieni uno nuovo.

## Passo 2: dai il token a vinted-sniper

Per ora il token va in un piccolo file di impostazioni sul computer dove gira vinted-sniper, non nella dashboard.

1. Apri la cartella dei dati di vinted-sniper:
   - Windows: `%LOCALAPPDATA%\vinted-sniper` (incollalo nella barra degli indirizzi di Esplora file)
   - Mac: `~/Library/Application Support/vinted-sniper` (nel Finder: Vai, Vai alla cartella)
   - Linux o Raspberry Pi: `~/.local/share/vinted-sniper`
   - Docker: la cartella con il tuo `docker-compose.yml`
2. Crea lì un file di testo semplice chiamato `.env` (o aprilo se esiste già).
3. Aggiungi questa riga, con il tuo token dopo l'uguale:

```
VINTED_SNIPER_TELEGRAM_BOT_TOKEN=7123456789:AAH-il-tuo-token
```

4. Salva e riavvia vinted-sniper: esegui di nuovo il comando di installazione, oppure `docker compose up -d` con Docker.

Se la dashboard dice ancora che il token manca, controlla che il file si chiami esattamente `.env` (Windows a volte aggiunge `.txt`) e che non ci siano spazi intorno all'uguale.

{{install}}

## Passo 3: collega la tua chat

Un bot Telegram non può scriverti per primo. È una regola di Telegram contro lo spam, ed è il motivo per cui quasi tutte le guide ti fanno cercare il "chat ID". Con vinted-sniper non serve:

1. Nella dashboard apri la pagina "Alerts" (dove scegli dove arrivano gli avvisi) e aggiungi una nuova destinazione. Scegli Telegram.
2. Premi "Connect my chat" (collega la mia chat). L'app crea un codice monouso.
3. Premi "Open Telegram". Si apre la chat con il tuo bot e il codice è già pronto. Premi Avvia.
4. La dashboard mostra che la chat è collegata. Premi "Send test" (invia un test) e su Telegram arriva un messaggio di prova.

Il link scade dopo trenta minuti: se ti distrai, premi di nuovo "Connect my chat".

### Avvisi in un gruppo o in un topic

Per condividere gli avvisi con il partner o con chi rivende insieme a te, usa un gruppo:

1. Crea un gruppo Telegram e aggiungi il tuo bot come un membro qualsiasi.
2. Apri il link di collegamento dall'interno del gruppo e premi Avvia lì.

Se il gruppo usa i topic, apri il link dentro il topic che vuoi: gli avvisi arriveranno solo lì. Comodo per avere un topic per ogni ricerca.

## Come sono fatti gli avvisi

Ogni nuovo annuncio arriva come messaggio con foto, con:

- Prima di tutto il prezzo totale, protezione acquisti inclusa, e una nota quando è chiaramente sotto il prezzo tipico di quella ricerca.
- Titolo, taglia, condizioni, marca e valutazione del venditore.
- Il sito Vinted del paese e il momento in cui l'annuncio è stato trovato.
- Un pulsante verde per comprare e uno per aprire l'annuncio su Vinted.

Puoi passare a uno stile a galleria con più foto per annuncio, oppure ricevere gli avvisi in silenzio e lasciare il suono solo agli affari migliori.

Dalla chat puoi anche gestire le ricerche. `/list` mostra le tue ricerche e come sta andando ciascuna, `/pause 3` e `/resume 3` fermano e riavviano la ricerca 3, e `/add` seguito da un link di ricerca Vinted la aggiunge. Funziona anche incollare direttamente un link Vinted: un link di ricerca aggiunge la ricerca, il link di un annuncio ne segue il prezzo e la vendita, il profilo di un membro ti avvisa dei suoi nuovi caricamenti.

## Poi aggiungi una ricerca

Nella dashboard incolla il link di una ricerca Vinted (dal browser o dal pulsante di condivisione dell'app), oppure costruisci la ricerca con le categorie, le marche e le taglie di Vinted. Imposta il prezzo massimo come totale che sei disposto a pagare e aggiungi parole da escludere, come "difettoso" o "solo scatola". Il primo controllo è silenzioso apposta, così ricevi solo gli annunci che compaiono da quel momento in poi.

## Quanto è veloce

vinted-sniper controlla ogni ricerca ogni minuto. Vinted però aggiunge i nuovi annunci alla sua ricerca qualche minuto dopo il caricamento, e questo vale per tutti gli strumenti, gratuiti o a pagamento. In pratica ricevi la maggior parte degli annunci entro pochi minuti dalla pubblicazione. Chi promette "zero ritardo" misura dal momento in cui l'annuncio compare nella ricerca, non dal caricamento.

Ricorda anche che l'app gira sul tuo computer: gli avvisi arrivano solo mentre quel computer è acceso e sveglio. Un Raspberry Pi o un vecchio portatile lasciato in carica risolvono il problema.

## Se qualcosa non funziona

### Telegram non si collega mai

L'app deve essere in esecuzione quando premi Avvia su Telegram, e il link deve avere meno di trenta minuti. Per un gruppo, aggiungi il bot al gruppo prima di toccare il link.

### Funzionava, poi si è fermato

Se hai bloccato il bot o lo hai tolto dal gruppo, Telegram lo comunica a vinted-sniper e l'app disattiva quella destinazione invece di continuare a fallire. Ricollega la chat dalla pagina "Alerts".

### La ricerca funziona ma non arriva niente

Di solito è il limite di prezzo: include la protezione acquisti, quindi un articolo a 19 € costa 20,65 € e non passa un limite di 20 €. La dashboard tiene un elenco degli annunci scartati con il motivo di ognuno.

### Troppi avvisi

Restringi la ricerca, aggiungi parole da escludere o usa il filtro affari, così passano solo gli annunci ben sotto il prezzo abituale.

## Telegram, Discord o notifica sul telefono?

Telegram è perfetto se lo usi già e vuoi avvisi da inoltrare o condividere in un gruppo. Se preferisci Discord, vinted-sniper lo supporta con un webhook, senza token. E se non vuoi né l'uno né l'altro, l'app gratuita ntfy ti dà una semplice notifica sul telefono, senza account. Per il quadro completo leggi la guida al [bot Vinted gratis](/guides/bot-vinted-gratis/), e se le notifiche di Vinted ti arrivano in ritardo, la guida su [notifiche Vinted che non arrivano](/guides/notifiche-vinted-non-arrivano/).
