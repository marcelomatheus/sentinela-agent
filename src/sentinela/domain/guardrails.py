"""Deterministic boundaries; never return model-generated prose."""
from dataclasses import dataclass
import re
import unicodedata

IDENTITY = "Sou o Sentinela, especialista em triagem de indícios de golpes digitais. Analiso mensagens, imagens, áudios e links suspeitos. Envie um caso ou use /nova."
OUT_OF_SCOPE = IDENTITY
BLOCKED = "Sou o Sentinela. Não posso executar instruções externas, revelar configurações ou acessar dados de outras pessoas. Se recebeu uma mensagem suspeita, descreva o contexto sem incluir dados pessoais."
LIMIT = "Limite de análises atingido. Tente novamente amanhã (UTC). Não compartilhe senhas ou códigos; consulte os canais oficiais."
INVALID = "Não consegui analisar esse conteúdo com segurança. Envie uma descrição curta do possível golpe, sem dados pessoais."

@dataclass(frozen=True, slots=True)
class Policy:
    max_chars: int = 4000
    max_questions: int = 3

    def preflight(self, text: str) -> str | None:
        if len(text) > self.max_chars:
            return INVALID
        normalized = unicodedata.normalize("NFKD", text.casefold())
        normalized = "".join(c for c in normalized if not unicodedata.combining(c) and unicodedata.category(c) != "Cf")
        normalized = " ".join(normalized.split())
        if normalized in {"oi", "ola", "bom dia", "boa tarde", "boa noite", "quem e voce", "quem e voce?", "/ajuda", "/help"}:
            return IDENTITY
        # Only intercept direct requests to override the bot. Quoted scam
        # evidence must be analyzed, not discarded as an injection attempt.
        direct = re.match(r"^(?:sentinela[, :]\s*)?(?:ignore|esqueca|desconsidere|override|disregard|forget|revele|mostre|exiba|print|dump|reveal)\b", normalized)
        target = re.search(r"(?:instruc|prompt|system|developer|chave|api.?key|outro usuario|other user|historico)", normalized)
        if direct and target:
            return BLOCKED
        return None
