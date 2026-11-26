import logging
import re
from dataclasses import dataclass, replace
from uuid import uuid4

from sentinela.application.ports import Extractor, Messenger, QuestionAgent, Reputation, Transcriber
from sentinela.domain.guardrails import CONFLICTING, OUT_OF_SCOPE, Policy
from sentinela.domain.inference import infer, question_options, render
from sentinela.domain.context import safe_context_note
from sentinela.domain.model import EXTERNAL_FACTS, Fact, Kind, Media, Message, Risk, Session

log = logging.getLogger(__name__)

_NEW_CASE = re.compile(
    r"^\s*(?:outro caso|outro golpe|nova mensagem|outra mensagem|"
    r"outro assunto|nova situação|outra situação|"
    r"mudando de assunto|agora (?:outro|outra)|recebi outr[ao])\b",
    re.IGNORECASE,
)
_SCENARIOS = frozenset({
    Fact.BANK, Fact.FAMILY, Fact.PRIZE, Fact.JOB,
    Fact.INVESTMENT, Fact.DELIVERY, Fact.SHOP,
})


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    session: Session
    response: str
    risk: Risk | None = None


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
                                  "Prontinho! 😊 Vamos começar outro caso. Pode me mandar a mensagem, foto ou áudio suspeito.")
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
            return AnalysisResult(session, CONFLICTING)
        # Facts from a previous scam must not contaminate a different case.
        present = observed.present - EXTERNAL_FACTS
        old_scenarios = session.facts & _SCENARIOS
        new_scenarios = present & _SCENARIOS
        changed_scenario = bool(old_scenarios and new_scenarios and not (old_scenarios & new_scenarios))
        new_case = (
            not observed.continues_previous
            or bool(_NEW_CASE.match(text))
            or changed_scenario
        )
        previous_assessment = infer(session.facts)
        if new_case and (
            session.facts or session.absent or session.last_question or session.asked_questions
        ):
            session = replace(
                session, session_id=uuid4(), facts=frozenset(),
                absent=frozenset(), last_question=None,
                asked_questions=frozenset(),
            )

        previous = session.facts if not new_case else frozenset()
        absent = observed.absent - EXTERNAL_FACTS
        facts = (previous - absent) | present | self.reputation.inspect(text)
        denied = ((session.absent if not new_case else frozenset()) | absent) - facts
        session = replace(session, facts=frozenset(facts), absent=frozenset(denied))
        assessment = infer(session.facts)
        repeated_high_risk = (
            not new_case
            and previous_assessment.risk == Risk.HIGH
            and assessment.risk == Risk.HIGH
            and {rule.id for rule in previous_assessment.rules}
                == {rule.id for rule in assessment.rules}
        )
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
        return AnalysisResult(
            replace(session, last_question=question,
                    asked_questions=session.asked_questions | ({question} if question else set())),
            render(assessment, question,
                   context_note=safe_context_note(observed.context_note, text),
                   follow_up=repeated_high_risk),
            assessment.risk,
        )
