"""Unicode Evolution instance names must remain safe and correctly URL-encoded."""
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError

from sentinela.config import Settings
from sentinela.domain.model import Kind, Message
from sentinela.infrastructure.evolution import Evolution

KEY = "test-credential-strong-enough-123456"


def settings(name: str) -> Settings:
    return Settings(
        postgres_password=KEY,
        webhook_api_key=KEY,
        evolution_api_url="https://evolution.example.invalid",
        evolution_api_key="evolution-secret",
        evolution_instance=name,
        openai_api_key="test-openai-key",
    )


@pytest.mark.parametrize("name", ["sentinela", "meu-número", "ação_2026", "汉字-٣"])
def test_unicode_instance_names_accepted(name: str) -> None:
    assert settings(name).evolution_instance == name


@pytest.mark.parametrize(
    "name",
    ["", "../other", "a/b", "a b", "a.b", "um@outro", "a?b", "a#b", "a\\b", "a\nb", "🔥", "a" * 81],
)
def test_invalid_instance_names_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        settings(name)


def test_outgoing_evolution_route_quotes_unicode() -> None:
    name = "meu-número"
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    messenger = Evolution(settings(name), client)
    messenger.send(Message(name, "msg-1", "5500000000000", Kind.TEXT, "teste"), "ok")
    assert len(urls) == 1
    assert urls[0].endswith("/message/sendText/" + quote(name, safe=""))


def test_outgoing_instance_mismatch_is_rejected() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("No network call expected")

    messenger = Evolution(settings("meu-número"), httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ValueError, match="unexpected instance"):
        messenger.send(Message("outro", "msg-1", "5500000000000", Kind.TEXT), "no")
