-- The 2.0 schema: richer searches, a per-search record of what each search has seen,
-- watches, marks, a seller blocklist and cache, and a log of why listings were skipped.
--
-- Three tables are rebuilt rather than altered, because SQLite cannot drop a constraint
-- in place: `queries` loses UNIQUE(url) so a search can be duplicated with different
-- filters, `destinations` gains the 'apprise' kind, and `outbox` gains watch
-- notifications (which have no search and may repeat for one listing). The runner turns
-- foreign keys off around this file and checks them before committing, which is the
-- procedure SQLite documents for exactly this.

-- --- Searches ------------------------------------------------------------------------

CREATE TABLE queries_new (
    id                   INTEGER PRIMARY KEY,
    name                 TEXT    NOT NULL,
    -- Normalised search URL. No longer unique: duplicating a search to send a stricter
    -- copy somewhere else is a feature. The CLI and dashboard still refuse an accidental
    -- second paste of the same URL.
    url                  TEXT    NOT NULL,
    tld                  TEXT    NOT NULL,
    params_json          TEXT    NOT NULL,
    poll_interval_s      INTEGER NOT NULL DEFAULT 60 CHECK (poll_interval_s >= 10),
    paused               INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0, 1)),
    banned_keywords_json TEXT    NOT NULL DEFAULT '[]',
    include_terms_json   TEXT    NOT NULL DEFAULT '[]',
    regex                TEXT,
    min_total_price      REAL,
    max_total_price      REAL,
    conditions_json      TEXT,
    countries_json       TEXT,
    seller_min_rating    REAL    CHECK (seller_min_rating BETWEEN 0 AND 5),
    seller_min_reviews   INTEGER CHECK (seller_min_reviews >= 0),
    skip_unrated_sellers INTEGER NOT NULL DEFAULT 0 CHECK (skip_unrated_sellers IN (0, 1)),
    deal_only_pct        INTEGER CHECK (deal_only_pct BETWEEN 1 AND 99),
    max_age_min          INTEGER CHECK (max_age_min >= 1),
    color                TEXT,
    quiet_start          TEXT,
    quiet_end            TEXT,
    quiet_mode           TEXT    NOT NULL DEFAULT 'hold'
                         CHECK (quiet_mode IN ('hold', 'drop', 'silent')),
    notes                TEXT,
    tags_json            TEXT    NOT NULL DEFAULT '[]',
    extra_tlds_json      TEXT    NOT NULL DEFAULT '[]',
    created_at           INTEGER NOT NULL,
    updated_at           INTEGER NOT NULL
);

-- Existing searches get a colour from the same palette new ones draw from.
INSERT INTO queries_new (
    id, name, url, tld, params_json, poll_interval_s, paused, banned_keywords_json,
    max_total_price, conditions_json, countries_json, color, created_at, updated_at
)
SELECT
    id, name, url, tld, params_json, poll_interval_s, paused, banned_keywords_json,
    max_total_price, conditions_json, countries_json,
    CASE (id - 1) % 8
        WHEN 0 THEN '#007782' WHEN 1 THEN '#D04555' WHEN 2 THEN '#F9BB42'
        WHEN 3 THEN '#28865A' WHEN 4 THEN '#6C5DD3' WHEN 5 THEN '#E07A2E'
        WHEN 6 THEN '#2F6FDE' ELSE '#B5487F'
    END,
    created_at, updated_at
FROM queries;

DROP TABLE queries;
ALTER TABLE queries_new RENAME TO queries;
CREATE INDEX idx_queries_url ON queries(url);

-- --- Destinations --------------------------------------------------------------------

CREATE TABLE destinations_new (
    id                 INTEGER PRIMARY KEY,
    kind               TEXT    NOT NULL
                       CHECK (kind IN ('discord', 'telegram', 'webhook', 'ntfy', 'apprise')),
    name               TEXT    NOT NULL,
    config_json        TEXT    NOT NULL,
    active             INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    notify_status      INTEGER NOT NULL DEFAULT 0 CHECK (notify_status IN (0, 1)),
    failure_count      INTEGER NOT NULL DEFAULT 0,
    deactivated_reason TEXT,
    created_at         INTEGER NOT NULL
);

INSERT INTO destinations_new SELECT
    id, kind, name, config_json, active, notify_status, failure_count, deactivated_reason,
    created_at
FROM destinations;

DROP TABLE destinations;
ALTER TABLE destinations_new RENAME TO destinations;

-- --- Search state --------------------------------------------------------------------

-- Listing ids are handed out in upload order across the whole platform, and the new
-- catalog endpoint no longer says when a photo was taken, so ids carry the "is this new"
-- question now. `floor_item_id` is the lowest id worth considering: anything below it was
-- already off the bottom of the first page last time, so if it shows up now it is old
-- stock pulled up by a deletion, not a new listing.
ALTER TABLE query_state ADD COLUMN floor_item_id INTEGER;
-- Newest id in the raw response, and when it last moved. The watchdog's "has this search
-- stopped moving" counter runs on this when timestamps are missing.
ALTER TABLE query_state ADD COLUMN newest_raw_id INTEGER;
ALTER TABLE query_state ADD COLUMN raw_advanced_at INTEGER;

-- --- Listings ------------------------------------------------------------------------

-- The search's median total price when the listing was recorded, so "12% under typical"
-- describes the market as it was, not as it is when someone reads the alert.
ALTER TABLE items ADD COLUMN typical_price REAL;
-- Only known for searches with a country filter, which is what pays for the lookup.
ALTER TABLE items ADD COLUMN seller_country TEXT;
-- Insertion order, for the dashboard's live feed. Listing ids are not it: they arrive out
-- of order and from several searches at once.
ALTER TABLE items ADD COLUMN seq INTEGER;
-- Set for listings a seller watch turned up, which belong to no search.
ALTER TABLE items ADD COLUMN watch_id INTEGER;

UPDATE items SET seq = ranked.position
FROM (
    SELECT item_id, ROW_NUMBER() OVER (ORDER BY first_seen_at, item_id) AS position
    FROM items
) AS ranked
WHERE ranked.item_id = items.item_id;

CREATE UNIQUE INDEX idx_items_seq ON items(seq);

-- Which searches have seen which listings, and what they decided. A listing two searches
-- both match belongs to both, so each search's routes hear about it once — a single
-- global "seen it" set silently starved the second search's destinations.
CREATE TABLE query_items (
    query_id      INTEGER NOT NULL REFERENCES queries(id) ON DELETE CASCADE,
    item_id       INTEGER NOT NULL,
    -- 'seeded': on the page at the search's first check, recorded so it is never
    -- mistaken for new, never announced. 'matched': new and passed the filters.
    -- 'rejected': new and failed one (the reason is in `rejections`).
    status        TEXT    NOT NULL CHECK (status IN ('seeded', 'matched', 'rejected')),
    -- Whether notifications were queued: a match can be kept quiet by deal-only or by
    -- quiet hours in drop mode.
    announced     INTEGER NOT NULL DEFAULT 0 CHECK (announced IN (0, 1)),
    first_seen_at INTEGER NOT NULL,
    PRIMARY KEY (query_id, item_id)
);

CREATE INDEX idx_query_items_item ON query_items(item_id);
CREATE INDEX idx_query_items_seen ON query_items(first_seen_at);

INSERT INTO query_items (query_id, item_id, status, announced, first_seen_at)
SELECT
    i.query_id, i.item_id,
    CASE WHEN EXISTS (SELECT 1 FROM outbox o WHERE o.item_id = i.item_id)
         THEN 'matched' ELSE 'seeded' END,
    EXISTS (SELECT 1 FROM outbox o WHERE o.item_id = i.item_id),
    i.first_seen_at
FROM items i
WHERE i.query_id IN (SELECT id FROM queries);

-- --- Watches -------------------------------------------------------------------------

CREATE TABLE watches (
    id              INTEGER PRIMARY KEY,
    -- 'item': one listing, for price drops and its sale. 'seller': a member, for new uploads.
    kind            TEXT    NOT NULL CHECK (kind IN ('item', 'seller')),
    tld             TEXT    NOT NULL,
    target_id       INTEGER NOT NULL,
    label           TEXT    NOT NULL,
    last_price      REAL,
    currency        TEXT,
    last_status     TEXT,
    last_checked_at INTEGER,
    -- Jittered at scheduling time, so watches added together drift apart.
    next_check_at   INTEGER NOT NULL,
    last_error      TEXT,
    active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at      INTEGER NOT NULL,
    UNIQUE (kind, target_id)
);

CREATE INDEX idx_watches_due ON watches(active, next_check_at);

-- Same rule as searches: a watch with no rows here goes to every active destination.
CREATE TABLE watch_destinations (
    watch_id       INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    destination_id INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    PRIMARY KEY (watch_id, destination_id)
);

-- --- Outbox --------------------------------------------------------------------------

CREATE TABLE outbox_new (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id          INTEGER NOT NULL,
    -- NULL for watch notifications, which no search produced.
    query_id         INTEGER,
    watch_id         INTEGER REFERENCES watches(id) ON DELETE CASCADE,
    destination_id   INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    kind             TEXT    NOT NULL DEFAULT 'listing'
                     CHECK (kind IN ('listing', 'price_drop', 'sold', 'reserved', 'removed',
                                     'seller_upload')),
    previous_price   REAL,
    -- Quiet hours in 'silent' mode: deliver, but without a sound.
    silent           INTEGER NOT NULL DEFAULT 0 CHECK (silent IN (0, 1)),
    -- Quiet hours in 'hold' mode: when the window ends. Expiry counts from here rather
    -- than from creation, or everything held overnight would be thrown away at dawn.
    held_until       INTEGER,
    status           TEXT    NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'sending', 'sent', 'failed', 'cancelled')),
    attempts         INTEGER NOT NULL DEFAULT 0,
    next_attempt_at  INTEGER NOT NULL,
    lease_expires_at INTEGER,
    last_error       TEXT,
    created_at       INTEGER NOT NULL,
    sent_at          INTEGER
);

INSERT INTO outbox_new (
    id, item_id, query_id, destination_id, status, attempts, next_attempt_at,
    lease_expires_at, last_error, created_at, sent_at
)
SELECT
    id, item_id, query_id, destination_id, status, attempts, next_attempt_at,
    lease_expires_at, last_error, created_at, sent_at
FROM outbox;

DROP TABLE outbox;
ALTER TABLE outbox_new RENAME TO outbox;

CREATE INDEX idx_outbox_claim ON outbox(destination_id, status, next_attempt_at);
-- One alert per listing per destination, however many searches match it. Watch events
-- are exempt: a listing can drop in price more than once.
CREATE UNIQUE INDEX idx_outbox_once ON outbox(item_id, destination_id) WHERE kind = 'listing';

-- --- Sellers -------------------------------------------------------------------------

CREATE TABLE blocked_sellers (
    seller_id  INTEGER PRIMARY KEY,
    login      TEXT,
    tld        TEXT,
    reason     TEXT,
    created_at INTEGER NOT NULL
);

-- Member-page lookups, kept for a week. Only searches with a country or seller-rating
-- filter cause one, and only for listings that passed every cheaper filter first.
CREATE TABLE seller_cache (
    seller_id  INTEGER PRIMARY KEY,
    tld        TEXT    NOT NULL,
    country    TEXT,
    rating     REAL,
    reviews    INTEGER,
    login      TEXT,
    fetched_at INTEGER NOT NULL
);

-- --- Marks and rejections ------------------------------------------------------------

CREATE TABLE item_marks (
    item_id    INTEGER PRIMARY KEY REFERENCES items(item_id) ON DELETE CASCADE,
    mark       TEXT    NOT NULL CHECK (mark IN ('saved', 'hidden')),
    created_at INTEGER NOT NULL
);

-- "Why wasn't this sent?" Capped by housekeeping; one row per search and listing.
CREATE TABLE rejections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id    INTEGER NOT NULL REFERENCES queries(id) ON DELETE CASCADE,
    item_id     INTEGER NOT NULL,
    reason      TEXT    NOT NULL,
    detail      TEXT    NOT NULL,
    title       TEXT,
    total_price REAL,
    currency    TEXT,
    photo_url   TEXT,
    url         TEXT,
    created_at  INTEGER NOT NULL,
    UNIQUE (query_id, item_id)
);

CREATE INDEX idx_rejections_query ON rejections(query_id, created_at);
