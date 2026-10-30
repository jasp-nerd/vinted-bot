---
title: "Bot Vinted gratuit : des alertes nouvelles annonces sans payer"
description: "Bot Vinted gratuit et open source : les nouvelles annonces de vos recherches sur Discord, Telegram ou mobile. Sans abonnement, sans connexion Vinted."
slug: bot-vinted-gratuit
key: free-bot
date: 2026-10-30
updated: 2026-10-30
keywords:
  - bot vinted gratuit
  - bot vinted gratuit discord
  - bot vinted gratuit telegram
  - bot vinted gratuit sans discord
  - robot vinted gratuit
  - bot vinted gratuit github
  - bot vinted 0 délai
faq:
  - q: "Existe-t-il un bot Vinted gratuit ?"
    a: "Oui. vinted-bot est gratuit et open source (licence MIT), sans formule payante. Il surveille vos recherches Vinted et envoie les nouvelles annonces sur Discord, Telegram, votre téléphone (appli ntfy) ou un webhook. Il tourne sur votre propre ordinateur, qui doit donc rester allumé."
  - q: "Un bot Vinted gratuit sans Discord, c'est possible ?"
    a: "Oui. vinted-bot fonctionne aussi avec Telegram, avec une notification sur le téléphone via l'appli gratuite ntfy (sans compte), par flux RSS ou par webhook. L'e-mail est possible avec un module optionnel."
  - q: "Un bot Vinted 0 délai, ça existe ?"
    a: "Non. Vinted ajoute les nouvelles annonces à sa recherche quelques minutes après leur mise en ligne, et aucun outil, payant ou gratuit, ne les voit avant. Le « 0 délai » se mesure à partir du moment où l'annonce apparaît dans la recherche, pas de la publication."
  - q: "Un bot Vinted gratuit peut-il faire bannir mon compte ?"
    a: "Un bot d'alerte qui ne se connecte jamais à votre compte n'a aucun compte à faire suspendre. Le risque concerne surtout les bots qui achètent, envoient des messages ou republient à votre place. Vinted peut en revanche ralentir temporairement une adresse IP trop insistante."
---

Oui, un bot Vinted gratuit existe. vinted-bot est une application gratuite et open source qui surveille vos recherches Vinted et envoie chaque nouvelle annonce sur Discord, Telegram ou votre téléphone, avec le prix que vous paierez vraiment. Elle tourne sur votre propre ordinateur plutôt que sur le serveur d'une société, ce qui explique qu'elle ne coûte rien, et elle ne demande jamais vos identifiants Vinted.

Ce guide explique ce qu'on appelle un « bot Vinted », quelles options gratuites existent vraiment, comment en installer un en une dizaine de minutes, et ses limites avant de compter dessus.

## Ce que « bot Vinted » veut dire

Le mot recouvre des outils très différents, et la différence compte autant pour le prix que pour le risque.

Un bot d'alerte (on dit aussi moniteur) surveille une recherche et vous prévient dès qu'une nouvelle annonce apparaît. Vous ouvrez l'annonce et vous achetez vous-même. C'est ce que cherchent la plupart des gens quand les alertes de recherche sauvegardée de Vinted ne suivent pas.

Un bot d'achat automatique (autobuy, autocop) se connecte à votre compte et lance l'achat dès qu'une annonce correspond. Ce sont les plus chers, et ils ont besoin de votre compte et de votre moyen de paiement.

Les bots de republication, de likes et d'abonnements servent aux vendeurs. Ils remontent les annonces ou génèrent de l'attention, toujours depuis votre compte connecté.

Ce guide parle des bots d'alerte. Pour le détail de chaque type, voyez [bot Vinted, c'est quoi et comment ça marche](/guides/bot-vinted-c-est-quoi/).

## Les options gratuites, comparées franchement

### Les recherches sauvegardées de Vinted

Gratuites et intégrées. Vous sauvegardez une recherche et Vinted est censé vous prévenir des nouveautés. En pratique, beaucoup de gens reçoivent ces notifications en retard, ou jamais, et le filtre de prix ignore les frais de protection acheteurs. Les causes et les réglages à vérifier sont dans [notification Vinted qui ne fonctionne pas](/guides/notification-vinted-ne-fonctionne-pas/).

### Les essais gratuits des bots payants

Plusieurs services sur Telegram ou en appli proposent une recherche gratuite ou quelques jours d'essai, puis facturent environ 5 à 30 € par mois (en octobre 2026). Bien pour tester, limité pour un usage réel.

### Les serveurs Discord communautaires gratuits

Des salons partagés qui publient les annonces de catégories populaires. Vous recevez la même chose que tous les autres membres, au même moment, sans choisir vos filtres.

### Les outils open source à faire tourner soi-même

Gratuits, sans limite de recherches, mais il faut un ordinateur qui reste allumé. vinted-bot en fait partie. Son parti pris : être simple à installer et vous dire clairement quand il ne fonctionne plus, ce qui est le reproche numéro un fait aux bots gratuits.

## Pourquoi vinted-bot est gratuit

Il n'y a pas de serveur de notre côté. L'application tourne sur votre PC portable, votre ordinateur fixe, un Raspberry Pi ou un NAS, interroge vos recherches depuis votre propre connexion internet et envoie les alertes depuis là. Pas d'hébergement à payer, donc rien à vous facturer. Le code est public sur GitHub sous licence MIT : n'importe qui peut lire exactement ce qu'il fait.

Ce que vous obtenez gratuitement :

- Des alertes sur Discord, Telegram, ntfy (appli de notifications gratuite, sans compte), RSS ou votre propre webhook. L'e-mail et des services comme Slack ou Pushover passent par un module optionnel.
- Le prix total dans chaque alerte, protection acheteurs comprise, et des limites de prix calculées sur ce total.
- Des mots obligatoires dans le titre et des mots à exclure, pour ne plus voir passer « pour pièces » ou « boîte seule ».
- Des filtres vendeur : note minimale, nombre d'avis minimum, pays du vendeur, et un bouton pour bloquer un vendeur.
- Un badge « bonne affaire » quand une annonce est nettement sous le prix habituel de la recherche.
- Une même recherche sur plusieurs pays Vinted, des heures de silence la nuit et un tableau de bord avec le fil des trouvailles.
- Un état en clair pour chaque recherche, pour savoir si Vinted la ralentit ou si elle est bloquée.

## L'installer en cinq étapes

1. Installez-le. Sur Windows, ouvrez PowerShell et collez la commande d'une ligne de la page d'accueil ; sur Mac ou Linux, ouvrez le Terminal et collez l'autre. Pas besoin de droits administrateur ni de Docker. À la fin, votre navigateur ouvre le tableau de bord sur `http://localhost:8000`.
2. Faites votre recherche sur Vinted comme d'habitude (mots, catégorie, taille, marque, état) et copiez l'adresse dans la barre du navigateur, ou partagez la recherche depuis l'appli et copiez le lien. Vous pouvez aussi construire la recherche dans le tableau de bord, avec les catégories et les marques de Vinted.
3. Collez-la dans le tableau de bord. Un compteur indique en direct combien d'annonces actuelles correspondent et combien chaque filtre en retire. Fixez le prix maximum comme le total que vous êtes prêt à payer.
4. Choisissez où arrivent les alertes. Le plus rapide est une notification sur le téléphone avec l'appli gratuite ntfy : installez-la, ajoutez le nom de sujet affiché par le tableau de bord, c'est fini. Pour Discord ou Telegram, suivez le [guide Discord](/guides/alerte-vinted-discord/) ou le [guide Telegram](/guides/bot-vinted-telegram-gratuit/). Envoyez un test (bouton « Send test ») avant de continuer.
5. Laissez tourner. Le premier passage est volontairement silencieux, pour ne pas vous noyer sous les annonces déjà en ligne. Ensuite, chaque nouvelle annonce arrive avec les photos, le prix total, la taille, l'état, la note du vendeur et des boutons Acheter, Contacter le vendeur et Ouvrir sur Vinted.

{{install}}

## Les limites, avant de compter dessus

### L'ordinateur doit rester allumé

Les alertes partent de la machine où il tourne. Un portable en veille n'envoie rien pendant sa veille. Sur Windows, réglez la mise en veille sur « Jamais » quand il est branché ; sur Mac, l'installateur propose de garder le Mac éveillé tant qu'il est sur secteur. Pour des alertes jour et nuit, un Raspberry Pi, un NAS ou un vieux portable laissé branché font très bien l'affaire et consomment peu.

### Le « 0 délai » n'existe pas

Vinted ajoute les nouvelles annonces à sa recherche quelques minutes après leur publication. Tous les outils qui lisent la recherche, payants ou gratuits, les voient à ce moment-là. Les serveurs qui promettent « 0 délai » mesurent le temps entre l'apparition dans la recherche et l'alerte, pas depuis la mise en ligne. vinted-bot vérifie chaque minute par défaut. Vérifier plus souvent ne trouve rien plus tôt et fait ralentir votre connexion par Vinted. Si vous voulez battre les bots d'achat automatique sur des consoles bradées, aucun outil d'alerte ne gagnera cette course. Si vous cherchez une taille, une marque ou une pièce de collection précise, une minute suffit largement.

### Votre connexion compte

Vinted bloque plus souvent certaines adresses de datacenter ou de VPN que les connexions de particuliers. Le faire tourner à la maison est en général le plus fiable. Si Vinted vous ralentit, l'application patiente toute seule et le tableau de bord vous le dit.

### Il n'achète pas à votre place

C'est voulu. L'achat automatique a besoin de votre compte connecté, et c'est comme ça que des comptes se font restreindre. Voyez [bot Vinted : légal, interdit, risque de ban ?](/guides/bot-vinted-legal-ban/) pour savoir où se situe le vrai risque.

## Gratuit ou payant : lequel choisir ?

Si vous avez un ordinateur allumé une bonne partie de la journée, ou un Pi ou un NAS, la solution gratuite fait ce que fait un service d'alertes à 5 à 30 € par mois. Si rien ne reste allumé chez vous et que vous ne voulez rien installer, un service payant est un choix honnête, puisqu'il tourne sur leurs serveurs. Les deux sont comparés sans classement dans [meilleur bot Vinted gratuit ou payant](/guides/meilleur-bot-vinted-gratuit/). Et si vous achetez pour revendre, lisez aussi [achat-revente sur Vinted](/guides/achat-revente-vinted/).
