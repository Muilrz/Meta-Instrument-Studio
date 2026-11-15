-- PROPOSAL ONLY. Not a P1 migration. Do not execute before owner approval.
-- Apply only to a separately approved test target using its migration owner.
BEGIN;
CREATE SCHEMA IF NOT EXISTS mis_integration;
CREATE TABLE mis_integration.thread_bindings (
    project_id text NOT NULL,
    task_id text NOT NULL,
    thread_id text NOT NULL,
    upstream_thread_id text NOT NULL UNIQUE,
    PRIMARY KEY (project_id, thread_id),
    UNIQUE (project_id, task_id, thread_id, upstream_thread_id)
);
CREATE TABLE mis_integration.run_commands (
    project_id text NOT NULL,
    run_id text NOT NULL,
    task_id text NOT NULL,
    thread_id text NOT NULL,
    upstream_thread_id text NOT NULL,
    idempotency_key text NOT NULL,
    brief_sha256 text NOT NULL CHECK (brief_sha256 ~ '^[0-9a-f]{64}$'),
    baseline_version integer NOT NULL CHECK (baseline_version > 0),
    specialist text NOT NULL CHECK (specialist IN ('lab', 'research', 'procurement')),
    config_sha256 text NOT NULL CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    budget jsonb NOT NULL CHECK (jsonb_typeof(budget) = 'object'),
    state text NOT NULL CHECK (state IN (
        'intent', 'uncertain', 'bound', 'completed', 'failed', 'cancelled'
    )),
    upstream_run_id text UNIQUE,
    runtime_status text,
    PRIMARY KEY (project_id, run_id),
    UNIQUE (project_id, idempotency_key),
    FOREIGN KEY (project_id, task_id, thread_id, upstream_thread_id)
        REFERENCES mis_integration.thread_bindings
        (project_id, task_id, thread_id, upstream_thread_id),
    CHECK ((state IN ('intent', 'uncertain')) OR upstream_run_id IS NOT NULL)
);
-- No automatic role creation/grant. After choosing the real MIS backend role,
-- a migration owner may separately grant only USAGE and SELECT/INSERT/UPDATE:
-- GRANT USAGE ON SCHEMA mis_integration TO <approved_mis_backend_role>;
-- GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA mis_integration
--     TO <approved_mis_backend_role>;
-- No grants to mis_runtime; no CREATE, DELETE, TRUNCATE, or P1 table grants.
COMMIT;
