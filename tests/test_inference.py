from sentinela.domain.inference import infer, render
from sentinela.domain.model import Fact, Risk

def test_otp():
    result = infer(frozenset({Fact.OTP, Fact.BANK}))
    assert result.risk == Risk.HIGH
    assert {"R01", "R12"} <= {r.id for r in result.rules}

def test_no_evidence():
    result = infer(frozenset())
    assert result.risk == Risk.INCONCLUSIVE
    assert not result.rules

def test_urgency():
    assert infer(frozenset({Fact.URGENCY})).risk == Risk.MODERATE

def test_prize():
    assert "R04" in {r.id for r in infer(frozenset({Fact.PRIZE, Fact.ADVANCE})).rules}

def test_explanation():
    response = render(infer(frozenset({Fact.MALICIOUS_URL})))
    assert "URL sinalizada" in response
    assert "R09" not in response
    assert "Referência:" not in response


def test_risk_response_is_short_and_actionable():
    response = render(infer(frozenset({Fact.BANK, Fact.OTP})))
    assert "possível golpe" in response
    assert "código" in response.lower()
    assert len(response) < 360
    assert "R01" not in response
    assert "Indícios:" not in response


def test_inconclusive_response_is_friendly_with_single_question():
    response = render(infer(frozenset()), "money")
    assert "poucas informações" in response
    assert "pagamento ou transferência" in response
    assert len(response) < 250
    assert "https://" not in response
