"""Webhook URL trust boundary: plain HTTP must never reach an external host."""
from unittest.mock import patch

import pytest

from scripts.configure_webhook import validate_webhook_target


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
