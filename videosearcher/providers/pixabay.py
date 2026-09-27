"""Pixabay — acervo grande de vídeo e foto.

Os termos da API exigem cache de 24h dos resultados; o cache de busca do
pipeline cumpre isso por construção.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..core.http import baixar, get_json
from ..core.models import Asset, ContentKind, Intent, MediaType, VisualBrief
from ..core.provider import BaseProvider, Capabilities
from ..core.registry import register

BASE = "https://pixabay.com/api"


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
        max_requests_per_hour=6_000,
        cache_ttl_hours=24,
        needs_subclip=False,
        cost_per_asset=0.0,
        requires_api_key=True,
        api_key_env="PIXABAY_API_KEY",
        docs_url="https://pixabay.com/api/docs/",
        notes="Os termos da API exigem cache de 24h dos resultados.",
    )

    def accepts(self, brief: VisualBrief) -> bool:
        if brief.intent is Intent.ARQUIVO or brief.era is not None:
            return False
        return super().accepts(brief)

    # ------------------------------------------------------------------ busca

    def search(
        self,
        brief: VisualBrief,
        limit: int = 15,
        *,
        duracao_minima: float | None = None,
        queries: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        chave = os.getenv("PIXABAY_API_KEY", "")
        termos = queries or brief.queries.primary[:1] or brief.queries.secondary[:1]
        saida: list[dict[str, Any]] = []
        cobriu = False

        for tipo in brief.media_preference:
            # Vídeo é sempre preferido a foto: se já há vídeo cobrindo o bloco,
            # a busca de foto é chamada desperdiçada.
            if tipo is MediaType.PHOTO and cobriu:
                break

            for termo in termos:
                comum = {"key": chave, "q": termo, "per_page": max(3, min(limit, 200))}
                if tipo is MediaType.VIDEO:
                    dados = get_json(f"{BASE}/videos/", params=comum)
                    for item in dados.get("hits", []):
                        item["_media_type"] = "video"
                        item["_query"] = termo
                        saida.append(item)
                        if duracao_minima and float(item.get("duration") or 0) >= duracao_minima:
                            cobriu = True
                else:
                    dados = get_json(
                        f"{BASE}/",
                        params={**comum, "image_type": "photo", "orientation": "horizontal"},
                    )
                    for item in dados.get("hits", []):
                        item["_media_type"] = "photo"
                        item["_query"] = termo
                        saida.append(item)
        return saida

    # ------------------------------------------------------------ normalização

    def normalize(self, raw: dict[str, Any]) -> Asset:
        autor = raw.get("user") or "Pixabay"
        if raw.get("_media_type") == "video":
            variantes = raw.get("videos") or {}
            escolhida = _melhor_variante(variantes)
            return Asset(
                uid=self.uid(raw["id"]),
                provider=self.name,
                media_type=MediaType.VIDEO,
                title=(raw.get("tags") or "").strip() or None,
                description=raw.get("pageURL"),
                tags=[t.strip() for t in (raw.get("tags") or "").split(",") if t.strip()],
                duration_s=float(raw.get("duration") or 0) or None,
                width=int(escolhida.get("width") or 0),
                height=int(escolhida.get("height") or 0),
                preview_url=escolhida.get("thumbnail"),
                download_url=escolhida.get("url", ""),
                license_id="pixabay-content-license",
                license_url="https://pixabay.com/service/license-summary/",
                attribution_required=False,
                credit_string=f"Vídeo de {autor} (Pixabay)",
                is_archival=False,
                source_page=raw.get("pageURL"),
            )

        return Asset(
            uid=self.uid(raw["id"]),
            provider=self.name,
            media_type=MediaType.PHOTO,
            title=(raw.get("tags") or "").strip() or None,
            description=raw.get("pageURL"),
            tags=[t.strip() for t in (raw.get("tags") or "").split(",") if t.strip()],
            width=int(raw.get("imageWidth") or 0),
            height=int(raw.get("imageHeight") or 0),
            preview_url=raw.get("webformatURL"),
            download_url=raw.get("largeImageURL") or raw.get("webformatURL") or "",
            license_id="pixabay-content-license",
            license_url="https://pixabay.com/service/license-summary/",
            attribution_required=False,
            credit_string=f"Foto de {autor} (Pixabay)",
            is_archival=False,
            source_page=raw.get("pageURL"),
        )

    def download(self, asset: Asset, dest: Path) -> Path:
        return baixar(asset.download_url, dest, max_bytes=400_000_000)


def _melhor_variante(variantes: dict[str, Any]) -> dict[str, Any]:
    """Prefere large, depois medium: 4K do Pixabay só encarece o download."""
    for nome in ("large", "medium", "small", "tiny"):
        item = variantes.get(nome)
        if isinstance(item, dict) and item.get("url"):
            return item
    return {}
