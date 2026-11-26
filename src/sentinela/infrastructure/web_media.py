"""Web media adapter: file storage is not part of the inference engine."""
import hashlib
import os
from pathlib import Path
from uuid import UUID

from sentinela.application.ports import Messenger
from sentinela.domain.model import Media, Message
from sentinela.infrastructure.web_store import WebStore

class WebMessenger(Messenger):
    def __init__(self, store: WebStore, root: str) -> None:
        self.store = store
        self.root = Path(root).resolve()

    def presence(self, message: Message, active: bool) -> None:
        return None

    def send(self, message: Message, text: str) -> None:
        # Web delivery is a DB event, never a WhatsApp send.
        return None

    def download(self, message: Message) -> Media:
        envelope = message.media_envelope or {}
        attachment = UUID(str(envelope["attachment_id"]))
        with self.store.connect() as conn:
            row = conn.execute(
                """SELECT mime, byte_size, sha256 FROM app.web_attachments
                   WHERE id=%s AND conversation_id=%s""",
                (attachment, UUID(message.wid)),
            ).fetchone()
        if row is None:
            raise ValueError("attachment unavailable")
        path = (self.root / str(attachment)).resolve()
        if path.parent != self.root:
            raise ValueError("attachment path not allowed")
        data = path.read_bytes()
        if len(data) != row["byte_size"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("attachment checksum mismatch")
        return Media(data=data, mime=row["mime"])


def sniff_media(data: bytes, mime: str) -> str:
    """Reject mismatched magic bytes and unsupported formats."""
    signature = {
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
        "audio/ogg": data.startswith(b"OggS"),
        "audio/webm": data.startswith(b"\x1a\x45\xdf\xa3"),
        "audio/mpeg": data.startswith(b"ID3") or (len(data) > 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0),
        "audio/wav": data.startswith(b"RIFF") and data[8:12] == b"WAVE",
    }
    if not signature.get(mime, False):
        raise ValueError("unsupported file or MIME mismatch")
    return mime


def private_file_root(path: str) -> Path:
    root = Path(path).resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    return root
