"""Transactional contact activation tests against disposable PostgreSQL.

Run with RUN_POSTGRES_TESTS=1 and a fresh PostgreSQL 18 service.
"""
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from sentinela.domain.chat import ACTIVATED, DEACTIVATED

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_POSTGRES_TESTS") != "1",
    reason="requires disposable PostgreSQL",
)


@pytest.fixture
def store():
    from sentinela.config import get_settings
    from sentinela.infrastructure.postgres import Store

    result = Store(get_settings())
    with result.connect() as conn:
        conn.execute(Path("db/001_initial.sql").read_text(encoding="utf-8"))
    result.migrate_guardrails()
    return result


def message(text: str, wid: str, *, instance: str = "sentinela", media: bool = False):
    from sentinela.domain.model import Kind, Message

    return Message(instance, str(uuid4()), wid, Kind.IMAGE if media else Kind.TEXT, text)


def wid() -> str:
    return str(uuid4().int)[:20]


def claim(store, sent):
    assert store.enqueue(sent)
    current = store.claim()
    assert current is not None
    assert current.message.message_id == sent.message_id
    return current


def confirm_ready(store, job, expected: str) -> None:
    with store.connect() as conn:
        row = conn.execute(
            "SELECT status,response,available_at,now() AS db_now FROM app.inbox WHERE id=%s",
            (job.id,),
        ).fetchone()
        assert row["status"] == "ready"
        assert row["response"] == expected
        # Scheduled delivery: the worker never sleeps inside a message handler.
        assert row["available_at"] > row["db_now"]
        conn.execute(
            "UPDATE app.inbox SET available_at=now() WHERE id=%s",
            (job.id,),
        )
    outgoing = store.claim()
    assert outgoing is not None
    assert outgoing.id == job.id and outgoing.response == expected
    store.finish(outgoing, "done")


def test_inactive_ignores_messages_and_does_not_reserve_quota(store) -> None:
    sender = wid()
    ignored = message("Oi, analise isto", sender)
    claimed = claim(store, ignored)
    assert store.gate(claimed) is False
    with store.connect() as conn:
        row = conn.execute(
            "SELECT status,response,payload FROM app.inbox WHERE id=%s", (claimed.id,)
        ).fetchone()
        session = conn.execute(
            "SELECT active FROM app.sessions WHERE instance=%s AND wid=%s",
            (ignored.instance, sender),
        ).fetchone()
        budget = conn.execute(
            "SELECT used FROM app.guard_budget WHERE scope=%s",
            (f"sender:{ignored.instance}:{sender}",),
        ).fetchone()
    assert row == {"status": "done", "response": None, "payload": {}}
    assert session == {"active": False}
    assert budget is None
    assert store.claim() is None


def test_activate_analyze_close_ignore_reactivate_and_recover(store) -> None:
    from sentinela.domain.model import Fact
    from sentinela.infrastructure.postgres import Store

    sender = wid()
    first = message("  sEnTiNeLa \t", sender)
    activated = claim(store, first)
    assert store.gate(activated) is False
    before = store.session(first)
    confirm_ready(store, activated, ACTIVATED)

    # State survives reconstructing the Store object and calling recovery.
    fresh = Store(store.settings)
    fresh.recover()
    assert fresh.session(first).session_id == before.session_id

    # Normal text follows the existing inference path, retaining session state.
    ordinary = message("O banco pediu meu código", sender)
    analyzing = claim(fresh, ordinary)
    assert fresh.gate(analyzing) is True
    changed = replace(fresh.session(ordinary), facts=frozenset({Fact.OTP}),
                      absent=frozenset({Fact.MONEY}), last_question="code",
                      asked_questions=frozenset({"code"}))
    fresh.save_result(analyzing, changed, "exemplo")
    confirm_ready(fresh, analyzing, "exemplo")

    # /nova and media go through analysis; the gate never treats them as commands.
    media = message("", sender, media=True)
    media_job = claim(fresh, media)
    assert fresh.gate(media_job) is True
    fresh.finish(media_job, "done")

    close = message("  ENcErRaR ", sender)
    closing = claim(fresh, close)
    assert fresh.gate(closing) is False
    confirm_ready(fresh, closing, DEACTIVATED)

    with fresh.connect() as conn:
        session = conn.execute(
            """SELECT active, session_id, facts, absent, last_question, asked_questions
               FROM app.sessions WHERE instance=%s AND wid=%s""",
            (close.instance, sender),
        ).fetchone()
    assert not session["active"]
    assert session["facts"] == session["absent"] == session["asked_questions"] == []
    assert session["last_question"] is None

    silent = message("/nova", sender)
    assert fresh.gate(claim(fresh, silent)) is False
    silent_media = message("", sender, media=True)
    assert fresh.gate(claim(fresh, silent_media)) is False

    # Reactivation must create a new conversation session without changing user ID.
    resume = message("SENTINELA", sender)
    resumed_job = claim(fresh, resume)
    assert fresh.gate(resumed_job) is False
    after = fresh.session(resume)
    assert after.user_id == before.user_id
    assert after.session_id != before.session_id
    assert not after.facts and not after.absent and not after.asked_questions
    assert after.last_question is None
    confirm_ready(fresh, resumed_job, ACTIVATED)


def test_separate_contact_remains_inactive_even_if_other_is_active(store) -> None:
    alice, bob = wid(), wid()
    active_message = message("Sentinela", alice)
    activated = claim(store, active_message)
    assert store.gate(activated) is False
    confirm_ready(store, activated, ACTIVATED)

    other = message("Ajuda", bob)
    assert store.gate(claim(store, other)) is False
    own = message("Envio uma denúncia", alice)
    active_job = claim(store, own)
    assert store.gate(active_job) is True
    store.finish(active_job, "done")

    different_instance = message("Ajuda", alice, instance="outra-instância")
    assert store.gate(claim(store, different_instance)) is False
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT instance,wid,active FROM app.sessions WHERE wid IN (%s,%s)",
            (alice,bob),
        ).fetchall()
    states = {(r["instance"],r["wid"]):r["active"] for r in rows}
    assert states[("sentinela",alice)] is True
    assert states[("sentinela",bob)] is False
    assert states[("outra-instância",alice)] is False


def test_ready_activation_blocks_following_message_until_delivery(store) -> None:
    sender = wid()
    command = message("Sentinela", sender)
    activation = claim(store, command)
    next_message = message("Golpe bancário", sender)
    assert store.enqueue(next_message)
    assert store.gate(activation) is False
    # The command confirmation is intentionally pending for a short moment.
    # A following message from this contact cannot bypass that waiting reply.
    assert store.claim() is None
    with store.connect() as conn:
        scheduled = conn.execute(
            "SELECT status,available_at,now() AS db_now FROM app.inbox WHERE id=%s",
            (activation.id,),
        ).fetchone()
        assert scheduled["status"] == "ready"
        assert scheduled["available_at"] > scheduled["db_now"]
        conn.execute("UPDATE app.inbox SET available_at=now() WHERE id=%s", (activation.id,))
    sending = store.claim()
    assert sending is not None and sending.id == activation.id
    with store.connect() as conn:
        row = conn.execute("SELECT status FROM app.inbox WHERE id=%s", (activation.id,)).fetchone()
    assert row["status"] == "sending"
    assert store.claim() is None
    store.recover()  # Sending is uncertain after a crash: never send twice.
    with store.connect() as conn:
        row = conn.execute("SELECT status FROM app.inbox WHERE id=%s", (activation.id,)).fetchone()
    assert row["status"] == "uncertain"
    second = store.claim()
    assert second is not None and second.message.message_id == next_message.message_id
    assert store.gate(second) is True
    store.finish(second, "done")


def test_gate_rollback_retry_and_duplicate_message(store, monkeypatch) -> None:
    from sentinela.infrastructure.postgres import Store

    sender = wid()
    msg = message("Sentinela", sender)
    job = claim(store, msg)
    original = Store._gate_complete

    def fail(*args, **kwargs):
        raise RuntimeError("transaction rollback test")

    monkeypatch.setattr(Store, "_gate_complete", staticmethod(fail))
    with pytest.raises(RuntimeError, match="transaction rollback"):
        store.gate(job)
    monkeypatch.setattr(Store, "_gate_complete", staticmethod(original))
    with store.connect() as conn:
        row = conn.execute("SELECT status,response FROM app.inbox WHERE id=%s", (job.id,)).fetchone()
        session = conn.execute(
            "SELECT active FROM app.sessions WHERE instance=%s AND wid=%s",
            (msg.instance,sender),
        ).fetchone()
    assert row == {"status": "processing", "response": None}
    assert session is None

    store.retry(job, "temporary failure")
    with store.connect() as conn:
        conn.execute("UPDATE app.inbox SET available_at=now() WHERE id=%s", (job.id,))
    pending = store.claim()
    assert pending is not None and pending.id == job.id
    assert store.gate(pending) is False
    # Duplicate webhook does not enqueue again, even after command processed.
    assert not store.enqueue(msg)
    confirm_ready(store, pending, ACTIVATED)


def test_worker_advisory_lock_is_exclusive(store) -> None:
    from sentinela.infrastructure.postgres import Store

    with store.worker_lock():
        with pytest.raises(RuntimeError, match="already holds the lock"):
            with Store(store.settings).worker_lock():
                raise AssertionError("second worker must not start")


def test_delayed_reply_does_not_block_other_contacts(store) -> None:
    sender, other = wid(), wid()
    activate = message("Sentinela", sender)
    assert store.gate(claim(store, activate)) is False

    # Same sender must wait for activation confirmation.
    second = message("Recebi um aviso suspeito", sender)
    assert store.enqueue(second)

    # An unrelated contact can still be claimed and gated immediately.
    stranger = message("Olá", other)
    assert store.enqueue(stranger)
    claimed = store.claim()
    assert claimed is not None and claimed.message.message_id == stranger.message_id
    assert store.gate(claimed) is False

    # The delayed activation is still pending and did not consume quota.
    with store.connect() as conn:
        row = conn.execute(
            "SELECT available_at,now() AS db_now FROM app.inbox WHERE instance=%s AND message_id=%s",
            (activate.instance,activate.message_id),
        ).fetchone()
        assert row["available_at"] > row["db_now"]
        quota = conn.execute(
            "SELECT used FROM app.guard_budget WHERE scope=%s",
            (f"sender:{activate.instance}:{sender}",),
        ).fetchone()
    assert quota is None


def test_zero_delay_can_be_configured(store) -> None:
    instant = type(store)(store.settings.model_copy(update={"gate_reply_delay_seconds": 0.0}))
    activate = message("Sentinela", wid())
    assert instant.gate(claim(instant, activate)) is False
    pending = instant.claim()
    assert pending is not None and pending.message.message_id == activate.message_id
    assert pending.response == ACTIVATED
    instant.finish(pending, "done")


def test_scheduled_reply_survives_worker_recovery(store) -> None:
    from sentinela.infrastructure.postgres import Store
    sender = wid()
    activation = message("SENTINELA", sender)
    job = claim(store, activation)
    assert store.gate(job) is False
    with store.connect() as conn:
        before = conn.execute(
            "SELECT available_at FROM app.inbox WHERE id=%s", (job.id,)
        ).fetchone()["available_at"]
    restarted = Store(store.settings)
    restarted.recover()
    with restarted.connect() as conn:
        after = conn.execute(
            "SELECT status,response,available_at FROM app.inbox WHERE id=%s", (job.id,)
        ).fetchone()
    assert after["status"] == "ready"
    assert after["response"] == ACTIVATED
    assert after["available_at"] == before
