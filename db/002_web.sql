-- Web channel: isolated from Evolution sessions and inbox.
CREATE TABLE IF NOT EXISTS app.web_conversations (
  id uuid PRIMARY KEY,
  owner_id text NOT NULL,
  user_id uuid NOT NULL,
  session_id uuid NOT NULL,
  title text NOT NULL DEFAULT 'Nova análise',
  generation integer NOT NULL DEFAULT 1,
  facts jsonb NOT NULL DEFAULT '[]',
  absent jsonb NOT NULL DEFAULT '[]',
  last_question text,
  asked_questions jsonb NOT NULL DEFAULT '[]',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS web_conversations_owner_idx
  ON app.web_conversations(owner_id, updated_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS app.web_attachments (
  id uuid PRIMARY KEY,
  conversation_id uuid NOT NULL REFERENCES app.web_conversations(id) ON DELETE CASCADE,
  owner_id text NOT NULL,
  mime text NOT NULL,
  byte_size bigint NOT NULL CHECK (byte_size > 0 AND byte_size <= 8000000),
  sha256 text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS web_attachments_owner_idx
  ON app.web_attachments(conversation_id, owner_id);

CREATE TABLE IF NOT EXISTS app.web_messages (
  id uuid PRIMARY KEY,
  conversation_id uuid NOT NULL REFERENCES app.web_conversations(id) ON DELETE CASCADE,
  client_message_id uuid,
  role text NOT NULL CHECK (role IN ('user','assistant')),
  kind text NOT NULL CHECK (kind IN ('text','image','audio')),
  body text NOT NULL DEFAULT '',
  attachment_id uuid REFERENCES app.web_attachments(id) ON DELETE SET NULL,
  status text NOT NULL CHECK (status IN ('queued','processing','completed','failed','canceled')),
  risk text CHECK (risk IN ('ALTO','MODERADO','INCONCLUSIVO')),
  generation integer NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(conversation_id, client_message_id)
);
CREATE INDEX IF NOT EXISTS web_messages_history_idx
  ON app.web_messages(conversation_id,created_at,id);

CREATE TABLE IF NOT EXISTS app.web_jobs (
  id uuid PRIMARY KEY,
  conversation_id uuid NOT NULL REFERENCES app.web_conversations(id) ON DELETE CASCADE,
  input_message_id uuid NOT NULL UNIQUE REFERENCES app.web_messages(id) ON DELETE CASCADE,
  generation integer NOT NULL,
  status text NOT NULL CHECK (status IN ('pending','processing','done','failed','canceled')),
  attempts integer NOT NULL DEFAULT 0,
  quota_reserved boolean NOT NULL DEFAULT false,
  available_at timestamptz NOT NULL DEFAULT now(),
  lease_until timestamptz,
  lease_token uuid,
  error_code text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS web_jobs_ready_idx ON app.web_jobs(available_at,created_at)
  WHERE status='pending';
CREATE INDEX IF NOT EXISTS web_jobs_order_idx ON app.web_jobs(conversation_id,created_at)
  WHERE status IN ('pending','processing');

CREATE TABLE IF NOT EXISTS app.web_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  conversation_id uuid NOT NULL REFERENCES app.web_conversations(id) ON DELETE CASCADE,
  kind text NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS web_events_cursor_idx
  ON app.web_events(conversation_id,id);

CREATE INDEX IF NOT EXISTS web_jobs_lease_idx ON app.web_jobs(lease_until)
  WHERE status='processing';

-- Compatible with installations that already ran the initial web migration.
ALTER TABLE app.web_jobs ADD COLUMN IF NOT EXISTS quota_reserved boolean NOT NULL DEFAULT false;


-- Replay protection for signed internal BFF requests. Removed after expiration.
CREATE TABLE IF NOT EXISTS app.web_request_nonces (
  id uuid PRIMARY KEY,
  used_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS web_request_nonces_retention_idx
  ON app.web_request_nonces(used_at);
