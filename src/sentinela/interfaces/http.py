"""Authenticated webhook with bounded request bodies."""
import hmac
from typing import Protocol
from fastapi import FastAPI, Request, HTTPException
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from sentinela.config import Settings,get_settings
from sentinela.domain.model import Message
from sentinela.interfaces.events import Event,parse_message

class Inbox(Protocol):
    def enqueue(self,message:Message)->bool: ...
    def ready(self)->None: ...

def create_app(settings:Settings|None=None, store:Inbox|None=None)->FastAPI:
    settings=settings or get_settings()
    if store is None:
        from sentinela.infrastructure.postgres import Store
        store=Store(settings)
    config=settings
    inbox=store
    app=FastAPI(title="Sentinela",docs_url=None,redoc_url=None,openapi_url=None)

    @app.get("/health/live")
    def live()->dict[str,str]:
        return {"status":"ok"}

    @app.get("/health/ready")
    def ready()->dict[str,str]:
        try:
            inbox.ready()
        except Exception:
            raise HTTPException(503,"database unavailable") from None
        return {"status":"ready"}

    @app.post("/webhooks/evolution",status_code=202)
    @app.post("/webhooks/evolution/messages-upsert",status_code=202)
    @app.post("/webhooks/evolution/presence-update",status_code=202)
    async def receive(request:Request)->dict[str,str]:
        supplied=request.headers.get("apikey","")
        if not hmac.compare_digest(supplied.encode(),config.webhook_api_key.get_secret_value().encode()):
            raise HTTPException(401,"invalid credentials")
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>config.max_body_bytes:
                raise HTTPException(413,"payload too large")
        try:
            event=Event.model_validate_json(body)
            if event.instance!=config.evolution_instance:
                raise HTTPException(403,"unexpected instance")
            message=parse_message(event,self_test_jid=config.self_test_jid)
        except (ValidationError,ValueError):
            raise HTTPException(422,"invalid event") from None
        if message is None:
            return {"status":"ignored"}
        try:
            inserted=await run_in_threadpool(inbox.enqueue,message)
        except Exception:
            raise HTTPException(503,"inbox unavailable") from None
        return {"status":"accepted" if inserted else "duplicate"}
    return app
