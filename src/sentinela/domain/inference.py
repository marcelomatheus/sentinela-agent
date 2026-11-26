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
    """Short and friendly messages composed from trusted rule content.

    Full rule details stay in the domain; only up to two concise, actionable
    findings are shown to the person, without raw model prose or IDs.
    """
    if assessment.risk == Risk.HIGH:
        lines = ["⚠️ Atenção, encontrei sinais de um possível golpe."]
        for matched in assessment.rules[:2]:
            lines.append(f"{matched.conclusion}. {matched.advice}")
    elif assessment.risk == Risk.MODERATE:
        lines = [
            "Tem alguns sinais de alerta aqui. 🤔",
            "Ainda não dá para afirmar que é golpe. Vamos entender melhor?",
        ]
    else:
        lines = [
            "Ainda tenho poucas informações para avaliar. 🙂",
            "Me conta só mais um detalhe?",
        ]

    if question is not None and question in QUESTIONS:
        lines.append(QUESTIONS[question][1])
    elif assessment.risk != Risk.HIGH:
        lines.append("Por segurança, não clique em links nem envie códigos ou senhas.")

    return "\n".join(lines)
