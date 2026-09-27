"""Internet Archive — acervo histórico e de domínio público.

É o provedor mais importante para canais de guerra, armas, militar e época, e o
mais diferente de todos: os itens são filmes longos, não clipes. Por isso
`needs_subclip=True` — a fase 5 quebra cada item em sub-clipes por detecção de
cena e indexa cada cena como asset autônomo.
"""

from __future__ import annotations

from ..core.models import ContentKind, Intent, MediaType, VisualBrief
from ..core.provider import BaseProvider, Capabilities
from ..core.registry import register


@register
class InternetArchiveProvider(BaseProvider):
    name = "internet_archive"

    capabilities = Capabilities(
        media_types={MediaType.VIDEO},
        content_kind={ContentKind.ARCHIVAL, ContentKind.EDITORIAL},
        supports_orientation_filter=False,
        supports_date_filter=True,
        supports_duration_filter=False,
        license_default="public-domain",
        license_url="https://archive.org/about/terms",
        attribution_required=False,
        max_requests_per_hour=None,
        cache_ttl_hours=168,
        needs_subclip=True,   # filmes de 20+ minutos precisam de corte por cena
        cost_per_asset=0.0,
        requires_api_key=False,
        api_key_env=None,
        docs_url="https://archive.org/developers/metadata.html",
        notes=(
            "Licença varia por item: conferir sempre antes de usar. "
            "Coleções úteis: usgovfilms, Fedflix, wwii-nat-archives-videos, prelinger."
        ),
    )

    def accepts(self, brief: VisualBrief) -> bool:
        # Só vale a pena quando o bloco pede material histórico.
        if brief.intent is Intent.ARQUIVO or brief.era is not None:
            return MediaType.VIDEO in brief.media_preference
        return False
