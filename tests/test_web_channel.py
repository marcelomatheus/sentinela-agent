"""Web channel integration: identity, isolation, idempotency, concurrency, leases."""
import hashlib
import hmac
import os
import time
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from sentinela.config import Settings
from sentinela.domain.model import Fact, Kind
from sentinela.domain.inference import infer
from sentinela.infrastructure.web_media import sniff_media
from sentinela.infrastructure.web_store import WebStore

SECRET="internal-bff-hmac-secret-1234567890-secure"
BASE="a"*64
OTHER="b"*64

pytestmark=pytest.mark.skipif(
    os.environ.get("RUN_POSTGRES_TESTS")!="1",reason="requires disposable PostgreSQL",
)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        postgres_host="localhost",postgres_port=5432,
        postgres_user="sentinela",
        postgres_password=os.environ.get("POSTGRES_PASSWORD","disposable-ci-password-123456789"),
        postgres_db="sentinela",
        webhook_api_key="integration-test-webhook-secret-123456789",
        evolution_api_url="https://example.invalid",
        evolution_api_key="test",evolution_instance="sentinela",
        openai_api_key="test",
        web_internal_key=SECRET,web_media_dir=str(tmp_path),
    )


@pytest.fixture
def store(settings):
    from pathlib import Path
    from sentinela.infrastructure.postgres import Store
    db=Store(settings)
    with db.connect() as conn:
        conn.execute(Path("db/001_initial.sql").read_text(encoding="utf-8"))
    web=WebStore(settings)
    web.migrate()
    with web.connect() as conn:
        conn.execute("TRUNCATE app.web_conversations CASCADE")
    return web


def signed(owner=BASE, ts=None, *, method="GET",
           path="/internal/web/conversations", body=b"", nonce=None):
    timestamp=str(int(time.time()) if ts is None else ts)
    unique=nonce or str(uuid4())
    digest=hashlib.sha256(body).hexdigest()
    canonical="\n".join((owner,timestamp,unique,method,path,digest))
    sig=hmac.new(SECRET.encode(),canonical.encode(),hashlib.sha256).hexdigest()
    return {
        "x-sentinela-principal":owner,
        "x-sentinela-timestamp":timestamp,
        "x-sentinela-nonce":unique,
        "x-sentinela-body-sha256":digest,
        "x-sentinela-signature":sig,
    }


def test_auth_signature_and_ownership(settings,store,monkeypatch):
    from sentinela.interfaces import web_auth
    from sentinela.interfaces.http import create_app

    monkeypatch.setattr(web_auth,"get_settings",lambda:settings)
    class Inbox:
        def enqueue(self,message):return True
        def ready(self):return None

    with TestClient(create_app(settings,Inbox())) as client:
        unauth=client.post("/internal/web/conversations")
        assert unauth.status_code==401
        expired=client.post("/internal/web/conversations",headers=signed(
            ts=int(time.time())-400,method="POST",
        ))
        assert expired.status_code==401
        created=client.post("/internal/web/conversations",headers=signed(method="POST"))
        assert created.status_code==201,created.text
        conv=created.json()["id"]
        path=f"/internal/web/conversations/{conv}/messages"
        assert client.get(path,headers=signed(OTHER,path=path)).status_code==404
        raw=b'{"clientMessageId":"' + str(uuid4()).encode() + b'","kind":"text","text":""}'
        bad=client.post(path,content=raw,headers={
            **signed(method="POST",path=path,body=raw),
            "content-type":"application/json",
        })
        assert bad.status_code==400
        assert client.get("/internal/web/conversations",headers=signed()).status_code==200


def test_internal_signature_covers_method_path_body_and_nonce(settings,store,monkeypatch):
    from sentinela.interfaces import web_auth
    from sentinela.interfaces.http import create_app

    monkeypatch.setattr(web_auth,"get_settings",lambda:settings)
    class Inbox:
        def enqueue(self,message):return True
        def ready(self):return None

    with TestClient(create_app(settings,Inbox())) as client:
        signed_post=signed(method="POST")
        good=client.post("/internal/web/conversations",headers=signed_post)
        assert good.status_code==201
        assert client.post("/internal/web/conversations",headers=signed_post).status_code==401
        # Signature for POST cannot authorize a GET nor another path.
        assert client.get("/internal/web/conversations",headers=signed(method="POST")).status_code==401
        assert client.post("/internal/web/conversations",
                           content=b"tampered",headers=signed(method="POST")).status_code==401


def test_idempotency_and_serialization(store):
    conv=UUID(store.create_conversation(BASE)["id"])
    first_id=uuid4()
    first,fresh=store.add_message(BASE,conv,first_id,Kind.TEXT,"Banco pediu código",None)
    again,new=store.add_message(BASE,conv,first_id,Kind.TEXT,"Outro texto",None)
    assert fresh and not new
    assert again["id"]==first["id"]
    assert again["text"]=="Banco pediu código"
    second,_=store.add_message(BASE,conv,uuid4(),Kind.TEXT,"Me pediu outro SMS",None)
    job=store.claim()
    assert job is not None and str(job.message_id)==first["id"]
    assert job.message.text=="Banco pediu código"
    assert store.claim() is None # same conversation cannot overtake
    assessed=frozenset({Fact.BANK,Fact.OTP})
    from dataclasses import replace
    result=replace(job.session,facts=assessed)
    assert store.complete(job,result,"Não informe o código",infer(assessed).risk.value)
    followup=store.claim()
    assert followup is not None and str(followup.message_id)==second["id"]
    assert followup.session.facts==assessed
    assert followup.session.session_id==job.session.session_id
    store.complete(followup,followup.session,"Confirme pelo aplicativo",None)
    history=store.messages(BASE,conv,None)
    assert len(history)==4 and history[0]["role"]=="user"
    assert history[1]["role"]=="user" or history[1]["role"]=="assistant"
    assert any(m["risk"]=="ALTO" for m in history)
    assert len(store.events(BASE,conv,0))>=4


def test_two_conversations_can_be_claimed_in_parallel(store):
    a,b=UUID(store.create_conversation(BASE)["id"]),UUID(store.create_conversation(OTHER)["id"])
    store.add_message(BASE,a,uuid4(),Kind.TEXT,"Banco",None)
    store.add_message(OTHER,b,uuid4(),Kind.TEXT,"Loja",None)
    first=store.claim()
    second=store.claim()
    assert first is not None and second is not None
    assert first.conversation_id != second.conversation_id
    store.complete(first,first.session,"Resposta A",None)
    store.complete(second,second.session,"Resposta B",None)


def test_reset_cancels_inflight_and_fences_old_completion(store):
    conv=UUID(store.create_conversation(BASE)["id"])
    store.add_message(BASE,conv,uuid4(),Kind.TEXT,"Conta bloqueada",None)
    job=store.claim()
    assert job is not None
    store.reset(BASE,conv)
    from dataclasses import replace
    assert store.complete(job,replace(job.session,facts=frozenset({Fact.BANK})),"stale","ALTO") is False
    with store.connect() as conn:
        c=conn.execute("SELECT session_id,generation,facts FROM app.web_conversations WHERE id=%s",(conv,)).fetchone()
        assert c["generation"]==2 and c["facts"]==[]
    assert not any(m["role"]=="assistant" for m in store.messages(BASE,conv,None))


def test_expired_lease_is_reclaimed_without_double_delivery(store):
    conv=UUID(store.create_conversation(BASE)["id"])
    store.add_message(BASE,conv,uuid4(),Kind.TEXT,"Preciso de ajuda",None)
    first=store.claim()
    assert first is not None
    with store.connect() as conn:
        conn.execute("UPDATE app.web_jobs SET lease_until=now()-interval '1 second' WHERE id=%s",(first.id,))
    store.recover()
    second=store.claim()
    assert second is not None and second.id==first.id
    assert second.lease_token != first.lease_token
    assert store.complete(first,first.session,"stale",None) is False
    assert store.complete(second,second.session,"trusted",None) is True
    assert sum(m["role"]=="assistant" for m in store.messages(BASE,conv,None))==1


def test_attachment_is_private_and_validated(store):
    conv=UUID(store.create_conversation(BASE)["id"])
    attachment=uuid4()
    data=b"\x89PNG\r\n\x1a\n"+b"valid-example-image"
    assert sniff_media(data,"image/png")=="image/png"
    with pytest.raises(ValueError):
        sniff_media(b"<html>bad</html>","image/png")
    store.upload_attachment(BASE,conv,attachment,"image/png",len(data),hashlib.sha256(data).hexdigest())
    with pytest.raises(LookupError):
        store.add_message(OTHER,conv,uuid4(),Kind.IMAGE,"",attachment)
    store.add_message(BASE,conv,uuid4(),Kind.IMAGE,"",attachment)
    job=store.claim()
    assert job is not None and job.message.kind==Kind.IMAGE
    assert job.message.media_envelope=={"attachment_id":str(attachment)}
    store.complete(job,job.session,"Analisado",None)


def test_web_worker_uses_common_analysis_case(store):
    from sentinela.application.analyze import AnalyzeMessage
    from sentinela.domain.model import Observation
    from sentinela.interfaces.web_worker import process_web_job
    class Fake:
        def extract(self,text,image,session):
            return Observation(frozenset({Fact.BANK,Fact.OTP}),frozenset(),False,True,
                               "um banco pediu um código por SMS")
        def choose(self,assessment,options,session):return None
        def inspect(self,text):return frozenset()
        def download(self,message):raise AssertionError("Text only")
        def transcribe(self,media):raise AssertionError("No audio")
    fake=Fake()
    app=AnalyzeMessage(fake,fake,fake,fake,fake)
    conv=UUID(store.create_conversation(BASE)["id"])
    store.add_message(BASE,conv,uuid4(),Kind.TEXT,"Um banco pediu um código por SMS",None)
    job=store.claim()
    assert job is not None
    process_web_job(job,store,app)
    history=store.messages(BASE,conv,None)
    replies=[m for m in history if m["role"]=="assistant"]
    assert len(replies)==1
    assert replies[0]["risk"]=="ALTO"
    assert "código" in replies[0]["text"].lower()



def test_web_audio_upload_enforces_same_500kb_limit(settings, store, monkeypatch):
    from sentinela.interfaces import web_auth
    from sentinela.interfaces.http import create_app

    monkeypatch.setattr(web_auth,"get_settings",lambda:settings)
    class Inbox:
        def enqueue(self,message):return True
        def ready(self):return None

    with TestClient(create_app(settings,Inbox())) as client:
        response=client.post("/internal/web/conversations",headers=signed(method="POST"))
        assert response.status_code==201,response.text
        ident=response.json()["id"]
        path=f"/internal/web/conversations/{ident}/attachments"
        valid=b"OggS"+b"a"*(settings.guard_audio_max_bytes-4)
        result=client.post(path,content=valid,headers={
            **signed(method="POST",path=path,body=valid),
            "content-type":"audio/ogg",
        })
        assert result.status_code==201,result.text
        oversized=b"OggS"+b"a"*(settings.guard_audio_max_bytes-3)
        response=client.post(path,content=oversized,headers={
            **signed(method="POST",path=path,body=oversized),
            "content-type":"audio/ogg",
        })
        assert response.status_code==413,response.text
