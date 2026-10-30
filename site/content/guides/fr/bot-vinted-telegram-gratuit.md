---
title: "Bot Vinted Telegram gratuit : des alertes sans Discord"
description: "Bot Vinted Telegram gratuit, sans Discord : créez votre bot avec BotFather, reliez votre conversation et recevez les nouvelles annonces avec le prix total."
slug: bot-vinted-telegram-gratuit
key: telegram
date: 2026-10-30
updated: 2026-10-30
keywords:
  - bot vinted telegram gratuit
  - bot vinted gratuit sans discord
  - bot vinted telegram
  - alerte vinted telegram
  - botfather token
  - bot vinted gratuit telegram
faq:
  - q: "Existe-t-il un bot Vinted gratuit sur Telegram ?"
    a: "Oui. Avec vinted-bot, vous créez votre propre bot Telegram privé en trois minutes environ, et il vous envoie les nouvelles annonces de vos recherches Vinted. C'est gratuit et open source, sans limite de recherches."
  - q: "Comment obtenir le token d'un bot Telegram ?"
    a: "Dans Telegram, cherchez BotFather (le compte officiel a un badge bleu), envoyez /newbot, choisissez un nom puis un nom d'utilisateur qui se termine par bot. BotFather répond avec un token : des chiffres, deux-points, puis une longue suite de caractères."
  - q: "Faut-il connaître son chat ID Telegram ?"
    a: "Pas avec vinted-bot. Le tableau de bord vous donne un code à usage unique, vous l'envoyez à votre bot et l'application trouve la conversation toute seule. Ça marche aussi pour les groupes et les sujets de forum."
  - q: "Pourquoi mon bot Telegram ne m'envoie rien ?"
    a: "Un bot Telegram ne peut pas vous écrire en premier : c'est à vous d'ouvrir la conversation. Vérifiez que vous avez appuyé sur Démarrer, que le token est bien renseigné et l'application redémarrée, et pour un groupe, que le bot y a été ajouté."
---

Vous pouvez recevoir vos alertes Vinted sur Telegram gratuitement, sans Discord. Créez votre propre bot privé avec BotFather, l'outil officiel de Telegram (trois minutes environ), donnez son token à vinted-bot et reliez votre conversation avec un code à usage unique. Ensuite, chaque nouvelle annonce de vos recherches Vinted arrive dans Telegram avec une photo, le prix total, la taille, l'état et des boutons Acheter et Ouvrir.

Beaucoup de gens ne veulent pas de Discord, ou ne l'utilisent pas du tout. En France, « bot Vinted gratuit sans Discord » fait d'ailleurs partie des recherches courantes. Voici l'installation complète.

## Pourquoi votre propre bot

Les bots d'alerte Telegram partagés font tourner un seul bot pour tous leurs clients et font payer les recherches supplémentaires. Avec vinted-bot, vous créez un bot qui ne sert qu'à vous. C'est gratuit, il vit dans votre compte Telegram, et seule l'application que vous faites tourner peut envoyer des messages par son intermédiaire.

Le « bot » n'est ici qu'un compte Telegram depuis lequel une application peut envoyer des messages. En créer un est gratuit et ne demande aucune programmation.

## Étape 1 : créer un bot avec BotFather

1. Ouvrez Telegram sur votre téléphone ou votre ordinateur et cherchez BotFather. Prenez celui qui a le badge bleu vérifié : il existe des imitations.
2. Appuyez sur Démarrer, puis envoyez `/newbot`.
3. BotFather demande un nom. C'est celui qui s'affichera en haut de la conversation, par exemple « Mes alertes Vinted ».
4. Il demande ensuite un nom d'utilisateur, unique, qui doit se terminer par « bot », par exemple `julie_alertes_vinted_bot`. S'il est pris, essayez-en un autre.
5. BotFather répond avec un message qui contient votre token. Il ressemble à `7123456789:AAH...` (des chiffres, deux-points, puis une longue suite de lettres et de chiffres).

Gardez ce token pour vous. Quiconque l'a peut envoyer des messages au nom de votre bot. Ne le collez ni dans une discussion, ni dans une capture d'écran, ni dans un assistant IA. S'il fuite, envoyez `/revoke` à BotFather pour en obtenir un nouveau.

## Étape 2 : donner le token à vinted-bot

Pour l'instant, le token se met dans un petit fichier de réglages sur l'ordinateur qui fait tourner vinted-bot, pas dans le tableau de bord.

1. Trouvez le dossier de données de vinted-bot :
   - Windows : `%LOCALAPPDATA%\vinted-bot` (collez-le dans la barre d'adresse de l'Explorateur de fichiers)
   - Mac : `~/Library/Application Support/vinted-bot` (dans le Finder, menu Aller, Aller au dossier)
   - Linux ou Raspberry Pi : `~/.local/share/vinted-bot`
   - Docker : le dossier qui contient votre `docker-compose.yml`
2. Créez-y un fichier texte nommé `.env` (ou ouvrez-le s'il existe).
3. Ajoutez cette ligne, avec votre propre token après le signe égal :

```
VINTED_BOT_TELEGRAM_BOT_TOKEN=7123456789:AAH-votre-token
```

4. Enregistrez et redémarrez vinted-bot : relancez la commande d'installation, ou `docker compose up -d` avec Docker.

Si le tableau de bord indique toujours que le token manque, vérifiez que le fichier s'appelle exactement `.env` (Windows ajoute parfois `.txt`) et qu'il n'y a pas d'espace autour du signe égal.

{{install}}

## Étape 3 : relier votre conversation

Un bot Telegram ne peut pas vous écrire en premier. C'est une règle de Telegram contre le spam, et c'est pour ça que la plupart des tutoriels vous font chercher un « chat ID ». vinted-bot s'en passe :

1. Dans le tableau de bord, ouvrez la page « Alerts » (où arrivent les alertes) et ajoutez une destination. Choisissez Telegram.
2. Appuyez sur « Connect my chat » (relier ma conversation). L'application génère un code à usage unique.
3. Appuyez sur « Open Telegram ». La conversation avec votre bot s'ouvre avec le code prêt : appuyez sur Démarrer.
4. Le tableau de bord affiche « Connected ». Appuyez sur « Send test » (envoyer un test) : un message de test arrive dans Telegram.

Le lien expire au bout de trente minutes. Si vous avez été interrompu, appuyez simplement à nouveau sur « Connect my chat ».

### Les alertes dans un groupe ou un sujet

Pour partager les alertes avec un conjoint ou un associé de revente, utilisez un groupe :

1. Créez un groupe Telegram et ajoutez-y votre bot comme n'importe quel membre.
2. Ouvrez le lien de connexion depuis ce groupe et appuyez sur Démarrer là.

Si votre groupe utilise les sujets, ouvrez le lien dans le sujet voulu : les alertes n'iront que dans ce sujet. Pratique pour avoir un sujet par recherche.

## À quoi ressemblent les alertes

Chaque nouvelle annonce arrive sous forme de message photo avec :

- Le prix total en premier, protection acheteurs comprise, et une mention quand il est nettement sous le prix habituel de la recherche.
- Le titre, la taille, l'état, la marque et la note du vendeur.
- Le site Vinted du pays et l'heure à laquelle l'annonce a été trouvée.
- Un bouton vert Acheter et un bouton Ouvrir sur Vinted.

Vous pouvez passer à un style galerie qui montre plusieurs photos par annonce, ou envoyer les alertes d'une destination sans son et ne laisser sonner que les bonnes affaires.

Vous pouvez aussi tout gérer depuis la conversation. `/list` affiche vos recherches et leur état, `/pause 3` et `/resume 3` arrêtent et relancent la recherche 3, et `/add` suivi d'un lien de recherche Vinted la met sous surveillance. Coller un lien Vinted fonctionne aussi : un lien de recherche ajoute la recherche, un lien d'annonce surveille son prix, et le lien d'un profil de membre suit ses nouvelles publications.

## Ajouter une recherche

Dans le tableau de bord, collez un lien de recherche Vinted (depuis le navigateur ou le bouton partager de l'appli) ou construisez la recherche avec les catégories, marques et tailles de Vinted. Fixez le prix maximum comme le total que vous paierez, et ajoutez les mots à exclure, comme « abîmé » ou « boîte seule ». Le premier passage est silencieux : vous n'êtes prévenu que des annonces publiées après ce moment.

## Dépannage des alertes Telegram

### « Telegram ne se connecte jamais »

L'application doit tourner au moment où vous appuyez sur Démarrer dans Telegram, et le lien doit avoir moins de trente minutes. Pour un groupe, ajoutez le bot au groupe avant d'ouvrir le lien.

### Ça marchait, puis plus rien

Si vous avez bloqué le bot ou l'avez retiré du groupe, Telegram signale à vinted-bot que la conversation n'existe plus, et l'application désactive cette destination au lieu d'échouer en boucle. Reliez de nouveau la conversation depuis la page « Alerts ».

### La recherche fonctionne mais rien n'arrive

En général, c'est le prix maximum : il inclut la protection acheteurs (en général 0,70 € plus 5 % du prix), donc un article affiché à 19 € coûte 20,65 € et ne passe pas une limite de 20 €. La liste des annonces écartées dans le tableau de bord donne la raison pour chacune.

### Trop d'alertes

Resserrez la recherche, ajoutez des mots à exclure, ou activez le filtre bonnes affaires pour ne laisser passer que les annonces nettement sous le prix habituel.

## Telegram, Discord ou notification sur le téléphone ?

Telegram est idéal si vous l'utilisez déjà et voulez des alertes à transférer ou à partager dans un groupe. Si vous préférez Discord, le [guide de l'alerte Vinted sur Discord](/guides/alerte-vinted-discord/) est encore plus rapide puisqu'il n'y a pas de token. Si vous ne voulez ni l'un ni l'autre, l'appli gratuite ntfy vous donne une simple notification sur le téléphone, sans aucun compte. Le [guide du bot Vinted gratuit](/guides/bot-vinted-gratuit/) couvre les trois.
