import httpx
from sentinela.domain.model import Fact
from sentinela.infrastructure.reputation import UrlReputation

def test_no_direct_navigation():
    def handler(request):
        assert request.url.host == "safebrowsing.googleapis.com"
        assert b"secret" not in request.content
        return httpx.Response(200,json={"matches":[{}]})
    client=httpx.Client(transport=httpx.MockTransport(handler))
    facts=UrlReputation("fake",client).inspect("https://example.com/?token=secret")
    assert Fact.MALICIOUS_URL in facts

def test_no_url():
    assert not UrlReputation().inspect("sem links")
