-- Tool 2 (KYC review): adds a column in place. Existing customers become 'pending'.
ALTER TABLE customer ADD COLUMN kyc_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (kyc_status IN ('pending', 'approved', 'rejected'));
CREATE INDEX ix_customer_kyc_status ON customer (kyc_status, id);

-- Hardening of the 001 refund cap: INSERT OR REPLACE on charge fires no UPDATE trigger,
-- so a replaced charge could end up smaller than its pending plus approved refunds.
CREATE TRIGGER charge_cap_replace BEFORE INSERT ON charge
BEGIN
    SELECT RAISE(ABORT, 'refund cap exceeded')
    WHERE (SELECT COALESCE(SUM(amount_cents), 0) FROM refund
           WHERE charge_id = NEW.id AND status IN ('pending_approval', 'approved'))
          > NEW.amount_cents;
END;
