-- Deciding what is new in a way that survives downtime, upgrades, edits and pruning.

-- --- Searches upgraded from 1.x ---------------------------------------------------------

-- 1.x had no floor. Without one, the first 2.0 check judged every listing on the page that
-- 1.x had not happened to store, and announced a whole page of old stock. What a search
-- already recorded is the best floor there is: anything at or below its newest listing
-- was on the shelf while 1.x was watching.
UPDATE query_state
SET floor_item_id = (
    SELECT MAX(qi.item_id) FROM query_items qi WHERE qi.query_id = query_state.query_id
)
WHERE floor_item_id IS NULL AND last_success_at IS NOT NULL;

-- --- When a listing was already on Vinted -----------------------------------------------

-- The catalog no longer says when a photo was taken, but listing ids are handed out in
-- upload order across the whole platform. So whenever a check sees a newer id than any
-- before, that id and every lower one provably existed at that moment. This table keeps
-- that staircase: both columns only ever rise. "Ignore listings older than" and the
-- freshness window read it to skip a listing that turns up late, for example after a
-- price cut brings it into a search's range. Thinned to about one row a minute.
CREATE TABLE id_clock (
    item_id INTEGER PRIMARY KEY,
    seen_at INTEGER NOT NULL
);

-- Seeded from what is stored: every listing existed when it was first recorded.
INSERT INTO id_clock (item_id, seen_at)
SELECT item_id, first_seen_at FROM (
    SELECT item_id, first_seen_at,
           MAX(item_id) OVER (
               ORDER BY first_seen_at, item_id
               ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
           ) AS higher_before
    FROM items
)
WHERE higher_before IS NULL OR item_id > higher_before;

-- --- Typical price per search -----------------------------------------------------------

-- A listing two searches match has one row in `items` but a different typical price for
-- each search. Kept here so each search's alert compares against its own median; the
-- copy on `items` was whichever search stored the listing first.
ALTER TABLE query_items ADD COLUMN typical_price REAL;

UPDATE query_items
SET typical_price = (
    SELECT i.typical_price FROM items i
    WHERE i.item_id = query_items.item_id AND i.query_id = query_items.query_id
);

-- Where a search's price history starts. Editing what a search fetches moves it to the
-- edit, so the median describes the new search rather than the old one.
ALTER TABLE query_state ADD COLUMN history_from INTEGER;

-- --- Seller watches ---------------------------------------------------------------------

-- The newest listing id a seller watch has seen. A wardrobe is listed newest first, so
-- anything at or below this is not a new upload, however long ago housekeeping pruned
-- the stored copy.
ALTER TABLE watches ADD COLUMN seen_up_to INTEGER;

UPDATE watches
SET seen_up_to = (SELECT MAX(i.item_id) FROM items i WHERE i.watch_id = watches.id)
WHERE kind = 'seller';
