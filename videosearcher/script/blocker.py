"""Segmentação de cues em blocos visuais.

Duas etapas, e a primeira existe por causa de dado real.

**Etapa 1 — divisão por frase.** A cue da legenda não é a unidade visual. Uma
cue de 8 segundos pode conter sete beats diferentes ("Long red lines. Men
shoulder to shoulder. Smoke everywhere. Right?"). Se o blocker só agrupa cues,
ele nunca consegue cortar no lugar certo. Então primeiro quebramos cada cue em
unidades de frase, com timecode interpolado proporcionalmente ao tamanho do
texto.

**Etapa 2 — agrupamento.** As unidades são reagrupadas em blocos que respeitam
a duração do canal, preferindo fronteira de pontuação forte.

Regras do agrupamento, em ordem de prioridade:
  1. Nunca cortar antes da duração mínima do canal.
  2. Preferir cortar em pontuação forte (. ! ? …) depois da duração alvo.
  3. Cortar à força na duração máxima.
  4. Pausa longa entre unidades (gap) é fronteira natural — corta ali.
  5. Bloco curto é fundido ao vizinho quando isso não estourar o máximo.
"""

from __future__ import annotations

import re

from ..core.config import EntregaConfig
from ..core.models import Block, Cue

_STRONG_END_RE = re.compile(r"[.!?…]['\"”’)\]]*$")
_WEAK_END_RE = re.compile(r"[,;:—–]['\"”’)\]]*$")

# Reticências (de 2 pontos para cima) são marcador de beat em roteiro narrado:
# normalizamos para "…" e tratamos como fim de frase.
_ELLIPSIS_RE = re.compile(r"\.{2,}")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
_HAS_WORD_RE = re.compile(r"\w")


def _ends_strong(text: str) -> bool:
    return bool(_STRONG_END_RE.search(text.strip()))


def _ends_weak(text: str) -> bool:
    return bool(_WEAK_END_RE.search(text.strip()))


def split_sentences(text: str) -> list[str]:
    """Divide um texto em frases, tratando reticências como fronteira."""
    normalized = _ELLIPSIS_RE.sub("…", text)
    parts = _SENTENCE_SPLIT_RE.split(normalized)
    return [p.strip() for p in parts if _HAS_WORD_RE.search(p)]


def split_into_units(cues: list[Cue], min_unit_s: float = 0.6) -> list[Cue]:
    """Quebra cues em unidades de frase, interpolando o timecode.

    A duração da cue é distribuída entre as frases proporcionalmente ao número
    de caracteres — aproximação boa porque a locução tem ritmo praticamente
    constante. O `index` da unidade preserva o da cue de origem, então o bloco
    final continua rastreável até a legenda.
    """
    units: list[Cue] = []

    for cue in cues:
        sentences = split_sentences(cue.text)
        if len(sentences) <= 1:
            units.append(cue)
            continue

        total_chars = sum(len(s) for s in sentences)
        if total_chars == 0:
            units.append(cue)
            continue

        duration = cue.duration_s
        start = cue.start_s
        consumed = 0

        produced: list[Cue] = []
        for i, sentence in enumerate(sentences):
            consumed += len(sentence)
            is_last = i == len(sentences) - 1
            end = cue.end_s if is_last else cue.start_s + duration * (consumed / total_chars)
            produced.append(
                Cue(index=cue.index, start_s=start, end_s=end, text=sentence)
            )
            start = end

        units.extend(_merge_tiny_units(produced, min_unit_s))

    return units


def _merge_tiny_units(units: list[Cue], min_unit_s: float) -> list[Cue]:
    """Funde unidades curtas demais (ex.: "Right?") com a vizinha."""
    if len(units) <= 1:
        return units

    merged: list[Cue] = []
    for unit in units:
        if merged and unit.duration_s < min_unit_s:
            prev = merged[-1]
            merged[-1] = Cue(
                index=prev.index,
                start_s=prev.start_s,
                end_s=unit.end_s,
                text=f"{prev.text} {unit.text}".strip(),
            )
        else:
            merged.append(unit)

    # Se a primeira unidade ficou curta, funde com a segunda
    if len(merged) > 1 and merged[0].duration_s < min_unit_s:
        first, second = merged[0], merged[1]
        merged[1] = Cue(
            index=first.index,
            start_s=first.start_s,
            end_s=second.end_s,
            text=f"{first.text} {second.text}".strip(),
        )
        merged.pop(0)

    return merged


def _make_block(number: int, cues: list[Cue]) -> Block:
    seen: list[int] = []
    for c in cues:
        if c.index not in seen:
            seen.append(c.index)
    return Block(
        number=number,
        start_s=cues[0].start_s,
        end_s=cues[-1].end_s,
        text=" ".join(c.text for c in cues).strip(),
        cue_indexes=seen,
    )


def build_blocks(cues: list[Cue], entrega: EntregaConfig | None = None) -> list[Block]:
    """Segmenta a legenda em blocos visuais conforme a configuração do canal."""
    if not cues:
        return []

    entrega = entrega or EntregaConfig()
    min_d = entrega.min_duracao
    max_d = entrega.max_duracao
    target = entrega.alvo
    max_gap = entrega.gap_maximo_s

    if entrega.dividir_por_frase:
        cues = split_into_units(cues, entrega.duracao_minima_unidade_s)

    groups: list[list[Cue]] = []
    current: list[Cue] = []

    for i, cue in enumerate(cues):
        if current:
            gap = cue.start_s - current[-1].end_s
            elapsed = current[-1].end_s - current[0].start_s
            # Pausa longa: fronteira natural, desde que o bloco já tenha corpo
            if gap > max_gap and elapsed >= min_d:
                groups.append(current)
                current = []

        # Lookahead: se adicionar esta cue estouraria o máximo e o bloco atual
        # já tem duração suficiente, fecha antes em vez de depois. Uma cue nunca
        # é dividida, então esta é a única forma de respeitar o teto do canal.
        if current:
            elapsed = current[-1].end_s - current[0].start_s
            projected = cue.end_s - current[0].start_s
            if projected > max_d and elapsed >= min_d:
                groups.append(current)
                current = []

        current.append(cue)
        duration = current[-1].end_s - current[0].start_s
        text = " ".join(c.text for c in current)

        if duration >= max_d:
            groups.append(current)
            current = []
            continue

        if duration >= target and _ends_strong(text):
            groups.append(current)
            current = []
            continue

        # Perto do teto e numa vírgula: melhor cortar aqui do que estourar
        if duration >= (max_d * 0.8) and _ends_weak(text):
            groups.append(current)
            current = []
            continue

        # Fim do arquivo
        if i == len(cues) - 1:
            groups.append(current)
            current = []

    if current:
        groups.append(current)

    groups = _merge_short_tail(groups, min_d=min_d, max_d=max_d)
    return [_make_block(n, g) for n, g in enumerate(groups, start=1)]


def _merge_short_tail(
    groups: list[list[Cue]], *, min_d: float, max_d: float
) -> list[list[Cue]]:
    """Funde blocos curtos demais com o vizinho anterior quando couber."""
    if len(groups) < 2:
        return groups

    merged: list[list[Cue]] = [groups[0]]
    for group in groups[1:]:
        duration = group[-1].end_s - group[0].start_s
        prev = merged[-1]
        combined = prev[-1].end_s - prev[0].start_s + duration
        if duration < min_d and combined <= max_d:
            merged[-1] = prev + group
        else:
            merged.append(group)
    return merged


def summarize(blocks: list[Block]) -> dict[str, float]:
    """Estatísticas para conferir se a segmentação ficou boa."""
    if not blocks:
        return {"blocos": 0}
    durations = [b.duration_s for b in blocks]
    chars = [len(b.text) for b in blocks]
    return {
        "blocos": len(blocks),
        "duracao_total_s": round(blocks[-1].end_s - blocks[0].start_s, 2),
        "duracao_media_s": round(sum(durations) / len(durations), 2),
        "duracao_min_s": round(min(durations), 2),
        "duracao_max_s": round(max(durations), 2),
        "caracteres_media": round(sum(chars) / len(chars), 1),
    }
