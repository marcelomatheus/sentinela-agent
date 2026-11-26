"""Authenticated internal web API; only the BFF may call these routes."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from sentinela.config import Settings
from sentinela.domain.model import Kind
from sentinela.infrastructure.web_media import private_file_root, sniff_media
from sentinela.infrastructure.web_store import WebStore
from sentinela.infrastructure.web_events import WebEventBus
from sentinela.interfaces.web_auth import verify_principal


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    clientMessageId: UUID
    kind: Kind
    text: str = Field(default="", max_length=4000)
    attachmentId: UUID | None = None


def create_web_router(settings: Settings, web_store: WebStore, event_bus: WebEventBus) -> APIRouter:
    router = APIRouter(prefix="/internal/web", tags=["internal-web"])
    owner_dep = Depends(verify_principal)

    @router.post("/conversations", status_code=201)
    async def create_conversation(owner: str = owner_dep):
        try:
            return await run_in_threadpool(web_store.create_conversation, owner)
        except ValueError as exc:
            raise HTTPException(status_code=429,detail=str(exc)) from None

    @router.get("/conversations")
    async def list_conversations(owner: str = owner_dep):
        return {"conversations": await run_in_threadpool(web_store.list_conversations, owner)}

    @router.get("/conversations/{conversation_id}/messages")
    async def history(
        conversation_id: UUID, before: datetime | None = None,
        owner: str = owner_dep,
    ):
        try:
            messages = await run_in_threadpool(web_store.messages,owner,conversation_id,before)
            return {"messages":messages}
        except LookupError:
            raise HTTPException(status_code=404,detail="conversation not found") from None

    @router.post("/conversations/{conversation_id}/messages", status_code=202)
    async def create_message(
        conversation_id: UUID, item: MessageInput,
        owner: str = owner_dep,
    ):
        try:
            view, fresh = await run_in_threadpool(
                web_store.add_message,owner,conversation_id,item.clientMessageId,
                item.kind,item.text,item.attachmentId,
            )
            return {"message":view,"duplicate":not fresh}
        except LookupError:
            raise HTTPException(status_code=404,detail="conversation not found") from None
        except ValueError as exc:
            status = 429 if "pending" in str(exc) else 400
            raise HTTPException(status_code=status,detail=str(exc)) from None

    @router.post("/conversations/{conversation_id}/attachments", status_code=201)
    async def add_attachment(
        conversation_id: UUID, request: Request,
        owner: str = owner_dep,
    ):
        mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
        is_image = mime.startswith("image/")
        limit = settings.max_media_bytes if is_image else settings.guard_audio_max_bytes
        if not (is_image or mime.startswith("audio/")):
            raise HTTPException(status_code=415,detail="unsupported MIME")
        payload = bytearray()
        async for part in request.stream():
            payload.extend(part)
            if len(payload)>limit:
                raise HTTPException(status_code=413,detail="attachment too large")
        if not payload:
            raise HTTPException(status_code=400,detail="empty attachment")
        data = bytes(payload)
        try:
            sniff_media(data,mime)
        except ValueError:
            raise HTTPException(status_code=415,detail="file signature does not match MIME") from None
        ident=uuid4()
        root=private_file_root(settings.web_media_dir)
        target=root/str(ident)
        try:
            # x mode prevents clobbering an existing object.
            with target.open("xb") as sink:
                sink.write(data)
            target.chmod(0o600)
            await run_in_threadpool(
                web_store.upload_attachment,owner,conversation_id,ident,mime,
                len(data),hashlib.sha256(data).hexdigest(),
            )
        except LookupError:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=404,detail="conversation not found") from None
        except ValueError as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=429,detail=str(exc)) from None
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return {"id":str(ident),"mime":mime,"size":len(data)}

    @router.post("/conversations/{conversation_id}/reset",status_code=204)
    async def reset_conversation(conversation_id: UUID,owner: str = owner_dep):
        try:
            await run_in_threadpool(web_store.reset,owner,conversation_id)
        except LookupError:
            raise HTTPException(status_code=404,detail="conversation not found") from None
        return Response(status_code=204)

    @router.delete("/conversations/{conversation_id}",status_code=204)
    async def delete_conversation(conversation_id: UUID,owner: str = owner_dep):
        try:
            files = await run_in_threadpool(web_store.delete,owner,conversation_id)
        except LookupError:
            raise HTTPException(status_code=404,detail="conversation not found") from None
        root=Path(settings.web_media_dir).resolve()
        for file_id in files:
            (root/str(file_id)).unlink(missing_ok=True)
        return Response(status_code=204)

    @router.get("/conversations/{conversation_id}/events")
    async def sse(
        conversation_id: UUID, request: Request,
        after: int = 0, owner: str = owner_dep,
    ):
        if after < 0:
            raise HTTPException(status_code=422,detail="invalid cursor")
        try:
            await run_in_threadpool(web_store.events,owner,conversation_id,after)
        except LookupError:
            raise HTTPException(status_code=404,detail="conversation not found") from None

        wake = event_bus.subscribe(conversation_id)

        async def stream():
            cursor = after
            try:
                while not await request.is_disconnected():
                    # Subscribe first, then clear before the durable query.
                    # A concurrent NOTIFY can never be lost between the read
                    # and our next wait.
                    wake.clear()
                    try:
                        entries = await run_in_threadpool(
                            web_store.events, owner, conversation_id, cursor
                        )
                    except LookupError:
                        break
                    for entry in entries:
                        cursor = entry["id"]
                        serialized = json.dumps(entry["payload"], ensure_ascii=False)
                        yield f"id: {cursor}\nevent: {entry['kind']}\ndata: {serialized}\n\n"
                    if len(entries) >= 50:
                        continue
                    try:
                        await asyncio.wait_for(wake.wait(), timeout=15.0)
                    except asyncio.TimeoutError:
                        # Slow fallback if the PostgreSQL listener is offline.
                        yield ": heartbeat\n\n"
            finally:
                event_bus.unsubscribe(conversation_id, wake)

        return StreamingResponse(stream(),media_type="text/event-stream",headers={
            "Cache-Control":"no-store,no-transform","X-Accel-Buffering":"no",
        })

    return router
