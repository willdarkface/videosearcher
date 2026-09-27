"""Pexels — vídeo e foto de b-roll moderno.

Vantagem relevante para este projeto: a API de vídeo aceita `min_duration`, o
que permite filtrar no servidor os clipes que cobrem o bloco, em vez de baixar
candidato para descartar depois.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

from ..core.http import baixar, get_json
from ..core.models import Asset, ContentKind, Intent, MediaType, Orientation, VisualBrief
from ..core.provider import BaseProvider, Capabilities
from ..core.registry import register

BASE = "https://api.pexels.com"


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
            "Limite removível de graça mediante aprovação e atribuição. "
            "Sem acervo histórico: bloco de arquivo é recusado aqui."
        ),
    )

    def accepts(self, brief: VisualBrief) -> bool:
        if brief.intent is Intent.ARQUIVO or brief.era is not None:
            return False
        return super().accepts(brief)

    # ------------------------------------------------------------------ busca

    def _headers(self) -> dict[str, str]:
        return {"Authorization": os.getenv("PEXELS_API_KEY", "")}

    def search(
        self,
        brief: VisualBrief,
        limit: int = 15,
        *,
        duracao_minima: float | None = None,
        queries: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        termos = queries or brief.queries.primary[:1] or brief.queries.secondary[:1]
        saida: list[dict[str, Any]] = []

        for tipo in brief.media_preference:
            for termo in termos:
                if tipo is MediaType.VIDEO:
                    params: dict[str, Any] = {
                        "query": termo,
                        "per_page": limit,
                        "orientation": "landscape",
                    }
                    if duracao_minima:
                        params["min_duration"] = math.ceil(duracao_minima)
                    dados = get_json(
                        f"{BASE}/videos/search", params=params, headers=self._headers()
                    )
                    for item in dados.get("videos", []):
                        item["_media_type"] = "video"
                        item["_query"] = termo
                        saida.append(item)
                else:
                    dados = get_json(
                        f"{BASE}/v1/search",
                        params={"query": termo, "per_page": limit, "orientation": "landscape"},
                        headers=self._headers(),
                    )
                    for item in dados.get("photos", []):
                        item["_media_type"] = "photo"
                        item["_query"] = termo
                        saida.append(item)
        return saida

    # ------------------------------------------------------------ normalização

    def normalize(self, raw: dict[str, Any]) -> Asset:
        if raw.get("_media_type") == "video":
            arquivo = _melhor_arquivo_video(raw.get("video_files", []))
            width = int(arquivo.get("width") or raw.get("width") or 0)
            height = int(arquivo.get("height") or raw.get("height") or 0)
            return Asset(
                uid=self.uid(raw["id"]),
                provider=self.name,
                media_type=MediaType.VIDEO,
                title=(raw.get("user") or {}).get("name"),
                description=raw.get("url"),
                tags=[raw.get("_query", "")],
                duration_s=float(raw.get("duration") or 0) or None,
                fps=None,
                width=width,
                height=height,
                preview_url=raw.get("image"),
                download_url=arquivo.get("link", ""),
                license_id="pexels",
                license_url="https://www.pexels.com/license/",
                attribution_required=False,
                credit_string=f"Vídeo de {(raw.get('user') or {}).get('name', 'Pexels')} (Pexels)",
                is_archival=False,
                source_page=raw.get("url"),
            )

        src = raw.get("src") or {}
        return Asset(
            uid=self.uid(raw["id"]),
            provider=self.name,
            media_type=MediaType.PHOTO,
            title=raw.get("alt") or raw.get("photographer"),
            description=raw.get("url"),
            tags=[raw.get("_query", "")],
            width=int(raw.get("width") or 0),
            height=int(raw.get("height") or 0),
            preview_url=src.get("medium"),
            download_url=src.get("original") or src.get("large2x") or "",
            license_id="pexels",
            license_url="https://www.pexels.com/license/",
            attribution_required=False,
            credit_string=f"Foto de {raw.get('photographer', 'Pexels')} (Pexels)",
            is_archival=False,
            source_page=raw.get("url"),
        )

    # -------------------------------------------------------------- download

    def download(self, asset: Asset, dest: Path) -> Path:
        return baixar(asset.download_url, dest, max_bytes=400_000_000)


def _melhor_arquivo_video(arquivos: list[dict[str, Any]]) -> dict[str, Any]:
    """Prefere o maior arquivo até 1920 de largura: 4K aqui só pesa download."""
    validos = [a for a in arquivos if a.get("link")]
    if not validos:
        return {}
    ate_full_hd = [a for a in validos if (a.get("width") or 0) <= 1920]
    pool = ate_full_hd or validos
    return max(pool, key=lambda a: (a.get("width") or 0, a.get("height") or 0))


def orientacao(width: int, height: int) -> Orientation:  # pragma: no cover
    return Orientation.from_size(width, height)
