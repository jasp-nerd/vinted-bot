---
title: "Bot Vinted gratis: notifiche dei nuovi annunci senza pagare"
description: "Bot Vinted gratis e open source: i nuovi annunci delle tue ricerche su Telegram, Discord o sul telefono. Senza abbonamento, senza login Vinted."
slug: bot-vinted-gratis
key: free-bot
date: 2026-10-30
updated: 2026-10-30
keywords:
  - bot vinted gratis
  - bot vinted gratuito
  - vinted bot free
  - bot vinted telegram gratis
  - bot vinted discord gratis
  - vinted bot github
faq:
  - q: "Esiste un bot Vinted gratis?"
    a: "Sì. vinted-bot è gratuito e open source (licenza MIT), senza versioni a pagamento. Controlla le tue ricerche Vinted e manda i nuovi annunci su Telegram, Discord, sul telefono con ntfy o a un webhook. Gira sul tuo computer, che deve restare acceso."
  - q: "Un bot Vinted gratis ha bisogno del mio login Vinted?"
    a: "Un bot di avvisi no: i risultati di ricerca si leggono anche senza essere loggati. Solo gli strumenti che comprano, scrivono o ripubblicano per te hanno bisogno del tuo account, ed è lì che l'account rischia."
  - q: "Un bot Vinted gratis può comprare per me?"
    a: "Questo no. Comprare in automatico richiede il tuo account loggato, ed è da lì che arrivano le restrizioni. vinted-bot mette invece un pulsante per comprare in ogni avviso, così l'acquisto resta tuo."
  - q: "Un bot Vinted per acquistare conviene?"
    a: "Raramente, a meno che tu non rivenda in grandi volumi. I bot che acquistano costano molto di più e usano il tuo account, che Vinted può limitare se sospetta l'automazione. Per chi cerca articoli precisi bastano gli avvisi."
---

Sì, un bot Vinted gratis esiste. vinted-bot è un'app gratuita e open source che controlla le tue ricerche Vinted e manda ogni nuovo annuncio su Telegram, Discord o sul telefono, con il prezzo che pagheresti davvero. Gira sul tuo computer invece che sul server di qualcun altro, per questo non costa niente, e non chiede mai il login di Vinted.

Qui sotto trovi cosa si intende di solito per "bot Vinted", quali opzioni gratuite esistono, come configurarne uno in una decina di minuti e i limiti da conoscere prima di affidartici.

## Cosa si intende per "bot Vinted"

La parola copre strumenti molto diversi, e la differenza conta sia per il prezzo sia per il rischio.

Un bot di avvisi (detto anche monitor) osserva una ricerca e ti dice quando compare qualcosa di nuovo. Poi apri l'annuncio e compri tu. È quello che serve a chi è deluso dalle notifiche delle ricerche salvate di Vinted.

Un bot per acquistare (autobuy) entra con il tuo account e conclude l'acquisto appena un annuncio corrisponde. Sono quelli costosi, e hanno bisogno del tuo account e dei tuoi dati di pagamento.

I bot per ripubblicare, mettere like o seguire servono ai venditori. Anche loro passano dal tuo account.

Questa guida parla dei bot di avvisi.

## Le opzioni gratuite, confrontate onestamente

### Le ricerche salvate di Vinted

Gratis e integrate nell'app. Salvi una ricerca e Vinted dovrebbe avvisarti dei nuovi articoli. In pratica molti ricevono notifiche in ritardo o nessuna, e il filtro prezzo ignora la protezione acquisti. Trovi le cause nella guida su [notifiche Vinted che non arrivano](/guides/notifiche-vinted-non-arrivano/).

### Prove gratuite dei bot a pagamento

Diversi bot su Telegram e app ti lasciano provare una ricerca gratis, poi costano più o meno da 5 a 30 euro al mese (a ottobre 2026). Bene per un test, limitati per l'uso vero.

### Server Discord e canali comunitari gratuiti

Canali condivisi che pubblicano annunci per le categorie più popolari. Vedi quello che vedono tutti gli altri, nello stesso momento, senza poter scegliere i filtri.

### Strumenti open source da far girare in proprio

Gratis e senza limite di ricerche, ma serve un computer che resti acceso. vinted-bot è uno di questi. È pensato per essere facile da installare e per dirti quando smette di funzionare, che è la lamentela più comune sui bot gratuiti.

## Perché vinted-bot è gratis

Dalla nostra parte non c'è nessun server. L'app gira sul tuo portatile, sul fisso, su un Raspberry Pi o su un NAS, controlla le ricerche dalla tua connessione e manda gli avvisi da lì. Niente costi di hosting, quindi niente da far pagare. Il codice è su GitHub con licenza MIT: chiunque può leggere cosa fa.

Cosa ottieni gratis:

- Avvisi su Telegram, Discord, ntfy (un'app gratuita per le notifiche sul telefono, senza account), RSS o un tuo webhook. Anche email e servizi come Slack o Pushover.
- Il prezzo totale in ogni avviso, protezione acquisti inclusa, e limiti di prezzo calcolati su quel totale. Il filtro prezzo di Vinted ignora la commissione.
- Parole che il titolo deve contenere e parole da escludere, così "per ricambi" o "solo scatola" non ti arrivano mai.
- Filtri sul venditore: valutazione minima, numero minimo di recensioni, paese, e un pulsante per bloccarlo.
- Un badge "affare" quando un annuncio è ben sotto il prezzo tipico di quella ricerca.
- Una ricerca su più siti Vinted di paesi diversi, ore di silenzio e una dashboard con il feed in diretta.
- Uno stato in parole semplici per ogni ricerca, così sai quando Vinted la sta rallentando o quando è bloccata.

## Configurazione in cinque passi

1. Installalo. Su Windows apri PowerShell e incolla il comando di una riga che trovi nella homepage; su Mac o Linux apri il Terminale e incolla l'altro. Non servono diritti di amministratore né Docker. Alla fine il browser apre la dashboard su `http://localhost:8000`.
2. Cerca su Vinted come fai sempre (parole, categoria, taglia, marca, condizioni) e copia l'indirizzo dalla barra del browser, oppure condividi la ricerca dall'app e copia il link. Puoi anche costruire la ricerca nella dashboard, con le categorie e le marche di Vinted.
3. Incollala nella dashboard. Vedi in diretta quanti annunci attuali corrispondono e quanti ne toglie ogni filtro. Imposta il prezzo massimo come totale che sei disposto a pagare.
4. Scegli dove arrivano gli avvisi. Il più veloce è una notifica sul telefono con l'app gratuita ntfy: la installi, aggiungi il nome che ti mostra la dashboard, fatto. Per Telegram c'è la guida al [bot Vinted su Telegram](/guides/bot-vinted-telegram/). Discord funziona con un webhook che copi dalle impostazioni del canale. Premi "Send test" (invia un test) prima di andare avanti.
5. Lascialo girare. Il primo controllo è silenzioso apposta, così non ricevi una valanga di annunci già presenti. Da lì in poi ogni nuovo annuncio arriva con foto, prezzo totale, taglia, condizioni, valutazione del venditore e pulsanti per comprare, scrivere al venditore o aprire l'annuncio.

{{install}}

## I limiti, prima di affidartici

### Il computer deve restare acceso

Gli avvisi partono dalla macchina su cui gira. Un portatile in stop non manda niente. Su Windows imposta la sospensione su "Mai" quando è collegato alla corrente; l'installer per Mac propone di tenere il Mac sveglio quando è in carica. Per avvisi 24 ore su 24 vanno benissimo un Raspberry Pi, un NAS o un vecchio portatile lasciato in carica, e consumano poco.

### Non è istantaneo, e niente lo è

Vinted aggiunge i nuovi annunci alla sua ricerca qualche minuto dopo il caricamento. Ogni strumento che legge la ricerca, gratuito o a pagamento, li vede in quel momento. vinted-bot controlla ogni minuto. Controllare più spesso non trova niente prima e fa rallentare la tua connessione. Se gareggi con i bot autobuy per le console sottoprezzo, nessun bot di avvisi vincerà. Se cerchi una taglia, una marca o un pezzo da collezione, un minuto basta e avanza.

### La tua connessione conta

Vinted mette alla prova alcuni indirizzi di datacenter e VPN più delle connessioni di casa. Farlo girare a casa di solito è la scelta più affidabile. Se Vinted ti rallenta, l'app si adegua da sola e la dashboard te lo dice.

### Non compra per te

Di proposito. Comprare in automatico richiede il tuo account loggato, ed è così che gli account vengono limitati. Le condizioni di Vinted vietano l'accesso automatizzato: un bot che non fa login non ha un account da perdere, mentre uno che compra per te sì.

## Gratis o a pagamento?

Se hai un computer acceso buona parte della giornata, o un Pi o un NAS, la via gratuita fa quello che fa un servizio di avvisi da 5 a 30 euro al mese. Se non hai niente che resti acceso e non vuoi installare nulla, un servizio a pagamento è una scelta legittima, perché gira sui loro server. In quel caso scegline uno che non chieda il tuo login Vinted.

Per impostare bene le notifiche, anche quelle di Vinted, leggi [come ricevere le notifiche dei nuovi articoli](/guides/notifiche-vinted-nuovi-articoli/).
