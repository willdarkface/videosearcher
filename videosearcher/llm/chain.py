"""Corrente de fallback de LLM.

Tenta os elos na ordem declarada no pack do canal. Chave ausente, 429, cota
esgotada ou erro de servidor fazem o próximo elo assumir. O pipeline só falha
quando todos os elos falharem — e aí diz exatamente o que faltou em cada um.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.config import LLMConfig, LLMLink
from .base import (
    LLMError,
    LLMMissingKey,
    LLMQuotaExhausted,
    LLMRateLimited,
    LLMServerError,
    OpenAICompatClient,
)
from .providers.specs import get_spec

# Erros que significam "tente o próximo elo" em vez de "aborte".
FALLBACK_ERRORS = (LLMMissingKey, LLMRateLimited, LLMQuotaExhausted, LLMServerError)


@dataclass
class LinkAttempt:
    provider: str
    model: str
    tier: str
    ok: bool
    detail: str = ""


@dataclass
class ChainResult:
    content: str
    provider: str
    model: str
    attempts: list[LinkAttempt] = field(default_factory=list)


class LLMChain:
    """Executa uma chamada percorrendo a corrente até alguém responder."""

    def __init__(self, config: LLMConfig) -> None:
        if not config.chain:
            raise ValueError(
                "nenhum elo de LLM configurado — preencha `llm.chain` em channels/_base.yaml"
            )
        self.config = config

    # ---- introspecção ----

    def client_for(self, link: LLMLink) -> OpenAICompatClient:
        spec = get_spec(link.provider)
        return OpenAICompatClient(spec, api_key_env=link.api_key_env)

    def links(self) -> list[LLMLink]:
        return list(self.config.chain)

    # ---- execução ----

    def complete(
        self,
        *,
        system: str,
        user: str,
        json_schema: dict[str, Any] | None = None,
    ) -> ChainResult:
        attempts: list[LinkAttempt] = []

        for link in self.config.chain:
            client = self.client_for(link)
            model = link.model or client.spec.default_model
            try:
                content = client.complete(
                    system=system,
                    user=user,
                    model=model,
                    json_schema=json_schema,
                    temperature=self.config.temperature,
                    max_output_tokens=self.config.max_output_tokens,
                    timeout_s=self.config.timeout_s,
                )
            except FALLBACK_ERRORS as exc:
                attempts.append(
                    LinkAttempt(link.provider, model, link.tier, ok=False, detail=str(exc))
                )
                continue
            except LLMError as exc:
                # Erro não recuperável (payload inválido, modelo inexistente).
                # Ainda assim seguimos: um elo quebrado não deve parar a produção.
                attempts.append(
                    LinkAttempt(link.provider, model, link.tier, ok=False, detail=str(exc))
                )
                continue

            attempts.append(LinkAttempt(link.provider, model, link.tier, ok=True))
            return ChainResult(
                content=content, provider=link.provider, model=model, attempts=attempts
            )

        summary = "\n".join(f"  - {a.provider}/{a.model}: {a.detail}" for a in attempts)
        raise LLMError(
            "todos os elos da corrente de LLM falharam:\n"
            f"{summary}\n"
            "Rode `videosearcher llm check` para ver o que cadastrar."
        )

    # ---- diagnóstico ----

    def check(self) -> list[LinkAttempt]:
        """Testa cada elo com uma chamada mínima e devolve o estado de todos.

        Diferente de `complete`, não para no primeiro sucesso: o objetivo é
        mostrar o retrato completo da configuração.
        """
        results: list[LinkAttempt] = []
        for link in self.config.chain:
            client = self.client_for(link)
            model = link.model or client.spec.default_model

            if not client.has_key():
                results.append(
                    LinkAttempt(
                        link.provider,
                        model,
                        link.tier,
                        ok=False,
                        detail=(
                            f"{client.api_key_env} não preenchida — "
                            f"cadastre em {client.spec.signup_url}"
                        ),
                    )
                )
                continue

            try:
                content = client.complete(
                    system="Responda apenas com a palavra OK.",
                    user="ping",
                    model=model,
                    temperature=0.0,
                    # Folga suficiente para modelo de raciocínio (gpt-oss e
                    # similares) gastar tokens pensando e ainda responder.
                    max_output_tokens=256,
                    timeout_s=30.0,
                )
            except LLMError as exc:
                results.append(
                    LinkAttempt(link.provider, model, link.tier, ok=False, detail=str(exc))
                )
                continue

            texto = content.strip()
            results.append(
                LinkAttempt(
                    link.provider,
                    model,
                    link.tier,
                    ok=True,
                    detail=texto[:40] if texto else "responde, mas devolveu conteúdo vazio",
                )
            )
        return results
