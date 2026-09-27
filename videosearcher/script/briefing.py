"""Motor de briefing: bloco → VisualBrief, via LLM.

Responsabilidades, nesta ordem de importância:
  1. Nunca deixar bloco sem brief. Se o modelo falha, reduz o lote; se ainda
     falha, monta brief de emergência a partir do texto e avisa. Pipeline de
     produção não pode parar porque um lote veio torto.
  2. Validar e reparar a saída. Modelo erra enum, esquece campo e perde número
     de bloco — tudo isso é corrigido aqui, com aviso rastreável.
  3. Economizar cota: cache por hash de prompt, lote configurável.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..core.cache import RespostaCache
from ..core.config import ChannelConfig
from ..core.models import (
    Block,
    BriefQueries,
    Intent,
    Look,
    MediaType,
    Motion,
    Sensitivity,
    VisualBrief,
)
from ..core.text import palavras_chave, slugify
from ..llm.base import LLMError
from ..llm.chain import LLMChain
from .prompt import (
    ESQUEMA_BRIEF,
    VERSAO_PROMPT,
    inferir_tema,
    montar_system_prompt,
    montar_user_prompt,
)


@dataclass
class ResultadoBriefing:
    briefs: list[VisualBrief] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    provedores_usados: dict[str, int] = field(default_factory=dict)
    lotes: int = 0
    emergencia: int = 0
    cache: str = ""

    @property
    def por_numero(self) -> dict[int, VisualBrief]:
        return {b.block_number: b for b in self.briefs}


class BriefingEngine:
    def __init__(
        self,
        channel: ChannelConfig,
        chain: LLMChain,
        cache: RespostaCache | None = None,
    ) -> None:
        self.channel = channel
        self.chain = chain
        self.cache = cache or RespostaCache()
        self.system_prompt = montar_system_prompt(channel)

    # ------------------------------------------------------------------ API

    def processar(
        self,
        blocks: list[Block],
        *,
        tema: str | None = None,
        progresso: Callable[[int, int], None] | None = None,
    ) -> ResultadoBriefing:
        resultado = ResultadoBriefing()
        if not blocks:
            return resultado

        tema = tema or inferir_tema(blocks)
        tamanho = max(1, self.channel.llm.batch_size)
        lotes = [blocks[i : i + tamanho] for i in range(0, len(blocks), tamanho)]
        resultado.lotes = len(lotes)

        por_numero = {b.number: b for b in blocks}
        indice = {b.number: i for i, b in enumerate(blocks)}

        for n, lote in enumerate(lotes):
            anterior = blocks[indice[lote[0].number] - 1] if indice[lote[0].number] > 0 else None
            fim = indice[lote[-1].number]
            seguinte = blocks[fim + 1] if fim + 1 < len(blocks) else None

            briefs = self._processar_lote(lote, tema, anterior, seguinte, resultado)
            resultado.briefs.extend(briefs)
            if progresso:
                progresso(n + 1, len(lotes))

        # Garante um brief por bloco, na ordem da legenda
        vistos = resultado.por_numero
        finais: list[VisualBrief] = []
        for block in blocks:
            brief = vistos.get(block.number)
            if brief is None:
                resultado.avisos.append(
                    f"bloco {block.number}: sem brief do modelo, usando brief de emergência"
                )
                brief = self.brief_emergencia(block)
                resultado.emergencia += 1
            finais.append(brief)
        resultado.briefs = finais
        resultado.cache = self.cache.resumo
        _ = por_numero  # mantido para clareza do fluxo
        return resultado

    # -------------------------------------------------------------- interno

    def _processar_lote(
        self,
        lote: list[Block],
        tema: str,
        anterior: Block | None,
        seguinte: Block | None,
        resultado: ResultadoBriefing,
    ) -> list[VisualBrief]:
        user_prompt = montar_user_prompt(
            lote, tema=tema, anterior=anterior, seguinte=seguinte
        )
        modelo_previsto = self.chain.links()[0].model if self.chain.links() else "?"
        chave = RespostaCache.chave(
            VERSAO_PROMPT, modelo_previsto, self.system_prompt, user_prompt
        )

        conteudo = self.cache.obter(chave)
        if conteudo is None:
            try:
                resposta = self.chain.complete(
                    system=self.system_prompt,
                    user=user_prompt,
                    json_schema=ESQUEMA_BRIEF,
                )
            except LLMError as exc:
                return self._degradar(lote, tema, anterior, seguinte, resultado, str(exc))
            conteudo = resposta.content
            resultado.provedores_usados[f"{resposta.provider}/{resposta.model}"] = (
                resultado.provedores_usados.get(f"{resposta.provider}/{resposta.model}", 0) + 1
            )
            self.cache.gravar(
                chave, conteudo, {"provider": resposta.provider, "model": resposta.model}
            )

        briefs, avisos = self.interpretar(conteudo, lote)
        resultado.avisos.extend(avisos)

        faltando = [b for b in lote if b.number not in {x.block_number for x in briefs}]
        if faltando and len(lote) > 1:
            # Lote grande demais para o modelo: tenta de novo só com o que faltou.
            resultado.avisos.append(
                f"lote de {len(lote)} devolveu {len(briefs)} briefs; "
                f"reprocessando {len(faltando)} bloco(s) isoladamente"
            )
            for bloco in faltando:
                briefs.extend(
                    self._processar_lote([bloco], tema, anterior, seguinte, resultado)
                )

        return briefs

    def _degradar(
        self,
        lote: list[Block],
        tema: str,
        anterior: Block | None,
        seguinte: Block | None,
        resultado: ResultadoBriefing,
        erro: str,
    ) -> list[VisualBrief]:
        """Toda a corrente falhou para este lote. Divide ou cai para emergência."""
        if len(lote) == 1:
            resultado.avisos.append(f"bloco {lote[0].number}: corrente de LLM falhou ({erro})")
            resultado.emergencia += 1
            return [self.brief_emergencia(lote[0])]

        meio = len(lote) // 2
        resultado.avisos.append(
            f"corrente falhou em lote de {len(lote)} blocos, dividindo ao meio ({erro})"
        )
        return [
            *self._processar_lote(lote[:meio], tema, anterior, seguinte, resultado),
            *self._processar_lote(lote[meio:], tema, anterior, seguinte, resultado),
        ]

    # ------------------------------------------------ validação e reparo

    def interpretar(
        self, conteudo: str, lote: list[Block]
    ) -> tuple[list[VisualBrief], list[str]]:
        """Converte a resposta crua em briefs válidos, reparando o que der."""
        avisos: list[str] = []
        dados = _carregar_json(conteudo)
        if dados is None:
            return [], [f"resposta não é JSON válido: {conteudo[:120]!r}"]

        itens = _extrair_lista(dados)
        if not itens:
            return [], ["resposta sem lista de briefs"]

        validos = {b.number for b in lote}
        por_ordem = list(lote)
        briefs: list[VisualBrief] = []

        for i, item in enumerate(itens):
            if not isinstance(item, dict):
                avisos.append(f"item {i} não é objeto, ignorado")
                continue

            numero = item.get("block_number")
            if not isinstance(numero, int) or numero not in validos:
                if i < len(por_ordem):
                    correto = por_ordem[i].number
                    avisos.append(
                        f"block_number inválido ({numero!r}) no item {i}: "
                        f"assumindo {correto} pela ordem"
                    )
                    numero = correto
                else:
                    avisos.append(f"item {i} com block_number inválido ({numero!r}), ignorado")
                    continue

            bloco = next((b for b in lote if b.number == numero), None)
            if bloco is None:
                continue
            briefs.append(self._montar_brief(item, bloco, avisos))

        # Remove duplicatas mantendo o primeiro
        unicos: dict[int, VisualBrief] = {}
        for brief in briefs:
            unicos.setdefault(brief.block_number, brief)
        return list(unicos.values()), avisos

    def _montar_brief(self, item: dict, bloco: Block, avisos: list[str]) -> VisualBrief:
        b = self.channel.briefing
        queries_raw = item.get("queries")
        if isinstance(queries_raw, list):
            queries = BriefQueries(primary=_lista_texto(queries_raw))
        elif isinstance(queries_raw, dict):
            queries = BriefQueries(
                primary=_lista_texto(queries_raw.get("primary")),
                secondary=_lista_texto(queries_raw.get("secondary")),
                archival=_lista_texto(queries_raw.get("archival")),
            )
        else:
            queries = BriefQueries()

        if not queries.primary:
            chaves = palavras_chave(bloco.text)
            queries.primary = [" ".join(chaves[:4])] if chaves else []
            avisos.append(f"bloco {bloco.number}: sem query primária, extraída do texto")

        slug = str(item.get("slug") or "").strip()
        if not slug:
            slug = bloco.text
            avisos.append(f"bloco {bloco.number}: sem slug, derivado do texto")

        return VisualBrief(
            block_number=bloco.number,
            text=bloco.text,
            intent=_enum(Intent, item.get("intent"), b.intent_padrao),
            media_preference=_media(item.get("media_preference"), b.media_padrao),
            era=_texto_ou_nulo(item.get("era")),
            entities=_lista_texto(item.get("entities")),
            queries=queries,
            tone=_texto_ou_nulo(item.get("tone")),
            motion=_enum(Motion, item.get("motion"), Motion.ANY),
            look=_enum(Look, item.get("look"), self.channel.estetica.look_padrao),
            sensitivity=_enum(Sensitivity, item.get("sensitivity"), Sensitivity.NONE),
            slug=slugify(slug),
        )

    def brief_emergencia(self, bloco: Block) -> VisualBrief:
        """Brief mínimo montado sem LLM, para o bloco nunca ficar órfão."""
        b = self.channel.briefing
        chaves = palavras_chave(bloco.text)
        return VisualBrief(
            block_number=bloco.number,
            text=bloco.text,
            intent=b.intent_padrao,
            media_preference=list(b.media_padrao),
            era=None,
            entities=[],
            queries=BriefQueries(primary=[" ".join(chaves[:4])] if chaves else []),
            tone=None,
            motion=Motion.ANY,
            look=self.channel.estetica.look_padrao,
            sensitivity=Sensitivity.NONE,
            slug=slugify(bloco.text),
        )


# ---------------------------------------------------------------------------
# Auxiliares de coerção
# ---------------------------------------------------------------------------


def _carregar_json(conteudo: str) -> Any | None:
    texto = conteudo.strip()
    if texto.startswith("```"):
        # Alguns modelos embrulham em bloco de código apesar do response_format
        texto = texto.strip("`")
        if texto.lower().startswith("json"):
            texto = texto[4:]
        texto = texto.strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        inicio = min(
            (i for i in (texto.find("{"), texto.find("[")) if i >= 0), default=-1
        )
        fim = max(texto.rfind("}"), texto.rfind("]"))
        if inicio >= 0 and fim > inicio:
            try:
                return json.loads(texto[inicio : fim + 1])
            except json.JSONDecodeError:
                return None
        return None


def _extrair_lista(dados: Any) -> list:
    if isinstance(dados, list):
        return dados
    if isinstance(dados, dict):
        for chave in ("briefs", "blocks", "blocos", "result", "data", "items"):
            valor = dados.get(chave)
            if isinstance(valor, list):
                return valor
        if "block_number" in dados:
            return [dados]
    return []


def _enum(cls, valor: Any, padrao):
    if isinstance(valor, str):
        try:
            return cls(valor.strip().lower())
        except ValueError:
            return padrao
    return padrao


def _media(valor: Any, padrao: list[MediaType]) -> list[MediaType]:
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, list):
        return list(padrao)
    saida: list[MediaType] = []
    for item in valor:
        if not isinstance(item, str):
            continue
        try:
            tipo = MediaType(item.strip().lower())
        except ValueError:
            continue
        if tipo not in saida:
            saida.append(tipo)
    return saida or list(padrao)


def _lista_texto(valor: Any) -> list[str]:
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, list):
        return []
    saida: list[str] = []
    for item in valor:
        if isinstance(item, str) and item.strip():
            limpo = item.strip()
            if limpo not in saida:
                saida.append(limpo)
    return saida


def _texto_ou_nulo(valor: Any) -> str | None:
    if isinstance(valor, str):
        limpo = valor.strip()
        if limpo and limpo.lower() not in {"null", "none", "n/a", "-"}:
            return limpo
    return None
