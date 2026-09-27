"""TEMPLATE — copie este arquivo para adicionar um provedor de mídia.

Passos:
  1. `cp _template.py meuprovedor.py`
  2. Troque `name`, preencha `capabilities` e escreva `accepts()`.
  3. Implemente `search()`, `normalize()` e `download()`.
  4. Descomente o `@register`. Pronto — ele aparece em `videosearcher providers`.

Nada mais no sistema precisa mudar: o roteador descobre o provedor sozinho e usa
`accepts()` para decidir quais briefs mandar para ele.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.models import Asset, ContentKind, MediaType, VisualBrief
from ..core.provider import BaseProvider, Capabilities

# from ..core.registry import register


# @register
class TemplateProvider(BaseProvider):
    name = "template"

    capabilities = Capabilities(
        media_types={MediaType.VIDEO, MediaType.PHOTO},
        content_kind={ContentKind.BROLL},
        supports_orientation_filter=False,
        supports_date_filter=False,
        supports_duration_filter=False,
        license_default="unknown",
        attribution_required=False,
        max_requests_per_hour=None,
        cache_ttl_hours=24,
        needs_subclip=False,
        cost_per_asset=0.0,
        requires_api_key=True,
        api_key_env="TEMPLATE_API_KEY",
        docs_url="https://exemplo.com/docs",
        notes="Descreva aqui a pegadinha do provedor (licença, cota, formato).",
    )

    def accepts(self, brief: VisualBrief) -> bool:
        """Decida aqui se vale gastar cota com este brief."""
        return super().accepts(brief)

    def search(self, brief: VisualBrief, limit: int = 20) -> list[dict[str, Any]]:
        raise NotImplementedError

    def normalize(self, raw: dict[str, Any]) -> Asset:
        raise NotImplementedError

    def download(self, asset: Asset, dest: Path) -> Path:
        raise NotImplementedError
