---
title: "Vinted alerts on Telegram, no Discord needed"
description: "Set up a free Vinted bot on Telegram: create your own bot with BotFather, connect your chat or group, and get new listings with photos and the full price."
slug: vinted-telegram-alerts
key: telegram
date: 2026-10-30
updated: 2026-10-30
keywords:
  - vinted bot telegram
  - vinted telegram bot free
  - vinted tracker bot telegram
  - vinted monitor bot telegram
  - telegram botfather token
  - vinted alerts without discord
faq:
  - q: "Is there a free Vinted bot on Telegram?"
    a: "Yes. With vinted-bot you create your own private Telegram bot in about three minutes and it sends you new listings from your Vinted searches. It's free and open source, with no limit on searches."
  - q: "How do I get a Telegram bot token?"
    a: "Open Telegram, search for BotFather (the official one has a blue tick), send /newbot, choose a display name and a username ending in bot. BotFather replies with a token: numbers, a colon, then a long code."
  - q: "Do I need my Telegram chat ID?"
    a: "Not with vinted-bot. The dashboard gives you a one-time code, you send it to your bot, and the app works out the chat for you. This also works for groups and forum topics."
  - q: "Why doesn't my Telegram bot send me anything?"
    a: "A Telegram bot can't message you first; you have to start the chat. Make sure you pressed Start in the chat with your bot, that the bot token is set and the app restarted, and for a group, that the bot was added to the group."
---

You can get Vinted alerts on Telegram for free, without Discord. Create your own private bot with Telegram's BotFather (about three minutes), give its token to vinted-bot, and connect your chat with a one-time code. From then on, every new listing from your Vinted searches arrives in Telegram with a photo, the total price, size, condition and Buy and Open buttons.

Telegram is the most popular way to get Vinted alerts in Italy and a close second in Germany and France, and plenty of people simply don't use Discord. Here's the full setup.

## Why your own bot

Shared Telegram alert bots run one bot for all their users and charge for more searches. With vinted-bot you make a bot that only you use. It's free, it lives in your Telegram account, and only the app you run can send through it.

The "bot" here is just Telegram's name for an account that apps can send messages from. Making one is free and doesn't need any coding.

## Step 1: create a bot with BotFather

1. Open Telegram on your phone or computer and search for BotFather. Pick the one with the blue verified tick; there are copycats.
2. Tap Start, then send `/newbot`.
3. BotFather asks for a name. This is what you'll see at the top of the chat, for example "My Vinted alerts".
4. Then it asks for a username. It has to be unique and end in "bot", for example `jane_vinted_alerts_bot`. If it's taken, try another.
5. BotFather replies with a message that includes your token. It looks like `7123456789:AAH...` (numbers, a colon, then a long string of letters and numbers).

Keep that token private. Anyone who has it can send messages as your bot. Don't paste it into chats, screenshots or AI assistants. If it leaks, send `/revoke` to BotFather to get a new one.

## Step 2: give the token to vinted-bot

For now, the token goes in a small settings file on the computer that runs vinted-bot, rather than in the dashboard.

1. Find vinted-bot's data folder:
   - Windows: `%LOCALAPPDATA%\vinted-bot` (paste that into the File Explorer address bar)
   - Mac: `~/Library/Application Support/vinted-bot` (in Finder, Go, Go to Folder)
   - Linux or Raspberry Pi: `~/.local/share/vinted-bot`
   - Docker: the folder with your `docker-compose.yml`
2. Create a plain text file there called `.env` (or open it if it exists).
3. Add this line, with your own token after the equals sign:

```
VINTED_BOT_TELEGRAM_BOT_TOKEN=7123456789:AAH-your-token
```

4. Save it and restart vinted-bot: run the install command again, or `docker compose up -d` with Docker.

If the dashboard still says the token is missing, check that the file is called exactly `.env` (Windows sometimes adds `.txt`) and that there are no spaces around the equals sign.

{{install}}

## Step 3: connect your chat

A Telegram bot can't message you first. That's a Telegram rule against spam, and it's why most Telegram setups ask you to dig out a "chat ID". vinted-bot skips that:

1. In the dashboard, open the Alerts page and add a new place for alerts. Choose Telegram.
2. Press Connect my chat. The app makes a one-time code.
3. Press Open Telegram. The chat with your bot opens with the code ready. Press Start.
4. The dashboard shows Connected. Press Send test, and a test message arrives in Telegram.

The link expires after thirty minutes, so if you get distracted, just press Connect my chat again.

### Alerts in a group or a forum topic

To share alerts with a partner or a reselling buddy, use a group:

1. Create a Telegram group and add your bot to it like any other member.
2. Open the connect link from inside that group and press Start there.

If your group uses topics, open the link inside the topic you want, and alerts go to that topic only. That's handy for one topic per search.

## What the alerts look like

Each new listing arrives as a photo message with:

- The total price first, buyer protection included, and a deal note when it's well under the typical price for that search.
- Title, size, condition, brand and the seller's rating.
- The Vinted country site and when it was found.
- A green Buy button and an Open on Vinted button.

You can switch to a gallery style that shows several photos per listing, or send a destination's alerts silently and only let the bargains make a sound.

You can also manage things from the chat. `/list` shows your searches and how each is doing, `/pause 3` and `/resume 3` stop and restart search 3, and `/add` followed by a Vinted search link starts watching it. Pasting a Vinted link works too: a search link adds the search, a listing link watches its price, and a member's profile link follows that seller's new uploads.

## Then add a search

In the dashboard, paste a Vinted search link (from the browser or the app's share button) or build the search with Vinted's categories, brands and sizes. Set the maximum price as the total you'll pay, and add any words to skip, such as "damaged" or "box only". The first check is silent, so you only hear about listings that appear after this point.

## Troubleshooting Telegram alerts

### "Telegram never connects"

The app must be running when you press Start in Telegram, and the link must be less than thirty minutes old. For a group, add the bot to the group before you tap the link.

### It worked, then stopped

If you blocked the bot or removed it from the group, Telegram tells vinted-bot the chat is gone, and the app switches that destination off rather than keep failing. Connect the chat again from the Alerts page.

### The search is working but nothing arrives

Usually the price limit: it includes buyer protection, so an item listed at €19 costs €20.65 and fails a €20 limit. The dashboard's list of skipped listings shows the reason for each one.

### Too many alerts

Narrow the search, add words to skip, or use the deal filter so only listings well under the usual price get through.

## Telegram, Discord or phone notification?

Telegram is great if you already use it and want alerts you can forward or share with a group. If you prefer Discord, the [Discord webhook guide](/guides/vinted-discord-alerts-webhook/) is even quicker since there's no token step. If you want neither, the free ntfy app gives you a plain phone notification with no account at all. The [free Vinted bot guide](/guides/free-vinted-bot/) covers all three.
