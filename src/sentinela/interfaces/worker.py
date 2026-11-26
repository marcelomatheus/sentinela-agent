"""Single worker: durable opt-in gate precedes presence, quota and inference."""
import logging
import time

from sentinela.application.analyze import AnalyzeMessage
from sentinela.application.errors import ExtractionFormatError
from sentinela.application.ports import Messenger
from sentinela.config import get_settings
from sentinela.domain.guardrails import FORMAT_UNAVAILABLE, INVALID, LIMIT, Policy, TEMPORARY_UNAVAILABLE
from sentinela.infrastructure.ai import AgnoSpecialist, OpenAITranscriber
from sentinela.infrastructure.evolution import Evolution
from sentinela.infrastructure.postgres import Job, Store
from sentinela.infrastructure.reputation import UrlReputation

log = logging.getLogger(__name__)


def process_job(job: Job, store: Store, messenger: Messenger, use_case: AnalyzeMessage) -> None:
    """Process exactly one claimed job, without recreating it after a send timeout."""
    if job.response is not None:
        try:
            messenger.send(job.message, job.response)
        except Exception as exc:
            log.warning("send_uncertain job=%s error=%s", job.id, type(exc).__name__)
            store.finish(job, "uncertain", type(exc).__name__)
        else:
            store.finish(job, "done")
        return

    # Gate always runs before presence, quota, media, transcription or OpenAI.
    # Its transaction changes both session state and inbox delivery status.
    try:
        if not store.gate(job):
            return
    except Exception as exc:
        log.warning("gate_failed job=%s error=%s", job.id, type(exc).__name__)
        store.retry(job, type(exc).__name__)
        return

    session = None
    presence_attempted = False
    try:
        presence_attempted = True
        try:
            messenger.presence(job.message, True)
        except Exception:
            log.warning("presence_unavailable job=%s", job.id)

        session = store.session(job.message)
        if not store.reserve(job):
            store.save_result(job, session, LIMIT)
            return

        result = use_case.execute(job.message, session)
        store.save_result(job, result.session, result.response)
    except ExtractionFormatError:
        log.warning("model_schema_unavailable job=%s", job.id)
        if session is not None:
            store.save_result(job, session, FORMAT_UNAVAILABLE)
        else:
            store.retry(job, "ExtractionFormatError")
    except ValueError as exc:
        log.warning("invalid_message job=%s error=%s", job.id, type(exc).__name__)
        if session is not None:
            store.save_result(job, session, INVALID)
        else:
            store.retry(job, type(exc).__name__)
    except Exception as exc:
        log.warning("analysis_failed job=%s error=%s", job.id, type(exc).__name__)
        if session is not None and job.attempts >= 3:
            # Give a truthful, bounded failure response instead of silently
            # failing after all retries. Never claim to have assessed a risk.
            try:
                store.save_result(job, session, TEMPORARY_UNAVAILABLE)
            except Exception:
                store.retry(job, type(exc).__name__)
        else:
            store.retry(job, type(exc).__name__)
    finally:
        if presence_attempted:
            try:
                messenger.presence(job.message, False)
            except Exception:
                log.warning("presence_unavailable job=%s", job.id)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    store = Store(settings)
    messenger = Evolution(settings)
    agent = AgnoSpecialist(settings)
    use_case = AnalyzeMessage(
        agent, agent,
        UrlReputation(settings.safe_browsing_api_key.get_secret_value()),
        messenger, OpenAITranscriber(settings),
        Policy(settings.guard_max_chars, settings.guard_max_questions),
    )
    with store.worker_lock():
        store.migrate_guardrails()
        store.recover()
        next_cleanup = time.monotonic()
        while True:
            if time.monotonic() >= next_cleanup:
                try:
                    store.prune()
                except Exception:
                    log.warning("retention_cleanup_failed")
                next_cleanup = time.monotonic() + 3600

            job = store.claim()
            if job is None:
                time.sleep(1)
                continue
            process_job(job, store, messenger, use_case)


if __name__ == "__main__":
    main()
