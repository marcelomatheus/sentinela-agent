import httpx

from sentinela.infrastructure.reputation import UrlReputation
from sentinela.domain.model import Fact


def test_reputation_keeps_path_but_not_sensitive_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "safebrowsing.googleapis.com"
        assert b"/alert-path" in request.content
        assert b"private-token" not in request.content
        return httpx.Response(200, json={"matches": [{"threatType": "SOCIAL_ENGINEERING"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    facts = UrlReputation("test-key", client).inspect(
        "Recebi https://example.com/alert-path?token=private-token"
    )
    assert Fact.MALICIOUS_URL in facts
