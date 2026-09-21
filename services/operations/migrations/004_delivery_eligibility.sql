-- Upgrade pre-release databases to the frozen rule: 30 days from delivery.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at date;
UPDATE orders SET delivered_at=purchased_at WHERE delivered_at IS NULL;
ALTER TABLE orders ALTER COLUMN delivered_at SET NOT NULL;
UPDATE documents SET body=replace(body,'within 30 days of purchase','within 30 days of delivery') WHERE id='retailer-policy';
