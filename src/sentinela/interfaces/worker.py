"""Single worker; delivery uncertainty is not automatically retried."""
import logging
import time
from sentinela.application.analyze import AnalyzeMessage
from sentinela.config import get_settings
from sentinela.domain.guardrails import LIMIT, Policy
from sentinela.infrastructure.ai import AgnoSpecialist,OpenAITranscriber
from sentinela.infrastructure.evolution import Evolution
from sentinela.infrastructure.postgres import Store
from sentinela.infrastructure.reputation import UrlReputation

log=logging.getLogger(__name__)

def main()->None:
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    settings=get_settings()
    store=Store(settings)
    messenger=Evolution(settings)
    agent=AgnoSpecialist(settings)
    use_case=AnalyzeMessage(agent,agent,UrlReputation(settings.safe_browsing_api_key.get_secret_value()),
        messenger,OpenAITranscriber(settings),Policy(settings.guard_max_chars,settings.guard_max_questions))
    store.migrate_guardrails()
    store.recover()
    while True:
        job=store.claim()
        if job is None:
            time.sleep(1)
            continue
        if job.response is not None:
            try:
                messenger.send(job.message,job.response)
            except Exception as exc:
                log.warning("send_uncertain job=%s error=%s",job.id,type(exc).__name__)
                store.finish(job,"uncertain",type(exc).__name__)
            else:
                store.finish(job,"done")
            continue
        try:
            try:
                messenger.presence(job.message,True)
            except Exception:
                log.warning("presence_unavailable job=%s",job.id)
            session=store.session(job.message)
            if not store.reserve(job):
                store.save_result(job,session,LIMIT)
                continue
            result=use_case.execute(job.message,session)
            store.save_result(job,result.session,result.response)
        except Exception as exc:
            log.warning("analysis_failed job=%s error=%s",job.id,type(exc).__name__)
            store.retry(job,type(exc).__name__)
        finally:
            try:
                messenger.presence(job.message,False)
            except Exception:
                log.warning("presence_unavailable job=%s",job.id)

if __name__=="__main__":
    main()
