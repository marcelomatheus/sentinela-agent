"""Evolution transport. No requests to user-supplied media URLs."""
import base64
import binascii
from io import BytesIO
from urllib.parse import quote
import httpx
from PIL import Image
from sentinela.config import Settings
from sentinela.domain.model import Kind, Media, Message

class Evolution:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.Client(timeout=30, follow_redirects=False)

    def _post(self, route: str, message: Message, body: dict[str, object]) -> httpx.Response:
        if message.instance != self.settings.evolution_instance:
            raise ValueError("unexpected instance")
        url = f"{str(self.settings.evolution_api_url).rstrip('/')}/{route}/{quote(message.instance,safe='')}"
        response = self.client.post(url,json=body,headers={"apikey":self.settings.evolution_api_key.get_secret_value()})
        response.raise_for_status()
        return response

    def presence(self, message: Message, active: bool) -> None:
        self._post("chat/sendPresence",message,{"number":message.remote_jid or message.wid,
                    "presence":"composing" if active else "paused","delay":1000})

    def send(self, message: Message, text: str) -> None:
        self._post("message/sendText",message,{"number":message.remote_jid or message.wid,"text":text})

    def download(self, message: Message) -> Media:
        if message.media_envelope is None:
            raise ValueError("missing media envelope")
        response = self._post("chat/getBase64FromMediaMessage", message,
            {"message": message.media_envelope, "convertToMp4": False})
        if len(response.content)>self.settings.max_media_bytes*2:
            raise ValueError("media too large")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("invalid media response")
        encoded = payload.get("base64")
        if encoded is None and isinstance(payload.get("data"), dict):
            encoded = payload["data"].get("base64")
        if not isinstance(encoded,str):
            raise ValueError("missing media")
        if encoded.startswith("data:"):
            encoded = encoded.split(",",1)[-1]
        try:
            raw = base64.b64decode(encoded,validate=True)
        except (ValueError,binascii.Error) as exc:
            raise ValueError("invalid media") from exc
        if not raw or len(raw)>self.settings.max_media_bytes:
            raise ValueError("media too large or empty")
        if message.kind == Kind.IMAGE:
            with Image.open(BytesIO(raw)) as image:
                if image.width*image.height>20_000_000:
                    raise ValueError("image too large")
                if image.format not in {"JPEG","PNG","WEBP"}:
                    raise ValueError("unsupported image")
                image.thumbnail((1600,1600))
                output=BytesIO()
                image.convert("RGB").save(output,format="JPEG",quality=85)
                return Media(output.getvalue(),"image/jpeg")
        mime=message.media_mime.split(";")[0].lower()
        if mime not in {"audio/ogg","audio/opus","audio/mpeg","audio/mp4","audio/wav","audio/webm","audio/x-wav"}:
            raise ValueError("unsupported audio")
        return Media(raw,mime)
