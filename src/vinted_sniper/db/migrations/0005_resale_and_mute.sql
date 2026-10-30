-- Reselling maths and a short mute, both per search.
--
-- A reseller decides on euros of profit, not on percent under typical, so a search can
-- say what its finds resell for. The margin an alert shows is
--   resale_price * (1 - resale_fee_pct / 100) - resale_shipping - total price
-- in the search's own site's currency. The fee is what the selling platform keeps (about
-- nothing when reselling on Vinted itself, around ten percent on eBay); the shipping is
-- what the reseller pays to send it on. `min_margin` turns the sum into a filter.
ALTER TABLE queries ADD COLUMN resale_price REAL CHECK (resale_price >= 0);
ALTER TABLE queries ADD COLUMN resale_fee_pct REAL CHECK (resale_fee_pct >= 0 AND resale_fee_pct < 100);
ALTER TABLE queries ADD COLUMN resale_shipping REAL CHECK (resale_shipping >= 0);
ALTER TABLE queries ADD COLUMN min_margin REAL CHECK (min_margin >= 0);

-- "Mute this search for an hour", from an alert's button. Until then the search keeps
-- checking (so it does not mistake the hour's listings for new ones afterwards) but
-- announces nothing; what it skipped is logged as muted.
ALTER TABLE queries ADD COLUMN muted_until INTEGER;
