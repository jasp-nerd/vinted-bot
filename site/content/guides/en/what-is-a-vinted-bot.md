---
title: "What is a Vinted bot and how does it work?"
description: "What are Vinted bots and how do they work? Alert bots, autobuy, relist and like bots explained, why none is truly zero delay, and where they run."
slug: what-is-a-vinted-bot
key: what-is-a-bot
date: 2026-10-30
updated: 2026-10-30
keywords:
  - what are vinted bots
  - how do vinted bots work
  - what is a vinted bot
  - vinted sniping bot
  - vinted monitor
  - is vinted full of bots
faq:
  - q: "What is a Vinted bot?"
    a: "A program that does something on Vinted automatically. Most often it means an alert bot that watches a search and messages you about new listings. It can also mean autobuy bots that purchase for you, or seller bots that relist, like or follow."
  - q: "How do Vinted sniping bots work?"
    a: "They load a Vinted search sorted by newest first over and over, compare the results with what they saw last time, and act on anything new: send an alert, or with autobuy, start checkout using your logged-in account."
  - q: "Are Vinted bots worth it?"
    a: "An alert bot is worth it if you hunt specific items, sizes or collectibles and Vinted's own notifications let you down, especially if it's free. Paying for autobuy rarely pays off unless you resell at volume, and it puts your account at risk."
  - q: "Is Vinted full of bots?"
    a: "In competitive categories such as consoles, phones and popular clothing at low prices, many good listings are bought within minutes by people using alerts or autobuy. In most other categories you're competing with ordinary shoppers."
---

A Vinted bot is a program that does something on Vinted automatically. Most of the time people mean an alert bot (also called a monitor or sniper) that watches a search and sends you new listings within minutes. The term also covers autobuy bots that purchase for you, and seller bots that relist items or send likes and follows. They work very differently and carry very different risks.

## The four kinds of Vinted bot

### Alert bots, monitors and snipers

These watch one or more searches and tell you when something new appears, usually on Discord or Telegram, sometimes as a phone notification. You still open the listing and buy it yourself. They don't need your Vinted account, because search results are public.

This is the kind that solves the most common complaint about Vinted: saved searches that don't notify you, or notify you late.

### Autobuy and autocop bots

These go a step further: when a listing matches, they start checkout for you. To do that they need your logged-in Vinted account and a saved payment method. They're popular with resellers going after underpriced electronics and branded clothing, and they're the expensive end of the market, with plans as of October 2026 running from about €30 up to €300 a month.

They're also where account restrictions come from. Vinted's terms prohibit automated access, and an account that checks out within seconds, again and again, is easy to spot.

### Relist, repost and bump bots

These are for sellers. They delete and re-upload listings, or bump them, so they show up as new. They need your account. The irony for buyers: relisted items are one reason "newest first" is full of things that aren't actually new.

### Like, follow and view bots

These farm attention by liking, following or viewing at scale through your account, hoping people follow back or buy. They're the riskiest kind and usually the least useful.

## How an alert bot actually works

The mechanics are simpler than the marketing suggests:

1. It opens a session with Vinted the way a browser does when you visit as a logged-out visitor.
2. It asks Vinted for your search's results, sorted by newest first.
3. It compares the listings with what it saw last time. Anything new that passes your filters becomes an alert.
4. It waits, then does it again. A sensible interval is about a minute.

Good tools also skip promoted listings (old items resurfacing), avoid alerting on everything that was already there when you added the search, and notice when Vinted stops answering or keeps serving the same results.

A detail that matters for honesty: Vinted's search results no longer say when a listing was posted. Tools work out what's new by comparing listing ids, which Vinted hands out in upload order.

## Why nothing is truly "zero delay"

French and UK Discord servers advertise "0 délai" and "instant" all the time. Here's the catch. Vinted adds new uploads to its search a few minutes after they're posted, sometimes longer. Every tool that reads the search, paid or free, sees the listing at that moment, not at the moment of upload.

When a service says "under one second", it means one second from the listing appearing in search to the alert reaching you. That's real, but it's the small part of the delay. The few minutes before it are the same for everyone, including Vinted's own notifications.

This has two consequences:

- Checking every second instead of every minute gains you very little and makes Vinted much more likely to slow your connection down.
- In the categories where people race, the winners are the ones who act fastest after a listing appears. That's usually autobuy, which is why resellers say alerts alone lose to it. More on this in [why you're never first on Vinted](/guides/why-youre-never-first-on-vinted/).

## Where Vinted bots run

### On someone else's servers

Most paid bots run on the company's servers. You get a Discord channel, a Telegram bot or an app, and pay monthly. Nothing to install, works when your computer is off.

### In shared Discord servers

Free community servers post listings from preset searches into shared channels. Easy to join, but everyone sees the same listing at the same time and you can't set your own filters.

### On your own computer

Open-source bots run on a machine you own: your laptop, a Raspberry Pi, a NAS. They're free, you control the filters, and your searches and alert links stay with you. The trade-off is that the machine has to stay on.

vinted-sniper is this kind. It's free and open source, never logs in, and sends alerts to Discord, Telegram, your phone (through the free ntfy app) or a webhook. It shows prices including buyer protection, lets you skip words and low-rated sellers, and tells you in plain words when a search stops working.

{{install}}

## Are Vinted bots worth it?

It depends on what you're after.

If you're looking for something specific (a coat in your size, a discontinued trainer, a Jellycat, a Pokémon card from a particular set), an alert bot is worth it, and a free one is the obvious start. You need to hear within minutes, not win a race measured in seconds.

If you resell underpriced electronics or hyped clothing, alerts help but won't win every race. Autobuy can, but you're paying a lot and betting your account on it. Read [are Vinted bots allowed?](/guides/are-vinted-bots-allowed/) before you decide.

If you're comparing tools, [free vs paid Vinted bots](/guides/free-vs-paid-vinted-bots/) lays out the categories and prices without a ranking.
