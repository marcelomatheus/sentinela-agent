"""Owner-only self-chat tests; outbound text never loops back to the bot."""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from sentinela.config import Settings
from sentinela.domain.model import Kind, Message
from sentinela.interfaces.events import Event, parse_message
from sentinela.interfaces.http import create_app

JID = "5511999999999@s.whatsapp.net"
LID = "123456789123@lid"
KEY = "safe-credential-for-test-123456789"


def settings(jid: str | None = None) -> Settings:
    return Settings(
        postgres_password=KEY, webhook_api_key=KEY,
        evolution_api_url="https://example.invalid",
        evolution_api_key="test", evolution_instance="sentinela",
        openai_api_key="test", self_test_jid=jid,
    )


def payload(content: dict, *, jid: str = JID, from_me: bool = True) -> dict:
    return {
        "event": "messages.upsert", "instance": "sentinela",
        "data": {
            "key": {"id": "test-message", "remoteJid": jid, "fromMe": from_me},
            "message": content,
        },
    }


def parse(content: dict, *, jid: str = JID, allow: str | None = JID,
          from_me: bool = True) -> Message | None:
    return parse_message(Event.model_validate(payload(content, jid=jid, from_me=from_me)),
                         self_test_jid=allow)


@pytest.mark.parametrize("value", [
    "  /treino Sentinela  ",
    "/TREINO Encerrar",
    "/Treino /nova",
    "/treino Minha conta foi bloqueada",
])
def test_owner_text_with_explicit_prefix(value: str) -> None:
    message = parse({"conversation": value})
    assert message is not None
    assert message.kind == Kind.TEXT
    assert message.text == value.strip()[8:].strip()
    assert message.wid == "5511999999999"
    assert message.remote_jid == JID


@pytest.mark.parametrize("value", [
    "Sentinela", "Encerrar", "⚠️ Atenção, encontrei sinais...",
    "Oi! 👋 Eu sou o Sentinela.", "/treino", "/treinamento Sentinela",
])
def test_bot_own_echo_or_unmarked_text_ignored(value: str) -> None:
    assert parse({"conversation": value}) is None


def test_self_chat_disabled_by_default() -> None:
    assert parse({"conversation": "/treino Sentinela"}, allow=None) is None


def test_self_message_to_different_chat_is_ignored() -> None:
    assert parse({"conversation": "/treino Sentinela"},
                 jid="559988887777@s.whatsapp.net") is None


def test_incoming_normal_contact_unchanged() -> None:
    message = parse({"conversation": "Sentinela"}, jid="559988887777@s.whatsapp.net",
                    allow=JID, from_me=False)
    assert message is not None
    assert message.text == "Sentinela"


def test_self_image_and_audio_without_caption_are_supported() -> None:
    for name, kind in (("imageMessage", Kind.IMAGE), ("audioMessage", Kind.AUDIO)):
        message = parse({name: {"mimetype": "image/jpeg" if kind == Kind.IMAGE else "audio/ogg",
                                "mediaKey": "synthetic"}})
        assert message is not None
        assert message.kind == kind
        assert message.media_envelope is not None
        assert message.media_envelope["key"]["fromMe"] is True
        assert message.media_envelope["message"][name]["mediaKey"] == "synthetic"


def test_self_chat_lid_is_distinct() -> None:
    message = parse({"conversation": "/treino Sentinela"}, jid=LID, allow=LID)
    assert message is not None and message.wid == "123456789123@lid"
    assert parse({"conversation": "/treino Sentinela"}, jid=LID, allow=JID) is None


@pytest.mark.parametrize("jid", [
    "5511999999999", "5511999999999@c.us",
    "../someone@s.whatsapp.net", "5511999999999@lid/extra", "nome@s.whatsapp.net",
])
def test_configuration_rejects_invalid_jid(jid: str) -> None:
    with pytest.raises(ValidationError):
        settings(jid)


class Inbox:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    def enqueue(self, message: Message) -> bool:
        self.messages.append(message)
        return True

    def ready(self) -> None:
        return None


def test_webhook_filters_self_echo_before_enqueuing() -> None:
    inbox = Inbox()
    app = create_app(settings(JID), inbox)
    with TestClient(app) as client:
        for text, expected in [
            ("⚠️ Atenção: encontrei sinais...", "ignored"),
            ("/treino Sentinela", "accepted"),
            ("Tudo certo! 😊 Encerrei nossa conversa.", "ignored"),
            ("/treino Banco pediu um código", "accepted"),
        ]:
            response = client.post("/webhooks/evolution",
                                   json=payload({"conversation": text}),
                                   headers={"apikey": KEY})
            assert response.status_code == 202
            assert response.json()["status"] == expected
    assert [m.text for m in inbox.messages] == [
        "Sentinela", "Banco pediu um código",
    ]


def test_webhook_does_not_enable_mode_for_every_sender() -> None:
    inbox = Inbox()
    app = create_app(settings(JID), inbox)
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/evolution",
            json=payload({"conversation": "/treino Sentinela"},
                         jid="559988887777@s.whatsapp.net"),
            headers={"apikey": KEY},
        )
    assert response.json() == {"status": "ignored"}
    assert not inbox.messages
