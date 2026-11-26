CREATE SCHEMA IF NOT EXISTS agno;
CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE IF NOT EXISTS app.sessions (
  instance text NOT NULL, wid text NOT NULL, user_id uuid NOT NULL,
  session_id uuid NOT NULL, facts jsonb NOT NULL DEFAULT '[]',
  absent jsonb NOT NULL DEFAULT '[]', last_question text,
  asked_questions jsonb NOT NULL DEFAULT '[]',
  active boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (instance, wid)
);
CREATE TABLE IF NOT EXISTS app.inbox (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  instance text NOT NULL, message_id text NOT NULL, wid text NOT NULL,
  payload jsonb NOT NULL, status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','processing','ready','sending','done','failed','uncertain')),
  attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
  response text, error_code text, created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE (instance, message_id)
);
CREATE INDEX IF NOT EXISTS inbox_pending_idx ON app.inbox (available_at, id)
WHERE status IN ('pending','ready');

CREATE TABLE IF NOT EXISTS app.guard_budget (
  day date NOT NULL, scope text NOT NULL, used integer NOT NULL DEFAULT 0,
  PRIMARY KEY(day,scope)
);

CREATE INDEX IF NOT EXISTS inbox_sender_open_idx ON app.inbox(instance,wid,id)
WHERE status IN ('pending','processing','ready','sending');
CREATE INDEX IF NOT EXISTS inbox_terminal_retention_idx ON app.inbox(updated_at)
WHERE status IN ('done','failed','uncertain');
