"""Pexels — vídeo e foto de b-roll moderno.

Fase 0: capabilities e roteamento (`accepts`) completos.
Fase 3: `search`, `normalize` e `download`.
"""

from __future__ import annotations

from ..core.models import ContentKind, Intent, MediaType, VisualBrief
from ..core.provider import BaseProvider, Capabilities
from ..core.registry import register


@register
class PexelsProvider(BaseProvider):
    name = "pexels"

    capabilities = Capabilities(
        media_types={MediaType.VIDEO, MediaType.PHOTO},
        content_kind={ContentKind.BROLL},
        supports_orientation_filter=True,
        supports_date_filter=False,
        supports_duration_filter=True,
        license_default="pexels",
        license_url="https://www.pexels.com/license/",
        attribution_required=False,
        max_requests_per_hour=200,
        max_requests_per_month=20_000,
        cache_ttl_hours=24,
        needs_subclip=False,
        cost_per_asset=0.0,
        requires_api_key=True,
        api_key_env="PEXELS_API_KEY",
        docs_url="https://www.pexels.com/api/documentation/",
        notes=(
            "Limite removível de graça mediante aprovação do caso de uso e atribuição. "
            "Não tem acervo histórico: bloco de arquivo é recusado aqui."
        ),
    )

    def accepts(self, brief: VisualBrief) -> bool:
        # Acervo moderno: não faz sentido gastar cota com bloco histórico.
        if brief.intent is Intent.ARQUIVO or brief.era is not None:
            return False
        return super().accepts(brief)
