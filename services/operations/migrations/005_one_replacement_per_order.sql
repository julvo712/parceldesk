-- A second conversation cannot create a second replacement for the same original order.
CREATE UNIQUE INDEX IF NOT EXISTS replacements_one_per_order ON replacements(run_id,order_id);
