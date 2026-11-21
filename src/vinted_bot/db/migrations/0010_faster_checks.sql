-- Searches may be checked as often as every second (the floor used to be ten seconds), and
-- searches left at the old default of a minute move to the new default of five seconds.
-- Any other interval was chosen on purpose and is kept.
--
-- Rebuilt rather than altered, because SQLite cannot change a CHECK constraint in place.
-- Columns are copied by name; the runner turns foreign keys off around this file and
-- checks them before committing, as for 0004.

CREATE TABLE queries_new (
    id                   INTEGER PRIMARY KEY,
    name                 TEXT    NOT NULL,
    -- Normalised search URL. Not unique: duplicating a search to send a stricter copy
    -- somewhere else is a feature. The CLI and dashboard still refuse an accidental
    -- second paste of the same URL.
    url                  TEXT    NOT NULL,
    tld                  TEXT    NOT NULL,
    params_json          TEXT    NOT NULL,
    poll_interval_s      INTEGER NOT NULL DEFAULT 5 CHECK (poll_interval_s >= 1),
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
    updated_at           INTEGER NOT NULL,
    resale_price         REAL    CHECK (resale_price >= 0),
    resale_fee_pct       REAL    CHECK (resale_fee_pct >= 0 AND resale_fee_pct < 100),
    resale_shipping      REAL    CHECK (resale_shipping >= 0),
    min_margin           REAL    CHECK (min_margin >= 0),
    muted_until          INTEGER
);

INSERT INTO queries_new (
    id, name, url, tld, params_json, poll_interval_s, paused, banned_keywords_json,
    include_terms_json, regex, min_total_price, max_total_price, conditions_json,
    countries_json, seller_min_rating, seller_min_reviews, skip_unrated_sellers,
    deal_only_pct, max_age_min, color, quiet_start, quiet_end, quiet_mode, notes,
    tags_json, extra_tlds_json, created_at, updated_at, resale_price, resale_fee_pct,
    resale_shipping, min_margin, muted_until
)
SELECT
    id, name, url, tld, params_json,
    CASE poll_interval_s WHEN 60 THEN 5 ELSE poll_interval_s END,
    paused, banned_keywords_json,
    include_terms_json, regex, min_total_price, max_total_price, conditions_json,
    countries_json, seller_min_rating, seller_min_reviews, skip_unrated_sellers,
    deal_only_pct, max_age_min, color, quiet_start, quiet_end, quiet_mode, notes,
    tags_json, extra_tlds_json, created_at, updated_at, resale_price, resale_fee_pct,
    resale_shipping, min_margin, muted_until
FROM queries;

DROP TABLE queries;
ALTER TABLE queries_new RENAME TO queries;
CREATE INDEX idx_queries_url ON queries(url);
