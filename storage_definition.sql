-- Single source of truth for the database schema.
--
-- Executed by Postgres exactly once, when it initializes an empty data volume
-- (via the docker-entrypoint-initdb.d mount in docker-compose.yaml). Subsequent
-- `docker compose up` runs keep the existing data untouched.
--
-- This is a deliberate pre-Alembic arrangement. While the schema is still moving,
-- the cheap answer is `docker compose down -v && up` to pick up changes. Once
-- the schema stabilizes (or real production installs appear), swap this for
-- Alembic.

CREATE TABLE users (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO users (id, name) VALUES (1, 'root');

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

INSERT INTO projects (id, name, uuid, user_id, project_root)
VALUES (1, 'default', 'default', 1, '/data/sessions/default');

-- The explicit id=1 insert above does not advance the SERIAL sequence, so the
-- next auto-generated insert (e.g. from POST /projects) would collide on id=1.
-- Align the sequence with the current max.
SELECT setval(pg_get_serial_sequence('projects', 'id'),
              (SELECT COALESCE(MAX(id), 1) FROM projects));

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

-- Default bootstrap seed. commit is empty and lazy-resolved on first branch
-- creation (see post_branch in coresearch-core/controlplane/api.py).
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
    parent_iteration_hash TEXT,
    deleted               BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE sessions (
    id             SERIAL PRIMARY KEY,
    branch_id      INT NOT NULL UNIQUE REFERENCES branches(id),
    runner         TEXT NOT NULL DEFAULT 'tmux',
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
    runner         TEXT NOT NULL,
    attach_command TEXT NOT NULL,
    agent          TEXT NOT NULL,
    status         TEXT NOT NULL,
    change_type    TEXT NOT NULL,
    changed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE FUNCTION log_session_change() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO session_history (session_id, attach_command, runner, agent, status, change_type)
    VALUES (NEW.id, NEW.attach_command, NEW.runner, NEW.agent, NEW.status,
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
