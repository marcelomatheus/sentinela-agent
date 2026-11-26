"""Useful, safe failures and case-specific deterministic follow-up."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from sentinela.application.errors import ExtractionFormatError
from sentinela.config import Settings
from sentinela.domain.guardrails import FORMAT_UNAVAILABLE, TEMPORARY_UNAVAILABLE
from sentinela.domain.inference import infer, question_options, render
from sentinela.domain.model import Fact, Kind, Message, Risk, Session
from sentinela.infrastructure.ai import AgnoSpecialist
from sentinela.infrastructure.postgres import Job
from sentinela.interfaces.worker import process_job

KEY = "credential-for-testing-safety-123456789"


def settings() -> Settings:
    return Settings(
        postgres_password=KEY, webhook_api_key=KEY,
        evolution_api_url="https://example.invalid",
        evolution_api_key="test", evolution_instance="sentinela",
        openai_api_key="test",
    )


def test_unrecognized_case_requests_actual_message_without_claiming_safety() -> None:
    text = render(infer(frozenset()))
    assert "copiar a mensagem" in text
    assert "segura" not in text
    assert len(text) < 240


def test_money_leads_to_origin_question_instead_of_otp_by_default() -> None:
    assessment = infer(frozenset({Fact.MONEY}))
    assert question_options(assessment, frozenset())[0] == "origin"


def test_bank_prefers_authentication_question() -> None:
    assessment = infer(frozenset({Fact.BANK}))
    assert assessment.risk == Risk.INCONCLUSIVE
    assert question_options(assessment, frozenset())[0] == "code"


def test_urgency_leads_to_contextual_warning() -> None:
    response = render(infer(frozenset({Fact.URGENCY})))
    assert "pressa" in response
    assert len(response) < 240


def test_no_question_with_partial_facts_requests_details() -> None:
    response = render(infer(frozenset({Fact.BANK})))
    assert "mensagem completa" in response


def test_ai_schema_mismatch_is_not_a_user_input_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import sentinela.infrastructure.ai as ai

    class BrokenAgent:
        def __init__(self, **kwargs: object) -> None:
            pass

        def run(self, *args: object, **kwargs: object):
            return SimpleNamespace(content="not a structured answer")

    monkeypatch.setattr(ai, "Agent", BrokenAgent)
    monkeypatch.setattr(AgnoSpecialist, "_model", lambda _: object())
    specialist = object.__new__(AgnoSpecialist)
    specialist.settings = settings()
    session = Session(uuid4(), uuid4(), frozenset())
    with pytest.raises(ExtractionFormatError, match="schema"):
        specialist.extract("Mensagem pedindo pix", None, session)


class FakeStore:
    def __init__(self) -> None:
        self.saved: list[str] = []
        self.retried: list[str] = []
        self.session_data = Session(uuid4(), uuid4(), frozenset())

    def gate(self, job: Job) -> bool:
        return True

    def session(self, message: Message) -> Session:
        return self.session_data

    def reserve(self, job: Job) -> bool:
        return True

    def save_result(self, job: Job, session: Session, response: str) -> None:
        self.saved.append(response)

    def retry(self, job: Job, code: str) -> None:
        self.retried.append(code)


class Messenger:
    def presence(self, message: Message, active: bool) -> None:
        return None


class BadCase:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def execute(self, message: Message, session: Session):
        raise self.exc


def job(attempt: int = 1) -> Job:
    return Job(1, Message("sentinela", "msg", "5511999999999", Kind.TEXT,
                          "Conta bloqueada"), attempt, None)


def test_schema_failure_gets_specific_response_without_retries() -> None:
    store = FakeStore()
    process_job(job(), store, Messenger(), BadCase(ExtractionFormatError("invalid")))
    assert store.saved == [FORMAT_UNAVAILABLE]
    assert not store.retried


def test_last_retry_returns_truthful_service_error() -> None:
    store = FakeStore()
    process_job(job(3), store, Messenger(), BadCase(RuntimeError("upstream")))
    assert store.saved == [TEMPORARY_UNAVAILABLE]
    assert not store.retried


def test_earlier_transient_failure_retries() -> None:
    store = FakeStore()
    process_job(job(1), store, Messenger(), BadCase(RuntimeError("upstream")))
    assert store.saved == []
    assert store.retried == ["RuntimeError"]
