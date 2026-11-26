"""Web-only persistence and concurrently claimable jobs. No Evolution dependency."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from psycopg.types.json import Jsonb

from sentinela.config import Settings
from sentinela.domain.model import Fact, Kind, Message, Session
from sentinela.infrastructure.web_pool import BoundedWebPool


@dataclass(frozen=True)
class WebJob:
    id: UUID
    conversation_id: UUID
    message_id: UUID
    generation: int
    lease_token: UUID
    attempts: int
    owner_id: str
    message: Message
    session: Session


class WebStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.pool = BoundedWebPool(settings)

    def connect(self):
        return self.pool.connection()

    def migrate(self) -> None:
        script = Path(__file__).resolve().parents[3] / "db" / "002_web.sql"
        with self.connect() as conn:
            conn.execute(script.read_text(encoding="utf-8"))

    @staticmethod
    def _event(conn, conversation_id: UUID, kind: str, payload: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO app.web_events(conversation_id,kind,payload) VALUES(%s,%s,%s)",
            (conversation_id, kind, Jsonb(payload)),
        )

    @staticmethod
    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]), "conversationId": str(row["conversation_id"]),
            "role": row["role"], "kind": row["kind"], "text": row["body"],
            "attachmentId": str(row["attachment_id"]) if row["attachment_id"] else None,
            "status": row["status"], "risk": row["risk"],
            "createdAt": row["created_at"].isoformat(),
        }

    def create_conversation(self, owner: str) -> dict[str, Any]:
        ident, user = uuid4(), uuid5(NAMESPACE_URL, "sentinela:web:" + owner)
        sess = uuid4()
        with self.connect() as conn:
            # Bound resource usage even when the account repeatedly opens conversations.
            count = conn.execute(
                "SELECT count(*) AS n FROM app.web_conversations WHERE owner_id=%s", (owner,)
            ).fetchone()["n"]
            if count >= 100:
                raise ValueError("conversation limit reached")
            conn.execute(
                """INSERT INTO app.web_conversations(id,owner_id,user_id,session_id)
                   VALUES(%s,%s,%s,%s)""",
                (ident, owner, user, sess),
            )
        return {"id": str(ident), "title": "Nova análise", "createdAt": datetime.now().astimezone().isoformat()}

    def list_conversations(self, owner: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id,title,updated_at FROM app.web_conversations
                   WHERE owner_id=%s ORDER BY updated_at DESC,id DESC LIMIT 100""", (owner,)
            ).fetchall()
        return [{"id": str(row["id"]), "title": row["title"],
                 "updatedAt": row["updated_at"].isoformat()} for row in rows]

    def _owned(self, conn, owner: str, conv: UUID, *, locked: bool = False):
        row = conn.execute(
            "SELECT * FROM app.web_conversations WHERE id=%s AND owner_id=%s"
            + (" FOR UPDATE" if locked else ""),
            (conv, owner),
        ).fetchone()
        if row is None:
            raise LookupError("conversation not found")
        return row

    def messages(self, owner: str, conv: UUID, before: datetime | None, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._owned(conn, owner, conv)
            rows = conn.execute(
                """SELECT * FROM app.web_messages
                   WHERE conversation_id=%s AND (%s::timestamptz IS NULL OR created_at < %s)
                   ORDER BY created_at DESC,id DESC LIMIT %s""",
                (conv, before, before, limit),
            ).fetchall()
        return [self._serialize(row) for row in reversed(rows)]

    def add_message(
        self, owner: str, conv: UUID, client_id: UUID, kind: Kind,
        text: str, attachment_id: UUID | None,
    ) -> tuple[dict[str, Any], bool]:
        with self.connect() as conn:
            conversation = self._owned(conn, owner, conv, locked=True)
            previous = conn.execute(
                """SELECT * FROM app.web_messages
                   WHERE conversation_id=%s AND client_message_id=%s""",
                (conv, client_id),
            ).fetchone()
            if previous:
                return self._serialize(previous), False
            queued = conn.execute(
                """SELECT count(*) AS n FROM app.web_jobs WHERE conversation_id=%s
                   AND status IN ('pending','processing')""", (conv,),
            ).fetchone()["n"]
            if queued >= 5:
                raise ValueError("too many pending messages")
            if kind == Kind.TEXT:
                if attachment_id is not None or not text.strip():
                    raise ValueError("invalid text input")
            elif attachment_id is None:
                raise ValueError("media attachment required")
            if attachment_id:
                exists = conn.execute(
                    """SELECT 1 FROM app.web_attachments WHERE id=%s
                       AND conversation_id=%s AND owner_id=%s AND mime LIKE %s""",
                    (attachment_id, conv, owner,
                     "image/%" if kind == Kind.IMAGE else "audio/%"),
                ).fetchone()
                if not exists:
                    raise ValueError("attachment does not belong to conversation")
            msg_id, job_id = uuid4(), uuid4()
            conn.execute(
                """INSERT INTO app.web_messages
                   (id,conversation_id,client_message_id,role,kind,body,attachment_id,status,generation)
                   VALUES (%s,%s,%s,'user',%s,%s,%s,'queued',%s)""",
                (msg_id, conv, client_id, kind.value, text, attachment_id,
                 conversation["generation"]),
            )
            conn.execute(
                """INSERT INTO app.web_jobs(id,conversation_id,input_message_id,generation,status)
                   VALUES (%s,%s,%s,%s,'pending')""",
                (job_id, conv, msg_id, conversation["generation"]),
            )
            if conversation["title"] == "Nova análise" and text.strip():
                title = " ".join(text.split())[:55]
                conn.execute(
                    "UPDATE app.web_conversations SET title=%s,updated_at=now() WHERE id=%s",
                    (title,conv),
                )
            else:
                conn.execute(
                    "UPDATE app.web_conversations SET updated_at=now() WHERE id=%s", (conv,)
                )
            saved = conn.execute("SELECT * FROM app.web_messages WHERE id=%s", (msg_id,)).fetchone()
            assert saved is not None
            view = self._serialize(saved)
            self._event(conn, conv, "message", {"message": view})
            return view, True

    def upload_attachment(
        self, owner: str, conv: UUID, ident: UUID, mime: str, size: int, checksum: str,
    ) -> None:
        with self.connect() as conn:
            self._owned(conn, owner, conv, locked=True)
            usage=conn.execute(
                """SELECT count(*) AS count,coalesce(sum(byte_size),0) AS total
                   FROM app.web_attachments WHERE conversation_id=%s""",(conv,),
            ).fetchone()
            if usage["count"]>=50 or usage["total"]+size>100000000:
                raise ValueError("attachment quota exceeded")
            conn.execute(
                """INSERT INTO app.web_attachments(id,conversation_id,owner_id,mime,byte_size,sha256)
                   VALUES(%s,%s,%s,%s,%s,%s)""",
                (ident, conv, owner, mime, size, checksum),
            )

    def reset(self, owner: str, conv: UUID) -> None:
        with self.connect() as conn:
            self._owned(conn, owner, conv, locked=True)
            conn.execute(
                """UPDATE app.web_conversations SET generation=generation+1, session_id=%s,
                   facts='[]',absent='[]',last_question=NULL,asked_questions='[]',
                   updated_at=now() WHERE id=%s""",
                (uuid4(), conv),
            )
            conn.execute(
                """UPDATE app.web_messages SET status='canceled'
                   WHERE conversation_id=%s AND status IN ('queued','processing')""", (conv,)
            )
            conn.execute(
                """UPDATE app.web_jobs SET status='canceled',updated_at=now()
                   WHERE conversation_id=%s AND status IN ('pending','processing')""", (conv,)
            )
            self._event(conn, conv, "reset", {"conversationId": str(conv)})

    def delete(self, owner: str, conv: UUID) -> list[UUID]:
        with self.connect() as conn:
            self._owned(conn, owner, conv, locked=True)
            files = conn.execute(
                "SELECT id FROM app.web_attachments WHERE conversation_id=%s", (conv,)
            ).fetchall()
            conn.execute("DELETE FROM app.web_conversations WHERE id=%s", (conv,))
            return [r["id"] for r in files]

    def events(self, owner: str, conv: UUID, after: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._owned(conn, owner, conv)
            rows = conn.execute(
                """SELECT id,kind,payload FROM app.web_events
                   WHERE conversation_id=%s AND id>%s ORDER BY id LIMIT 50""",
                (conv, after),
            ).fetchall()
        return [{"id": row["id"], "kind": row["kind"], "payload": row["payload"]} for row in rows]

    def prune_orphans(self) -> list[UUID]:
        with self.connect() as conn:
            rows=conn.execute(
                """DELETE FROM app.web_attachments a
                   WHERE a.created_at < now()-interval '1 day'
                     AND NOT EXISTS(SELECT 1 FROM app.web_messages m WHERE m.attachment_id=a.id)
                   RETURNING id"""
            ).fetchall()
            conn.execute("DELETE FROM app.web_events WHERE created_at<now()-interval '14 days'")
            return [row["id"] for row in rows]

    def recover(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE app.web_jobs SET status='pending',lease_token=NULL,lease_until=NULL,
                   updated_at=now() WHERE status='processing' AND lease_until<now()"""
            )

    def claim(self) -> WebJob | None:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT j.id,j.conversation_id,j.input_message_id,j.generation,
                          j.attempts,m.kind,m.body,m.attachment_id,c.owner_id,c.user_id,
                          c.session_id,c.facts,c.absent,c.last_question,c.asked_questions
                   FROM app.web_jobs j
                   JOIN app.web_conversations c ON c.id=j.conversation_id
                   JOIN app.web_messages m ON m.id=j.input_message_id
                   WHERE j.status='pending' AND j.available_at<=now()
                     AND j.generation=c.generation
                     AND NOT EXISTS (
                       SELECT 1 FROM app.web_jobs earlier
                       WHERE earlier.conversation_id=j.conversation_id
                         AND earlier.created_at<=j.created_at
                         AND earlier.id<>j.id
                         AND earlier.status IN ('pending','processing')
                         AND (earlier.created_at<j.created_at OR earlier.id<j.id)
                     )
                   ORDER BY j.created_at,j.id LIMIT 1 FOR UPDATE OF j SKIP LOCKED"""
            ).fetchone()
            if row is None:
                return None
            token = uuid4()
            conn.execute(
                """UPDATE app.web_jobs SET status='processing',attempts=attempts+1,
                   lease_token=%s,lease_until=now()+interval '120 seconds',updated_at=now()
                   WHERE id=%s""", (token,row["id"])
            )
            conn.execute(
                "UPDATE app.web_messages SET status='processing' WHERE id=%s",
                (row["input_message_id"],)
            )
            self._event(conn, row["conversation_id"], "processing", {
                "messageId": str(row["input_message_id"]), "status": "processing",
            })
            media = {"attachment_id": str(row["attachment_id"])} if row["attachment_id"] else None
            return WebJob(
                row["id"],row["conversation_id"],row["input_message_id"],row["generation"],
                token,row["attempts"]+1,row["owner_id"],
                Message("web",str(row["input_message_id"]),str(row["conversation_id"]),
                        Kind(row["kind"]),row["body"],media_envelope=media),
                Session(row["user_id"],row["session_id"],frozenset(map(Fact,row["facts"])),
                        frozenset(map(Fact,row["absent"])),row["last_question"],
                        frozenset(row["asked_questions"])),
            )

    def heartbeat(self, job: WebJob) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE app.web_jobs SET lease_until=now()+interval '120 seconds'
                   WHERE id=%s AND lease_token=%s AND status='processing'""",
                (job.id,job.lease_token),
            )

    def reserve(self, job: WebJob) -> bool:
        """Reserve one inference quota per job, never once per delivery attempt.

        The job lock and budget locks are held in one transaction. On a retry,
        quota_reserved makes this a no-op. Both web and WhatsApp use the same
        global daily budget; scopes are locked in deterministic order.
        """
        scopes = (("global", self.settings.guard_global_daily),
                  ("web:" + job.owner_id, self.settings.guard_user_daily))
        with self.connect() as conn:
            row = conn.execute(
                """SELECT quota_reserved FROM app.web_jobs
                   WHERE id=%s AND lease_token=%s AND status='processing'
                   FOR UPDATE""",
                (job.id, job.lease_token),
            ).fetchone()
            if row is None:
                return False
            if row["quota_reserved"]:
                return True
            for scope, _ in scopes:
                conn.execute(
                    """INSERT INTO app.guard_budget(day,scope)
                       VALUES((now() AT TIME ZONE 'UTC')::date,%s)
                       ON CONFLICT DO NOTHING""",
                    (scope,),
                )
            for scope, maximum in scopes:
                used = conn.execute(
                    """SELECT used FROM app.guard_budget
                       WHERE day=(now() AT TIME ZONE 'UTC')::date AND scope=%s
                       FOR UPDATE""", (scope,),
                ).fetchone()
                if used is None or used["used"] >= maximum:
                    return False
            for scope, _ in scopes:
                conn.execute(
                    """UPDATE app.guard_budget SET used=used+1
                       WHERE day=(now() AT TIME ZONE 'UTC')::date AND scope=%s""",
                    (scope,),
                )
            conn.execute(
                "UPDATE app.web_jobs SET quota_reserved=true WHERE id=%s",
                (job.id,),
            )
            return True

    def complete(self, job: WebJob, result: Session, response: str, risk: str | None) -> bool:
        with self.connect() as conn:
            valid = conn.execute(
                """SELECT j.id FROM app.web_jobs j
                   JOIN app.web_conversations c ON c.id=j.conversation_id
                   WHERE j.id=%s AND j.status='processing' AND j.lease_token=%s
                     AND j.generation=c.generation FOR UPDATE OF j,c""",
                (job.id, job.lease_token),
            ).fetchone()
            if not valid:
                return False
            conn.execute(
                """UPDATE app.web_conversations SET session_id=%s,facts=%s,absent=%s,
                   last_question=%s,asked_questions=%s,updated_at=now() WHERE id=%s""",
                (result.session_id,Jsonb(sorted(result.facts)),Jsonb(sorted(result.absent)),
                 result.last_question,Jsonb(sorted(result.asked_questions)),job.conversation_id),
            )
            assistant_id=uuid4()
            conn.execute(
                """INSERT INTO app.web_messages
                   (id,conversation_id,role,kind,body,status,risk,generation)
                   VALUES(%s,%s,'assistant','text',%s,'completed',%s,%s)""",
                (assistant_id,job.conversation_id,response,risk,job.generation),
            )
            conn.execute(
                "UPDATE app.web_messages SET status='completed' WHERE id=%s",
                (job.message_id,),
            )
            conn.execute(
                """UPDATE app.web_jobs SET status='done',lease_token=NULL,
                   lease_until=NULL,updated_at=now() WHERE id=%s""", (job.id,)
            )
            msg = conn.execute("SELECT * FROM app.web_messages WHERE id=%s",(assistant_id,)).fetchone()
            assert msg is not None
            self._event(conn,job.conversation_id,"message",{"message":self._serialize(msg)})
            return True

    def fail(self, job: WebJob, code: str, *, transient: bool = True) -> None:
        with self.connect() as conn:
            valid = conn.execute(
                """SELECT 1 FROM app.web_jobs WHERE id=%s AND lease_token=%s
                   AND status='processing' FOR UPDATE""",
                (job.id,job.lease_token),
            ).fetchone()
            if not valid:
                return
            if transient and job.attempts < 3:
                conn.execute(
                    """UPDATE app.web_jobs SET status='pending',lease_token=NULL,
                       lease_until=NULL,available_at=now()+(%s * interval '1 second'),
                       error_code=%s,updated_at=now() WHERE id=%s""",
                    (2**job.attempts,code,job.id),
                )
            else:
                conn.execute(
                    """UPDATE app.web_jobs SET status='failed',lease_token=NULL,
                       lease_until=NULL,error_code=%s,updated_at=now() WHERE id=%s""",
                    (code,job.id),
                )
                conn.execute(
                    "UPDATE app.web_messages SET status='failed' WHERE id=%s",
                    (job.message_id,),
                )
                self._event(conn,job.conversation_id,"failed",{
                    "messageId":str(job.message_id),"status":"failed",
                    "text":"Não consegui analisar agora. Você pode tentar novamente.",
                })
