import base64
import httpx
from sentinela.interfaces.events import Event, parse_message
from sentinela.domain.model import Kind, Message
from sentinela.infrastructure.evolution import Evolution
from sentinela.config import Settings

KEY = "test-webhook-secret-for-media-tests-123"

def settings() -> Settings:
    return Settings(postgres_password=KEY, webhook_api_key=KEY,
        evolution_api_url="https://evolution.example.invalid",
        evolution_api_key="secret", evolution_instance="sentinela",
        openai_api_key="fake")

def event(body: dict) -> Event:
    return Event(event="messages.upsert", instance="sentinela",
        data={"key": {"id": "msg-1", "remoteJid": "5500000000000@s.whatsapp.net", "fromMe": False},
              "message": body})

def test_ephemeral_image_retains_encrypted_media_metadata() -> None:
    body = {"ephemeralMessage": {"message": {"imageMessage":
        {"mimetype": "image/jpeg", "mediaKey": "fake-key", "directPath": "/encrypted-path"}}}}
    message = parse_message(event(body))
    assert message is not None and message.kind == Kind.IMAGE
    assert message.media_envelope is not None
    assert message.media_envelope["message"] == body

def test_media_request_includes_whatsapp_envelope() -> None:
    body = {"audioMessage": {"mimetype": "audio/ogg", "mediaKey": "fake-key"}}
    message = parse_message(event(body))
    assert message is not None
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/chat/getBase64FromMediaMessage/sentinela")
        assert b"mediaKey" in request.content
        return httpx.Response(200, json={"base64": base64.b64encode(b"OggS-fake-data").decode()})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    media = Evolution(settings(), client).download(message)
    assert media.mime == "audio/ogg"
    assert media.data == b"OggS-fake-data"

def test_missing_envelope_rejected_before_call() -> None:
    message = Message("sentinela", "m1", "5500000000000", Kind.IMAGE)
    try:
        Evolution(settings()).download(message)
    except ValueError as error:
        assert "envelope" in str(error)
    else:
        raise AssertionError("expected ValueError")

def test_lid_and_number_do_not_share_user_identity() -> None:
    data = event({"conversation": "bom dia"}).model_dump()
    lid = dict(data)
    lid["data"] = {**data["data"], "key": {**data["data"]["key"],
        "remoteJid": "123456789@lid", "remoteJidAlt": "5500000000000@s.whatsapp.net"}}
    a, b = parse_message(Event.model_validate(data)), parse_message(Event.model_validate(lid))
    assert a is not None and b is not None and a.wid != b.wid
