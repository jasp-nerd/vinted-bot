---
title: "Alerte Vinted sur Discord : créer un webhook en 2 minutes"
description: "Alerte Vinted sur Discord gratuite : créer un serveur, copier l'URL du webhook sur PC ou mobile, la relier à un bot Vinted gratuit et être notifié."
slug: alerte-vinted-discord
key: discord
date: 2026-10-30
updated: 2026-10-30
keywords:
  - alerte vinted discord
  - bot vinted gratuit discord
  - bot vinted discord
  - serveur discord bot vinted gratuit
  - webhook discord vinted
  - meilleur bot vinted gratuit discord
faq:
  - q: "Comment avoir un bot Vinted gratuit sur Discord ?"
    a: "Créez votre propre serveur Discord, ajoutez un webhook dans un salon et copiez son URL. Collez-la dans vinted-bot (gratuit et open source), puis ajoutez vos recherches : chaque nouvelle annonce arrive dans le salon avec photos, prix total et boutons."
  - q: "Comment créer un webhook Discord ?"
    a: "Sur un serveur où vous pouvez gérer les salons, ouvrez les paramètres du salon (Modifier le salon), puis Intégrations, Webhooks, Nouveau webhook, et copiez l'URL du webhook. Sur mobile, appuyez longuement sur le nom du salon pour accéder à Modifier le salon."
  - q: "Faut-il inviter un bot sur mon serveur Discord ?"
    a: "Non, pas avec un webhook. Un webhook permet seulement de publier dans un salon : rien à inviter, et rien qui ait accès au reste de votre serveur."
  - q: "Pourquoi je ne peux pas créer de webhook sur un serveur Discord ?"
    a: "Il faut la permission de gérer les webhooks, ce qui sur le serveur de quelqu'un d'autre veut souvent dire être administrateur. Créer votre propre serveur est gratuit et prend moins d'une minute."
---

Pour recevoir des alertes Vinted sur Discord, il vous faut l'URL d'un webhook Discord : un lien privé qui permet à une application de publier dans un salon. Créez un serveur (gratuit), ouvrez les paramètres du salon, allez dans Intégrations, puis Webhooks, puis Nouveau webhook, et copiez l'URL. Collez-la dans votre bot Vinted et envoyez un test. Avec vinted-bot, l'ensemble est gratuit et prend environ deux minutes.

Les libellés ci-dessous sont ceux de Discord en français ; ils peuvent varier légèrement selon la version.

## Pourquoi un webhook plutôt qu'un bot Discord

Un webhook est une porte à sens unique vers un seul salon. Ce qui possède l'URL peut publier des messages dans ce salon, et rien d'autre : pas de lecture de vos messages, pas d'accès aux autres salons. Vous n'invitez rien sur votre serveur.

C'est donc la façon la plus simple et la plus sûre de recevoir des alertes. Une seule chose à retenir : quiconque a l'URL peut publier dans ce salon. Traitez-la comme un mot de passe, et ne la collez ni dans une discussion, ni dans une capture d'écran, ni dans un assistant IA.

## Étape 1 : créer votre propre serveur

On ne peut créer de webhook que là où l'on a le droit de gérer le salon. Sur le serveur d'un ami, il faudrait qu'il vous nomme administrateur : plus simple d'avoir le vôtre.

Sur ordinateur :

1. Dans Discord, cliquez sur le + en bas de la liste des serveurs, à gauche.
2. Choisissez de créer votre propre serveur, pour vous et vos amis.
3. Donnez-lui un nom, par exemple « Trouvailles Vinted », et validez.

Sur téléphone, c'est la même chose : le + dans la liste des serveurs, créer le vôtre, le nommer, valider.

Votre nouveau serveur a un salon #général. Vous pouvez l'utiliser, ou créer un salon par recherche, comme #vestes et #pokemon, pour pouvoir les mettre en sourdine ou les prioriser séparément.

## Étape 2 : créer le webhook et copier son URL

### Sur ordinateur

1. Survolez le salon qui doit recevoir les alertes et cliquez sur la roue dentée à côté de son nom (Modifier le salon).
2. Cliquez sur Intégrations dans le menu de gauche.
3. Cliquez sur Webhooks, puis Nouveau webhook. Discord en crée un avec un nom au hasard.
4. Cliquez sur le webhook pour le déplier. Renommez-le si vous voulez, par exemple « Alertes Vinted ».
5. Cliquez sur Copier l'URL du webhook.

### Sur téléphone

1. Appuyez longuement sur le nom du salon et choisissez Modifier le salon.
2. Touchez Intégrations, puis Webhooks, puis Nouveau webhook.
3. Touchez le nouveau webhook pour l'ouvrir, puis Copier l'URL du webhook.

L'URL commence par `https://discord.com/api/webhooks/` suivi de deux longs codes. Si ce que vous avez copié ne commence pas ainsi, vous avez copié autre chose, souvent le lien du salon.

Petit piège : Discord refuse les noms de webhook qui contiennent le mot « discord ». Si le renommage échoue, c'est pour ça.

## Étape 3 : la coller dans vinted-bot

vinted-bot est une application gratuite et open source qui surveille vos recherches Vinted et envoie les nouvelles annonces vers Discord, entre autres. Après l'installation, le tableau de bord s'ouvre sur `http://localhost:8000`.

1. Ouvrez la page « Alerts » (où arrivent les alertes) et ajoutez une destination.
2. Choisissez Discord et collez l'URL du webhook.
3. Appuyez sur « Send test » (envoyer un test). Un message de test doit apparaître dans votre salon en quelques secondes.

Ajoutez ensuite une recherche : collez un lien de recherche Vinted ou construisez-la dans le tableau de bord, fixez votre prix maximum et les mots à exclure, et choisissez vers quelles destinations elle envoie. Une recherche sans destination choisie envoie vers toutes celles que vous avez ajoutées.

{{install}}

## À quoi ressemble une alerte Vinted dans Discord

Chaque nouvelle annonce arrive sous forme de carte dans le salon :

- La galerie de photos de l'annonce.
- Le prix total que vous paierez, protection acheteurs comprise, avec le prix demandé en dessous.
- Un badge quand le prix est nettement sous le prix habituel de la recherche, par exemple quand il est 24 % sous ce prix.
- La taille, l'état, la marque, la note du vendeur et son nombre d'évaluations.
- Des boutons Acheter, Contacter le vendeur et Ouvrir sur Vinted.

Il existe aussi un style compact pour voir plus d'annonces par écran. Vous pouvez aussi mentionner un rôle seulement pour les meilleures affaires, pour que votre téléphone ne sonne fort que pour celles-là.

## Étape 4 : être notifié sur votre téléphone

La plupart des « je n'ai jamais reçu l'alerte » viennent des notifications Discord. Deux minutes bien investies :

1. Dans l'appli Discord, appuyez longuement sur l'icône de votre serveur, puis Notifications, et choisissez Tous les messages.
2. Si vous avez un salon par recherche, réglez chacun séparément : Tous les messages pour #pokemon, Rien pour une recherche bavarde.
3. Sur iPhone, autorisez les notifications de Discord dans Réglages, Notifications, Discord, et vérifiez que les modes Concentration le laissent passer.
4. Sur Android, autorisez les notifications de Discord et mettez sa batterie en « Non restreinte », pour que le téléphone ne retienne pas les notifications.
5. Si vous êtes connecté sur un ordinateur en même temps, Discord peut retenir les notifications du téléphone pendant que vous êtes actif sur l'ordinateur. Dans les paramètres de Discord, rubrique Notifications, vous pouvez régler ce délai.

## Si les messages n'arrivent plus

### Le webhook a été supprimé

Si quelqu'un supprime le webhook ou le salon, Discord répond à vinted-bot qu'il n'existe plus, et l'application désactive cette destination. C'est voulu : envoyer en boucle vers un webhook mort, c'est ce qui fait limiter une adresse par Discord lui-même. Créez un nouveau webhook et ajoutez-le à nouveau.

### L'URL a fuité

Si vous avez collé l'URL quelque part en public, supprimez ce webhook dans Discord (Modifier le salon, Intégrations, Webhooks) et créez-en un autre. L'ancienne URL cesse de fonctionner immédiatement.

### La recherche fonctionne mais ne trouve rien

Vérifiez le prix maximum. Il inclut la protection acheteurs (en général 0,70 € plus 5 % du prix) : une limite de 20 € écarte un article à 19 € qui coûte 20,65 € à l'achat. Le tableau de bord garde la liste des annonces écartées avec la raison, ce qui répond à la plupart des « pourquoi je n'ai pas eu celle-là ? ».

## Un bot Vinted gratuit sans Discord ?

Discord est le choix par défaut de beaucoup d'utilisateurs en France, mais Telegram marche tout aussi bien. Si vous n'utilisez pas Discord, voyez [bot Vinted gratuit sur Telegram](/guides/bot-vinted-telegram-gratuit/), ou passez-vous des deux avec une simple notification sur le téléphone via l'appli gratuite ntfy, sans compte. Le [guide du bot Vinted gratuit](/guides/bot-vinted-gratuit/) couvre toute l'installation.
