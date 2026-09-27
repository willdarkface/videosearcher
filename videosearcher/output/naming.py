"""Nomeação dos arquivos entregues.

Regra: `NNN - tipo slug.ext`, com zero-padding calculado pelo total de blocos.
Sem o padding, o explorador de arquivos ordena 10 antes de 2 e a pasta vira
bagunça.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..core.models import Asset, MediaType

# Proibidos em Windows, macOS e Linux somados
_INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_ESPACOS = re.compile(r"\s+")

NOME_MIDIA = {MediaType.VIDEO: "video", MediaType.PHOTO: "imagem"}

EXTENSOES = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


def largura_numero(total_blocos: int) -> int:
    """100 blocos -> 3 dígitos. 40 blocos -> 2 dígitos."""
    return max(2, len(str(max(1, total_blocos))))


def higienizar(texto: str, *, max_chars: int = 60) -> str:
    limpo = _INVALIDOS.sub("", texto)
    limpo = _ESPACOS.sub(" ", limpo).strip(" .")
    if len(limpo) <= max_chars:
        return limpo or "sem-titulo"
    corte = limpo[:max_chars]
    if " " in corte:
        corte = corte[: corte.rfind(" ")]
    return corte.strip(" .") or "sem-titulo"


def extensao_de(asset: Asset, *, padrao: str | None = None) -> str:
    url = (asset.download_url or "").split("?")[0].lower()
    for ext in (".mp4", ".webm", ".m4v", ".ogv", ".mov", ".jpg", ".jpeg", ".png", ".webp"):
        if url.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    if padrao:
        return padrao
    return ".mp4" if asset.media_type is MediaType.VIDEO else ".jpg"


def nome_arquivo(
    numero: int,
    asset: Asset,
    slug: str,
    *,
    total_blocos: int,
    sufixo: str = "",
) -> str:
    """Monta `007b - imagem retrato piloto.jpg`."""
    largura = largura_numero(total_blocos)
    prefixo = f"{numero:0{largura}d}{sufixo}"
    tipo = NOME_MIDIA[asset.media_type]
    corpo = higienizar(slug.replace("-", " "))
    return f"{prefixo} - {tipo} {corpo}{extensao_de(asset)}"


def caminho_sem_colisao(pasta: Path, nome: str) -> Path:
    """Nunca sobrescreve: acrescenta (2), (3)... se o nome já existir."""
    destino = pasta / nome
    if not destino.exists():
        return destino
    base, ext = destino.stem, destino.suffix
    for n in range(2, 100):
        alternativo = pasta / f"{base} ({n}){ext}"
        if not alternativo.exists():
            return alternativo
    return pasta / f"{base} ({destino.stat().st_mtime_ns}){ext}"
