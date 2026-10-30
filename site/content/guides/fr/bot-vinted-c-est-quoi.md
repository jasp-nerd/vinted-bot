---
title: "Bot Vinted, c'est quoi et comment ça marche ?"
description: "Bot Vinted, c'est quoi ? Bots d'alerte, d'achat automatique, de republication et de likes : comment ils marchent et pourquoi le 0 délai n'existe pas."
slug: bot-vinted-c-est-quoi
key: what-is-a-bot
date: 2026-10-30
updated: 2026-10-30
keywords:
  - bot vinted c'est quoi
  - bot vinted comment ça marche
  - bot vinted explication
  - bot vinted 0 délai
  - bot vinted autobuy
faq:
  - q: "C'est quoi un bot Vinted ?"
    a: "Un programme qui fait quelque chose sur Vinted automatiquement. Le plus souvent, c'est un bot d'alerte qui surveille une recherche et vous envoie les nouvelles annonces. Le mot désigne aussi les bots d'achat automatique et les bots pour vendeurs (republication, likes, abonnements)."
  - q: "Comment marche un bot Vinted ?"
    a: "Il charge une recherche Vinted triée par plus récents, encore et encore, compare les résultats avec ce qu'il a vu la fois précédente et agit sur ce qui est nouveau : envoyer une alerte ou, pour un bot d'achat automatique, lancer l'achat avec votre compte connecté."
  - q: "Un bot Vinted 0 délai, c'est vrai ?"
    a: "Non. Vinted ajoute les nouvelles annonces à sa recherche quelques minutes après leur publication. Le « 0 délai » ou « moins d'une seconde » se mesure entre l'apparition dans la recherche et l'alerte, pas depuis la mise en ligne."
  - q: "Un bot Vinted, ça vaut le coup ?"
    a: "Un bot d'alerte vaut le coup si vous cherchez des articles, des tailles ou des pièces de collection précises et que les notifications de Vinted vous déçoivent, surtout s'il est gratuit. Payer pour de l'achat automatique se justifie rarement hors revente à gros volume, et expose votre compte."
---

Un bot Vinted, c'est un programme qui fait quelque chose sur Vinted automatiquement. La plupart du temps, on parle d'un bot d'alerte (aussi appelé moniteur) qui surveille une recherche et vous envoie les nouvelles annonces en quelques minutes. Le terme recouvre aussi les bots d'achat automatique, qui achètent à votre place, et les bots pour vendeurs qui republient des annonces ou distribuent likes et abonnements. Ils fonctionnent très différemment et ne présentent pas du tout les mêmes risques.

## Les quatre types de bots Vinted

### Les bots d'alerte et moniteurs

Ils surveillent une ou plusieurs recherches et vous préviennent quand une nouvelle annonce apparaît, en général sur Discord ou Telegram, parfois par notification sur le téléphone. Vous ouvrez l'annonce et vous achetez vous-même. Ils n'ont pas besoin de votre compte Vinted, puisque les résultats de recherche sont publics.

C'est le type de bot qui répond au reproche le plus courant fait à Vinted : des recherches sauvegardées qui ne préviennent pas, ou trop tard.

### Les bots d'achat automatique (autobuy, autocop)

Ils vont plus loin : quand une annonce correspond, ils lancent l'achat pour vous. Pour cela, ils ont besoin de votre compte Vinted connecté et d'un moyen de paiement enregistré. Ils sont populaires chez les revendeurs qui chassent l'électronique et les marques bradées, et ce sont les plus chers du marché : en octobre 2026, les formules vont d'environ 30 € jusqu'à 300 € par mois.

C'est aussi d'eux que viennent les restrictions de compte. Les conditions de Vinted interdisent l'accès automatisé, et un compte qui passe commande en quelques secondes, encore et encore, se repère facilement.

### Les bots de republication et de remontée

Ils servent aux vendeurs : ils suppriment et remettent en ligne les annonces, ou les remontent, pour qu'elles apparaissent comme nouvelles. Ils ont besoin de votre compte. L'ironie pour les acheteurs : les annonces republiées sont l'une des raisons pour lesquelles le tri par plus récents est plein d'articles qui n'ont rien de nouveau.

### Les bots de likes, d'abonnements et de vues

Ils cherchent à attirer l'attention en likant, en s'abonnant ou en consultant en masse depuis votre compte, dans l'espoir que les gens s'abonnent en retour ou achètent. Ce sont les plus risqués et en général les moins utiles.

## Comment marche un bot d'alerte, concrètement

Le fonctionnement est plus simple que ce que le marketing laisse croire :

1. Il ouvre une session avec Vinted, comme le fait un navigateur quand vous visitez le site sans être connecté.
2. Il demande à Vinted les résultats de votre recherche, triés par plus récents.
3. Il compare les annonces avec celles qu'il a vues la fois précédente. Tout ce qui est nouveau et passe vos filtres devient une alerte.
4. Il attend, puis recommence. Un intervalle raisonnable, c'est environ une minute.

Les bons outils ignorent aussi les annonces mises en avant (des articles anciens qui remontent), évitent d'alerter sur tout ce qui existait déjà quand vous avez ajouté la recherche, et remarquent quand Vinted cesse de répondre ou renvoie toujours les mêmes résultats.

Un détail qui compte : les résultats de recherche de Vinted n'indiquent plus la date de publication d'une annonce. Les outils déduisent ce qui est nouveau en comparant les numéros d'annonce, que Vinted attribue dans l'ordre de mise en ligne.

## Pourquoi le « 0 délai » n'existe pas

Les serveurs Discord qui promettent un bot Vinted « 0 délai » ou « instantané » sont partout. Voici le piège. Vinted ajoute les nouvelles annonces à sa recherche quelques minutes après leur publication, parfois plus. Tout outil qui lit la recherche, payant ou gratuit, voit l'annonce à ce moment-là, pas au moment de la mise en ligne.

Quand un service annonce « moins d'une seconde », il parle du temps entre l'apparition de l'annonce dans la recherche et l'alerte sur votre téléphone. C'est réel, mais c'est la petite partie du délai. Les quelques minutes d'avant sont les mêmes pour tout le monde, notifications de Vinted comprises.

Deux conséquences :

- Vérifier chaque seconde au lieu de chaque minute ne fait presque rien gagner, et augmente nettement le risque que Vinted ralentisse votre connexion.
- Dans les catégories où ça se bat, ceux qui gagnent sont ceux qui réagissent le plus vite une fois l'annonce apparue. C'est souvent l'achat automatique, d'où l'avis des revendeurs : les alertes seules perdent contre lui.

## Où tournent les bots Vinted

### Sur les serveurs de quelqu'un d'autre

La plupart des bots payants tournent sur les serveurs de la société. Vous recevez un salon Discord, un bot Telegram ou une appli, et vous payez chaque mois. Rien à installer, ça marche même quand votre ordinateur est éteint.

### Dans des serveurs Discord partagés

Les serveurs communautaires gratuits publient les annonces de recherches prédéfinies dans des salons partagés. Facile à rejoindre, mais tout le monde voit la même annonce au même moment et vous ne choisissez pas vos filtres.

### Sur votre propre ordinateur

Les bots open source tournent sur une machine à vous : votre portable, un Raspberry Pi, un NAS. Ils sont gratuits, vous réglez tous les filtres, et vos recherches et liens d'alerte restent chez vous. La contrepartie : la machine doit rester allumée.

vinted-bot est de ce type. Il est gratuit et open source, ne se connecte jamais à Vinted et envoie les alertes sur Discord, Telegram, votre téléphone (via l'appli gratuite ntfy) ou un webhook. Il affiche les prix protection acheteurs comprise, permet d'exclure des mots et les vendeurs mal notés, et vous dit en clair quand une recherche ne fonctionne plus.

{{install}}

## Un bot Vinted, ça vaut le coup ?

Tout dépend de ce que vous cherchez.

Si vous cherchez quelque chose de précis (un manteau à votre taille, une paire de baskets introuvable, une peluche Jellycat, une carte Pokémon d'une extension donnée), un bot d'alerte vaut le coup, et commencer par un gratuit est logique. Il vous faut être prévenu en quelques minutes, pas gagner une course à la seconde. Pour les cartes, voyez [bot Vinted Pokémon](/guides/bot-vinted-pokemon/).

Si vous revendez de l'électronique bradée ou des vêtements très demandés, les alertes aident mais ne gagneront pas toutes les courses. L'achat automatique peut le faire, mais vous payez cher et vous misez votre compte. Lisez [bot Vinted : légal, interdit, risque de ban ?](/guides/bot-vinted-legal-ban/) avant de décider, et [achat-revente sur Vinted](/guides/achat-revente-vinted/) pour le calcul des marges.

Pour comparer les outils, [meilleur bot Vinted gratuit ou payant](/guides/meilleur-bot-vinted-gratuit/) présente les catégories et les prix, sans classement. Et pour installer directement la version gratuite, suivez le [guide du bot Vinted gratuit](/guides/bot-vinted-gratuit/).
