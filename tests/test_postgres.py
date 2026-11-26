import os
from pathlib import Path
import pytest

@pytest.mark.skipif(os.environ.get("RUN_POSTGRES_TESTS") != "1",reason="requires disposable postgres")
def test_persistence():
    from sentinela.config import get_settings
    from sentinela.infrastructure.postgres import Store
    from sentinela.domain.model import Kind, Message
    from uuid import uuid4
    store=Store(get_settings())
    with store.connect() as conn:
        conn.execute(Path("db/001_initial.sql").read_text())
    m=Message("sentinela",str(uuid4()),"5500000000000",Kind.TEXT,"teste")
    assert store.enqueue(m)
    assert not store.enqueue(m)
    assert store.session(m).user_id==store.session(m).user_id
    job=store.claim()
    assert job is not None
    store.finish(job,"done")
