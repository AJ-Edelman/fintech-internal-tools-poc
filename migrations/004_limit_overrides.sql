-- BUILD_SPEC_2 item 4: tool 3, account limit overrides.
ALTER TABLE customer ADD COLUMN daily_limit_cents INTEGER NOT NULL DEFAULT 500000
    CHECK (typeof(daily_limit_cents) = 'integer' AND daily_limit_cents > 0);

CREATE TABLE limit_override (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customer(id),
    current_limit_cents INTEGER NOT NULL,
    requested_limit_cents INTEGER NOT NULL
        CHECK (typeof(requested_limit_cents) = 'integer' AND requested_limit_cents <= 5000000),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    status TEXT NOT NULL CHECK (status IN ('pending_approval', 'approved', 'rejected')),
    requested_by TEXT NOT NULL,
    decided_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (requested_limit_cents > current_limit_cents)
);
CREATE INDEX ix_limit_override_status_id ON limit_override (status, id);
-- One pending request per customer, enforced against direct SQL too.
CREATE UNIQUE INDEX ux_limit_override_one_pending ON limit_override (customer_id)
    WHERE status = 'pending_approval';

-- The recorded current limit must be the customer's real limit at request time.
CREATE TRIGGER limit_override_current BEFORE INSERT ON limit_override
BEGIN
    SELECT RAISE(ABORT, 'current limit mismatch')
    WHERE NEW.current_limit_cents <> (SELECT daily_limit_cents FROM customer WHERE id = NEW.customer_id);
END;
