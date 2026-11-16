-- Tool 2 (KYC review): adds a column in place. Existing customers become 'pending'.
ALTER TABLE customer ADD COLUMN kyc_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (kyc_status IN ('pending', 'approved', 'rejected'));
CREATE INDEX ix_customer_kyc_status ON customer (kyc_status, id);
