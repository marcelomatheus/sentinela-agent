"""Inbound Evolution API v2 individual-message parser.

Messages sent from the linked account are opt-in for a *single* own chat.
Self text must start with /treino, preventing the bot from ingesting its echo.
"""
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sentinela.domain.model import Kind, Message

class Event(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event: str
    instance: str = Field(min_length=1, max_length=80)
    data: dict[str, Any]


def _untrusted_body(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    body = data.get("message")
    if not isinstance(body, dict):
        return None
    original = body
    for _ in range(3):
        wrapper = next(
            (body.get(name) for name in (
                "ephemeralMessage", "viewOnceMessage", "viewOnceMessageV2",
                "viewOnceMessageV2Extension",
            ) if isinstance(body.get(name), dict)),
            None,
        )
        if wrapper is None or not isinstance(wrapper.get("message"), dict):
            break
        body = wrapper["message"]
    return original, body


def _self_test_text(value: str) -> str | None:
    """Require a standalone prefix plus text; never ingest bot replies."""
    result = re.fullmatch(r"/treino\s+(.+)", value.strip(), flags=re.IGNORECASE | re.DOTALL)
    if result is None:
        return None
    text = result.group(1).strip()
    return text or None


def parse_message(event: Event, *, self_test_jid: str | None = None) -> Message | None:
    if event.event.lower().replace("_", ".") != "messages.upsert":
        return None
    data = event.data
    key = data.get("key")
    if not isinstance(key, dict) or type(key.get("fromMe")) is not bool:
        return None
    from_me = key["fromMe"]
    jid = key.get("remoteJid")
    mid = key.get("id")
    if not isinstance(jid, str) or not isinstance(mid, str) or not 1 <= len(mid) <= 200:
        raise ValueError("invalid message key")
    if not jid.endswith(("@s.whatsapp.net", "@lid")):
        return None
    if from_me and (self_test_jid is None or jid != self_test_jid):
        # Sent messages to other contacts and ordinary bot echoes are ignored.
        return None

    local, _, server = jid.partition("@")
    number = local.split(":")[0]
    if re.fullmatch(r"[0-9]+(?::[0-9]+)?", local) is None:
        raise ValueError("invalid sender format")
    if not number.isascii() or not number.isdigit() or len(number) > 25:
        raise ValueError("invalid sender")
    wid = number if server == "s.whatsapp.net" else f"{number}@lid"

    parsed = _untrusted_body(data)
    if parsed is None:
        return None
    original, body = parsed

    kind: Kind
    text: str
    mime: str = ""
    if isinstance(body.get("conversation"), str):
        kind, text = Kind.TEXT, body["conversation"]
    else:
        part = next(
            ((name, body[name]) for name in (
                "extendedTextMessage", "imageMessage", "audioMessage",
            ) if isinstance(body.get(name), dict)),
            None,
        )
        if part is None:
            return None
        name, value = part
        kind = {
            "extendedTextMessage": Kind.TEXT,
            "imageMessage": Kind.IMAGE,
            "audioMessage": Kind.AUDIO,
        }[name]
        incoming = value.get("text" if kind == Kind.TEXT else "caption", "")
        text = incoming if isinstance(incoming, str) else ""
        incoming_mime = value.get("mimetype", "")
        mime = incoming_mime[:100] if isinstance(incoming_mime, str) else ""

    if from_me and kind == Kind.TEXT:
        # Only *explicit* self-authored training text is processed.
        # Outbound bot replies never include the /treino prefix.
        stripped = _self_test_text(text)
        if stripped is None:
            return None
        text = stripped

    envelope = (
        {"key": {"id": mid, "remoteJid": jid, "fromMe": from_me}, "message": original}
        if kind != Kind.TEXT else None
    )
    return Message(event.instance, mid, wid, kind, text[:12000], mime, jid, envelope)
