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
    assert "R09" in render(infer(frozenset({Fact.MALICIOUS_URL})))
