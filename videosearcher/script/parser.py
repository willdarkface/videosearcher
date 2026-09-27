"""Leitura de legendas SRT e WebVTT.

Implementado à mão de propósito: legenda vem de mil ferramentas diferentes
(YouTube, Whisper, CapCut, tradutores) e o parser precisa ser tolerante a BOM,
CRLF, índice ausente, tags inline e blocos NOTE/STYLE do VTT.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from ..core.models import Cue

# 00:01:02,500  |  00:01:02.500  |  01:02.500 (VTT sem hora)
_TIME_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
_ARROW_RE = re.compile(r"-{2,}>")

# Tags a remover do texto
_TAG_RE = re.compile(r"<[^>]+>")          # <i>, <c.yellow>, <00:00:01.000>
_ASS_RE = re.compile(r"\{[^}]*\}")        # {\an8}, {\b1}
_SPEAKER_RE = re.compile(r"^\s*[-–—]\s*") # travessão de diálogo no início da linha

_VTT_SKIP_PREFIXES = ("WEBVTT", "NOTE", "STYLE", "REGION")


class SubtitleParseError(ValueError):
    """O arquivo não pôde ser interpretado como legenda."""


def parse_timestamp(raw: str) -> float:
    """Converte um timestamp de legenda em segundos."""
    match = _TIME_RE.search(raw)
    if not match:
        raise SubtitleParseError(f"timestamp inválido: {raw!r}")
    hours, minutes, seconds, fraction = match.groups()
    ms = int(fraction.ljust(3, "0")[:3])
    return (
        int(hours or 0) * 3600
        + int(minutes) * 60
        + int(seconds)
        + ms / 1000.0
    )


def clean_text(raw: str) -> str:
    """Remove tags, normaliza espaços e desescapa entidades HTML."""
    text = _TAG_RE.sub("", raw)
    text = _ASS_RE.sub("", text)
    text = html.unescape(text)
    lines = []
    for line in text.splitlines():
        line = _SPEAKER_RE.sub("", line.strip())
        if line:
            lines.append(line)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _split_blocks(content: str) -> list[list[str]]:
    """Divide o arquivo em blocos separados por linha em branco."""
    content = content.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in content.split("\n"):
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def parse_subtitles(path: str | Path) -> list[Cue]:
    """Lê um arquivo .srt ou .vtt e devolve as cues em ordem cronológica."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"legenda não encontrada: {path}")

    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        # Legendas antigas em Latin-1 ainda circulam muito
        content = path.read_text(encoding="latin-1")

    cues: list[Cue] = []
    for block in _split_blocks(content):
        first = block[0].strip()
        if any(first.upper().startswith(p) for p in _VTT_SKIP_PREFIXES):
            continue

        arrow_at = next((i for i, line in enumerate(block) if _ARROW_RE.search(line)), None)
        if arrow_at is None:
            continue  # bloco sem timestamp: cabeçalho, metadado ou lixo

        timing_line = block[arrow_at]
        left, right = _ARROW_RE.split(timing_line, maxsplit=1)
        try:
            start_s = parse_timestamp(left)
            end_s = parse_timestamp(right)
        except SubtitleParseError:
            continue

        text = clean_text("\n".join(block[arrow_at + 1 :]))
        if not text:
            continue

        cues.append(Cue(index=len(cues) + 1, start_s=start_s, end_s=end_s, text=text))

    if not cues:
        raise SubtitleParseError(
            f"nenhuma legenda encontrada em {path} — confirme que é SRT ou VTT válido"
        )

    cues.sort(key=lambda c: (c.start_s, c.end_s))
    for i, cue in enumerate(cues, start=1):
        cue.index = i
    return cues
