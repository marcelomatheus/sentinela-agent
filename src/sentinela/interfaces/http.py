"""Authenticated webhook with bounded request bodies."""
import hmac
from contextlib import asynccontextmanager
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
    from sentinela.infrastructure.web_store import WebStore
    from sentinela.infrastructure.web_events import WebEventBus
    web_store=WebStore(config)
    event_bus=WebEventBus(config)
    web_enabled=len(config.web_internal_key.get_secret_value()) >= 32

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if web_enabled:
            await run_in_threadpool(web_store.migrate)
            event_bus.start()
        try:
            yield
        finally:
            await event_bus.close()
            web_store.pool.close()

    app=FastAPI(title="Sentinela",docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)

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
    # Web routes are gated by a signed, private BFF identity. When no key is
    # configured, the WhatsApp-only installation continues unchanged.
    from sentinela.interfaces.web_api import create_web_router
    app.state.web_store=web_store
    app.include_router(create_web_router(config,web_store,event_bus))
    return app
