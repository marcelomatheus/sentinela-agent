import os
from pathlib import Path
from dataclasses import replace
from uuid import uuid4
import pytest

@pytest.mark.skipif(os.environ.get("RUN_POSTGRES_TESTS") != "1", reason="requires disposable postgres")
def test_quota_and_ownership():
    from sentinela.config import get_settings
    from sentinela.infrastructure.postgres import Store, Job
    from sentinela.domain.model import Message, Kind
    settings = get_settings().model_copy(update={"guard_user_daily": 1, "guard_global_daily": 200})
    store = Store(settings)
    with store.connect() as conn:
        conn.execute(Path("db/001_initial.sql").read_text())
    store.migrate_guardrails()
    first = Message("sentinela", str(uuid4()), str(uuid4().int)[:24], Kind.TEXT, "teste")
    second = replace(first, message_id=str(uuid4()), wid=str(uuid4().int)[:24])
    a, b = store.session(first), store.session(second)
    assert a.user_id != b.user_id
    assert a.session_id != b.session_id
    job = Job(-1, first, 1, None)
    assert store.reserve(job)
    assert not store.reserve(job)
    assert store.reserve(Job(-2, second, 1, None))
    with pytest.raises(ValueError, match="ownership"):
        store.save_result(job, b, "wrong owner")
