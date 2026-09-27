"""Orquestração: legenda → blocos → briefs → busca → ranqueamento → entrega."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .core.cache import RespostaCache
from .core.config import ChannelConfig
from .core.http import HttpError, RateLimited
from .core.models import Asset, Block, VisualBrief
from .core.provider import Provider
from .core.registry import providers_for
from .llm.chain import LLMChain
from .ranking.rules import Selecao, Veredito, selecionar
from .script.blocker import build_blocks
from .script.briefing import BriefingEngine, ResultadoBriefing
from .script.parser import parse_subtitles


@dataclass
class ResultadoBloco:
    block: Block
    brief: VisualBrief
    selecao: Selecao
    provedores_consultados: list[str] = field(default_factory=list)
    candidatos: int = 0
    erros: list[str] = field(default_factory=list)
    arquivo: Path | None = None
    alternativas_baixadas: list[Path] = field(default_factory=list)

    @property
    def escolhido(self) -> tuple[Asset, Veredito] | None:
        return self.selecao.escolhido

    @property
    def encontrou(self) -> bool:
        return self.selecao.escolhido is not None


@dataclass
class ResultadoPipeline:
    canal: ChannelConfig
    legenda: Path
    blocos: list[Block] = field(default_factory=list)
    briefing: ResultadoBriefing | None = None
    resultados: list[ResultadoBloco] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    cache_busca: str = ""

    @property
    def com_resultado(self) -> list[ResultadoBloco]:
        return [r for r in self.resultados if r.encontrou]

    @property
    def sem_resultado(self) -> list[ResultadoBloco]:
        return [r for r in self.resultados if not r.encontrou]


class Pipeline:
    def __init__(
        self,
        canal: ChannelConfig,
        *,
        cache_llm: RespostaCache | None = None,
        cache_busca: RespostaCache | None = None,
    ) -> None:
        self.canal = canal
        self.cache_llm = cache_llm or RespostaCache()
        self.cache_busca = cache_busca or RespostaCache(Path(".cache/busca"))

    # ------------------------------------------------------------------ etapas

    def executar(
        self,
        legenda: Path,
        *,
        limite_blocos: int = 0,
        tema: str | None = None,
        candidatos_por_provedor: int = 12,
        progresso: Callable[[str, int, int], None] | None = None,
    ) -> ResultadoPipeline:
        cues = parse_subtitles(legenda)
        blocos = build_blocks(cues, self.canal.entrega)
        if limite_blocos > 0:
            blocos = blocos[:limite_blocos]

        resultado = ResultadoPipeline(canal=self.canal, legenda=legenda, blocos=blocos)

        chain = LLMChain(self.canal.llm)
        engine = BriefingEngine(self.canal, chain, self.cache_llm)

        def avanco_brief(feito: int, total: int) -> None:
            if progresso:
                progresso("briefing", feito, total)

        resultado.briefing = engine.processar(blocos, tema=tema, progresso=avanco_brief)
        briefs = resultado.briefing.por_numero

        for i, bloco in enumerate(blocos):
            brief = briefs.get(bloco.number)
            if brief is None:  # pragma: no cover - processar() garante
                continue
            resultado.resultados.append(
                self._buscar_bloco(bloco, brief, candidatos_por_provedor)
            )
            if progresso:
                progresso("busca", i + 1, len(blocos))

        resultado.cache_busca = self.cache_busca.resumo
        return resultado

    def _buscar_bloco(
        self, bloco: Block, brief: VisualBrief, limite: int
    ) -> ResultadoBloco:
        prioridade = self.canal.provedores.prioridade or None
        provedores = providers_for(brief, allowed=prioridade)

        candidatos: list[Asset] = []
        consultados: list[str] = []
        erros: list[str] = []

        for provedor in provedores:
            consultados.append(provedor.name)
            try:
                crus = self._buscar_com_cache(provedor, brief, bloco, limite)
            except RateLimited:
                erros.append(f"{provedor.name}: cota estourada (429), degradando")
                continue
            except HttpError as exc:
                erros.append(f"{provedor.name}: {exc}")
                continue
            except Exception as exc:  # provedor quebrado não derruba o pipeline
                erros.append(f"{provedor.name}: erro inesperado ({exc})")
                continue

            for cru in crus:
                try:
                    candidatos.append(provedor.normalize(cru))
                except Exception as exc:
                    erros.append(f"{provedor.name}: normalização falhou ({exc})")

        relevancia = {
            a.uid: self.canal.provedores.peso(a.provider) for a in candidatos
        }
        selecao = selecionar(
            bloco,
            candidatos,
            self.canal.midia,
            self.canal.entrega.resolucao_minima,
            relevancia=relevancia,
            brief=brief,
        )

        return ResultadoBloco(
            block=bloco,
            brief=brief,
            selecao=selecao,
            provedores_consultados=consultados,
            candidatos=len(candidatos),
            erros=erros,
        )

    def _buscar_com_cache(
        self, provedor: Provider, brief: VisualBrief, bloco: Block, limite: int
    ) -> list[dict]:
        termos = brief.queries.primary[:1] or brief.queries.secondary[:1]
        chave = RespostaCache.chave(
            provedor.name,
            "|".join(termos),
            "|".join(m.value for m in brief.media_preference),
            f"{bloco.duration_s:.1f}",
            str(limite),
        )
        guardado = self.cache_busca.obter(chave)
        if guardado is not None:
            return guardado

        crus = provedor.search(  # type: ignore[call-arg]
            brief, limite, duracao_minima=bloco.duration_s, queries=termos
        )
        self.cache_busca.gravar(chave, crus, {"provider": provedor.name})
        return crus
