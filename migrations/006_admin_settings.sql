-- Admin user management, session timeout and more stored settings.
ALTER TABLE app_user ADD COLUMN active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1));
ALTER TABLE user_session ADD COLUMN last_seen_at TEXT;

-- Setting values are JSON. The 001 limit ('50000') already parses as a JSON number.
INSERT INTO setting (key, value) VALUES
    ('session_timeout_minutes', '60'),
    ('refund_requires_kyc', 'true'),
    ('max_refund_age_days', '90'),
    ('reasons_refund_request', '["Duplicate charge", "Product not received", "Product defective or not as described", "Cancelled order or subscription", "Billing error or wrong amount", "Fraudulent or unauthorized charge", "Goodwill gesture"]'),
    ('reasons_refund_approve', '["Verified with customer", "Matches refund policy", "Confirmed duplicate or billing error", "Confirmed fraud", "Goodwill approved by manager"]'),
    ('reasons_refund_reject', '["Outside refund window", "Does not meet refund policy", "Insufficient evidence", "Already refunded", "Suspected abuse"]'),
    ('reasons_kyc_approve', '["Identity documents verified", "Details match records", "Verified by phone"]'),
    ('reasons_kyc_reject', '["Documents missing or unreadable", "Details do not match", "Suspected fraud", "Sanctions or watchlist match"]');
