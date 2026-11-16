-- BUILD_SPEC_2 item 1: outbound messages, written in the same transaction as the transition.
CREATE TABLE connector_message (
    id INTEGER PRIMARY KEY,
    connector TEXT NOT NULL,
    kind TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error TEXT,
    -- No message without its audit event.
    audit_event_id INTEGER NOT NULL REFERENCES audit_event(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX ix_connector_message_status_id ON connector_message (status, id);
CREATE INDEX ix_connector_message_entity ON connector_message (entity, entity_id, id);

-- Receiver addresses are configuration. fake:// resolves to the in-process fake services.
INSERT INTO setting (key, value) VALUES
    ('connector_payments_url', '"fake://payments"'),
    ('connector_ledger_url', '"fake://ledger"');
