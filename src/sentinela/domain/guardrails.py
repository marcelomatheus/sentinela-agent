"""Deterministic boundaries; never return model-generated prose."""
from dataclasses import dataclass
import re
import unicodedata

IDENTITY = (
    "Oi! 👋 Eu sou o Sentinela. Te ajudo a avaliar mensagens, fotos, áudios "
    "ou links suspeitos. O que aconteceu?"
)
OUT_OF_SCOPE = (
    "Posso te ajudar com possíveis golpes digitais. 🙂 "
    "Se recebeu algo suspeito, me conte o que aconteceu."
)
BLOCKED = (
    "Eu só analiso possíveis golpes e não posso compartilhar informações "
    "de outras pessoas nem instruções internas. Se recebeu algo suspeito, posso ajudar."
)
LIMIT = (
    "Você atingiu o limite de análises por hoje. Pode tentar novamente amanhã. "
    "Enquanto isso, não compartilhe senhas ou códigos."
)
FORMAT_UNAVAILABLE = (
    "Não consegui interpretar essa mensagem com clareza. "
    "Pode reenviar o texto original ou uma captura mais legível, sem dados pessoais?"
)
TEMPORARY_UNAVAILABLE = (
    "Tive uma dificuldade técnica para analisar agora. "
    "Pode tentar de novo em alguns minutos? Se houver urgência, confirme por um canal oficial."
)
CONFLICTING = (
    "Encontrei informações que não combinam. "
    "Pode me enviar a mensagem completa para eu conferir?"
)
INVALID = (
    "Não consegui entender esse conteúdo com segurança. "
    "Pode me enviar uma descrição curta, sem dados pessoais?"
)
THANKS = "Por nada! 🙂 Se receber outra mensagem suspeita, pode me chamar."

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
        if normalized in {
            "oi", "ola", "e ai", "eai", "tudo bem", "oi sentinela",
            "bom dia", "boa tarde", "boa noite", "quem e voce",
            "quem e voce?", "/ajuda", "/help",
        }:
            return IDENTITY
        if normalized in {"obrigado", "obrigada", "valeu", "muito obrigado", "muito obrigada"}:
            return THANKS
        # Only intercept direct requests to override the bot. Quoted scam
        # evidence must be analyzed, not discarded as an injection attempt.
        direct = re.match(r"^(?:sentinela[, :]\s*)?(?:ignore|esqueca|desconsidere|override|disregard|forget|revele|mostre|exiba|print|dump|reveal)\b", normalized)
        target = re.search(r"(?:instruc|prompt|system|developer|chave|api.?key|outro usuario|other user|historico)", normalized)
        if direct and target:
            return BLOCKED
        return None
