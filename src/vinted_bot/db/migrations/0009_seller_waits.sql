-- Listings waiting for a seller lookup (a search filtering on the seller's country or
-- rating, on a busy search where not every seller can be looked up in one check). The
-- list lived in the running search only, so renaming, muting or pausing the search, or
-- restarting the app, lost it: those listings were never judged, and "Not sent" kept
-- saying they would be tried again. Kept here, it survives all of that.
CREATE TABLE seller_waits (
    query_id  INTEGER NOT NULL REFERENCES queries(id) ON DELETE CASCADE,
    item_id   INTEGER NOT NULL,
    -- When the listing first waited; it is given up once the freshness window has passed.
    since     INTEGER NOT NULL,
    -- The listing as the catalog gave it, to judge it again without fetching it.
    item_json TEXT    NOT NULL,
    PRIMARY KEY (query_id, item_id)
);

-- What the old in-memory list left behind: rows promising another try that never came.
UPDATE rejections
SET detail = 'gave up: vinted-bot stopped before this seller could be looked up'
WHERE reason = 'seller_unknown' AND detail LIKE '%tried again on the next check%';
