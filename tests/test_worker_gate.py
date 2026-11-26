"""The worker must not consume quota, type or call OpenAI for gate-only messages."""
from uuid import uuid4
from sentinela.domain.model import Kind, Message, Session
from sentinela.infrastructure.postgres import Job
from sentinela.interfaces.worker import process_job

class FakeStore:
    def __init__(self, gate_result: bool | Exception) -> None:
        self.gate_result = gate_result
        self.calls: list[str] = []
        self.session_data = Session(uuid4(), uuid4(), frozenset())

    def gate(self, job: Job) -> bool:
        self.calls.append("gate")
        if isinstance(self.gate_result, Exception):
            raise self.gate_result
        return self.gate_result

    def session(self, message: Message) -> Session:
        self.calls.append("session")
        return self.session_data

    def reserve(self, job: Job) -> bool:
        self.calls.append("reserve")
        return True

    def save_result(self, job: Job, session: Session, response: str) -> None:
        self.calls.append("save")

    def finish(self, job: Job, status: str, error: str | None = None) -> None:
        self.calls.append(f"finish:{status}")

    def retry(self, job: Job, error: str) -> None:
        self.calls.append("retry")


class FakeMessenger:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def presence(self, message: Message, active: bool) -> None:
        self.calls.append(f"presence:{active}")

    def send(self, message: Message, text: str) -> None:
        self.calls.append(f"send:{text}")

    def download(self, message: Message) -> None:
        raise AssertionError("No media expected")


class FakeCase:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, message: Message, session: Session):
        from sentinela.application.analyze import AnalysisResult
        self.calls += 1
        return AnalysisResult(session, "resultado")


def job(response: str | None = None) -> Job:
    message = Message("sentinela", "id", "5500000000000", Kind.TEXT, "Sentinela")
    return Job(1, message, 1, response)


def test_inactive_or_command_bypasses_all_external_calls() -> None:
    store, messenger, case = FakeStore(False), FakeMessenger(), FakeCase()
    process_job(job(), store, messenger, case)  # type: ignore[arg-type]
    assert store.calls == ["gate"]
    assert messenger.calls == []
    assert case.calls == 0


def test_active_message_runs_normal_pipeline() -> None:
    store, messenger, case = FakeStore(True), FakeMessenger(), FakeCase()
    process_job(job(), store, messenger, case)  # type: ignore[arg-type]
    assert store.calls == ["gate", "session", "reserve", "save"]
    assert messenger.calls == ["presence:True", "presence:False"]
    assert case.calls == 1


def test_existing_ready_response_skips_gate_and_quota() -> None:
    store, messenger, case = FakeStore(False), FakeMessenger(), FakeCase()
    process_job(job("Sentinela ativo."), store, messenger, case)  # type: ignore[arg-type]
    assert store.calls == ["finish:done"]
    assert messenger.calls == ["send:Sentinela ativo."]
    assert case.calls == 0


def test_gate_failure_uses_retry_without_message_or_model() -> None:
    store, messenger, case = FakeStore(RuntimeError("db failure")), FakeMessenger(), FakeCase()
    process_job(job(), store, messenger, case)  # type: ignore[arg-type]
    assert store.calls == ["gate", "retry"]
    assert not messenger.calls and case.calls == 0


def test_failed_delivery_is_uncertain_not_retried() -> None:
    store, messenger, case = FakeStore(False), FakeMessenger(), FakeCase()

    def failed_send(message: Message, text: str) -> None:
        raise TimeoutError("delivery unknown")

    messenger.send = failed_send  # type: ignore[method-assign]
    process_job(job("Sessão encerrada."), store, messenger, case)  # type: ignore[arg-type]
    assert store.calls == ["finish:uncertain"]
    assert case.calls == 0
