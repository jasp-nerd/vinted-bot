-- A destination can be paused by its own server: ntfy.sh answers 429 once the day's message
-- allowance is used up, and retrying every minute until midnight only spends requests. The
-- reason is kept so the Alerts page can say why nothing is arriving and when it resumes.
ALTER TABLE destinations ADD COLUMN paused_until INTEGER;
ALTER TABLE destinations ADD COLUMN paused_reason TEXT;
