<div align="center">

[English](https://github.com/jasp-nerd/vinted-bot/blob/main/README.md) · **Français**

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/banner-dark.png">
  <img src="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/banner.png" alt="vinted-bot : des alertes pour vos recherches Vinted" width="820">
</picture>

# vinted-bot : bot Vinted gratuit pour les alertes de nouvelles annonces

**Vinted ne vous prévient pas quand votre recherche enregistrée a du nouveau. Cet outil, si.**

Collez une recherche Vinted, choisissez où recevoir les alertes, et recevez un message avec les photos<br>
et le prix que vous paierez vraiment dès qu'une nouvelle annonce apparaît. Gratuit pour toujours, open source,<br>
sur votre ordinateur, sans compte Vinted ni abonnement, là où les bots Vinted payants coûtent de 5 à 300 € par mois.

[![CI](https://github.com/jasp-nerd/vinted-bot/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/jasp-nerd/vinted-bot/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/jasp-nerd/vinted-bot?color=007782&label=version)](https://github.com/jasp-nerd/vinted-bot/releases)
[![Image du conteneur](https://img.shields.io/badge/ghcr.io-vinted--bot-2496ED?logo=docker&logoColor=white)](https://github.com/jasp-nerd/vinted-bot/pkgs/container/vinted-bot)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MIT](https://img.shields.io/badge/licence-MIT-green)](https://github.com/jasp-nerd/vinted-bot/blob/main/LICENSE)

**[Installer](#installer)** · **[Se faire aider par une IA](#se-faire-guider-par-une-ia)** · [Site web](https://vinted-bot.jaspnerd.dev) · [Documentation](#documentation) · [Signaler un problème](https://github.com/jasp-nerd/vinted-bot/issues/new/choose)

<img src="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/dashboard.png" width="820" alt="Le tableau de bord : un bandeau qui montre les recherches surveillées et l'état de chacune, puis les nouvelles trouvailles en fiches photo avec le prix frais compris, les badges de bonne affaire et la recherche qui les a trouvées">

</div>

> La version anglaise fait référence. Cette traduction peut avoir un temps de retard.

## Comment ça marche

1. **Cherchez sur Vinted** comme d'habitude et copiez le lien. Ou construisez la recherche dans le tableau de bord.
2. **Collez-le dans vinted-bot** et choisissez où vont les alertes : Discord, Telegram, votre téléphone, un e-mail.
3. **Recevez un message** pour chaque nouvelle annonce, avec les photos, le prix total protection acheteurs comprise, la taille, l'état et la note du vendeur.

L'outil vérifie chaque minute. Le premier passage est silencieux exprès : vous n'entendez parler que des annonces publiées après l'ajout de la recherche.

> [!IMPORTANT]
> Vinted a déplacé sa recherche vers une nouvelle adresse en septembre 2026, et les versions antérieures à la 2.0 ne trouvent plus rien depuis. Si vous l'aviez déjà installé, [mettez-le à jour](#mettre-à-jour).

## Installer

| Vous avez | Utilisez | Continue sans vous ? |
|---|---|---|
| Un PC Windows | [Windows](#windows) | Tant qu'il est allumé et éveillé |
| Un Mac | [macOS](#macos) | Tant qu'il est allumé et éveillé |
| Un Raspberry Pi ou une machine Linux | [Linux et Raspberry Pi](#linux-et-raspberry-pi) | Oui |
| Docker déjà installé | [Docker](#docker) | Oui, si la machine reste allumée |
| Unraid, Synology, Umbrel ou CasaOS | [NAS](#nas) | Oui |
| Rien qui reste allumé | [Cloud](#cloud), quelques euros par mois | Oui |

Les installateurs ne demandent ni droits administrateur ni Docker, et ouvrent le tableau de bord sur http://localhost:8000 à la fin. Relancez la même commande pour mettre à jour.

### Windows

Ouvrez **PowerShell** (menu Démarrer, tapez `PowerShell`, appuyez sur Entrée), collez ceci et appuyez sur Entrée :

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/install.ps1 | iex"
```

### macOS

Ouvrez le **Terminal** (Cmd+Espace, tapez `Terminal`, appuyez sur Entrée), collez ceci et appuyez sur Entrée :

```bash
curl -LsSf https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/install.sh | sh
```

### Linux et Raspberry Pi

La même commande fonctionne sur tout Linux et sur un Raspberry Pi sous Raspberry Pi OS 64 bits :

```bash
curl -LsSf https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/install.sh | sh
```

Vous préférez lire un script avant de le lancer ? Téléchargez d'abord [install.sh](https://github.com/jasp-nerd/vinted-bot/blob/main/install.sh) ou [install.ps1](https://github.com/jasp-nerd/vinted-bot/blob/main/install.ps1) ; chacun explique ses étapes en tête de fichier.

### Docker

```bash
mkdir vinted-bot && cd vinted-bot
curl -fsSLO https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docker-compose.yml
docker compose up -d
```

Ouvrez ensuite http://localhost:8000. Les images tournent sur x86 et ARM. Dans Windows PowerShell, téléchargez le fichier avec `Invoke-WebRequest <lien> -OutFile docker-compose.yml` plutôt qu'avec `curl`.

### NAS

Unraid, Umbrel, CasaOS, Synology et Portainer acceptent chacun un modèle prêt à l'emploi ou le fichier compose : voir [On a NAS](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/self-hosting.md#on-a-nas) (en anglais).

### Cloud

Un petit serveur loué ou une plateforme comme Render ou Railway fonctionne, mais aucun n'est gratuit dès qu'il doit rester allumé. Vinted refuse certaines adresses de centres de données, alors [lisez ceci d'abord](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/self-hosting.md#on-a-vps-or-a-cloud-host) (en anglais).

## Se faire guider par une IA

Vous ne savez pas par où commencer ? Copiez ceci dans ChatGPT, Claude ou Gemini, qui vous guidera étape par étape :

```text
Aide-moi à installer et configurer vinted-bot, une application gratuite et open source qui surveille mes recherches Vinted et m'envoie un message sur Discord ou Telegram quand une nouvelle annonce correspond. Réponds-moi en français.

Lis d'abord son guide d'installation : https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/llms.txt
Si tu ne peux pas ouvrir de liens, dis-le-moi et je le collerai ici.

Comment j'aimerais que tu m'aides :
- Je ne suis pas technicien. Commence par me demander quel ordinateur j'ai et s'il reste allumé.
- Donne-moi une petite étape à la fois. Dis-moi exactement où cliquer ou quoi coller, et ce que je dois voir ensuite. Attends que je te dise que ça a marché avant l'étape suivante.
- Utilise uniquement les commandes du guide. N'invente ni commandes ni réglages.
- Ne me demande jamais de coller ici mon lien de webhook Discord, mon jeton Telegram ou un mot de passe. Dis-moi plutôt où les mettre dans l'application.
- Si quelque chose ne marche pas, demande-moi le message d'erreur exact, puis aide-moi avec la partie dépannage du guide.

Une fois l'installation faite, aide-moi à ajouter ma première recherche Vinted et à vérifier qu'une alerte de test arrive.
```

Ou ouvrez-le directement : **[Ouvrir dans Claude](https://claude.ai/new?q=Aide-moi%20%C3%A0%20installer%20et%20configurer%20vinted-bot%2C%20une%20application%20gratuite%20et%20open%20source%20qui%20surveille%20mes%20recherches%20Vinted%20et%20m%27envoie%20un%20message%20sur%20Discord%20ou%20Telegram%20quand%20une%20nouvelle%20annonce%20correspond.%20R%C3%A9ponds-moi%20en%20fran%C3%A7ais.%0A%0ALis%20d%27abord%20son%20guide%20d%27installation%20%3A%20https%3A%2F%2Fraw.githubusercontent.com%2Fjasp-nerd%2Fvinted-bot%2Fmain%2Fllms.txt%0ASi%20tu%20ne%20peux%20pas%20ouvrir%20de%20liens%2C%20dis-le-moi%20et%20je%20le%20collerai%20ici.%0A%0AComment%20j%27aimerais%20que%20tu%20m%27aides%20%3A%0A-%20Je%20ne%20suis%20pas%20technicien.%20Commence%20par%20me%20demander%20quel%20ordinateur%20j%27ai%20et%20s%27il%20reste%20allum%C3%A9.%0A-%20Donne-moi%20une%20petite%20%C3%A9tape%20%C3%A0%20la%20fois.%20Dis-moi%20exactement%20o%C3%B9%20cliquer%20ou%20quoi%20coller%2C%20et%20ce%20que%20je%20dois%20voir%20ensuite.%20Attends%20que%20je%20te%20dise%20que%20%C3%A7a%20a%20march%C3%A9%20avant%20l%27%C3%A9tape%20suivante.%0A-%20Utilise%20uniquement%20les%20commandes%20du%20guide.%20N%27invente%20ni%20commandes%20ni%20r%C3%A9glages.%0A-%20Ne%20me%20demande%20jamais%20de%20coller%20ici%20mon%20lien%20de%20webhook%20Discord%2C%20mon%20jeton%20Telegram%20ou%20un%20mot%20de%20passe.%20Dis-moi%20plut%C3%B4t%20o%C3%B9%20les%20mettre%20dans%20l%27application.%0A-%20Si%20quelque%20chose%20ne%20marche%20pas%2C%20demande-moi%20le%20message%20d%27erreur%20exact%2C%20puis%20aide-moi%20avec%20la%20partie%20d%C3%A9pannage%20du%20guide.%0A%0AUne%20fois%20l%27installation%20faite%2C%20aide-moi%20%C3%A0%20ajouter%20ma%20premi%C3%A8re%20recherche%20Vinted%20et%20%C3%A0%20v%C3%A9rifier%20qu%27une%20alerte%20de%20test%20arrive.)** · **[Ouvrir dans ChatGPT](https://chatgpt.com/?q=Aide-moi%20%C3%A0%20installer%20et%20configurer%20vinted-bot%2C%20une%20application%20gratuite%20et%20open%20source%20qui%20surveille%20mes%20recherches%20Vinted%20et%20m%27envoie%20un%20message%20sur%20Discord%20ou%20Telegram%20quand%20une%20nouvelle%20annonce%20correspond.%20R%C3%A9ponds-moi%20en%20fran%C3%A7ais.%0A%0ALis%20d%27abord%20son%20guide%20d%27installation%20%3A%20https%3A%2F%2Fraw.githubusercontent.com%2Fjasp-nerd%2Fvinted-bot%2Fmain%2Fllms.txt%0ASi%20tu%20ne%20peux%20pas%20ouvrir%20de%20liens%2C%20dis-le-moi%20et%20je%20le%20collerai%20ici.%0A%0AComment%20j%27aimerais%20que%20tu%20m%27aides%20%3A%0A-%20Je%20ne%20suis%20pas%20technicien.%20Commence%20par%20me%20demander%20quel%20ordinateur%20j%27ai%20et%20s%27il%20reste%20allum%C3%A9.%0A-%20Donne-moi%20une%20petite%20%C3%A9tape%20%C3%A0%20la%20fois.%20Dis-moi%20exactement%20o%C3%B9%20cliquer%20ou%20quoi%20coller%2C%20et%20ce%20que%20je%20dois%20voir%20ensuite.%20Attends%20que%20je%20te%20dise%20que%20%C3%A7a%20a%20march%C3%A9%20avant%20l%27%C3%A9tape%20suivante.%0A-%20Utilise%20uniquement%20les%20commandes%20du%20guide.%20N%27invente%20ni%20commandes%20ni%20r%C3%A9glages.%0A-%20Ne%20me%20demande%20jamais%20de%20coller%20ici%20mon%20lien%20de%20webhook%20Discord%2C%20mon%20jeton%20Telegram%20ou%20un%20mot%20de%20passe.%20Dis-moi%20plut%C3%B4t%20o%C3%B9%20les%20mettre%20dans%20l%27application.%0A-%20Si%20quelque%20chose%20ne%20marche%20pas%2C%20demande-moi%20le%20message%20d%27erreur%20exact%2C%20puis%20aide-moi%20avec%20la%20partie%20d%C3%A9pannage%20du%20guide.%0A%0AUne%20fois%20l%27installation%20faite%2C%20aide-moi%20%C3%A0%20ajouter%20ma%20premi%C3%A8re%20recherche%20Vinted%20et%20%C3%A0%20v%C3%A9rifier%20qu%27une%20alerte%20de%20test%20arrive.)**

## Ce que vous obtenez

<table>
<tr>
<td width="50%" valign="top">

**Trouver les bonnes annonces**

- Des limites de prix sur ce que vous payez vraiment, protection acheteurs comprise. Le filtre de Vinted ignore ces frais.
- Les mots que le titre doit contenir (avec des variantes comme `501|505`) et ceux à écarter.
- Un badge quand une annonce est nettement sous le prix habituel de la recherche, et une option « bonnes affaires seulement ».
- La note du vendeur, son nombre d'avis et son pays. Bloquez un vendeur pour de bon.
- Une recherche sur plusieurs sites nationaux, et des heures calmes qui gardent les alertes jusqu'au matin.

</td>
<td width="50%" valign="top">

**Être prévenu**

- Des fiches Discord avec la galerie photo, le prix total et les boutons Acheter, Contacter et Voir.
- Des fiches photo Telegram, plus `/list`, `/pause` et `/add` pour gérer vos recherches depuis la conversation.
- Des notifications ntfy sur votre téléphone, sans compte.
- E-mail, Slack, Pushover, Gotify, Matrix et d'autres grâce à [Apprise](https://github.com/caronc/apprise).
- Des flux RSS et des webhooks JSON signés pour vos propres automatisations.

</td>
</tr>
<tr>
<td valign="top">

**Le tableau de bord**

- Un fil des trouvailles en direct, comme la grille de Vinted : garder, masquer, bloquer le vendeur.
- Une mise en route au premier lancement : collez un lien ou construisez la recherche, puis envoyez une alerte de test.
- Aucun fichier de réglages à modifier : le bot Telegram, un mot de passe et l'accès depuis votre téléphone se règlent dans le tableau de bord.
- « Non envoyées » : chaque annonce écartée, avec la raison.
- Une liste de suivi pour les baisses de prix et les articles vendus, et pour les nouveautés d'un vendeur.
- Des statistiques : trouvailles par jour, heures les plus actives, délai des alertes.

</td>
<td valign="top">

**Rester fiable**

- **Il vous prévient quand il ne marche plus.** Chaque recherche dit en clair comment elle va, et une surveillance repère quand Vinted se tait et renouvelle la session d'elle-même.
- Aucune alerte perdue ni en double : chacune est enregistrée avant l'envoi, et envoyée une seule fois.
- Pas de compte Vinted, pas de connexion : aucun compte à perdre.
- Pas de déluge de vieilles annonces quand vous ajoutez une recherche.

</td>
</tr>
</table>

## Les alertes

<table>
<tr>
<td align="center" valign="top"><img src="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/alert-discord.png" height="420" alt="Une alerte Discord pour un jean Levi's 501 : trois photos, le prix total de 23,80 € avec un badge bonne affaire à 24 % sous le prix habituel, le prix demandé plus la protection acheteurs, taille, état, marque, note du vendeur, et les boutons Buy, Message seller, Open on Vinted et eBay sold"><br><sub><b>Discord</b></sub></td>
<td align="center" valign="top"><img src="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/alert-telegram.png" height="420" alt="La même alerte dans Telegram : la photo, le prix total et la note de bonne affaire, le titre, la taille, l'état, la marque, la note du vendeur, le site et l'heure, avec un bouton vert Buy, un bouton bleu Open on Vinted et des boutons Mute et Hide"><br><sub><b>Telegram</b></sub></td>
<td align="center" valign="top"><img src="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/phone.png" height="420" alt="Le tableau de bord sur téléphone : les recherches surveillées, les filtres et les dernières trouvailles en fiches photo, avec une barre d'onglets en bas"><br><sub><b>Le tableau de bord sur téléphone</b></sub></td>
</tr>
</table>

<sub>Les alertes sont rédigées dans la langue du site de l'annonce : en français pour vinted.fr ou vinted.be.</sub>

<details>
<summary>Plus de captures d'écran</summary>
<br>
<img src="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/setup.png" width="820" alt="La mise en route : une première recherche construite avec des mots, une catégorie, une marque, des tailles, un état et un prix maximum, à côté du nombre d'annonces correspondantes et de ce que chaque filtre a retiré">
<br><sub>Une première recherche, avec en direct le nombre d'annonces qu'elle trouverait</sub>
<br><br>
<img src="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/stats.png" width="820" alt="La page de statistiques : trouvailles, alertes envoyées, délai médian entre l'annonce et l'alerte, taux de livraison, trouvailles par jour, une carte des jours et des heures et la rapidité des alertes">
<br><sub>Les statistiques</sub>
</details>

## Mettre à jour

- **Installateur :** cliquez sur **Update now** quand le tableau de bord annonce une nouvelle version, ou relancez la commande d'installation. Dans Settings, Updates, il peut aussi installer les nouvelles versions tout seul, la nuit.
- **Docker :** `docker compose pull && docker compose up -d`
- **Magasins d'applications des NAS :** le bouton de mise à jour du magasin.

Vos recherches sont conservées, et les changements de base de données s'appliquent tout seuls au démarrage. Le détail est dans le [journal des modifications](https://github.com/jasp-nerd/vinted-bot/blob/main/CHANGELOG.md).

## Questions fréquentes

**Mon compte Vinted risque-t-il d'être banni ?** L'outil ne se connecte jamais, donc aucun compte n'est en jeu. Vinted peut en revanche cesser de répondre à votre adresse internet pendant un moment si elle l'interroge trop souvent. L'outil ralentit alors de lui-même, et le tableau de bord vous le dit.

**C'est vraiment gratuit ?** Oui. Licence MIT, pas d'offre payante, pas d'inscription. Les services d'alertes Vinted payants coûtent à partir d'environ 5 € par mois, et certains jusqu'à 300 €.

**Mon ordinateur doit-il rester allumé ?** Oui. Les alertes partent de la machine où il tourne, donc elles s'arrêtent quand elle se met en veille. Un Raspberry Pi, un NAS ou un vieux portable branché en permanence règle la question : voir [le guide d'hébergement](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/self-hosting.md) (en anglais).

**Pourquoi ce n'est pas instantané ?** Vinted ajoute les nouvelles annonces à sa recherche quelques minutes après leur mise en ligne, donc tout outil qui lit la recherche, payant ou gratuit, les voit à ce moment-là. Vérifier plus souvent n'y change rien. C'est assez rapide pour les collectionneurs et ceux qui cherchent une taille précise, pas pour rivaliser avec les robots d'achat automatique.

**Est-ce autorisé ?** Les conditions de Vinted interdisent l'accès automatisé : à vous de juger. L'outil lit des annonces publiques comme un visiteur non connecté, sans se presser. Plus de détails dans [docs/legal.md](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/legal.md) (en anglais).

## Documentation

En anglais :

- [Running it somewhere](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/self-hosting.md) : votre ordinateur, un Raspberry Pi, Docker, un NAS, un serveur dans le cloud, sauvegardes et mises à jour.
- [Configuration](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/configuration.md) : tous les réglages, la ligne de commande, chaque type de destination et le mot de passe du tableau de bord. Rien n'est nécessaire pour démarrer.
- [Troubleshooting](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/troubleshooting.md) : rien n'arrive, « stale », les 403, et le test en une ligne qui montre si Vinted répond à votre connexion.
- [How it works](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/architecture.md) et [les règles](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/legal.md), pour les curieux.
- [llms.txt](https://github.com/jasp-nerd/vinted-bot/blob/main/llms.txt) : le guide d'installation que lit un assistant IA.

## Contribuer

Les rapports de bug avec le journal joint sont les plus utiles : le [formulaire](https://github.com/jasp-nerd/vinted-bot/issues/new/choose) demande ce qu'il faut. Pour le code, voir [CONTRIBUTING.md](https://github.com/jasp-nerd/vinted-bot/blob/main/CONTRIBUTING.md). Les problèmes de sécurité passent par [SECURITY.md](https://github.com/jasp-nerd/vinted-bot/blob/main/SECURITY.md).

## Soutenir le projet

C'est gratuit, sans publicité, et ça le restera. Si l'outil vous a fait dénicher une bonne affaire, vous pouvez m'offrir un café ou [le sponsoriser sur GitHub](https://github.com/sponsors/jasp-nerd). Une étoile aide aussi d'autres personnes à le trouver.

[![Me soutenir sur Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/jaspnerd)

---

<sub>Outil open source indépendant. Sans affiliation avec Vinted. Il lit des annonces publiques de façon anonyme et ne se connecte jamais, n'achète rien et ne publie rien ; acheter à votre place n'est volontairement pas une fonction. Licence MIT.</sub>
