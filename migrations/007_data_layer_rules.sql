-- Migration 007: data-layer rules (BUILD_SPEC_3 fix 2). These hold for direct SQL too.

-- 2(a) Nobody decides their own request. The 'system' actor cannot be a username (001).
CREATE TRIGGER refund_no_self_decision_insert BEFORE INSERT ON refund
WHEN NEW.status IN ('approved', 'rejected') AND NEW.decided_by = NEW.requested_by
BEGIN
    SELECT RAISE(ABORT, 'requester cannot decide own refund');
END;

CREATE TRIGGER refund_no_self_decision_update BEFORE UPDATE ON refund
WHEN NEW.status IN ('approved', 'rejected') AND NEW.decided_by = NEW.requested_by
BEGIN
    SELECT RAISE(ABORT, 'requester cannot decide own refund');
END;

CREATE TRIGGER limit_override_no_self_decision_insert BEFORE INSERT ON limit_override
WHEN NEW.status IN ('approved', 'rejected') AND NEW.decided_by = NEW.requested_by
BEGIN
    SELECT RAISE(ABORT, 'requester cannot decide own limit override');
END;

CREATE TRIGGER limit_override_no_self_decision_update BEFORE UPDATE ON limit_override
WHEN NEW.status IN ('approved', 'rejected') AND NEW.decided_by = NEW.requested_by
BEGIN
    SELECT RAISE(ABORT, 'requester cannot decide own limit override');
END;

-- 2(b) While refund_requires_kyc is on (a missing row means on), refunds need an
-- approved-KYC customer, both when created and when approved.
CREATE TRIGGER refund_kyc_insert BEFORE INSERT ON refund
WHEN COALESCE((SELECT value FROM setting WHERE key = 'refund_requires_kyc'), 'true') <> 'false'
    AND COALESCE((SELECT cu.kyc_status FROM charge ch JOIN customer cu ON cu.id = ch.customer_id
                  WHERE ch.id = NEW.charge_id), '') <> 'approved'
BEGIN
    SELECT RAISE(ABORT, 'refund requires approved KYC');
END;

CREATE TRIGGER refund_kyc_update BEFORE UPDATE ON refund
WHEN NEW.status = 'approved'
    AND (OLD.status <> 'approved' OR NEW.charge_id <> OLD.charge_id)
    AND COALESCE((SELECT value FROM setting WHERE key = 'refund_requires_kyc'), 'true') <> 'false'
    AND COALESCE((SELECT cu.kyc_status FROM charge ch JOIN customer cu ON cu.id = ch.customer_id
                  WHERE ch.id = NEW.charge_id), '') <> 'approved'
BEGIN
    SELECT RAISE(ABORT, 'refund requires approved KYC');
END;

-- 2(c) The auto-approve limit is a whole number of cents from 0 to 75000.
-- BEFORE INSERT also covers INSERT OR REPLACE.
CREATE TRIGGER setting_auto_approve_limit_insert BEFORE INSERT ON setting
WHEN NEW.key = 'auto_approve_limit_cents'
    AND NOT (typeof(NEW.value) = 'text' AND NEW.value GLOB '[0-9]*' AND NEW.value NOT GLOB '*[^0-9]*'
             AND length(NEW.value) <= 6 AND CAST(NEW.value AS INTEGER) <= 75000)
BEGIN
    SELECT RAISE(ABORT, 'auto-approve limit must be whole cents from 0 to 75000');
END;

CREATE TRIGGER setting_auto_approve_limit_update BEFORE UPDATE ON setting
WHEN NEW.key = 'auto_approve_limit_cents'
    AND NOT (typeof(NEW.value) = 'text' AND NEW.value GLOB '[0-9]*' AND NEW.value NOT GLOB '*[^0-9]*'
             AND length(NEW.value) <= 6 AND CAST(NEW.value AS INTEGER) <= 75000)
BEGIN
    SELECT RAISE(ABORT, 'auto-approve limit must be whole cents from 0 to 75000');
END;
