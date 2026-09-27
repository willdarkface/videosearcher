"""Contrato dos provedores de mídia — o núcleo plug-and-play.

Adicionar um banco de vídeo novo (Storyblocks, Internet Archive, geração por IA,
qualquer coisa) significa criar UM arquivo em `videosearcher/providers/` que
implemente esta interface e use o decorator `@register`. Nada mais no sistema
muda.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from .models import Asset, ContentKind, MediaType, VisualBrief


class Capabilities(BaseModel):
    """Declaração do que um provedor sabe e pode fazer.

    O roteador usa isso para decidir quem recebe cada brief, e o ranqueamento
    usa para aplicar regras de licença, resolução e deduplicação.
    """

    media_types: set[MediaType]
    content_kind: set[ContentKind]

    supports_orientation_filter: bool = False
    supports_date_filter: bool = False
    supports_duration_filter: bool = False

    license_default: str = "unknown"
    license_url: str | None = None
    attribution_required: bool = False

    # cota
    max_requests_per_hour: int | None = None
    max_requests_per_month: int | None = None
    cache_ttl_hours: int = 24  # Pixabay exige 24h por termo de uso

    # aquisição
    needs_subclip: bool = False  # itens longos (arquivo) precisam de corte por cena
    cost_per_asset: float = 0.0  # USD

    # operacional
    requires_api_key: bool = True
    api_key_env: str | None = None
    docs_url: str | None = None
    notes: str = ""


@runtime_checkable
class Provider(Protocol):
    """Interface que todo provedor de mídia implementa."""

    name: str
    capabilities: Capabilities

    def accepts(self, brief: VisualBrief) -> bool:
        """O provedor é adequado para este brief?

        É aqui que o roteamento acontece. Exemplo: o Pexels devolve False para
        um bloco de intenção `arquivo`, então nenhuma cota é gasta com ele.
        """
        ...

    def search(
        self,
        brief: VisualBrief,
        limit: int = 20,
        *,
        duracao_minima: float | None = None,
        queries: list[str] | None = None,
        tipos: list[MediaType] | None = None,
    ) -> list[dict[str, Any]]:
        """Busca no provedor e devolve as respostas cruas, sem normalizar.

        `tipos` sobrescreve a preferência de mídia do brief. O pipeline usa isso
        para o alvo de proporção vídeo/imagem: não faz sentido gastar cota
        buscando vídeo num bloco que já foi destinado a receber imagem.
        """
        ...

    def normalize(self, raw: dict[str, Any]) -> Asset:
        """Converte a resposta crua no schema Asset comum."""
        ...

    def download(self, asset: Asset, dest: Path) -> Path:
        """Baixa o asset para `dest` e devolve o caminho final."""
        ...


class BaseProvider:
    """Base opcional com comportamento comum.

    Herdar daqui é conveniente, mas não obrigatório: o que vale é satisfazer o
    Protocol acima.
    """

    name: str = "base"
    capabilities: Capabilities

    def accepts(self, brief: VisualBrief) -> bool:  # pragma: no cover - trivial
        media_ok = any(m in self.capabilities.media_types for m in brief.media_preference)
        if not media_ok:
            return False
        if brief.wants_archival:
            return ContentKind.ARCHIVAL in self.capabilities.content_kind
        return True

    def search(self, brief: VisualBrief, limit: int = 20) -> list[dict[str, Any]]:
        raise NotImplementedError(
            f"{self.name}.search() será implementado na fase de integração deste provedor"
        )

    def normalize(self, raw: dict[str, Any]) -> Asset:
        raise NotImplementedError(f"{self.name}.normalize() ainda não implementado")

    def download(self, asset: Asset, dest: Path) -> Path:
        raise NotImplementedError(f"{self.name}.download() ainda não implementado")

    # ---- utilidades ----

    def uid(self, provider_id: str | int) -> str:
        return f"{self.name}:{provider_id}"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Provider {self.name}>"


class ProviderStatus(BaseModel):
    """Estado de um provedor para exibição no CLI."""

    name: str
    implemented: bool
    api_key_present: bool
    capabilities: Capabilities
    missing: list[str] = Field(default_factory=list)
