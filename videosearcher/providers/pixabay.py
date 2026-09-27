"""Pixabay — acervo grande de vídeo e foto.

Atenção de licença: os termos da API exigem cache de 24h dos resultados. O
catálogo local do projeto já cumpre isso por construção.
"""

from __future__ import annotations

from ..core.models import ContentKind, Intent, MediaType, VisualBrief
from ..core.provider import BaseProvider, Capabilities
from ..core.registry import register


@register
class PixabayProvider(BaseProvider):
    name = "pixabay"

    capabilities = Capabilities(
        media_types={MediaType.VIDEO, MediaType.PHOTO},
        content_kind={ContentKind.BROLL},
        supports_orientation_filter=True,
        supports_date_filter=False,
        supports_duration_filter=False,
        license_default="pixabay-content-license",
        license_url="https://pixabay.com/service/license-summary/",
        attribution_required=False,
        max_requests_per_hour=6_000,  # ~100 req/60s
        cache_ttl_hours=24,           # exigência contratual
        needs_subclip=False,
        cost_per_asset=0.0,
        requires_api_key=True,
        api_key_env="PIXABAY_API_KEY",
        docs_url="https://pixabay.com/api/docs/",
        notes="Os termos da API exigem cache de 24h dos resultados — o catálogo local cobre isso.",
    )

    def accepts(self, brief: VisualBrief) -> bool:
        if brief.intent is Intent.ARQUIVO or brief.era is not None:
            return False
        return super().accepts(brief)
