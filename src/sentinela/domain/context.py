"""Filter LLM-provided context notes before showing them to WhatsApp users.

A note is untrusted prose, not a fact, verdict or recommendation. If a note
contains sensitive details or does not overlap with the current text evidence,
the reply falls back to the deterministic response.
"""
import re
import unicodedata

_FORBIDDEN = re.compile(
    r"(?:https?://|www\.|@|[<>`{}\[\]\\|#$]|\b\d{4,}\b|"
    r"\b(?:ignore|ignorar|obedeça|obedeca|revele|clique|acesse|"
    r"abra|instale|baixe|pague|transfira|compartilhe|informe|envie|"
    r"responda|execute|prompt|system|developer|assistant)\b)",
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-z]{5,}", re.IGNORECASE)


def _words(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return set(_WORD.findall(ascii_text))


def safe_context_note(value: str, evidence: str = "") -> str:
    """Accept a short grounded observational clause or return empty."""
    note = unicodedata.normalize("NFC", value).strip().rstrip(" .!?")
    if not note or len(note) > 145 or "\n" in note or "\r" in note:
        return ""
    if _FORBIDDEN.search(note):
        return ""
    if not re.fullmatch(r"[\wÀ-ÿ ,;:'’()/-]+", note):
        return ""
    note = re.sub(r"\s+", " ", note)
    # Image evidence may have no textual caption.
    if evidence.strip() and len(evidence.strip()) >= 12 and not (_words(note) & _words(evidence)):
        return ""
    return note[0].lower() + note[1:]
