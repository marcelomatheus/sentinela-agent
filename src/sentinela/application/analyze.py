import logging
from dataclasses import dataclass, replace
from uuid import uuid4

from sentinela.application.ports import Extractor, Messenger, QuestionAgent, Reputation, Transcriber
from sentinela.domain.guardrails import INVALID, OUT_OF_SCOPE, Policy
from sentinela.domain.inference import infer, question_options, render
from sentinela.domain.model import EXTERNAL_FACTS, Kind, Media, Message, Session

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    session: Session
    response: str


@dataclass(slots=True)
class AnalyzeMessage:
    extractor: Extractor
    question_agent: QuestionAgent
    reputation: Reputation
    messenger: Messenger
    transcriber: Transcriber
    policy: Policy = Policy()

    def execute(self, message: Message, session: Session) -> AnalysisResult:
        if message.kind == Kind.TEXT and message.text.strip().lower() == "/nova":
            return AnalysisResult(replace(session, session_id=uuid4(), facts=frozenset(), absent=frozenset(), last_question=None, asked_questions=frozenset()),
                                  "Novo caso iniciado. Envie a mensagem, foto ou áudio suspeito.")
        text = message.text
        rejection = self.policy.preflight(text)
        if rejection is not None:
            return AnalysisResult(session, rejection)
        image: Media | None = None
        if message.kind != Kind.TEXT:
            media = self.messenger.download(message)
            if message.kind == Kind.IMAGE:
                image = media
            else:
                text = self.transcriber.transcribe(media)
        rejection = self.policy.preflight(text)
        if rejection is not None:
            return AnalysisResult(session, rejection)
        observed = self.extractor.extract(text, image, session)
        if not observed.in_scope:
            return AnalysisResult(session, OUT_OF_SCOPE)
        if observed.present & observed.absent:
            return AnalysisResult(session, INVALID)
        previous = session.facts if observed.continues_previous else frozenset()
        if not observed.continues_previous and (session.facts or session.absent or session.last_question):
            session = replace(session, session_id=uuid4(), absent=frozenset(), last_question=None)
        present = observed.present - EXTERNAL_FACTS
        absent = observed.absent - EXTERNAL_FACTS
        facts = (previous - absent) | present | self.reputation.inspect(text)
        denied = ((session.absent if observed.continues_previous else frozenset()) | absent) - facts
        session = replace(session, facts=frozenset(facts), absent=frozenset(denied))
        assessment = infer(session.facts)
        options = tuple(q for q in question_options(assessment, session.absent) if q not in session.asked_questions)
        if len(session.asked_questions) >= self.policy.max_questions:
            options = ()
        try:
            selected = self.question_agent.choose(assessment, options, session) if options else None
        except Exception:
            # O motor de regras continua operando mesmo sem a fase conversacional.
            log.warning("question_agent_unavailable")
            selected = None
        question = selected if selected in options else next(iter(options), None)
        return AnalysisResult(replace(session, last_question=question, asked_questions=session.asked_questions | ({question} if question else set())), render(assessment, question))
