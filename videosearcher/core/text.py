"""Utilidades de texto compartilhadas."""

from __future__ import annotations

import re
import unicodedata

_NAO_ALFANUM = re.compile(r"[^a-z0-9]+")

# Palavras sem valor visual: não ajudam a nomear arquivo nem a buscar imagem.
_STOPWORDS_PT = {
    "a", "à", "ao", "aos", "as", "às", "com", "como", "da", "das", "de", "do",
    "dos", "e", "em", "essa", "esse", "esta", "este", "eu", "foi", "isso",
    "já", "la", "lhe", "mais", "mas", "me", "mesmo", "muito", "na", "nas",
    "não", "no", "nos", "num", "numa", "o", "os", "ou", "para", "pela",
    "pelo", "por", "que", "se", "sem", "ser", "seu", "sua", "são", "também",
    "tem", "um", "uma", "você", "vocês",
}
_STOPWORDS_EN = {
    "a", "about", "after", "all", "an", "and", "any", "are", "as", "at", "be",
    "because", "been", "but", "by", "can", "did", "do", "for", "from", "had",
    "has", "have", "he", "her", "his", "how", "i", "if", "in", "into", "is",
    "it", "its", "just", "me", "no", "not", "of", "on", "one", "only", "or",
    "our", "out", "so", "that", "the", "their", "them", "then", "there",
    "these", "they", "this", "to", "up", "was", "we", "were", "what", "when",
    "which", "who", "why", "will", "with", "you", "your",
}
STOPWORDS = _STOPWORDS_PT | _STOPWORDS_EN


def remover_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def slugify(texto: str, *, max_chars: int = 60, separador: str = "-") -> str:
    """Converte texto em slug seguro para nome de arquivo.

    Corta em palavra inteira para não gerar nome truncado no meio, porque o
    slug vai virar nome de arquivo que você lê no explorador.
    """
    base = _NAO_ALFANUM.sub(" ", remover_acentos(texto).lower()).strip()
    if not base:
        return "sem-titulo"

    palavras = base.split()
    saida: list[str] = []
    tamanho = 0
    for palavra in palavras:
        extra = len(palavra) + (1 if saida else 0)
        if tamanho + extra > max_chars:
            break
        saida.append(palavra)
        tamanho += extra

    if not saida:
        saida = [palavras[0][:max_chars]]
    return separador.join(saida)


def palavras_chave(texto: str, *, maximo: int = 6) -> list[str]:
    """Extrai palavras de conteúdo — usado como rede de segurança quando o
    briefing por LLM falha e é preciso montar uma query mínima."""
    base = _NAO_ALFANUM.sub(" ", remover_acentos(texto).lower())
    vistas: set[str] = set()
    saida: list[str] = []
    for palavra in base.split():
        if len(palavra) < 3 or palavra in STOPWORDS or palavra in vistas:
            continue
        vistas.add(palavra)
        saida.append(palavra)
        if len(saida) >= maximo:
            break
    return saida
