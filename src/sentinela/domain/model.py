from dataclasses import dataclass
from typing import Any
from enum import StrEnum
from uuid import UUID


class Kind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"


class Fact(StrEnum):
    OTP = "solicitacao_codigo"
    PASSWORD = "solicitacao_senha"
    URGENCY = "urgencia"
    UNKNOWN_SENDER = "origem_nao_verificada"
    MONEY = "solicitacao_dinheiro"
    FAMILY = "alega_parentesco"
    BANK = "alega_banco"
    PRIZE = "premio_inesperado"
    ADVANCE = "pagamento_antecipado"
    JOB = "oferta_emprego"
    INVESTMENT = "oferta_investimento"
    GUARANTEED = "retorno_garantido"
    REMOTE = "acesso_remoto_inesperado"
    DELIVERY = "alega_entrega"
    LINK = "link_presente"
    SUSPICIOUS_URL = "caracteristica_url_suspeita"
    MALICIOUS_URL = "url_sinalizada_por_reputacao"
    SHOP = "oferta_loja"
    UNREAL_PRICE = "preco_desproporcional"
    PAYMENT_MISMATCH = "divergencia_pagamento"


EXTERNAL_FACTS = frozenset({Fact.MALICIOUS_URL, Fact.SUSPICIOUS_URL})


@dataclass(frozen=True, slots=True)
class Message:
    instance: str
    message_id: str
    wid: str
    kind: Kind
    text: str = ""
    media_mime: str = ""
    remote_jid: str = ""
    media_envelope: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Session:
    user_id: UUID
    session_id: UUID
    facts: frozenset[Fact]
    absent: frozenset[Fact] = frozenset()
    last_question: str | None = None
    asked_questions: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Observation:
    present: frozenset[Fact]
    absent: frozenset[Fact]
    continues_previous: bool
    in_scope: bool = True


@dataclass(frozen=True, slots=True)
class Media:
    data: bytes
    mime: str


class Risk(StrEnum):
    HIGH = "ALTO"
    MODERATE = "MODERADO"
    INCONCLUSIVE = "INCONCLUSIVO"
