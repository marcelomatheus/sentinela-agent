from dataclasses import dataclass

from sentinela.domain.model import Fact, Risk

SOURCE = "https://cartilha.cert.br/fasciculos/"


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    conditions: frozenset[Fact]
    conclusion: str
    advice: str
    risk: Risk = Risk.HIGH
    source: str = SOURCE


def rule(id: str, facts: tuple[Fact, ...], conclusion: str, advice: str) -> Rule:
    return Rule(id, frozenset(facts), conclusion, advice)


RULES = (
    rule("R01", (Fact.BANK, Fact.OTP), "Possível falsa central bancária", "Ligue para o banco pelos canais oficiais."),
    rule("R02", (Fact.PASSWORD,), "Solicitação de senha", "Não compartilhe senhas."),
    rule("R03", (Fact.FAMILY, Fact.UNKNOWN_SENDER, Fact.MONEY), "Possível falso familiar", "Confirme com o familiar por outro canal."),
    rule("R04", (Fact.PRIZE, Fact.ADVANCE), "Possível falso prêmio", "Não pague para receber um prêmio."),
    rule("R05", (Fact.JOB, Fact.ADVANCE), "Possível falso emprego", "Verifique a vaga diretamente com a empresa."),
    rule("R06", (Fact.INVESTMENT, Fact.GUARANTEED), "Possível fraude de investimento", "Não transfira dinheiro sem verificar a instituição."),
    rule("R07", (Fact.REMOTE,), "Solicitação inesperada de acesso remoto", "Não instale programas nem conceda acesso remoto."),
    rule("R08", (Fact.DELIVERY, Fact.LINK, Fact.MONEY), "Possível falsa entrega", "Consulte o rastreio no aplicativo oficial."),
    rule("R09", (Fact.MALICIOUS_URL,), "URL sinalizada por fonte de reputação", "Não acesse o endereço."),
    rule("R10", (Fact.SHOP, Fact.UNREAL_PRICE, Fact.ADVANCE), "Possível falsa loja", "Verifique a loja independentemente do anúncio."),
    rule("R11", (Fact.PAYMENT_MISMATCH,), "Divergência nos dados de pagamento", "Confirme o beneficiário com o emissor oficial."),
    rule("R12", (Fact.OTP,), "Solicitação de código de autenticação", "Não informe códigos recebidos por SMS ou aplicativo."),
)


@dataclass(frozen=True, slots=True)
class Assessment:
    risk: Risk
    rules: tuple[Rule, ...]
    facts: frozenset[Fact]


def infer(facts: frozenset[Fact]) -> Assessment:
    matched = tuple(r for r in RULES if r.conditions <= facts)
    indicators = {Fact.URGENCY, Fact.UNKNOWN_SENDER, Fact.SUSPICIOUS_URL, Fact.ADVANCE, Fact.UNREAL_PRICE}
    risk = Risk.HIGH if matched else Risk.MODERATE if facts & indicators else Risk.INCONCLUSIVE
    return Assessment(risk, matched, facts)


QUESTIONS: dict[str, tuple[Fact, str]] = {
    "code": (Fact.OTP, "O contato pediu algum código de autenticação? Não envie o código."),
    "money": (Fact.MONEY, "Foi solicitado algum pagamento ou transferência?"),
    "origin": (Fact.UNKNOWN_SENDER, "O contato veio de um número ou perfil que você não reconhece?"),
    "advance": (Fact.ADVANCE, "Foi solicitado pagamento antecipado?"),
}


def question_options(assessment: Assessment, absent: frozenset[Fact]) -> tuple[str, ...]:
    if assessment.risk == Risk.HIGH:
        return ()
    # Prioritize what is missing *for this case*, not the same OTP question
    # for every vague message.
    facts = assessment.facts
    if Fact.BANK in facts or Fact.FAMILY in facts:
        priority = ("code", "origin", "money", "advance")
    elif Fact.MONEY in facts or Fact.INVESTMENT in facts:
        priority = ("origin", "advance", "code", "money")
    elif Fact.SHOP in facts or Fact.PRIZE in facts or Fact.JOB in facts:
        priority = ("advance", "origin", "money", "code")
    else:
        priority = ("money", "origin", "code", "advance")
    return tuple(key for key in priority if QUESTIONS[key][0] not in facts | absent)


def render(assessment: Assessment, question: str | None = None) -> str:
    """Actionable, non-hallucinated guidance from validated facts and rules."""
    if assessment.risk == Risk.HIGH:
        lines = ["⚠️ Atenção, encontrei sinais de um possível golpe."]
        for matched in assessment.rules[:2]:
            lines.append(f"{matched.conclusion}. {matched.advice}")
        return "\n".join(lines)

    if assessment.risk == Risk.MODERATE:
        if Fact.URGENCY in assessment.facts:
            intro = "Pediram pressa, e isso merece cuidado."
        elif Fact.SUSPICIOUS_URL in assessment.facts or Fact.LINK in assessment.facts:
            intro = "Esse link merece cuidado antes de abrir."
        elif Fact.UNKNOWN_SENDER in assessment.facts:
            intro = "Ainda não sabemos se esse contato é confiável."
        elif Fact.ADVANCE in assessment.facts:
            intro = "Um pagamento antecipado merece atenção."
        else:
            intro = "Percebi um possível sinal de alerta."
        if question in QUESTIONS:
            return f"🤔 {intro} {QUESTIONS[question][1]}"
        return f"🤔 {intro} Confirme a situação por um canal oficial antes de agir."

    if question in QUESTIONS:
        return (
            "Ainda não tenho indícios suficientes para avaliar. "
            + QUESTIONS[question][1]
        )
    if assessment.facts:
        return (
            "Entendi parte da situação, mas ainda não dá para concluir. "
            "Se puder, envie a mensagem completa ou diga exatamente o que pediram."
        )
    return (
        "Não consegui identificar o que o contato pediu. "
        "Pode copiar a mensagem ou contar o que aconteceu, sem incluir dados pessoais?"
    )
