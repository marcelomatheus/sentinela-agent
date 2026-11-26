from typing import Protocol

from sentinela.domain.inference import Assessment
from sentinela.domain.model import Fact, Media, Message, Observation, Session


class Extractor(Protocol):
    def extract(self, text: str, image: Media | None, session: Session) -> Observation: ...


class QuestionAgent(Protocol):
    def choose(self, assessment: Assessment, options: tuple[str, ...], session: Session) -> str | None: ...


class Reputation(Protocol):
    def inspect(self, text: str) -> frozenset[Fact]: ...


class Messenger(Protocol):
    def presence(self, message: Message, active: bool) -> None: ...
    def download(self, message: Message) -> Media: ...
    def send(self, message: Message, text: str) -> None: ...


class Transcriber(Protocol):
    def transcribe(self, media: Media) -> str: ...
