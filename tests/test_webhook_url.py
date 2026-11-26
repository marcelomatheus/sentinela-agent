"""Webhook URL trust boundary: plain HTTP must never reach an external host."""
from unittest.mock import patch

import pytest

from sentinela.infrastructure.webhook_setup import validate_webhook_target


@pytest.mark.parametrize(
    "target",
    [
        "http://sentinela-api:8080/webhooks/evolution",
        "https://sentinela.example.com/webhooks/evolution",
        "https://hooks.example.net:8443/webhooks/evolution",
    ],
)
def test_webhook_allowed(target: str) -> None:
    assert validate_webhook_target(target) == target


@pytest.mark.parametrize(
    "target",
    [
        "",
        "http://example.com/webhooks/evolution",
        "http://127.0.0.1:8080/webhooks/evolution",
        "http://10.0.0.20:8080/webhooks/evolution",
        "http://sentinela-api:9090/webhooks/evolution",
        "http://sentinela-api:8080/webhooks/evolution?token=secret",
        "http://user:password@sentinela-api:8080/webhooks/evolution",
        "http://sentinela-api:8080/admin",
        "http://sentinela-api:8080/webhooks/evolution#fragment",
        "ftp://sentinela-api:8080/webhooks/evolution",
        "https://user:password@example.com/webhooks/evolution",
        "http://sentinela-api:bad/webhooks/evolution",
        "http://sentinela-api:8080/webhooks/evolution\n",
    ],
)
def test_webhook_rejected(target: str) -> None:
    with pytest.raises(ValueError):
        validate_webhook_target(target)


def test_configuration_does_not_contact_external_host_before_apply() -> None:
    # The CLI is opt-in; importing it never configures a remote instance.
    with patch("httpx.Client.post") as request:
        validate_webhook_target("http://sentinela-api:8080/webhooks/evolution")
        request.assert_not_called()


def test_webhook_configuration_requires_explicit_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    from sentinela.infrastructure.webhook_setup import main
    monkeypatch.setattr(sys, "argv", ["configure_webhook"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_webhook_configuration_sends_authenticated_internal_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from sentinela.infrastructure import webhook_setup

    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

    class Client:
        def __init__(self, **kwargs: object) -> None:
            captured["client_options"] = kwargs

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **kwargs: object) -> Response:
            captured["url"] = url
            captured["options"] = kwargs
            return Response()

    monkeypatch.setattr(sys, "argv", ["configure_webhook", "--apply"])
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution-api:8080")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "sentinela")
    monkeypatch.setenv("WEBHOOK_URL", "http://sentinela-api:8080/webhooks/evolution")
    monkeypatch.setenv("WEBHOOK_API_KEY", "webhook-credential-1234567890")
    monkeypatch.setenv("EVOLUTION_API_KEY", "evolution-credential")
    monkeypatch.setattr(webhook_setup.httpx, "Client", Client)
    webhook_setup.main()
    assert captured["url"] == "http://evolution-api:8080/webhook/set/sentinela"
    options = captured["options"]
    assert isinstance(options, dict)
    assert options["headers"] == {"apikey": "evolution-credential"}
    payload = options["json"]
    assert isinstance(payload, dict)
    webhook = payload["webhook"]
    assert webhook["url"] == "http://sentinela-api:8080/webhooks/evolution"
    assert webhook["headers"] == {"apikey": "webhook-credential-1234567890"}
    assert webhook["events"] == ["MESSAGES_UPSERT", "PRESENCE_UPDATE"]
    assert webhook["enabled"] is True
