"""Race, retry, event delivery and media-retention regression tests.

Uses disposable PostgreSQL 18, not mocks for transaction boundaries.
"""
import asyncio
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest

from sentinela.application.analyze import AnalyzeMessage
from sentinela.config import Settings
from sentinela.domain.model import Fact, Kind, Observation
from sentinela.infrastructure.web_events import WebEventBus
from sentinela.infrastructure.web_store import WebStore
from sentinela.infrastructure.postgres import Store
from sentinela.interfaces.web_worker import process_web_job


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_POSTGRES_TESTS") != "1",
    reason="requires disposable PostgreSQL",
)
OWNER = "e" * 64
SECOND = "d" * 64


@pytest.fixture
def store(tmp_path: Path) -> WebStore:
    config = Settings(
        postgres_host="localhost",postgres_port=5432,postgres_user="sentinela",
        postgres_password=os.environ.get("POSTGRES_PASSWORD","disposable-ci-password-123456789"),
        postgres_db="sentinela",
        webhook_api_key="disposable-webhook-secret-123456789",
        evolution_api_url="https://example.invalid",
        evolution_api_key="test",evolution_instance="sentinela",openai_api_key="test",
        web_internal_key="internal-test-key-with-at-least-32-characters",
        web_media_dir=str(tmp_path),
    )
    with Store(config).connect() as connection:
        connection.execute(Path("db/001_initial.sql").read_text(encoding="utf-8"))
    web = WebStore(config)
    web.migrate()
    with web.connect() as connection:
        connection.execute("TRUNCATE app.web_conversations CASCADE")
    yield web
    web.pool.close()


def open_case(store: WebStore, owner: str = OWNER) -> UUID:
    return UUID(store.create_conversation(owner)["id"])


def submit(store: WebStore, conversation: UUID, owner: str = OWNER) -> None:
    store.add_message(owner, conversation, uuid4(), Kind.TEXT,
                      "Meu banco pediu código por SMS", None)


def used(store: WebStore, scope: str) -> int:
    with store.connect() as connection:
        result = connection.execute(
            """SELECT used FROM app.guard_budget
               WHERE scope=%s AND day=(now() AT TIME ZONE 'UTC')::date""",
            (scope,),
        ).fetchone()
    return result["used"] if result else 0


def test_quota_is_charged_once_across_transient_retries(store: WebStore) -> None:
    conv = open_case(store)
    submit(store, conv)
    job = store.claim()
    assert job is not None
    before_user = used(store, "web:" + OWNER)
    before_global = used(store, "global")
    assert store.reserve(job) is True
    assert used(store, "web:" + OWNER) == before_user + 1
    assert used(store, "global") == before_global + 1
    store.fail(job, "transient-model-timeout")
    with store.connect() as connection:
        connection.execute(
            "UPDATE app.web_jobs SET available_at=now()-interval '1 second' WHERE id=%s",
            (job.id,),
        )
    repeated = store.claim()
    assert repeated is not None and repeated.id == job.id
    assert repeated.attempts == 2
    assert store.reserve(repeated) is True
    assert used(store, "web:" + OWNER) == before_user + 1
    assert used(store, "global") == before_global + 1
    assert store.complete(repeated, repeated.session, "Concluído", None)


def test_preflight_reply_does_not_inherit_old_risk_label(store: WebStore) -> None:
    class Fake:
        def extract(self, text, image, session):
            return Observation(frozenset({Fact.BANK, Fact.OTP}), frozenset(), False)
        def choose(self, assessment, options, session): return None
        def inspect(self, text): return frozenset()
        def download(self, message): raise AssertionError("text only")
        def transcribe(self, media): raise AssertionError("text only")

    fake = Fake()
    core = AnalyzeMessage(fake,fake,fake,fake,fake)
    conversation = open_case(store)
    submit(store, conversation)
    first=store.claim()
    assert first is not None
    process_web_job(first,store,core)
    assert store.messages(OWNER,conversation,None)[-1]["risk"] == "ALTO"

    store.add_message(OWNER,conversation,uuid4(),Kind.TEXT,"oi",None)
    quota_before = used(store, "web:" + OWNER)
    greeting=store.claim()
    assert greeting is not None
    process_web_job(greeting,store,core)
    messages=store.messages(OWNER,conversation,None)
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["risk"] is None
    assert "Sentinela" in messages[-1]["text"]
    assert used(store, "web:" + OWNER) == quota_before


def test_workers_claim_distinct_conversations_concurrently(store: WebStore) -> None:
    c1,c2=open_case(store),open_case(store,SECOND)
    submit(store,c1)
    submit(store,c2,SECOND)
    barrier=Barrier(2)

    def claim():
        barrier.wait(timeout=5)
        return store.claim()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures=[executor.submit(claim) for _ in range(2)]
        jobs=[f.result(timeout=10) for f in futures]
    assert all(job is not None for job in jobs)
    assert {job.conversation_id for job in jobs if job is not None} == {c1,c2}
    for job in jobs:
        assert job is not None
        assert store.complete(job,job.session,"Resolução",None)


def test_concurrent_reset_and_completion_do_not_deadlock(store: WebStore) -> None:
    conversation=open_case(store)
    submit(store,conversation)
    job=store.claim()
    assert job is not None
    barrier=Barrier(2)

    def complete():
        barrier.wait(timeout=5)
        return store.complete(job,replace(job.session,facts=frozenset({Fact.BANK})),
                              "Resposta da sessão anterior","MODERADO")

    def reset():
        barrier.wait(timeout=5)
        return store.reset(OWNER,conversation)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1=pool.submit(complete)
        f2=pool.submit(reset)
        f1.result(timeout=10)
        f2.result(timeout=10)
    with store.connect() as connection:
        row=connection.execute(
            "SELECT generation,facts FROM app.web_conversations WHERE id=%s",
            (conversation,),
        ).fetchone()
    assert row is not None and row["generation"]==2 and row["facts"]==[]
    # The new generation must never include an old response.
    with store.connect() as connection:
        count=connection.execute(
            """SELECT count(*) AS n FROM app.web_messages
               WHERE conversation_id=%s AND generation=2 AND role='assistant'""",
            (conversation,),
        ).fetchone()["n"]
    assert count==0


def test_database_notifications_wake_sse_subscribers(store: WebStore) -> None:
    async def scenario():
        bus=WebEventBus(store.settings)
        bus.start()
        try:
            await asyncio.wait_for(bus.ready.wait(),timeout=10)
            conv=await asyncio.to_thread(open_case,store)
            wake=bus.subscribe(conv)
            try:
                await asyncio.to_thread(submit,store,conv)
                await asyncio.wait_for(wake.wait(),timeout=10)
                events=await asyncio.to_thread(store.events,OWNER,conv,0)
                assert any(event["kind"]=="message" for event in events)
            finally:
                bus.unsubscribe(conv,wake)
        finally:
            await bus.close()

    asyncio.run(scenario())


def test_filesystem_reconciliation_and_retention(store: WebStore, tmp_path: Path) -> None:
    conversation=open_case(store)
    keep=uuid4()
    payload=b"\x89PNG\r\n\x1a\n"+b"valid-test-image"
    store.upload_attachment(OWNER,conversation,keep,"image/png",
                            len(payload),hashlib.sha256(payload).hexdigest())
    keep_file=tmp_path/str(keep)
    keep_file.write_bytes(payload)
    orphan_file=tmp_path/str(uuid4())
    orphan_file.write_bytes(payload)
    stale_time=os.stat(orphan_file).st_mtime-7200
    os.utime(orphan_file,(stale_time,stale_time))
    os.utime(keep_file,(stale_time,stale_time))
    assert store.reconcile_files(str(tmp_path),min_age_seconds=3600)==1
    assert keep_file.exists() and not orphan_file.exists()

    with store.connect() as connection:
        connection.execute(
            "UPDATE app.web_conversations SET updated_at=now()-interval '100 days' WHERE id=%s",
            (conversation,),
        )
    deleted=store.prune_orphans()
    assert keep in deleted
    assert store.reconcile_files(str(tmp_path),min_age_seconds=3600)==1
    assert not keep_file.exists()
