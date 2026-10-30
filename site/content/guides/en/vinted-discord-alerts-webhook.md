---
title: "Vinted alerts on Discord: set up a webhook in 2 minutes"
description: "Get Vinted alerts on Discord for free: create a server, copy a webhook URL on desktop or phone, connect it to a Vinted bot and set up notifications."
slug: vinted-discord-alerts-webhook
key: discord
date: 2026-10-30
updated: 2026-10-30
keywords:
  - vinted alert discord
  - vinted bot discord
  - vinted bot discord free
  - discord webhook url
  - vinted webhook url
  - vinted monitor discord
faq:
  - q: "How do I get a Discord webhook URL?"
    a: "On a server where you can manage channels, open the channel's settings (Edit Channel), go to Integrations, then Webhooks, then New Webhook, and press Copy Webhook URL. On a phone, long-press the channel name to reach Edit Channel."
  - q: "Can I create a Discord webhook on my phone?"
    a: "Yes. Long-press the channel, tap Edit Channel, Integrations, Webhooks, New Webhook, then tap the new webhook and Copy Webhook URL."
  - q: "Do I need to invite a bot to my Discord server for Vinted alerts?"
    a: "Not with a webhook. A webhook only lets something post into one channel, so there is nothing to invite and nothing with access to the rest of your server."
  - q: "Why can't I create a webhook in a Discord server?"
    a: "You need the Manage Webhooks permission, which on someone else's server usually means being an admin. Making your own server is free and takes under a minute."
---

To get Vinted alerts on Discord, you need a Discord webhook URL: a private link that lets an app post into one channel. Create a server (free), open the channel's settings, go to Integrations, then Webhooks, then New Webhook, and copy the URL. Paste it into your Vinted bot and send a test. With vinted-bot the whole thing is free and takes about two minutes.

## Why a webhook and not a Discord bot

A webhook is a one-way door into a single channel. Whatever has the URL can post messages there and nothing else: it can't read your messages, see other channels or join voice. You don't invite anything to your server.

That makes it the simplest and safest way to get alerts. The one thing to remember: anyone who has the URL can post in that channel, so treat it like a password. Don't paste it into chats, screenshots or AI assistants.

## Step 1: make your own server

You can only create webhooks where you're allowed to manage the channel. On a friend's server that means they'd have to make you an admin, so it's easier to have your own.

On a computer:

1. In Discord, click the + at the bottom of the server list on the left.
2. Choose Create My Own, then For me and my friends.
3. Give it a name, for example "Vinted finds", and click Create.

On a phone, it's the same: tap the + in the server list, Create My Own, For me and my friends, name it, Create.

Your new server comes with a #general channel. You can use that, or create a channel per search, such as #jackets and #pokemon, so you can mute or prioritise them separately.

## Step 2: create the webhook and copy its URL

### On a computer

1. Hover over the channel you want alerts in and click the cog next to its name (Edit Channel).
2. Click Integrations in the left menu.
3. Click Webhooks, then New Webhook. Discord creates one with a random name like "Captain Hook".
4. Click the webhook to expand it. Optionally rename it, for example "Vinted alerts".
5. Click Copy Webhook URL.

### On a phone

1. Long-press the channel name and tap Edit Channel.
2. Tap Integrations, then Webhooks, then New Webhook.
3. Tap the new webhook to open it, then tap Copy Webhook URL.

The URL starts with `https://discord.com/api/webhooks/` followed by two long codes. If what you copied doesn't start that way, you copied something else, often the channel link.

A small trap: Discord refuses webhook names that contain the word "discord". If renaming fails, that's why.

## Step 3: paste it into vinted-bot

vinted-bot is a free, open-source app that watches your Vinted searches and sends new listings to places like Discord. After installing it, the dashboard opens at `http://localhost:8000`.

1. Open the Alerts page and add a new place for alerts.
2. Choose Discord and paste the webhook URL.
3. Press Send test. A test message should appear in your channel within a few seconds.

Then add a search: paste a Vinted search link or build one in the dashboard, set your price limit and words to skip, and choose which places that search sends to. A search you haven't pointed anywhere goes to every place you've added.

{{install}}

## What a Vinted alert looks like in Discord

Each new listing arrives as a card in the channel:

- The photo gallery of the listing.
- The total price you'd pay, buyer protection included, with the asking price underneath.
- A deal badge when it's clearly under the typical price for that search, for example "24% under typical".
- Size, condition, brand, and the seller's rating with their number of reviews.
- Buttons to Buy, Message the seller and Open on Vinted.

There's a compact style too, if you'd rather see more listings per screen. You can also have it mention a role for the best deals only, so your phone only buzzes loudly for bargains.

## Step 4: get notified on your phone

Discord notifications are where most "I never got the alert" problems come from, so it's worth two minutes.

1. In the Discord app on your phone, long-press your server's icon, tap Notifications, and set it to All Messages.
2. If you created one channel per search, you can long-press a channel and set its own notification level, for example All Messages for #pokemon and Nothing for a noisy search.
3. On iPhone, allow Discord notifications in Settings, Notifications, Discord, and make sure Focus modes allow it.
4. On Android, allow notifications for Discord and set its battery use to unrestricted, so the phone doesn't hold notifications back.
5. If you're signed in on a computer at the same time, Discord may hold back phone notifications while you're active there. In Discord's settings under Notifications, you can change how long it waits before sending to your phone.

## If messages stop arriving

### The webhook was deleted

If someone deletes the webhook or the channel, Discord tells vinted-bot it no longer exists, and the app switches that destination off. That's deliberate: sending repeatedly to a dead webhook is what gets an address rate-limited by Discord itself. Create a new webhook and add it again.

### The URL got out

If you pasted the URL somewhere public, delete that webhook in Discord (Edit Channel, Integrations, Webhooks) and make a new one. The old URL stops working immediately.

### The search is working but finds nothing

Check the price limit. It includes buyer protection, so a limit of €20 rejects a €19 listing that costs €20.65 to buy. The dashboard keeps a list of skipped listings with the reason, which answers most "why didn't I get this one?" questions.

## Prefer Telegram?

Discord is the default for many people in France, the UK and the Netherlands, but Telegram is just as good and is the first choice in Italy and much of Germany. If you don't use Discord at all, see [Vinted alerts on Telegram](/guides/vinted-telegram-alerts/), or skip both and use a phone notification through the free ntfy app, which needs no account. The [free Vinted bot guide](/guides/free-vinted-bot/) covers the full setup.
