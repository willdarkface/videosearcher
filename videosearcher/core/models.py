"""Modelos de dados do pipeline.

Estes tipos são o contrato entre todas as camadas. Qualquer provedor de mídia,
qualquer LLM e qualquer etapa de ranqueamento falam nesta linguagem.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MediaType(StrEnum):
    VIDEO = "video"
    PHOTO = "photo"


class Intent(StrEnum):
    """Intenção visual do bloco. Define para quais provedores a busca é roteada."""

    LITERAL = "literal"        # mostra exatamente o que o texto diz
    METAFORICO = "metaforico"  # representa a ideia, não a palavra
    ARQUIVO = "arquivo"        # material histórico / de época
    GRAFICO = "grafico"        # mapa, diagrama, número, gráfico
    RETRATO = "retrato"        # rosto, pessoa específica, expressão


class Look(StrEnum):
    """Estética exigida pelo bloco ou pelo canal."""

    ANY = "any"
    BW_ARCHIVAL = "bw_archival"
    COLOR_MODERN = "color_modern"
    SEPIA = "sepia"


class Sensitivity(StrEnum):
    """Nível de sensibilidade do conteúdo, para política de monetização."""

    NONE = "none"
    SENSITIVE = "sensitive"
    GRAPHIC = "graphic"

    @property
    def level(self) -> int:
        return {"none": 0, "sensitive": 1, "graphic": 2}[self.value]


class ContentKind(StrEnum):
    BROLL = "broll"
    ARCHIVAL = "archival"
    EDITORIAL = "editorial"


class Orientation(StrEnum):
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    SQUARE = "square"

    @classmethod
    def from_size(cls, width: int, height: int) -> Orientation:
        if height == 0:
            return cls.LANDSCAPE
        ratio = width / height
        if ratio > 1.05:
            return cls.LANDSCAPE
        if ratio < 0.95:
            return cls.PORTRAIT
        return cls.SQUARE


class Motion(StrEnum):
    ANY = "any"
    STILL = "still"
    SLOW = "slow"
    FAST = "fast"


# ---------------------------------------------------------------------------
# Roteiro
# ---------------------------------------------------------------------------


def format_timecode(seconds: float) -> str:
    """Converte segundos para HH:MM:SS,mmm (formato SRT)."""
    if seconds < 0:
        seconds = 0.0
    total_ms = round(seconds * 1000)
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class Cue(BaseModel):
    """Uma legenda individual, como vem do arquivo SRT/VTT."""

    index: int
    start_s: float
    end_s: float
    text: str

    @field_validator("end_s")
    @classmethod
    def _end_after_start(cls, v: float, info) -> float:
        start = info.data.get("start_s")
        if start is not None and v < start:
            return start
        return v

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)

    @property
    def timecode(self) -> str:
        return f"{format_timecode(self.start_s)} --> {format_timecode(self.end_s)}"


class Block(BaseModel):
    """Unidade visual do roteiro: o que vai receber UM asset.

    O `number` é o que aparece no nome do arquivo entregue e nunca é
    reordenado, mesmo que o bloco termine sem resultado.
    """

    number: int
    start_s: float
    end_s: float
    text: str
    cue_indexes: list[int] = Field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)

    @property
    def timecode(self) -> str:
        return f"{format_timecode(self.start_s)} --> {format_timecode(self.end_s)}"


# ---------------------------------------------------------------------------
# Briefing visual
# ---------------------------------------------------------------------------


class BriefQueries(BaseModel):
    """Consultas de busca, sempre em inglês e em vocabulário de banco de mídia."""

    primary: list[str] = Field(default_factory=list)
    secondary: list[str] = Field(default_factory=list)
    archival: list[str] = Field(default_factory=list)

    def all_queries(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for q in [*self.primary, *self.secondary, *self.archival]:
            key = q.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(q.strip())
        return out


class VisualBrief(BaseModel):
    """O que a camada de LLM produz para cada bloco.

    É a peça que transforma "busca por palavra-chave" em "entender o roteiro".
    """

    block_number: int
    text: str
    intent: Intent = Intent.LITERAL
    media_preference: list[MediaType] = Field(default_factory=lambda: [MediaType.VIDEO])
    era: str | None = None
    entities: list[str] = Field(default_factory=list)
    queries: BriefQueries = Field(default_factory=BriefQueries)
    tone: str | None = None
    motion: Motion = Motion.ANY
    look: Look = Look.ANY
    sensitivity: Sensitivity = Sensitivity.NONE
    slug: str = ""

    @property
    def wants_archival(self) -> bool:
        return self.intent is Intent.ARQUIVO or self.era is not None


# ---------------------------------------------------------------------------
# Mídia
# ---------------------------------------------------------------------------


class Asset(BaseModel):
    """Resultado normalizado de qualquer provedor.

    Os campos de licença são obrigatórios por design: é o que impede material
    com atribuição viral entrar no pipeline sem ninguém perceber.
    """

    uid: str                      # "{provider}:{provider_id}"
    provider: str
    media_type: MediaType
    title: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)

    # vídeo
    duration_s: float | None = None
    fps: float | None = None

    # comum
    width: int = 0
    height: int = 0
    preview_url: str | None = None
    download_url: str = ""

    # licença
    license_id: str
    license_url: str | None = None
    attribution_required: bool = False
    credit_string: str | None = None

    # arquivo
    date_original: str | None = None
    is_archival: bool = False

    # rastreabilidade
    source_page: str | None = None

    @property
    def orientation(self) -> Orientation:
        return Orientation.from_size(self.width, self.height)


class Match(BaseModel):
    """Ligação entre um bloco e um asset, com o porquê da escolha."""

    block_number: int
    asset: Asset
    score: float
    rank: int = 1
    reasons: list[str] = Field(default_factory=list)
