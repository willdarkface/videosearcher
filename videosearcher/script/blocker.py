"""Segmentação de cues em blocos visuais.

Legenda vem picada em cues de 1 a 3 segundos, que é granularidade errada para
escolher imagem. Bloco visual é a unidade que recebe UM asset: dura alguns
segundos e termina em fronteira de ideia, não no meio de uma frase.

Regras, em ordem de prioridade:
  1. Nunca cortar antes da duração mínima do canal.
  2. Preferir cortar em pontuação forte (. ! ? …) depois da duração alvo.
  3. Cortar à força na duração máxima.
  4. Pausa longa entre cues (gap) é fronteira natural — corta ali.
  5. Último bloco curto é fundido ao anterior quando isso não estourar o máximo.
"""

from __future__ import annotations

import re

from ..core.config import EntregaConfig
from ..core.models import Block, Cue

_STRONG_END_RE = re.compile(r"[.!?…]['\"”’)\]]*$")
_WEAK_END_RE = re.compile(r"[,;:—–]['\"”’)\]]*$")


def _ends_strong(text: str) -> bool:
    return bool(_STRONG_END_RE.search(text.strip()))


def _ends_weak(text: str) -> bool:
    return bool(_WEAK_END_RE.search(text.strip()))


def _make_block(number: int, cues: list[Cue]) -> Block:
    return Block(
        number=number,
        start_s=cues[0].start_s,
        end_s=cues[-1].end_s,
        text=" ".join(c.text for c in cues).strip(),
        cue_indexes=[c.index for c in cues],
    )


def build_blocks(cues: list[Cue], entrega: EntregaConfig | None = None) -> list[Block]:
    """Agrupa cues em blocos visuais conforme a configuração de entrega do canal."""
    if not cues:
        return []

    entrega = entrega or EntregaConfig()
    min_d = entrega.min_duracao
    max_d = entrega.max_duracao
    target = entrega.alvo
    max_gap = entrega.gap_maximo_s

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
