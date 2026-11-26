from fastapi.testclient import TestClient
from sentinela.config import Settings
from sentinela.domain.model import Message, Kind
from sentinela.interfaces.http import create_app

KEY = "test-webhook-key-1234567890123"

class FakeInbox:
    def __init__(self) -> None:
        self.messages: list[Message] = []
    def ready(self) -> None:
        pass
    def enqueue(self, message: Message) -> bool:
        if any(m.message_id == message.message_id for m in self.messages):
            return False
        self.messages.append(message)
        return True

def setup():
    settings = Settings(postgres_password=KEY, webhook_api_key=KEY,
                        evolution_api_url="https://example.invalid", evolution_api_key="fake",
                        evolution_instance="sentinela", openai_api_key="fake")
    inbox = FakeInbox()
    return TestClient(create_app(settings,inbox)), inbox

def event(message):
    return {"event":"messages.upsert","instance":"sentinela","data":{
        "key":{"id":"fake-id","remoteJid":"5500000000000@s.whatsapp.net","fromMe":False},
        "message":message}}

def test_auth():
    client, _ = setup()
    assert client.post("/webhooks/evolution",json={}).status_code == 401

def test_duplicate():
    client, inbox = setup()
    for expected in ("accepted","duplicate"):
        r=client.post("/webhooks/evolution",json=event({"conversation":"teste"}),headers={"apikey":KEY})
        assert r.status_code == 202
        assert r.json()["status"] == expected
    assert len(inbox.messages)==1

def test_image():
    client,inbox=setup()
    assert client.post("/webhooks/evolution/messages-upsert",json=event({"imageMessage":{"mimetype":"image/jpeg"}}),headers={"apikey":KEY}).status_code==202
    assert inbox.messages[0].kind==Kind.IMAGE

def test_audio():
    client,inbox=setup()
    assert client.post("/webhooks/evolution",json=event({"audioMessage":{"mimetype":"audio/ogg"}}),headers={"apikey":KEY}).status_code==202
    assert inbox.messages[0].kind==Kind.AUDIO

def test_invalid():
    client,_=setup()
    assert client.post("/webhooks/evolution",json={},headers={"apikey":KEY}).status_code==422
