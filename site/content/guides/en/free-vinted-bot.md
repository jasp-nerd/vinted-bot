---
title: "Free Vinted bot: get alerts for new listings without paying"
description: "A free Vinted bot that sends new listings from your searches to Discord, Telegram or your phone. No subscription, no Vinted login. Setup and limits."
slug: free-vinted-bot
key: free-bot
date: 2026-10-30
updated: 2026-10-30
keywords:
  - vinted bot free
  - free vinted bot
  - free vinted bot uk
  - vinted alert bot
  - vinted monitor bot free
  - vinted bot github
faq:
  - q: "Is there a free Vinted bot?"
    a: "Yes. vinted-sniper is free and open source (MIT licence) with no paid tier. It watches your Vinted searches and sends new listings to Discord, Telegram, ntfy on your phone or a webhook. It runs on your own computer, so that computer has to stay on."
  - q: "Do free Vinted bots need my Vinted login?"
    a: "An alert bot doesn't. Reading search results works as a logged-out visitor. Only tools that buy, message or relist for you need your account, and those are the ones that put it at risk."
  - q: "What's the catch with a free Vinted bot?"
    a: "With vinted-sniper it's that you run it yourself: alerts only arrive while the machine it runs on is on and online. Paid services run on their servers. Neither can be instant, because Vinted shows new listings to its search a few minutes late."
  - q: "Can a free Vinted bot buy items for me?"
    a: "Not this one. Buying automatically needs your logged-in account, which is where account restrictions come from. vinted-sniper puts a Buy button in each alert instead, so the purchase is still yours."
---

Yes, you can get a Vinted bot for free. vinted-sniper is a free, open-source app that watches your Vinted searches and sends every new listing to Discord, Telegram or your phone, with the price you'd actually pay. It runs on your own computer instead of someone's server, which is why it costs nothing, and it never asks for your Vinted login.

Below: what people mean by "Vinted bot", which free options exist, how to set one up in about ten minutes, and the limits you should know before you rely on it.

## What "Vinted bot" usually means

The word covers very different tools, and the difference matters for both price and risk.

An alert bot (also called a monitor or sniper) watches a search and tells you when something new appears. You still open the listing and buy it yourself. This is what most people want when Vinted's own saved-search notifications let them down.

An autobuy bot logs in as you and checks out the moment a listing matches. These are the expensive ones, and they need your account and payment details.

Relist, like and follow bots are for sellers. They bump listings or farm attention, again through your logged-in account.

This guide is about alert bots. If you want the full breakdown, see [what a Vinted bot is and how it works](/guides/what-is-a-vinted-bot/).

## The free options, honestly compared

### Vinted's own saved searches

Free and built in. You save a search and Vinted is supposed to notify you about new matches. In practice a lot of people get late notifications or none, and the price filter ignores the buyer protection fee. We go through the reasons in [why Vinted saved search notifications don't work](/guides/vinted-saved-search-notifications-not-working/).

### Free trials and free tiers of paid bots

Several Telegram and app-based services let you try one search for free, then charge roughly €5 to €30 a month (as of October 2026). Fine for a test, limited for real use.

### Free community Discord servers

Shared channels that post listings for popular categories. You get what everyone else in the server gets, at the same moment, with no control over the filters.

### Open-source tools you run yourself

Free with no limits on searches, but you need a computer that stays on. vinted-sniper is one of these. Its focus is on being easy to install and telling you when it stops working, which is the most common complaint about free bots.

## Why vinted-sniper is free

There's no server on our side. The app runs on your laptop, desktop, Raspberry Pi or NAS, checks your searches from your own internet connection, and sends alerts from there. No hosting costs means nothing to charge for. The code is on GitHub under the MIT licence, so anyone can read exactly what it does.

What you get for free:

- Alerts on Discord, Telegram, ntfy (a free phone notification app, no account needed), RSS or your own webhook. Email and services like Slack or Pushover work through an optional add-on.
- The total price in every alert, buyer protection included, and price limits that use that total. Vinted's own price filter ignores the fee (more in [the buyer protection fee explained](/guides/vinted-buyer-protection-fee/)).
- Words a title must contain and words to skip, so "for parts" or "box only" never reach you.
- Seller filters: minimum rating, minimum number of reviews, seller country, and a block button.
- A deal badge when a listing is well under what that search usually finds.
- One search across several Vinted country sites, quiet hours, and a dashboard with a live feed of finds.
- A plain-words status for every search, so you know when Vinted is slowing it down or when it's stuck.

## Set it up in five steps

1. Install it. On Windows, open PowerShell and paste the one-line command from the homepage; on a Mac or Linux, open Terminal and paste the other one. No admin rights and no Docker needed. When it finishes, your browser opens the dashboard at `http://localhost:8000`.
2. Search on Vinted the way you normally do (words, category, size, brand, condition) and copy the address from the browser bar, or share the search from the app and copy the link. You can also build the search inside the dashboard, using Vinted's own categories and brand list.
3. Paste it into the dashboard. You'll see a live count of how many current listings match and how many each filter removes. Set the maximum price as the total you're willing to pay.
4. Choose where alerts go. The quickest is a notification on your phone with the free ntfy app: install it, add the topic name the dashboard shows you, done. For Discord or Telegram, follow the [Discord webhook guide](/guides/vinted-discord-alerts-webhook/) or the [Telegram bot guide](/guides/vinted-telegram-alerts/). Send a test alert before moving on.
5. Leave it running. The first check is silent on purpose, so you don't get a flood of listings that were already there. From then on, each new match arrives as a message with photos, the total price, size, condition, seller rating and Buy, Message and Open buttons.

{{install}}

## The limits, before you rely on it

### The computer has to stay on

Alerts come from the machine it runs on. A laptop that sleeps sends nothing while asleep. On Windows, set sleep to "Never" while plugged in; the Mac installer offers to keep the Mac awake while it's plugged in. For round-the-clock alerts, a Raspberry Pi, a NAS or an old laptop left plugged in works well, and uses little power.

### It isn't instant, and nothing is

Vinted adds new listings to its search a few minutes after they're uploaded. Every tool that reads the search, paid or free, sees them at that point. vinted-sniper checks every minute by default. Checking faster finds nothing sooner and gets your connection slowed down. If you're racing autobuy bots for underpriced consoles, no alert tool will win that race. If you're hunting a specific size, brand or collectible, a minute is plenty. [Why you're never first on Vinted](/guides/why-youre-never-first-on-vinted/) covers this in detail.

### Your internet connection matters

Vinted challenges some datacenter and VPN addresses more than home connections. Running it at home is usually the most reliable option. If Vinted does slow you down, the app backs off by itself and the dashboard tells you.

### It doesn't buy for you

That's deliberate. Buying automatically needs your logged-in account, and that's how accounts get restricted. See [are Vinted bots allowed?](/guides/are-vinted-bots-allowed/) for where the real risk lies.

## Free or paid: which is right for you?

If you have a computer that's on most of the day, or a Pi or NAS, the free route does what a €5 to €30 a month alert service does. If you have nothing that stays on and don't want to install anything, a paid service is a fair choice, since it runs on their servers. We compare both without a ranking in [free vs paid Vinted bots](/guides/free-vs-paid-vinted-bots/).
