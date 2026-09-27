"""Contrato dos clientes de LLM.

Todos os provedores suportados expõem API compatível com OpenAI, então um único
cliente genérico resolve todos. Adicionar um provedor novo é adicionar uma
entrada em `SPECS` (arquivo `videosearcher/llm/providers/specs.py`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class LLMError(RuntimeError):
    """Erro genérico de LLM."""


class LLMMissingKey(LLMError):
    """A variável de ambiente da chave não está preenchida."""


class LLMRateLimited(LLMError):
    """429 — limite de taxa. A corrente deve pular para o próximo elo."""


class LLMQuotaExhausted(LLMError):
    """402/403 — cota ou crédito esgotado. A corrente deve pular."""


class LLMServerError(LLMError):
    """5xx ou timeout — o provedor está com problema. A corrente deve pular."""


@dataclass(frozen=True)
class ProviderSpec:
    """Tudo que se precisa saber para falar com um provedor de LLM."""

    name: str
    base_url: str
    api_key_env: str
    default_model: str
    signup_url: str
    docs_url: str
    free_tier: str = ""
    supports_json_schema: bool = True
    extra_headers: dict[str, str] | None = None


class LLMClient(Protocol):
    """Interface mínima que a camada de briefing consome."""

    spec: ProviderSpec

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_output_tokens: int = 8000,
        timeout_s: float = 120.0,
    ) -> str:
        ...


class OpenAICompatClient:
    """Cliente para qualquer endpoint `/chat/completions` compatível com OpenAI.

    Cobre Mistral, Z.ai, Groq, OpenRouter, NVIDIA NIM, Cerebras e OpenAI com o
    mesmo código. A diferença entre eles é só a `ProviderSpec`.
    """

    def __init__(self, spec: ProviderSpec, api_key_env: str | None = None) -> None:
        self.spec = spec
        self._api_key_env = api_key_env or spec.api_key_env

    # ---- chave ----

    @property
    def api_key_env(self) -> str:
        return self._api_key_env

    def api_key(self) -> str:
        key = os.getenv(self._api_key_env, "").strip()
        if not key:
            raise LLMMissingKey(
                f"variável {self._api_key_env} vazia — cadastre em {self.spec.signup_url}"
            )
        return key

    def has_key(self) -> bool:
        return bool(os.getenv(self._api_key_env, "").strip())

    # ---- requisição ----

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key()}",
            "Content-Type": "application/json",
        }
        if self.spec.extra_headers:
            for key, env_name in self.spec.extra_headers.items():
                value = os.getenv(env_name, "").strip()
                if value:
                    headers[key] = value
        return headers

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_output_tokens: int = 8000,
        timeout_s: float = 120.0,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.spec.default_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_output_tokens,
        }

        if json_schema is not None:
            if self.spec.supports_json_schema:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "visual_briefs",
                        "strict": True,
                        "schema": json_schema,
                    },
                }
            else:
                payload["response_format"] = {"type": "json_object"}

        url = self.spec.base_url.rstrip("/") + "/chat/completions"
        try:
            response = httpx.post(
                url, json=payload, headers=self._headers(), timeout=timeout_s
            )
        except httpx.TimeoutException as exc:
            raise LLMServerError(f"{self.spec.name}: timeout após {timeout_s}s") from exc
        except httpx.HTTPError as exc:
            raise LLMServerError(f"{self.spec.name}: erro de rede ({exc})") from exc

        self._raise_for_status(response)

        try:
            data = response.json()
            return data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(
                f"{self.spec.name}: resposta em formato inesperado: {response.text[:300]}"
            ) from exc

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        detail = response.text[:300]
        if response.status_code == 429:
            raise LLMRateLimited(f"{self.spec.name}: 429 rate limit — {detail}")
        if response.status_code in (402, 403):
            raise LLMQuotaExhausted(f"{self.spec.name}: {response.status_code} — {detail}")
        if response.status_code == 401:
            raise LLMMissingKey(
                f"{self.spec.name}: 401 — chave inválida em {self._api_key_env}. {detail}"
            )
        if response.status_code >= 500:
            raise LLMServerError(f"{self.spec.name}: {response.status_code} — {detail}")
        raise LLMError(f"{self.spec.name}: HTTP {response.status_code} — {detail}")
