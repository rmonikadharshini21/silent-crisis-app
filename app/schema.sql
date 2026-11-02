CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student' CHECK (role IN ('student', 'admin')),
    pin_hash TEXT,
    duress_pin_hash TEXT,
    location_label TEXT,
    location_lat REAL,
    location_lng REAL,
    consent_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    trigger_source TEXT NOT NULL CHECK (trigger_source IN ('AI', 'SOS')),
    confidence REAL,
    -- state: counting -> cancelled | alerted. Admins only see alerted incidents.
    state TEXT NOT NULL CHECK (state IN ('counting', 'cancelled', 'alerted')),
    status TEXT CHECK (status IN ('New', 'Acknowledged', 'Help sent', 'Resolved', 'False alarm')),
    duress INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    alerted_at TEXT,
    location_label TEXT,
    location_lat REAL,
    location_lng REAL,
    location_source TEXT,
    email_status TEXT,
    all_clear_at TEXT,
    token TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_incidents_user ON incidents (user_id, started_at);
CREATE INDEX IF NOT EXISTS idx_incidents_state ON incidents (state, alerted_at);
