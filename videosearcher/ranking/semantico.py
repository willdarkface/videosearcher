"""Re-ranqueamento semântico: mede se a imagem tem a ver com o bloco.

Resolve o defeito que ficou provado com dado real: o ranqueamento por
palavra-chave entregou um **céu estrelado** para o bloco "The British Army
already had a fast gun", e um filme sobre o motim do Bounty para um bloco sobre
Waterloo. As regras duras conferem duração, resolução, licença e aspecto — mas
nenhuma delas sabe *do que a imagem é*.

Aqui a pergunta é outra: o que este quadro mostra combina com o que o bloco
narra? A resposta vem de comparar o embedding da miniatura com o embedding do
texto do briefing, no mesmo espaço vetorial.

O modelo é opcional de propósito. `fastembed` pesa ~0,9 GB entre os dois
encoders, e quem só quer rodar o pipeline com busca por palavra-chave não
deveria ser obrigado a baixar isso. Sem a dependência, o re-rank se desliga e
avisa, em vez de quebrar.
"""

from __future__ import annotations

import hashlib
import logging
import math
from pathlib import Path

from ..core.http import baixar
from ..core.models import Asset, VisualBrief

log = logging.getLogger(__name__)

MODELO_PADRAO = "jinaai/jina-clip-v1"
CACHE_PREVIEWS = Path(".cache/previews")

# Calibrado com medição real (ver docs): material relevante ficou entre 0,16 e
# 0,28; irrelevante entre 0,01 e 0,02; contraditório ficou negativo. 0,08 corta
# o lixo sem descartar acerto fraco.
SIMILARIDADE_MINIMA_PADRAO = 0.08


class SemanticoIndisponivel(RuntimeError):
    """Levantado quando `fastembed` não está instalado."""


class ReRankSemantico:
    """Pontua candidatos por similaridade entre miniatura e texto do briefing.

    Carrega os encoders uma vez. Instanciar por bloco seria o erro que
    transforma um pipeline de minutos em um de horas.
    """

    def __init__(
        self,
        modelo: str = MODELO_PADRAO,
        *,
        cache_dir: Path | None = None,
    ) -> None:
        self.modelo = modelo
        self.cache_dir = cache_dir or CACHE_PREVIEWS
        self._imagem = None
        self._texto = None
        self._cache_vetor: dict[str, list[float]] = {}
        self.previews_baixadas = 0
        self.previews_falhas = 0

    # ---- carregamento tardio ----

    @staticmethod
    def disponivel() -> bool:
        try:
            import fastembed  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def imagem(self):
        if self._imagem is None:
            try:
                from fastembed import ImageEmbedding
            except ImportError as exc:
                raise SemanticoIndisponivel(
                    "re-rank semântico exige `fastembed`. "
                    "Instale com: pip install 'videosearcher[semantico]'"
                ) from exc
            log.info("carregando encoder de imagem %s", self.modelo)
            self._imagem = ImageEmbedding(model_name=self.modelo)
        return self._imagem

    @property
    def texto(self):
        if self._texto is None:
            try:
                from fastembed import TextEmbedding
            except ImportError as exc:
                raise SemanticoIndisponivel(
                    "re-rank semântico exige `fastembed`."
                ) from exc
            log.info("carregando encoder de texto %s", self.modelo)
            self._texto = TextEmbedding(model_name=self.modelo)
        return self._texto

    # ---- miniaturas ----

    def _caminho_preview(self, asset: Asset) -> Path:
        chave = hashlib.sha256(asset.uid.encode()).hexdigest()[:24]
        return self.cache_dir / f"{chave}.jpg"

    def _garantir_preview(self, asset: Asset) -> Path | None:
        """Baixa a miniatura do candidato. É o que torna o re-rank viável antes
        do download: miniatura tem dezenas de KB, o vídeo tem dezenas de MB."""
        if not asset.preview_url:
            return None
        destino = self._caminho_preview(asset)
        if destino.exists() and destino.stat().st_size > 0:
            return destino
        try:
            baixar(asset.preview_url, destino, max_bytes=8_000_000)
        except Exception as exc:
            self.previews_falhas += 1
            log.debug("preview de %s falhou: %s", asset.uid, exc)
            return None
        else:
            self.previews_baixadas += 1
            return destino

    # ---- pontuação ----

    def texto_do_brief(self, brief: VisualBrief) -> str:
        """Monta a consulta que representa o bloco.

        Usa a query em inglês, não o texto narrado: a query já foi traduzida
        para vocabulário visual pelo briefing, e é isso que se compara com
        imagem. O texto narrado traz argumento e conectivo, que só adicionam
        ruído ao vetor.
        """
        partes = [*brief.queries.primary[:2], *brief.queries.secondary[:1]]
        if brief.entities:
            partes.append(" ".join(brief.entities[:3]))
        consulta = ". ".join(p for p in partes if p)
        return consulta or brief.text[:200]

    def pontuar(
        self, brief: VisualBrief, assets: list[Asset]
    ) -> dict[str, float]:
        """Devolve `{uid: similaridade}` no intervalo -1 a 1.

        Candidato sem miniatura fica de fora do dicionário. O chamador trata
        ausência como "não avaliado", e não como "reprovado": penalizar por
        falta de miniatura puniria o provedor, não o conteúdo.
        """
        if not assets:
            return {}

        pendentes: list[tuple[Asset, Path]] = []
        pontos: dict[str, float] = {}

        for asset in assets:
            if asset.uid in self._cache_vetor:
                continue
            caminho = self._garantir_preview(asset)
            if caminho is not None:
                pendentes.append((asset, caminho))

        if pendentes:
            caminhos = [str(c) for _, c in pendentes]
            try:
                vetores = list(self.imagem.embed(caminhos))
            except SemanticoIndisponivel:
                raise
            except Exception as exc:
                log.warning("embedding de imagens falhou: %s", exc)
                vetores = []
            for (asset, _), vetor in zip(pendentes, vetores, strict=False):
                self._cache_vetor[asset.uid] = list(vetor)

        consulta = self.texto_do_brief(brief)
        try:
            vetor_texto = list(next(iter(self.texto.embed([consulta]))))
        except SemanticoIndisponivel:
            raise
        except Exception as exc:
            log.warning("embedding do texto falhou: %s", exc)
            return {}

        for asset in assets:
            vetor = self._cache_vetor.get(asset.uid)
            if vetor is not None:
                pontos[asset.uid] = cosseno(vetor_texto, vetor)
        return pontos


def cosseno(a: list[float], b: list[float]) -> float:
    """Similaridade de cosseno sem numpy: a lista tem 768 posições e isso roda
    milhares de vezes, mas ainda é barato comparado a baixar uma miniatura."""
    if not a or not b or len(a) != len(b):
        return 0.0
    produto = sum(x * y for x, y in zip(a, b, strict=True))
    norma_a = math.sqrt(sum(x * x for x in a))
    norma_b = math.sqrt(sum(y * y for y in b))
    if norma_a == 0.0 or norma_b == 0.0:
        return 0.0
    return produto / (norma_a * norma_b)


def para_multiplicador(similaridade: float) -> float:
    """Converte similaridade em multiplicador de nota.

    Mapeia a faixa útil observada (0 a ~0,30) para 0,2 a 1,0. Não é linear a
    partir de zero porque similaridade 0,25 e 0,30 são praticamente empate na
    prática, enquanto 0,05 e 0,15 são diferença enorme.
    """
    limpa = max(0.0, min(0.35, similaridade))
    return 0.2 + 0.8 * (limpa / 0.35)
