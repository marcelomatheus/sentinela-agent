"""Configure webhook for an existing Evolution API instance.

The operation replaces the instance's existing webhook configuration.
Plain HTTP is allowed only for the fixed Docker-network alias.
"""
import argparse
import os
from urllib.parse import quote, urlsplit

import httpx
from dotenv import load_dotenv
from sentinela.config import validate_evolution_instance_name

PRIVATE_WEBHOOK_HOST = "sentinela-api"
PRIVATE_WEBHOOK_PORT = 8080
WEBHOOK_PATH = "/webhooks/evolution"


def validate_webhook_target(target: str) -> str:
    """Prevent configuring plaintext webhook delivery to public or unexpected hosts."""
    if not target or target != target.strip() or any(c.isspace() for c in target):
        raise ValueError("Webhook URL must be nonempty and must not contain whitespace")

    try:
        parts = urlsplit(target)
        hostname = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise ValueError("Invalid webhook URL") from exc

    if (
        not hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path != WEBHOOK_PATH
    ):
        raise ValueError("Webhook URL must use the expected path without credentials, query or fragment")

    if parts.scheme == "https":
        return target

    if parts.scheme == "http" and hostname == PRIVATE_WEBHOOK_HOST and port == PRIVATE_WEBHOOK_PORT:
        return target

    raise ValueError(
        "Plain HTTP is allowed only for http://sentinela-api:8080/webhooks/evolution "
        "on the shared private Docker network; use HTTPS otherwise"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="confirm replacement of the existing instance webhook")
    parser.add_argument("--route", choices=["webhook/set", "event/webhook/set"], default="webhook/set")
    args = parser.parse_args()

    if not args.apply:
        parser.error("Use --apply to confirm replacement of the existing instance webhook")

    load_dotenv()
    base = os.environ["EVOLUTION_API_URL"].rstrip("/")
    try:
        instance = quote(validate_evolution_instance_name(os.environ["EVOLUTION_INSTANCE"]), safe="")
    except ValueError as exc:
        parser.error(str(exc))
    target_raw = os.getenv("WEBHOOK_URL") or os.getenv("PUBLIC_WEBHOOK_URL", "")
    try:
        target = validate_webhook_target(target_raw)
    except ValueError as exc:
        parser.error(str(exc))

    secret = os.environ["WEBHOOK_API_KEY"]
    if len(secret) < 24:
        parser.error("WEBHOOK_API_KEY must contain at least 24 characters")

    payload = {
        "webhook": {
            "enabled": True,
            "url": target,
            "byEvents": False,
            "base64": False,
            "headers": {"apikey": secret},
            "events": ["MESSAGES_UPSERT", "PRESENCE_UPDATE"],
        }
    }

    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.post(
                f"{base}/{args.route}/{instance}",
                json=payload,
                headers={"apikey": os.environ["EVOLUTION_API_KEY"]},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SystemExit(
            f"Webhook configuration failed: {type(exc).__name__}. "
            "Verify the Evolution API version, route and credentials."
        ) from None

    print("Webhook accepted. Verify message delivery from the Evolution container.")


if __name__ == "__main__":
    main()
