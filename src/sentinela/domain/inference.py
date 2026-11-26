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
    return tuple(k for k, (f, _) in QUESTIONS.items() if f not in assessment.facts | absent)


def render(assessment: Assessment, question: str | None = None) -> str:
    lines = [f"🛡️ *Sentinela — risco {assessment.risk.value}*", ""]
    if assessment.rules:
        for r in assessment.rules:
            lines.append(f"• {r.conclusion} ({r.id}). {r.advice}")
    else:
        lines.append("Não há informação suficiente para confirmar fraude ou segurança.")
    if assessment.facts:
        lines.extend(["", "Indícios: " + ", ".join(f.value.replace("_", " ") for f in sorted(assessment.facts)) + "."])
    lines.extend(["", "Não compartilhe senhas/códigos. Confirme pelo canal oficial; não use links enviados pelo contato.",
                  "Se já houve pagamento ou exposição de dados, contate seu banco pelos canais oficiais.",
                  "Esta é uma triagem, não uma confirmação de fraude."])
    if question is not None and question in QUESTIONS:
        lines.extend(["", QUESTIONS[question][1]])
    lines.extend(["", "Envie /nova para iniciar outro caso.", f"Referência: {SOURCE}"])
    return "\n".join(lines)
