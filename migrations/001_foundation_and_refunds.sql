-- Foundation + shared model + tool 1 (refunds)
CREATE TABLE app_user (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE CHECK (username <> 'system'),
    password_salt TEXT NOT NULL,
    password_hash TEXT NOT NULL
);

CREATE TABLE role_assignment (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES app_user(id),
    role TEXT NOT NULL,
    UNIQUE (user_id, role)
);

CREATE TABLE user_session (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES app_user(id),
    created_at TEXT NOT NULL
);

CREATE TABLE setting (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO setting (key, value) VALUES ('auto_approve_limit_cents', '50000');

CREATE TABLE audit_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    before TEXT,
    after TEXT,
    reason TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX ix_audit_entity ON audit_event (entity, entity_id, id);

CREATE TRIGGER audit_event_no_update BEFORE UPDATE ON audit_event
BEGIN
    SELECT RAISE(ABORT, 'audit_event is append-only');
END;

CREATE TRIGGER audit_event_no_delete BEFORE DELETE ON audit_event
BEGIN
    SELECT RAISE(ABORT, 'audit_event is append-only');
END;

-- INSERT OR REPLACE would delete the old row without firing the delete trigger.
CREATE TRIGGER audit_event_no_replace BEFORE INSERT ON audit_event
WHEN EXISTS (SELECT 1 FROM audit_event WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'audit_event is append-only');
END;

CREATE TABLE customer (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    ssn TEXT NOT NULL,
    bank_account TEXT NOT NULL
);

CREATE TABLE charge (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customer(id),
    amount_cents INTEGER NOT NULL CHECK (typeof(amount_cents) = 'integer' AND amount_cents > 0),
    created_at TEXT NOT NULL
);
CREATE INDEX ix_charge_customer ON charge (customer_id);

CREATE TABLE refund (
    id INTEGER PRIMARY KEY,
    charge_id INTEGER NOT NULL REFERENCES charge(id),
    amount_cents INTEGER NOT NULL CHECK (typeof(amount_cents) = 'integer' AND amount_cents > 0),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    status TEXT NOT NULL CHECK (status IN ('pending_approval', 'approved', 'rejected')),
    requested_by TEXT NOT NULL,
    decided_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX ix_refund_status_id ON refund (status, id);
CREATE INDEX ix_refund_charge ON refund (charge_id);

-- Cap: pending + approved refunds on a charge may never exceed the charge amount.
CREATE TRIGGER refund_cap_insert BEFORE INSERT ON refund
WHEN NEW.status IN ('pending_approval', 'approved')
BEGIN
    SELECT RAISE(ABORT, 'refund cap exceeded')
    WHERE (SELECT COALESCE(SUM(amount_cents), 0) FROM refund
           WHERE charge_id = NEW.charge_id AND status IN ('pending_approval', 'approved'))
          + NEW.amount_cents
          > (SELECT amount_cents FROM charge WHERE id = NEW.charge_id);
END;

CREATE TRIGGER refund_cap_update BEFORE UPDATE ON refund
WHEN NEW.status IN ('pending_approval', 'approved')
BEGIN
    SELECT RAISE(ABORT, 'refund cap exceeded')
    WHERE (SELECT COALESCE(SUM(amount_cents), 0) FROM refund
           WHERE charge_id = NEW.charge_id AND status IN ('pending_approval', 'approved')
             AND id <> OLD.id)
          + NEW.amount_cents
          > (SELECT amount_cents FROM charge WHERE id = NEW.charge_id);
END;

CREATE TRIGGER charge_cap_update BEFORE UPDATE OF amount_cents ON charge
BEGIN
    SELECT RAISE(ABORT, 'refund cap exceeded')
    WHERE (SELECT COALESCE(SUM(amount_cents), 0) FROM refund
           WHERE charge_id = NEW.id AND status IN ('pending_approval', 'approved'))
          > NEW.amount_cents;
END;
