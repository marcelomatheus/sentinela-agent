"""Independent web worker; the WhatsApp worker and inference code are unchanged."""
import logging
import threading
import time
from pathlib import Path

from sentinela.application.analyze import AnalyzeMessage
from sentinela.application.errors import ExtractionFormatError
from sentinela.config import get_settings
from sentinela.domain.model import Kind
from sentinela.domain.guardrails import FORMAT_UNAVAILABLE, INVALID, LIMIT, Policy, TEMPORARY_UNAVAILABLE
from sentinela.infrastructure.ai import AgnoSpecialist, OpenAITranscriber
from sentinela.infrastructure.reputation import UrlReputation
from sentinela.infrastructure.web_media import WebMessenger
from sentinela.infrastructure.web_store import WebJob, WebStore

log = logging.getLogger(__name__)


def process_web_job(job: WebJob, store: WebStore, use_case: AnalyzeMessage) -> None:
    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(20):
            try:
                store.heartbeat(job)
            except Exception:
                log.warning("web_lease_heartbeat_failed job=%s",job.id)

    heartbeat = threading.Thread(target=renew,name="lease-renew",daemon=True)
    heartbeat.start()
    try:
        # Pure deterministic replies (greeting, thanks, /nova, invalid input)
        # must not consume the OpenAI inference budget.
        if job.message.kind == Kind.TEXT and (
            job.message.text.strip().lower() == "/nova"
            or use_case.policy.preflight(job.message.text) is not None
        ):
            result = use_case.execute(job.message, job.session)
            store.complete(job, result.session, result.response, None)
            return
        if not store.reserve(job):
            store.complete(job,job.session,LIMIT,None)
            return
        result = use_case.execute(job.message,job.session)
        risk = result.risk.value if result.risk is not None else None
        store.complete(job,result.session,result.response,risk)
    except ExtractionFormatError:
        store.complete(job,job.session,FORMAT_UNAVAILABLE,None)
    except ValueError:
        store.complete(job,job.session,INVALID,None)
    except Exception as exc:
        log.warning("web_analysis_failed job=%s error=%s",job.id,type(exc).__name__)
        if job.attempts >= 3:
            store.complete(job,job.session,TEMPORARY_UNAVAILABLE,None)
        else:
            store.fail(job,type(exc).__name__)
    finally:
        stop.set()
        heartbeat.join(timeout=2)


def main() -> None:
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    settings=get_settings()
    store=WebStore(settings)
    store.migrate()
    agent=AgnoSpecialist(settings)
    messenger=WebMessenger(store,settings.web_media_dir)
    use_case=AnalyzeMessage(
        agent,agent,UrlReputation(settings.safe_browsing_api_key.get_secret_value()),
        messenger,OpenAITranscriber(settings),
        Policy(settings.guard_max_chars,settings.guard_max_questions),
    )
    last_recover=0.0
    last_cleanup=0.0
    while True:
        if time.monotonic()-last_cleanup>=3600:
            try:
                for attachment in store.prune_orphans():
                    (Path(settings.web_media_dir)/str(attachment)).unlink(missing_ok=True)
                store.reconcile_files(settings.web_media_dir)
            except Exception:
                log.warning("web_retention_cleanup_failed")
            last_cleanup=time.monotonic()
        if time.monotonic()-last_recover>=15:
            store.recover()
            last_recover=time.monotonic()
        job=store.claim()
        if job is None:
            time.sleep(0.4)
            continue
        process_web_job(job,store,use_case)


if __name__=="__main__":
    main()
