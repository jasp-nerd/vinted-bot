-- Status notices (every search on a site failing, a search stuck, an update installed)
-- used to be sent once and forgotten: one sent while the network was down was lost, and
-- that is exactly when such a notice matters. Each now waits here, one row per place that
-- asked for them, until that place has accepted it, or it is a day old.
CREATE TABLE status_notices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    destination_id  INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    message         TEXT    NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at INTEGER NOT NULL,
    last_error      TEXT,
    created_at      INTEGER NOT NULL
);

CREATE INDEX idx_status_notices_due ON status_notices(next_attempt_at);
