-- BUILD_SPEC_2 item 3: record-level access by region.
ALTER TABLE customer ADD COLUMN region TEXT NOT NULL DEFAULT 'US' CHECK (region IN ('US', 'EU'));
CREATE INDEX ix_customer_region ON customer (region, id);
-- Existing assignments keep working everywhere until an admin narrows them.
ALTER TABLE role_assignment ADD COLUMN region TEXT NOT NULL DEFAULT 'ALL' CHECK (region IN ('US', 'EU', 'ALL'));
