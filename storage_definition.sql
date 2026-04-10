CREATE TABLE users (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO users (name) VALUES ('root');

CREATE TABLE projects (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    uuid         TEXT NOT NULL UNIQUE,
    user_id      INT NOT NULL REFERENCES users(id) DEFAULT 1,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    llm_provider TEXT NOT NULL DEFAULT 'default_llm',
    llm_model    TEXT NOT NULL DEFAULT 'default_model',
    project_root TEXT NOT NULL
);

INSERT INTO projects (name, uuid, user_id, project_root)
VALUES ('default', 'default', 1, '/data/sessions/default');

CREATE TABLE runners (
    id             SERIAL PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,
    url            TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',
    capabilities   JSONB NOT NULL DEFAULT '{}',
    registered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_heartbeat TIMESTAMPTZ
);

CREATE TABLE runner_history (
    id          SERIAL PRIMARY KEY,
    runner_id   INT NOT NULL REFERENCES runners(id),
    status      TEXT NOT NULL,
    change_type TEXT NOT NULL,
    changed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE FUNCTION log_runner_change() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO runner_history (runner_id, status, change_type)
    VALUES (NEW.id, NEW.status,
            CASE WHEN TG_OP = 'INSERT' THEN 'registered' ELSE 'updated' END);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER runner_audit
AFTER INSERT OR UPDATE ON runners
FOR EACH ROW EXECUTE FUNCTION log_runner_change();

CREATE TABLE seeds (
    id              SERIAL PRIMARY KEY,
    uuid            TEXT NOT NULL UNIQUE,
    project_id      INT NOT NULL REFERENCES projects(id),
    name            TEXT NOT NULL,
    repository_url  TEXT NOT NULL,
    branch          TEXT NOT NULL DEFAULT 'main',
    commit          TEXT NOT NULL,
    access_token    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted         BOOLEAN NOT NULL DEFAULT FALSE
);

INSERT INTO seeds (uuid, project_id, name, repository_url, commit)
VALUES ('default-cdc', 1, 'cdc', 'https://github.com/qriostech/cdchealth', '');

CREATE TABLE branches (
    id                    SERIAL PRIMARY KEY,
    uuid                  TEXT NOT NULL UNIQUE,
    seed_id               INT NOT NULL REFERENCES seeds(id),
    runner_id             INT NOT NULL REFERENCES runners(id),
    name                  TEXT NOT NULL,
    description           TEXT NOT NULL DEFAULT '',
    path                  TEXT NOT NULL,
    sync_command          TEXT NOT NULL,
    commit                TEXT NOT NULL,
    git_branch            TEXT NOT NULL DEFAULT '',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    parent_branch_id      INT REFERENCES branches(id),
    parent_iteration_id   INT,  -- FK constraint added below, after iterations table is created
    deleted               BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE sessions (
    id             SERIAL PRIMARY KEY,
    branch_id      INT NOT NULL UNIQUE REFERENCES branches(id),
    kind           TEXT NOT NULL DEFAULT 'tmux',
    attach_command TEXT NOT NULL DEFAULT '',
    agent          TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'inactive',
    started_at     TIMESTAMPTZ,
    ended_at       TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE session_history (
    id             SERIAL PRIMARY KEY,
    session_id     INT NOT NULL REFERENCES sessions(id),
    kind           TEXT NOT NULL,
    attach_command TEXT NOT NULL,
    agent          TEXT NOT NULL,
    status         TEXT NOT NULL,
    change_type    TEXT NOT NULL,
    changed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE FUNCTION log_session_change() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO session_history (session_id, attach_command, kind, agent, status, change_type)
    VALUES (NEW.id, NEW.attach_command, NEW.kind, NEW.agent, NEW.status,
            CASE WHEN TG_OP = 'INSERT' THEN 'created' ELSE 'updated' END);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER session_audit
AFTER INSERT OR UPDATE ON sessions
FOR EACH ROW EXECUTE FUNCTION log_session_change();

CREATE TABLE iterations (
    id                 SERIAL PRIMARY KEY,
    branch_id          INT NOT NULL REFERENCES branches(id),
    hash               TEXT NOT NULL,
    name               TEXT NOT NULL,
    description        TEXT,
    hypothesis         TEXT,
    analysis           TEXT,
    guidelines_version TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (branch_id, hash)
);

CREATE TABLE iteration_metrics (
    id           SERIAL PRIMARY KEY,
    iteration_id INT NOT NULL REFERENCES iterations(id),
    key          TEXT NOT NULL,
    value        DOUBLE PRECISION NOT NULL,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (iteration_id, key)
);

CREATE TABLE iteration_comments (
    id           SERIAL PRIMARY KEY,
    iteration_id INT NOT NULL REFERENCES iterations(id),
    user_id      INT NOT NULL REFERENCES users(id) DEFAULT 1,
    body         TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE iteration_visuals (
    id           SERIAL PRIMARY KEY,
    iteration_id INT NOT NULL REFERENCES iterations(id),
    filename     TEXT NOT NULL,
    format       TEXT NOT NULL,
    path         TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (iteration_id, filename)
);

-- branches.parent_iteration_id is declared above without REFERENCES because
-- iterations is defined later in this file (and iterations.branch_id references
-- branches, so a forward FK on either side would be a chicken-and-egg). Add the
-- FK constraint now that both tables exist.
ALTER TABLE branches
    ADD CONSTRAINT branches_parent_iteration_id_fkey
    FOREIGN KEY (parent_iteration_id) REFERENCES iterations(id);

-- ----------------------------------------------------------------------------
-- cory_sessions: tmux sessions belonging directly to a user, hosted inside the
-- cory container (its own sandbox). Lifecycle is managed by the controlplane,
-- mirroring the way the controlplane manages branch-scoped sessions on the
-- runner — except cory_sessions have no branch/seed, just an owner.
-- ----------------------------------------------------------------------------

CREATE TABLE cory_sessions (
    id             SERIAL PRIMARY KEY,
    uuid           TEXT NOT NULL UNIQUE,
    user_id        INT NOT NULL REFERENCES users(id) DEFAULT 1,
    name           TEXT NOT NULL DEFAULT '',
    kind           TEXT NOT NULL DEFAULT 'tmux',
    attach_command TEXT NOT NULL DEFAULT '',
    agent          TEXT NOT NULL DEFAULT 'cory',
    status         TEXT NOT NULL DEFAULT 'inactive',
    started_at     TIMESTAMPTZ,
    ended_at       TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted        BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE cory_session_history (
    id              SERIAL PRIMARY KEY,
    cory_session_id INT NOT NULL REFERENCES cory_sessions(id),
    kind            TEXT NOT NULL,
    attach_command  TEXT NOT NULL,
    agent           TEXT NOT NULL,
    status          TEXT NOT NULL,
    change_type     TEXT NOT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE FUNCTION log_cory_session_change() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO cory_session_history (cory_session_id, kind, attach_command, agent, status, change_type)
    VALUES (NEW.id, NEW.kind, NEW.attach_command, NEW.agent, NEW.status,
            CASE WHEN TG_OP = 'INSERT' THEN 'created' ELSE 'updated' END);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER cory_session_audit
AFTER INSERT OR UPDATE ON cory_sessions
FOR EACH ROW EXECUTE FUNCTION log_cory_session_change();

-- ----------------------------------------------------------------------------
-- cory: postgres role used by the controlplane's cory agent (via the postgres
-- MCP server at coresearch-core/controlplane/mcp/postgres.py).
--
-- Read+write on all current public-schema tables, but no DDL (no CREATE,
-- DROP, ALTER, TRUNCATE) and no privileges on system catalogs. The
-- controlplane's main `coresearch` user is granted membership so it can
-- temporarily assume cory's privileges via SET LOCAL ROLE inside the MCP
-- tool transaction.
--
-- Safety note: cory CAN modify experiment data (branches, seeds, iterations,
-- comments). Prompt injection in user questions is therefore a real concern —
-- a hostile question could trick the agent into composing a destructive
-- UPDATE. The DB role limits damage to "things the controlplane API could
-- already do" (no DDL, no system table writes), but it does NOT prevent the
-- agent from e.g. wiping iteration_metrics with an unconstrained DELETE.
-- Treat the cory chat as semi-trusted code execution.
-- ----------------------------------------------------------------------------

CREATE ROLE cory;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cory;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cory;

-- Allow the main controlplane user to switch into the cory role mid-transaction
-- (used by SET LOCAL ROLE in the MCP server).
GRANT cory TO coresearch;
