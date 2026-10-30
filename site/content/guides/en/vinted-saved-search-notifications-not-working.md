---
title: "Vinted saved search notifications not working? Why, and what to do"
description: "Vinted saved search notifications not working, late or missing? The real causes, fixes for iPhone and Android, and a free way to get reliable alerts."
slug: vinted-saved-search-notifications-not-working
key: notifications-not-working
date: 2026-10-30
updated: 2026-10-30
keywords:
  - vinted saved search notifications not working
  - vinted saved searches not updating
  - vinted notifications delayed
  - vinted notifications not working on iphone
  - vinted notifications not working android
  - vinted saved search notifications
  - vinted new listings not showing
faq:
  - q: "Does Vinted send notifications for saved searches?"
    a: "Vinted's help pages say saved searches can notify you about new items. In practice many users report getting those notifications late or not at all, even with every notification setting switched on. Notifications about sellers you follow tend to be more dependable."
  - q: "Why are my Vinted notifications delayed?"
    a: "Two delays stack up. Vinted adds new listings to its search a few minutes after upload, and saved-search notifications are sent some time after that. Phone battery savers and Focus or Do Not Disturb modes can hold notifications back further."
  - q: "Why are my Vinted saved searches not updating?"
    a: "Users have reported several changes in 2026: saved searches capped at 20 brands, the count of new items no longer shown, some filters silently dropped and old items showing under newest first. Re-create the search and check its filters after saving it."
  - q: "How do I get reliable alerts for a Vinted search?"
    a: "Use an external alert tool that checks the search itself and messages you. vinted-bot does this for free: it checks every minute and sends new listings to Discord, Telegram or your phone, and it tells you when a search stops working."
---

If your Vinted saved search notifications aren't arriving, it's often not your phone. Many users with every notification setting switched on still get saved-search alerts late or not at all, and Vinted has never said much about how these alerts are batched. Check the settings below first, since they do fix some cases. If they don't, the reliable fix is an alert tool that checks the search itself.

## How Vinted's saved searches are supposed to work

You search on Vinted, set your filters and tap the save option above the results. The search then shows up in your saved searches, and Vinted's help centre says you can be notified about new items that match, in real time or as a daily summary.

That's the theory. The complaint that saved searches never notify goes back years, and it's the reason almost every third-party Vinted alert tool exists. A typical report: push notifications on, new item notifications on, and still nothing, while notifications about sellers they follow do come through.

Two other things to know before you start fixing:

- Vinted adds new listings to its search a few minutes after they're uploaded. Anything built on the search, Vinted's own alerts included, can only fire after that.
- In 2026 several users reported changes to saved searches themselves: a cap of 20 brands per saved search (longer lists were cut), the "new items" counter disappearing, some filters dropped without warning and older items showing up under newest first. If your saved search "stopped finding things", open it and check what's actually in it.

## Fixes worth trying first

These take five minutes and solve the cases where the problem really is on your side.

### In the Vinted app

1. Open your profile, then Settings, then Notifications. Wording differs a little between app versions and countries.
2. Make sure push notifications are on, and that the types covering new items and saved searches are switched on.
3. Log out and back in. A fresh login registers your phone for notifications again, which fixes some cases after a reinstall or a new phone.
4. Update the app. Older versions have had notification bugs that were later fixed.

### On an iPhone

1. Settings, Notifications, Vinted: Allow Notifications on, with Lock Screen and Banners enabled.
2. Check Focus. If a Focus mode or Do Not Disturb is on, Vinted needs to be in its allowed apps, or its notifications wait until the Focus ends.
3. If you use Notification Summary, take Vinted out of it. Otherwise its alerts get bundled into a summary at fixed times.
4. Background App Refresh on for Vinted (Settings, General, Background App Refresh) doesn't hurt.

### On Android

1. Settings, Apps, Vinted, Notifications: allowed, and each notification category inside switched on.
2. Battery: set Vinted to Unrestricted (the name varies: "Don't optimise", "No restrictions"). On Samsung, make sure Vinted isn't in Sleeping apps or Deep sleeping apps. Xiaomi, Oppo and OnePlus phones have their own autostart and battery managers that silently stop apps from receiving notifications.
3. Data saver can block background data. Allow Vinted to use data while data saver is on.

### Make the search narrower

A search with thousands of results changes all the time. Whatever Vinted does to decide what's worth a notification, a tight search (size, brand, condition, a sensible price) gives you fewer, better alerts and is easier to check by hand.

## When it's Vinted, not you

If you've done all of the above and still get nothing, or get notified twenty minutes after the item sold, you've hit the limit of Vinted's feature. You can't change how Vinted schedules its notifications, and there's no setting for "notify me immediately for this search only".

What you can control is who checks the search. Instead of waiting for Vinted to push a notification, a separate tool can load your saved search's results itself every minute and message you when something new appears.

## The free alternative: alerts that check the search themselves

vinted-bot is a free, open-source app that does exactly that. You paste the same Vinted search link, and it checks it every minute from your own computer. Each new listing arrives as a message on Discord, Telegram, ntfy on your phone or a webhook, with the photos, the total price including buyer protection, the size and condition, the seller's rating and a button that opens the listing.

It also fixes a few things Vinted's saved searches don't do:

- Price limits on what you'll actually pay, buyer protection included.
- Words to skip, so a seller who stuffs every title with your keyword doesn't flood you.
- No 20-brand cap. A search can also cover several Vinted country sites at once.
- Each search shows whether it's working, quiet, stuck or being slowed down by Vinted. The most common complaint about alert tools, Vinted's included, is that they stop without telling you.

It doesn't need your Vinted login. It reads public search results as a logged-out visitor, so there's no account involved.

{{install}}

### What it can't fix

It can't see a listing before Vinted's search does. New items appear in search a few minutes after upload, and that applies to every tool. In practice that means you'll usually hear about a listing within a few minutes of it going up, which is a lot better than a notification that never comes, but not a guarantee you'll be first. [Why you're never first on Vinted](/guides/why-youre-never-first-on-vinted/) explains the race.

It also runs on your computer, so alerts only arrive while that computer is on and awake. A Raspberry Pi or an old laptop left plugged in solves that.

## Quick checklist

- Vinted app notifications on, including new items and saved searches.
- Phone allows Vinted notifications, Focus and summaries don't hold them back, battery optimisation off for Vinted.
- Logged in, app updated.
- Saved search re-checked after the 2026 changes: brands, filters, sort order.
- Still unreliable: use an external alert. Setup guides for [Discord](/guides/vinted-discord-alerts-webhook/) and [Telegram](/guides/vinted-telegram-alerts/), or start with the [free Vinted bot guide](/guides/free-vinted-bot/).
