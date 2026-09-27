"""Internet Archive — acervo histórico e de domínio público.

Não exige chave de API, então é o único provedor que funciona de imediato.

É também o mais diferente de todos: os itens são filmes longos, não clipes. Por
isso `needs_subclip=True`. Nesta fase o item inteiro é catalogado como asset com
a duração real do arquivo — o que satisfaz a regra de cobertura trivialmente,
já que um filme de 20 minutos cobre qualquer bloco. A quebra por detecção de
cena entra na fase 5.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..core.http import baixar, get_json
from ..core.models import Asset, ContentKind, Intent, MediaType, VisualBrief
from ..core.provider import BaseProvider, Capabilities
from ..core.registry import register

BUSCA = "https://archive.org/advancedsearch.php"
METADATA = "https://archive.org/metadata"
DOWNLOAD = "https://archive.org/download"

# Formatos de vídeo utilizáveis, em ordem de preferência.
FORMATOS = (
    "h.264",
    "MPEG4",
    "HiRes MPEG4",
    "512Kb MPEG4",
    "MPEG2",
    "WebM",
    "Ogg Video",
)


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
        needs_subclip=True,
        cost_per_asset=0.0,
        requires_api_key=False,
        api_key_env=None,
        docs_url="https://archive.org/developers/metadata.html",
        notes=(
            "Sem chave de API. Licença varia por item: conferir antes de usar. "
            "Itens são filmes longos — a quebra por cena entra na fase 5."
        ),
    )

    def accepts(self, brief: VisualBrief) -> bool:
        # Só vale a pena quando o bloco pede material histórico.
        if brief.intent is Intent.ARQUIVO or brief.era is not None:
            return MediaType.VIDEO in brief.media_preference
        return False

    # ------------------------------------------------------------------ busca

    def search(
        self,
        brief: VisualBrief,
        limit: int = 8,
        *,
        duracao_minima: float | None = None,
        queries: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        termos_busca = queries or brief.queries.archival[:1] or brief.queries.primary[:1]
        palavras = _termos_de_titulo(brief, termos_busca)
        if not palavras:
            return []

        faixa = _faixa_de_anos(brief.era)
        consultas = _montar_consultas(palavras, faixa)

        saida: list[dict[str, Any]] = []
        rotulo = " OR ".join(palavras)

        for consulta in consultas:
            dados = get_json(
                BUSCA,
                params={
                    "q": consulta,
                    "fl[]": ["identifier", "title", "year", "date", "description"],
                    "rows": limit,
                    "page": 1,
                    "output": "json",
                },
            )
            docs = ((dados or {}).get("response") or {}).get("docs") or []
            if not docs:
                continue  # tenta a próxima estratégia, mais aberta

            # Cada doc custa uma chamada de metadata, então para assim que
            # houver candidatos suficientes.
            for doc in docs[:5]:
                arquivo = self._melhor_arquivo(doc.get("identifier", ""))
                if not arquivo:
                    continue
                saida.append({**doc, "_file": arquivo, "_query": rotulo})
                if len(saida) >= 3:
                    break
            if saida:
                break  # a primeira estratégia que devolve algo é a mais precisa
        return saida

    def _melhor_arquivo(self, identifier: str) -> dict[str, Any] | None:
        if not identifier:
            return None
        try:
            meta = get_json(f"{METADATA}/{identifier}")
        except Exception:
            return None

        arquivos = [f for f in (meta.get("files") or []) if isinstance(f, dict)]
        candidatos = [
            f for f in arquivos
            if f.get("format") in FORMATOS or str(f.get("name", "")).lower().endswith(
                (".mp4", ".ogv", ".webm", ".m4v")
            )
        ]
        if not candidatos:
            return None

        def nota(f: dict[str, Any]) -> tuple[int, int]:
            try:
                pref = FORMATOS.index(f.get("format", ""))
            except ValueError:
                pref = len(FORMATOS)
            return (pref, -int(f.get("size") or 0))

        escolhido = min(candidatos, key=nota)
        escolhido["_identifier"] = identifier
        return escolhido

    # ------------------------------------------------------------ normalização

    def normalize(self, raw: dict[str, Any]) -> Asset:
        arquivo = raw.get("_file") or {}
        identifier = raw.get("identifier", "")
        nome = arquivo.get("name", "")
        ano = str(raw.get("year") or "") or None

        return Asset(
            uid=self.uid(f"{identifier}/{nome}"),
            provider=self.name,
            media_type=MediaType.VIDEO,
            title=raw.get("title"),
            description=_texto(raw.get("description")),
            tags=[raw.get("_query", "")],
            duration_s=_segundos(arquivo.get("length")),
            fps=None,
            width=int(arquivo.get("width") or 0),
            height=int(arquivo.get("height") or 0),
            preview_url=f"https://archive.org/services/img/{identifier}",
            download_url=f"{DOWNLOAD}/{identifier}/{quote(nome)}",
            license_id="public-domain",
            license_url="https://archive.org/about/terms",
            attribution_required=False,
            credit_string=f"{raw.get('title') or identifier} (Internet Archive)",
            date_original=ano,
            is_archival=True,
            source_page=f"https://archive.org/details/{identifier}",
        )

    def download(self, asset: Asset, dest: Path) -> Path:
        # Filme de arquivo é grande; o corte por cena da fase 5 reduz isso.
        return baixar(asset.download_url, dest, max_bytes=2_000_000_000)


# ---------------------------------------------------------------------------


def _segundos(valor: Any) -> float | None:
    """`length` do IA vem como '1234.5' ou 'MM:SS' ou 'HH:MM:SS'."""
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    if ":" in texto:
        partes = texto.split(":")
        try:
            numeros = [float(p) for p in partes]
        except ValueError:
            return None
        total = 0.0
        for n in numeros:
            total = total * 60 + n
        return total or None
    try:
        return float(texto) or None
    except ValueError:
        return None


def _texto(valor: Any) -> str | None:
    if isinstance(valor, list):
        valor = " ".join(str(v) for v in valor)
    if isinstance(valor, str):
        limpo = " ".join(valor.split())
        return limpo[:400] or None
    return None


# O acervo de filmes do IA é cheio de captura de TV e espelho de YouTube.
# Excluir isso é a diferença entre newsreel de 1944 e reunião de câmara municipal.
_SEM_LIXO = "NOT collection:(tvarchive) AND NOT collection:(tvnews)"

# Coleções curadas, usadas quando não há era para filtrar por ano.
_CURADAS = (
    "usgovfilms",
    "prelinger",
    "FedFlix",
    "newsreels",
    "universal_newsreels",
    "nasa",
)

# Palavras de vocabulário de banco de imagem que não aparecem em título de
# acervo histórico — poluem a busca por título.
_GENERICAS = {
    "historical", "history", "close", "closeup", "up", "footage", "video",
    "clip", "old", "vintage", "antique", "detail", "shot", "view", "scene",
    "background", "concept", "illustration", "abstract", "modern", "style",
    "comparison", "vs", "versus", "and", "or", "the", "of", "in", "on", "with",
    "for", "to", "at", "a", "an", "from", "by", "being", "behind",
}

_LUCENE_ESPECIAIS = str.maketrans({c: " " for c in r'+-&|!(){}[]^"~*?:\/'})


def _termos_de_titulo(brief: VisualBrief, termos_busca: list[str]) -> list[str]:
    """Extrai palavras para casar contra o TÍTULO do item.

    Buscar a frase inteira no IA devolve zero: ele trata como AND de tudo, em
    todos os campos. Nome próprio é o que funciona, porque é o que o acervo
    histórico tem no título.
    """
    candidatos: list[str] = []

    # Entidades primeiro: são nomes próprios, exatamente o que o IA indexa bem.
    for entidade in brief.entities:
        for parte in entidade.translate(_LUCENE_ESPECIAIS).lower().split():
            if len(parte) > 3 and parte not in _GENERICAS and parte not in candidatos:
                candidatos.append(parte)

    for termo in termos_busca:
        for parte in termo.translate(_LUCENE_ESPECIAIS).lower().split():
            if len(parte) > 3 and parte not in _GENERICAS and parte not in candidatos:
                candidatos.append(parte)

    return candidatos[:4]


def _montar_consultas(palavras: list[str], faixa: tuple[int, int] | None) -> list[str]:
    """Estratégias da mais precisa para a mais aberta."""
    alvo = " OR ".join(palavras)
    consultas: list[str] = []

    if faixa:
        # Mais preciso que existe: título casa E o ano bate com a era do bloco.
        consultas.append(
            f"title:({alvo}) AND mediatype:(movies) AND {_SEM_LIXO} "
            f"AND year:[{faixa[0]} TO {faixa[1]}]"
        )
        consultas.append(
            f"({alvo}) AND mediatype:(movies) AND {_SEM_LIXO} "
            f"AND year:[{faixa[0]} TO {faixa[1]}]"
        )

    colecoes = " OR ".join(_CURADAS)
    consultas.append(
        f"title:({alvo}) AND mediatype:(movies) AND collection:({colecoes})"
    )
    consultas.append(
        f"({alvo}) AND mediatype:(movies) AND collection:({colecoes})"
    )
    return consultas


def _faixa_de_anos(era: str | None) -> tuple[int, int] | None:
    """Converte '1809-1809' em faixa para o filtro `year` do IA.

    Abre a janela em 15 anos de cada lado: newsreel e documentário sobre um
    evento costumam ser catalogados com o ano de produção, não o do fato.
    """
    if not era:
        return None
    numeros = [int(p) for p in era.replace("—", "-").split("-") if p.strip().isdigit()]
    if not numeros:
        return None
    inicio, fim = min(numeros), max(numeros)
    return (max(1800, inicio - 15), min(2030, fim + 15))
