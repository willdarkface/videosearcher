"""Orquestração: legenda → blocos → briefs → busca → ranqueamento → entrega."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .core.cache import RespostaCache
from .core.config import ChannelConfig
from .core.http import HttpError, RateLimited
from .core.models import Asset, Block, MediaType, VisualBrief
from .core.provider import Provider
from .core.quota import QuotaTracker
from .core.registry import all_providers, providers_for
from .llm.chain import LLMChain
from .ranking.mistura import ResultadoMistura, aplicar_proporcao
from .ranking.rules import Selecao, Veredito, selecionar
from .script.blocker import build_blocks
from .script.briefing import BriefingEngine, ResultadoBriefing
from .script.parser import parse_subtitles

log = logging.getLogger(__name__)


@dataclass
class ResultadoBloco:
    block: Block
    brief: VisualBrief
    selecao: Selecao
    provedores_consultados: list[str] = field(default_factory=list)
    candidatos: int = 0
    erros: list[str] = field(default_factory=list)
    rodadas: list[str] = field(default_factory=list)
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
    mistura: ResultadoMistura | None = None
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
        quota: QuotaTracker | None = None,
    ) -> None:
        self.canal = canal
        self.cache_llm = cache_llm or RespostaCache()
        self.cache_busca = cache_busca or RespostaCache(Path(".cache/busca"))
        self.quota = quota or QuotaTracker()
        # Provedores que já devolveram 429 nesta execução. Insistir só gasta
        # tempo e piora o bloqueio.
        self.esgotados: set[str] = set()
        # Carregado sob demanda: o modelo pesa ~0,9 GB e nem toda execução usa.
        self._rerank = None
        self._rerank_indisponivel = False
        self._configurar_quota()

    def _configurar_quota(self) -> None:
        for nome, provedor in all_providers().items():
            caps = provedor.capabilities
            if caps.max_requests_per_hour:
                self.quota.configure(nome, per_hour=caps.max_requests_per_hour)

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

        candidatos_a_video = self._pre_alocar_video(blocos, briefs)

        for i, bloco in enumerate(blocos):
            brief = briefs.get(bloco.number)
            if brief is None:  # pragma: no cover - processar() garante
                continue
            resultado.resultados.append(
                self._buscar_bloco(
                    bloco,
                    brief,
                    candidatos_por_provedor,
                    disputa_video=bloco.number in candidatos_a_video,
                )
            )
            if progresso:
                progresso("busca", i + 1, len(blocos))

        # A proporção vídeo/imagem é decisão global, então só pode ser aplicada
        # depois que todos os blocos souberam o que existe para eles.
        resultado.mistura = aplicar_proporcao(resultado.resultados, self.canal.midia)
        resultado.avisos.extend(resultado.mistura.avisos)

        resultado.cache_busca = self.cache_busca.resumo
        return resultado

    def _pre_alocar_video(
        self, blocos: list[Block], briefs: dict[int, VisualBrief]
    ) -> set[int]:
        """Escolhe, antes de buscar, quais blocos disputam o orçamento de vídeo.

        Sem isso, o alvo de proporção exigiria buscar vídeo E foto em todos os
        blocos — 228 chamadas num roteiro de 114 blocos, e o limite do Pexels é
        200 por hora. Como a prioridade para vídeo depende só do brief (motion e
        media_preference), ela pode ser calculada de graça, antes de gastar cota.

        A margem é deliberada: pede-se o dobro do alvo, porque parte dos blocos
        não vai achar vídeo dentro da janela de duração.
        """
        proporcao = self.canal.midia.proporcao_video
        if proporcao is None:
            return {b.number for b in blocos}  # alvo desligado: busca tudo

        alvo = round(len(blocos) * min(1.0, max(0.0, proporcao)))
        if alvo <= 0:
            return set()

        pesos = self.canal.midia.peso_motion_video

        def prioridade(bloco: Block) -> float:
            brief = briefs.get(bloco.number)
            if brief is None:
                return 0.0
            nota = pesos.get(brief.motion.value, 1.0)
            if brief.media_preference == [MediaType.VIDEO]:
                nota *= 2.0
            elif brief.media_preference and brief.media_preference[0] is MediaType.VIDEO:
                nota *= 1.2
            return nota

        ordenados = sorted(blocos, key=prioridade, reverse=True)
        return {b.number for b in ordenados[: alvo * 2]}

    def _tipos_para_busca(
        self, brief: VisualBrief, *, disputa_video: bool, incluir_video: bool
    ) -> list[MediaType]:
        desejados = list(brief.media_preference) or [MediaType.PHOTO]
        if self.canal.midia.proporcao_video is None:
            return desejados
        if disputa_video or incluir_video:
            return desejados
        # Bloco fora da disputa por vídeo: buscar vídeo aqui é cota jogada fora.
        so_foto = [t for t in desejados if t is MediaType.PHOTO]
        return so_foto or desejados

    def _buscar_bloco(
        self,
        bloco: Block,
        brief: VisualBrief,
        limite: int,
        *,
        disputa_video: bool = True,
    ) -> ResultadoBloco:
        prioridade = self.canal.provedores.prioridade or None
        provedores = providers_for(brief, allowed=prioridade)

        candidatos: list[Asset] = []
        consultados: list[str] = []
        erros: list[str] = []
        rodadas_usadas: list[str] = []

        # Rodadas de busca, da mais direta para a mais exploratória. Só avança
        # quando a rodada anterior não produziu nada aprovável: query extra custa
        # cota, e a maioria dos blocos resolve na primeira.
        # A última rodada libera vídeo mesmo em bloco destinado a imagem — é
        # melhor furar a proporção que devolver bloco vazio.
        for nome_rodada, termos in self._rodadas(brief):
            if not termos:
                continue
            rodadas_usadas.append(nome_rodada)
            tipos = self._tipos_para_busca(
                brief,
                disputa_video=disputa_video,
                incluir_video=nome_rodada == "resgate",
            )

            for provedor in provedores:
                if provedor.name in self.esgotados:
                    continue
                if provedor.name not in consultados:
                    consultados.append(provedor.name)
                try:
                    crus = self._buscar_com_cache(
                        provedor, brief, bloco, limite, termos, tipos
                    )
                except RateLimited:
                    self.esgotados.add(provedor.name)
                    erros.append(
                        f"{provedor.name}: cota estourada (429) — provedor "
                        f"desativado pelo resto da execução"
                    )
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

            selecao = self._ranquear(bloco, brief, candidatos)
            if selecao.aprovados:
                return ResultadoBloco(
                    block=bloco,
                    brief=brief,
                    selecao=selecao,
                    provedores_consultados=consultados,
                    candidatos=len(candidatos),
                    erros=erros,
                    rodadas=rodadas_usadas,
                )

        return ResultadoBloco(
            block=bloco,
            brief=brief,
            selecao=self._ranquear(bloco, brief, candidatos),
            provedores_consultados=consultados,
            candidatos=len(candidatos),
            erros=erros,
            rodadas=rodadas_usadas,
        )

    @staticmethod
    def _rodadas(brief: VisualBrief) -> list[tuple[str, list[str]]]:
        return [
            ("primary", brief.queries.primary[:1]),
            ("secondary", brief.queries.secondary[:2]),
            ("archival", brief.queries.archival[:1]),
            ("primary-extra", brief.queries.primary[1:3]),
            ("resgate", brief.queries.primary[:1] + brief.queries.secondary[:1]),
        ]

    def _ranquear(
        self, bloco: Block, brief: VisualBrief, candidatos: list[Asset]
    ) -> Selecao:
        unicos: dict[str, Asset] = {}
        for asset in candidatos:
            unicos.setdefault(asset.uid, asset)
        lista = list(unicos.values())
        relevancia = {a.uid: self.canal.provedores.peso(a.provider) for a in lista}
        return selecionar(
            bloco,
            lista,
            self.canal.midia,
            self.canal.entrega.resolucao_minima,
            relevancia=relevancia,
            similaridades=self._similaridades(brief, lista),
            brief=brief,
            politica=self.canal.politica,
        )

    def _similaridades(
        self, brief: VisualBrief, assets: list[Asset]
    ) -> dict[str, float]:
        """Mede a similaridade visual dos candidatos, se o re-rank estiver ativo.

        Falha aqui nunca derruba o bloco: sem medida, o ranqueamento volta a
        decidir só pelas regras duras, que é o comportamento anterior.
        """
        if not self.canal.midia.usar_rerank_semantico or not assets:
            return {}

        rerank = self._obter_rerank()
        if rerank is None:
            return {}
        try:
            return rerank.pontuar(brief, assets)
        except Exception as exc:
            log.warning("re-rank semântico falhou no bloco, seguindo sem: %s", exc)
            return {}

    def _obter_rerank(self):
        if self._rerank is not None:
            return self._rerank
        if self._rerank_indisponivel:
            return None

        from .ranking.semantico import ReRankSemantico

        if not ReRankSemantico.disponivel():
            self._rerank_indisponivel = True
            log.warning(
                "re-rank semântico desligado: `fastembed` não instalado. "
                "Instale com: pip install 'videosearcher[semantico]'"
            )
            return None
        self._rerank = ReRankSemantico(self.canal.midia.modelo_semantico)
        return self._rerank

    def _buscar_com_cache(
        self,
        provedor: Provider,
        brief: VisualBrief,
        bloco: Block,
        limite: int,
        termos: list[str],
        tipos: list[MediaType],
    ) -> list[dict]:
        chave = RespostaCache.chave(
            provedor.name,
            "|".join(termos),
            "|".join(m.value for m in tipos),
            f"{bloco.duration_s:.1f}",
            str(limite),
        )
        guardado = self.cache_busca.obter(chave)
        if guardado is not None:
            return guardado

        # Checa a cota ANTES de gastar a requisição: o contador é persistido em
        # disco, então o limite por hora sobrevive a reinício do processo.
        if not self.quota.allow(provedor.name):
            espera = self.quota.retry_after(provedor.name)
            raise RateLimited(
                f"cota local de {provedor.name} esgotada, liberando em {espera / 60:.0f} min"
            )

        crus = provedor.search(  # type: ignore[call-arg]
            brief, limite, duracao_minima=bloco.duration_s, queries=termos, tipos=tipos
        )
        self.quota.record(provedor.name)
        self.cache_busca.gravar(chave, crus, {"provider": provedor.name})
        return crus
