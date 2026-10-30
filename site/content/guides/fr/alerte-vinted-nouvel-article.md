---
title: "Alerte Vinted : être prévenu dès qu'un nouvel article est publié"
description: "Créer une alerte Vinted pour chaque nouvel article : recherche sauvegardée, membres suivis et alertes gratuites sur Discord, Telegram ou mobile, comparés."
slug: alerte-vinted-nouvel-article
key: get-notified
date: 2026-10-30
updated: 2026-10-30
keywords:
  - alerte vinted
  - créer alerte vinted
  - alerte vinted gratuit
  - vinted notification nouvel article
  - comment activer les notifications vinted
  - application alerte vinted
  - alerte vinted recherche
faq:
  - q: "Comment créer une alerte sur Vinted ?"
    a: "Faites votre recherche, appliquez vos filtres et sauvegardez la recherche avec le bouton au-dessus des résultats. Activez ensuite les notifications dans Profil, Paramètres, Notifications. Ces alertes arrivent souvent en retard : pour une alerte fiable, utilisez un outil qui consulte la recherche chaque minute."
  - q: "Comment activer les notifications Vinted ?"
    a: "Dans l'appli Vinted, allez dans Profil, Paramètres, Notifications et activez les notifications push. Sur le téléphone, autorisez les notifications de Vinted et retirez l'appli de l'optimisation de batterie et des résumés de notifications."
  - q: "Existe-t-il une application d'alerte Vinted gratuite ?"
    a: "Les applis d'alerte dédiées sont en général payantes, quelques euros par mois. Une alternative gratuite : faire tourner vinted-sniper sur un ordinateur et recevoir ses alertes dans l'appli gratuite ntfy sur votre téléphone, sans créer de compte."
  - q: "Comment avoir les notifications Vinted sur PC ?"
    a: "Vinted n'envoie pas de notifications sur ordinateur pour les recherches. Avec vinted-sniper, les alertes peuvent arriver dans Discord ou Telegram sur PC, et le tableau de bord affiche les trouvailles en direct dans votre navigateur."
---

Pour être prévenu quand un nouvel article est publié sur Vinted, il y a trois façons : sauvegarder la recherche dans l'appli Vinted, suivre les membres qui vendent ce que vous cherchez, ou utiliser un outil d'alerte qui consulte votre recherche et vous envoie un message. Les deux premières sont intégrées et gratuites mais limitées. La troisième est la seule vraiment fiable pour une recherche, et elle peut être gratuite aussi.

Voici comment fonctionne chacune, étape par étape, et quand utiliser laquelle.

## Option 1 : une recherche sauvegardée dans l'appli Vinted

C'est la méthode intégrée. Elle vaut le coup même si vous utilisez autre chose, car elle garde votre recherche à portée de main.

1. Cherchez ce que vous voulez dans l'appli ou sur le site.
2. Ajoutez vos filtres : catégorie, taille, marque, état, couleur, prix.
3. Sauvegardez la recherche avec le bouton prévu, juste au-dessus des résultats.
4. Dans l'appli, allez dans votre profil, Paramètres, Notifications, et vérifiez que les notifications pour les nouveaux articles et les recherches sauvegardées sont activées.
5. Sur votre téléphone, autorisez les notifications de Vinted et sortez l'appli de l'économie de batterie et des résumés de notifications.

Le hic : beaucoup de membres reçoivent ces notifications en retard, par paquets, ou pas du tout, même avec tout activé. Et le filtre de prix de Vinted travaille sur le prix affiché, pas sur le prix payé avec la protection acheteurs. Si vos alertes se sont tues, notre guide [notification Vinted qui ne fonctionne pas](/guides/notification-vinted-ne-fonctionne-pas/) passe en revue chaque réglage et les changements de 2026.

## Option 2 : suivre un membre

Si ce que vous cherchez vient de quelques vendeurs (une friperie qui publie chaque dimanche, une maman qui vend la taille de votre enfant, un collectionneur qui fait du tri), abonnez-vous à eux. Ouvrez leur profil et appuyez sur S'abonner. Vinted vous prévient quand ils publient, et ces notifications sont en général plus fiables que celles des recherches sauvegardées.

Mais ça ne couvre que les vendeurs que vous connaissez déjà. Ça ne vous aide pas à trouver le prochain bon vendeur.

## Option 3 : un outil d'alerte qui consulte votre recherche

Un outil d'alerte, souvent appelé bot Vinted ou moniteur, charge les annonces les plus récentes de votre recherche à intervalle régulier et vous envoie tout ce qu'il n'a pas encore vu. Vous choisissez où arrivent les messages : un salon Discord, une conversation Telegram, une notification sur votre téléphone, un e-mail.

Les services payants le font depuis leurs serveurs pour environ 5 à 30 € par mois (en octobre 2026). vinted-sniper le fait gratuitement depuis votre propre ordinateur. La mise en place ressemble à ceci :

1. Installez-le avec la commande d'une ligne de la page d'accueil. Le tableau de bord s'ouvre dans votre navigateur.
2. Collez le lien de votre recherche Vinted, ou construisez la recherche dans le tableau de bord avec les catégories, marques et tailles de Vinted.
3. Fixez la limite de prix comme le total que vous paierez (protection acheteurs comprise), et ajoutez les mots qu'un titre doit contenir ou ne doit pas contenir.
4. Choisissez où arrivent les alertes. ntfy sur le téléphone se règle en une minute, sans compte. Discord et Telegram ont leur guide : [Discord](/guides/alerte-vinted-discord/), [Telegram](/guides/bot-vinted-telegram-gratuit/).
5. Appuyez sur « Send test » (envoyer un test), vérifiez que le message arrive, c'est prêt.

Chaque alerte affiche les photos, le prix total, la taille, l'état, la marque, la note du vendeur et des boutons pour acheter, contacter le vendeur ou ouvrir l'annonce. Le premier passage d'une nouvelle recherche reste silencieux : vous n'êtes prévenu que des annonces publiées après l'ajout.

{{install}}

## Laquelle choisir ?

| | Recherche sauvegardée (Vinted) | Suivre un membre | Alerte gratuite (vinted-sniper) | Service d'alerte payant |
|---|---|---|---|---|
| Prix | Gratuit | Gratuit | Gratuit | Environ 5 à 30 € par mois |
| Fiabilité | Souvent en retard ou absente | Plutôt correcte | Vérifie chaque minute, prévient s'il s'arrête | Selon le service |
| Prix filtré frais compris | Non | Sans objet | Oui | Variable |
| Mots à exclure | Non | Non | Oui | Variable |
| Ordinateur allumé nécessaire | Non | Non | Oui | Non |
| Connexion à votre compte Vinted | Oui (c'est votre compte) | Oui | Non | Pas pour les alertes |

En résumé : suivez les vendeurs de confiance, gardez la recherche sauvegardée pour flâner, et confiez les recherches qui comptent vraiment à un outil d'alerte. Si rien ne reste allumé chez vous et que vous ne voulez rien installer, un service payant est un choix honnête. Les deux sont comparés dans [meilleur bot Vinted gratuit ou payant](/guides/meilleur-bot-vinted-gratuit/).

## Tirer le meilleur de vos alertes

### Une recherche pour être alerté, pas pour flâner

Une recherche qu'on parcourt peut être large, parce qu'on survole. Une recherche qui fait vibrer votre téléphone doit être précise. Mettez votre taille, l'état accepté et un prix total réaliste. Si vous recevez des alertes inutiles, ajoutez le mot qui revient à la liste des exclusions plutôt que de couper la recherche.

### « Ceci ou cela » au lieu de cinq recherches

« Levi's 501 ou 505 » peut tenir en une seule recherche : dans vinted-sniper, un mot obligatoire peut avoir des alternatives, écrites `501|505`. Moins de recherches, c'est moins de requêtes vers Vinted et moins de risque d'être ralenti.

### Plusieurs pays d'un coup

Chaque site Vinted national montre un mélange un peu différent de vendeurs. Une recherche vinted-sniper peut surveiller plusieurs sites, et une annonce vue sur deux d'entre eux n'est signalée qu'une fois.

### Des heures de silence

Si une alerte à 3 h du matin ne mérite pas de vous réveiller, les heures de silence gardent les alertes jusqu'au matin, les envoient sans son ou les ignorent. Au choix, recherche par recherche.

## Pourquoi aucune alerte n'est instantanée

Vinted ajoute les nouvelles annonces à sa recherche avec quelques minutes de retard. Toutes les alertes, celles de Vinted comme celles des outils tiers, ne peuvent partir qu'après. Un outil qui promet « 0 délai » mesure à partir de l'apparition dans la recherche, pas de la mise en ligne. Pour un collectionneur, quelqu'un qui cherche sa taille ou un article précis, quelques minutes suffisent. Pour l'électronique bradée que se disputent les revendeurs, souvent non : là, ce qui compte est d'avoir son moyen de paiement enregistré et d'acheter directement depuis l'alerte.
