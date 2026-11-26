"""Durable inbox, user identity, and session state."""
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from sentinela.config import Settings
from sentinela.domain.model import Fact, Kind, Message, Session

@dataclass(frozen=True, slots=True)
class Job:
    id: int
    message: Message
    attempts: int
    response: str | None

class Store:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def connect(self) -> psycopg.Connection[dict[str, Any]]:
        s = self.settings
        return psycopg.connect(host=s.postgres_host, port=s.postgres_port, user=s.postgres_user,
            password=s.postgres_password.get_secret_value(), dbname=s.postgres_db,
            row_factory=dict_row, connect_timeout=5)

    def migrate_guardrails(self) -> None:
        # Idempotent migration, also applied on existing VPS volumes.
        with self.connect() as conn:
            conn.execute("ALTER TABLE app.sessions ADD COLUMN IF NOT EXISTS asked_questions jsonb NOT NULL DEFAULT '[]'")
            conn.execute("""CREATE INDEX IF NOT EXISTS inbox_sender_open_idx ON app.inbox(instance,wid,id)
                WHERE status IN ('pending','processing','ready','sending')""")
            conn.execute("""CREATE INDEX IF NOT EXISTS inbox_terminal_retention_idx ON app.inbox(updated_at)
                WHERE status IN ('done','failed','uncertain')""")
            conn.execute("""CREATE TABLE IF NOT EXISTS app.guard_budget (
                day date NOT NULL, scope text NOT NULL, used integer NOT NULL DEFAULT 0,
                PRIMARY KEY(day,scope))""")

    def reserve(self, job: Job) -> bool:
        """Atomic daily quota per sender and global; each attempt consumes one reservation."""
        with self.connect() as conn:
            scopes = (("global", self.settings.guard_global_daily),
                      ("sender:" + job.message.instance + ":" + job.message.wid, self.settings.guard_user_daily))
            for scope, _ in scopes:
                conn.execute("""INSERT INTO app.guard_budget(day,scope) VALUES((now() AT TIME ZONE 'UTC')::date,%s)
                    ON CONFLICT DO NOTHING""",(scope,))
            for scope, maximum in scopes:
                row = conn.execute("""SELECT used FROM app.guard_budget
                    WHERE day=(now() AT TIME ZONE 'UTC')::date AND scope=%s FOR UPDATE""",(scope,)).fetchone()
                if row is None or row["used"] >= maximum:
                    return False
            for scope, _ in scopes:
                conn.execute("""UPDATE app.guard_budget SET used=used+1
                    WHERE day=(now() AT TIME ZONE 'UTC')::date AND scope=%s""",(scope,))
            return True

    def prune(self, *, days: int = 7) -> int:
        """Remove terminal inbox rows and expired quota counters."""
        if days < 1:
            raise ValueError("retention must be positive")
        with self.connect() as conn:
            deleted = conn.execute("""DELETE FROM app.inbox
                WHERE status IN ('done','failed','uncertain')
                AND updated_at < now() - (%s * interval '1 day')""", (days,))
            conn.execute("""DELETE FROM app.guard_budget
                WHERE day < (now() AT TIME ZONE 'UTC')::date - interval '31 days'""")
            return deleted.rowcount

    def ready(self) -> None:
        with self.connect() as conn:
            conn.execute("SELECT 1 FROM app.inbox LIMIT 1")

    def enqueue(self, message: Message) -> bool:
        with self.connect() as conn:
            cur = conn.execute("""INSERT INTO app.inbox(instance,message_id,wid,payload)
                VALUES (%s,%s,%s,%s) ON CONFLICT(instance,message_id) DO NOTHING""",
                (message.instance, message.message_id, message.wid, Jsonb(asdict(message))))
            return cur.rowcount == 1

    def recover(self) -> None:
        # Single worker deployment. A crashed send cannot safely be replayed.
        with self.connect() as conn:
            conn.execute("UPDATE app.inbox SET status='pending' WHERE status='processing'")
            conn.execute("UPDATE app.inbox SET status='uncertain', payload='{}' WHERE status='sending'")

    def claim(self) -> Job | None:
        with self.connect() as conn:
            row = conn.execute("""SELECT * FROM app.inbox i WHERE status IN ('pending','ready')
                AND available_at<=now() AND NOT EXISTS (
                SELECT 1 FROM app.inbox p WHERE p.instance=i.instance AND p.wid=i.wid
                  AND p.id<i.id AND p.status IN ('pending','processing','ready','sending'))
                ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED""").fetchone()
            if row is None:
                return None
            conn.execute("UPDATE app.inbox SET status=%s,attempts=attempts+1,updated_at=now() WHERE id=%s",
                         ("sending" if row["response"] else "processing", row["id"]))
            payload = dict(row["payload"])
            payload["kind"] = Kind(payload["kind"])
            return Job(row["id"], Message(**payload), row["attempts"]+1, row["response"])

    def session(self, message: Message) -> Session:
        with self.connect() as conn:
            conn.execute("""INSERT INTO app.sessions(instance,wid,user_id,session_id)
                VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (message.instance,message.wid,uuid4(),uuid4()))
            row = conn.execute("SELECT * FROM app.sessions WHERE instance=%s AND wid=%s",
                (message.instance,message.wid)).fetchone()
            assert row is not None
            return Session(row["user_id"],row["session_id"],frozenset(map(Fact,row["facts"])),
                frozenset(map(Fact,row["absent"])),row["last_question"],frozenset(row["asked_questions"]))

    def save_result(self, job: Job, session: Session, response: str) -> None:
        with self.connect() as conn:
            changed = conn.execute("""UPDATE app.sessions SET session_id=%s,facts=%s,absent=%s,last_question=%s,asked_questions=%s,
                updated_at=now() WHERE instance=%s AND wid=%s AND user_id=%s""",
                (session.session_id,Jsonb(sorted(session.facts)),Jsonb(sorted(session.absent)),
                 session.last_question,Jsonb(sorted(session.asked_questions)),job.message.instance,job.message.wid,session.user_id))
            if changed.rowcount != 1:
                raise ValueError("session ownership mismatch")
            conn.execute("UPDATE app.inbox SET status='ready',response=%s,updated_at=now() WHERE id=%s",
                         (response,job.id))

    def finish(self, job: Job, status: str, error: str | None = None) -> None:
        if status not in {"done","failed","uncertain"}:
            raise ValueError("invalid terminal status")
        with self.connect() as conn:
            conn.execute("UPDATE app.inbox SET status=%s,error_code=%s,payload='{}',response=NULL,updated_at=now() WHERE id=%s",
                         (status,error,job.id))

    def retry(self, job: Job, error: str) -> None:
        if job.attempts >= 3:
            self.finish(job,"failed",error)
            return
        with self.connect() as conn:
            conn.execute("""UPDATE app.inbox SET status='pending',error_code=%s,
                available_at=now()+(%s * interval '1 second'),updated_at=now() WHERE id=%s""",
                (error,2**job.attempts,job.id))
