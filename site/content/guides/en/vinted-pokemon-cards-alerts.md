---
title: "How to find Pokémon cards on Vinted before they sell"
description: "Find Pokémon cards on Vinted before they sell: search recipes for sets and graded cards, price caps with fees, spotting fakes, and free alerts."
slug: vinted-pokemon-cards-alerts
key: pokemon
date: 2026-10-30
updated: 2026-10-30
keywords:
  - vinted pokemon cards bot
  - pokemon cards vinted
  - vinted pokemon alerts
  - vinted bot pokemon
  - fake pokemon cards vinted
  - vinted trading cards
faq:
  - q: "Is there a bot for Pokémon cards on Vinted?"
    a: "Yes. Any Vinted alert bot works for Pokémon cards if you give it good searches. vinted-sniper is free: it checks your card searches every minute and sends new listings to Discord, Telegram or your phone, with words to skip like proxy or custom."
  - q: "Are Pokémon cards on Vinted fake?"
    a: "Most aren't, but fakes and proxies do turn up, especially in cheap bulk lots and high-value singles. Ask for clear photos of the front, back and edges, compare with a card you own, and check the seller's reviews."
  - q: "Is it safe to buy Pokémon cards on Vinted?"
    a: "Buying through Vinted's checkout is covered by buyer protection if an item doesn't arrive or isn't as described. Never pay outside Vinted, and be extra careful with sealed packs, which can be resealed."
---

To find Pokémon cards on Vinted before they sell, set up narrow searches for the exact sets, cards or graded slabs you want, cap them at the total price you'll pay including buyer protection, skip words like "proxy" and "custom", and get alerts that check those searches every minute. Good cards at fair prices go quickly, so relying on Vinted's saved-search notifications usually means arriving after they've sold.

## Why Pokémon cards go so fast on Vinted

Cards are small, easy to post and easy to price, which makes them attractive to resellers as well as collectors. Many sellers are parents or people clearing out childhood collections who don't check market prices. Those listings are exactly what everyone is watching for, and the good ones can sell within minutes.

On top of that, Vinted adds new uploads to its search a few minutes after they're posted. Nobody sees a listing before then. What decides who gets it is how quickly you hear about it afterwards and how fast you check out.

## Search recipes that work

The general search "pokemon" returns tens of thousands of listings, mostly toys, clothes and bulk commons. Build several narrow searches instead.

### By set

Use the set's name the way sellers write it, in the language of the Vinted site you're searching. On vinted.fr, many sellers write French set names; on vinted.de, German ones. Some examples that work across sites:

- `pokemon 151` for the Scarlet & Violet 151 set.
- `evolving skies` or `evolution celeste` (French) for Sword & Shield era chase cards.
- `prismatic evolutions` or `evolutions prismatiques` for the 2025 Eeveelution set.
- `base set` or `set de base`, plus `1st edition` or `edition 1` for vintage.

### By card

Name the Pokémon and the variant: `charizard ex`, `umbreon vmax alt`, `pikachu illustrator` (if you're very optimistic). Add the language of the card if it matters to you, such as "japanese" or "japonais".

### Graded cards

Search for the grading company and grade: `psa 10`, `psa 9`, `pca`, `cgc`, `bgs`. Combine with a Pokémon name to stay focused.

### Lots and collections

`lot cartes pokemon`, `classeur pokemon` (binder), `collection pokemon`, `bulk pokemon`. Lots from people clearing out are where the underpriced holos and vintage cards hide. These searches are noisy, so pair them with a price cap and seller filters.

### Words to skip

Add these as exclusions: `proxy`, `custom`, `fake`, `replica`, `fan art`, `sticker`, `metal` (for metal novelty cards), `empty` (empty boxes or tins), `code` (online code cards), and `figurine` or `plush` if you only want cards. Adjust to the site's language, such as `faux` on French sites.

## Price caps that include fees

Vinted's price filter uses the asking price. What you pay is the price plus buyer protection (usually €0.70 plus 5%) plus postage. On a €10 card that's €11.20 before postage; on a €100 slab it's €105.70.

When you set a cap, use the total. In vinted-sniper the price limit already includes buyer protection, so "max €40" means €40 at checkout before postage. The full maths is in [the buyer protection fee explained](/guides/vinted-buyer-protection-fee/).

A better test than a fixed cap is "under what this search usually costs". vinted-sniper learns the typical total for each search and badges listings that are clearly below it, once it has seen enough finds (15 in two weeks).

## Spotting fakes and scams

Fakes aren't everywhere, but they do show up, mostly in two places: cheap "100 cards with guaranteed holos" lots and high-value singles at prices that are too good. Before buying:

- Check the photos are of the actual card, not stock images. Ask for more if needed: front, back, edges and a close-up of the holo.
- Compare the font, colours and the back of the card with a real card you own. Fakes often have the wrong blue on the back, blurry text or a glossy finish where it should be matte.
- Be wary of cards that look too bright or too saturated.
- For sealed packs and boxes, watch for loose booster packs at low prices. Resealed packs are a known problem. Shrink-wrapped boxes from established sellers are safer.
- Look at the seller: number of reviews, rating, and whether their wardrobe looks like a real person's collection or a stream of identical "rare" cards.

You can automate the last check. vinted-sniper can skip sellers below a minimum rating or with too few reviews, skip sellers with no reviews yet, and block a seller for good.

Always buy through Vinted's checkout, so buyer protection applies. Never agree to pay a seller directly.

## Setting up Pokémon card alerts

vinted-sniper is a free, open-source app that runs on your computer, checks your Vinted searches every minute and sends new listings to Discord, Telegram or your phone. It never logs in to Vinted.

1. Install it with the one-line command from the homepage.
2. Paste each search link from Vinted, or build the search in the dashboard and pick the trading cards category.
3. Add your exclusions, a total-price cap and, for expensive cards, a minimum seller rating.
4. Send alerts somewhere fast. A Discord server with one channel per set, or a Telegram group with one topic per search, keeps things tidy. See [Discord setup](/guides/vinted-discord-alerts-webhook/) or [Telegram setup](/guides/vinted-telegram-alerts/).
5. Turn sound on only for deals, if you have many searches.

{{install}}

Each alert shows the photos, the total price, the seller's rating and Buy and Message buttons. If you're after a particular listing that's overpriced, add it to the watchlist and get told when its price drops or when it sells.

## Search more than one country

Cards are the same in every country, but sellers aren't. The same search on vinted.fr, vinted.de, vinted.it and vinted.es surfaces different listings, and cards in a given language can be easier to find, and sometimes cheaper, on that country's site. One vinted-sniper search can cover several country sites at once, and a listing seen on two of them is announced once.

## Be realistic about speed

A €2 Charizard in a lot listed by someone who doesn't know what they have will attract everyone. Alerts get you there within minutes of the listing appearing in search, but you can still lose to someone faster. You'll win far more often on less hyped sets, graded cards at fair prices and mixed lots that take a moment to read. For more on the race itself, see [why you're never first on Vinted](/guides/why-youre-never-first-on-vinted/).
