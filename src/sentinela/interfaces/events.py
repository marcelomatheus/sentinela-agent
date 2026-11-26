"""Contratos de entrada: apenas eventos de conversas individuais."""
from typing import Any
import re
from pydantic import BaseModel, ConfigDict, Field
from sentinela.domain.model import Kind, Message

class Event(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event: str
    instance: str = Field(min_length=1, max_length=80)
    data: dict[str, Any]

def parse_message(event: Event) -> Message | None:
    if event.event.lower().replace("_", ".") != "messages.upsert":
        return None
    data = event.data
    key = data.get("key")
    if not isinstance(key, dict) or key.get("fromMe") is not False:
        return None
    jid = key.get("remoteJid")
    mid = key.get("id")
    if not isinstance(jid, str) or not isinstance(mid, str) or not 1 <= len(mid) <= 200:
        raise ValueError("invalid message key")
    if not jid.endswith(("@s.whatsapp.net", "@lid")):
        return None
    # Never alias a sender to a different number based on alternate metadata.
    # LID identities stay distinct until a verified mapping is available.
    identity = jid
    local, _, server = identity.partition("@")
    number = local.split(":")[0]
    if not re.fullmatch(r"[0-9]+(?::[0-9]+)?", local):
        raise ValueError("invalid sender format")
    if not number.isascii() or not number.isdigit() or len(number) > 25:
        raise ValueError("invalid sender")
    wid = number if server == "s.whatsapp.net" else f"{number}@lid"
    body = data.get("message")
    if not isinstance(body, dict):
        return None
    original = body
    for _ in range(3):
        wrapper = next((body.get(k) for k in ("ephemeralMessage", "viewOnceMessage",
            "viewOnceMessageV2", "viewOnceMessageV2Extension")
            if isinstance(body.get(k), dict)), None)
        if wrapper is None or not isinstance(wrapper.get("message"), dict):
            break
        body = wrapper["message"]
    if isinstance(body.get("conversation"), str):
        return Message(event.instance, mid, wid, Kind.TEXT, body["conversation"][:12000], remote_jid=jid)
    for name, kind in (("extendedTextMessage", Kind.TEXT), ("imageMessage", Kind.IMAGE), ("audioMessage", Kind.AUDIO)):
        part = body.get(name)
        if isinstance(part, dict):
            text = part.get("text" if kind == Kind.TEXT else "caption", "")
            mime = part.get("mimetype", "")
            return Message(event.instance, mid, wid, kind, text[:12000] if isinstance(text, str) else "",
                           mime[:100] if isinstance(mime, str) else "", jid,
                           {"key": {"id": mid, "remoteJid": jid, "fromMe": False},
                            "message": original} if kind != Kind.TEXT else None)
    return None
