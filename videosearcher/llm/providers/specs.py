"""Catálogo de provedores de LLM.

Adicionar um provedor novo = adicionar uma entrada aqui. Todos falam a API
`/chat/completions` compatível com OpenAI, então nenhum código novo é preciso.

Os campos `signup_url` e `free_tier` são usados pelo comando
`videosearcher llm check` para te dizer exatamente onde cadastrar o que falta.
"""

from __future__ import annotations

from ..base import ProviderSpec

# Cabeçalhos opcionais: {header: NOME_DA_VARIAVEL_DE_AMBIENTE}
_OPENROUTER_HEADERS = {
    "HTTP-Referer": "OPENROUTER_APP_URL",
    "X-Title": "OPENROUTER_APP_TITLE",
}

_FREE_MISTRAL = (
    "Tier Experiment gratuito com cota alta. ATENÇÃO: a família mistral-small / "
    "medium / large devolve 429 em conta gratuita (limite efetivo zero). Os que "
    "funcionam de fato são ministral-14b-2512, ministral-8b-2512, "
    "ministral-3b-2512 e open-mistral-nemo. Confira seus limites por modelo em "
    "https://admin.mistral.ai/plateforme/limits"
)
_FREE_ZAI = (
    "GLM-4.7-Flash e GLM-4.5-Flash são gratuitos na API (não é trial). "
    "GLM-4.6V-Flash é um modelo de VISÃO também gratuito, útil para legendar keyframes."
)
_FREE_GROQ = (
    "Free tier sem cartão de crédito, ~30 req/min, com teto diário por modelo "
    "(na ordem de 200k tokens/dia no GPT-OSS). Extremamente rápido — ideal para iterar prompt."
)
_FREE_NVIDIA = (
    "100+ modelos hospedados (Llama, Qwen, DeepSeek, Nemotron, GLM) com cota de "
    "avaliação gratuita, sem cartão de crédito."
)
_FREE_CEREBRAS = (
    "Free tier com inferência muito rápida em modelos abertos. "
    "Os limites publicados variam — confirme no painel."
)
_FREE_OPENROUTER = (
    "Modelos com sufixo ':free' custam zero: 20 req/min e 50 req/dia, subindo para "
    "1.000 req/dia depois de uma compra única de US$10 em créditos. "
    "Modelos pagos acessíveis pela mesma chave."
)
_FREE_OPENAI = (
    "Sem tier gratuito permanente. Melhor suporte a JSON Schema estrito do mercado."
)
_FREE_ANTHROPIC = (
    "Sem tier gratuito. Use via OpenRouter se quiser testar sem abrir conta."
)


SPECS: dict[str, ProviderSpec] = {
    # ---------------------------------------------------------------- grátis
    "mistral": ProviderSpec(
        name="mistral",
        base_url="https://api.mistral.ai/v1",
        api_key_env="MISTRAL_API_KEY",
        # Escolhido empiricamente: melhor qualidade de briefing entre os modelos
        # efetivamente disponíveis no tier gratuito.
        default_model="ministral-14b-2512",
        signup_url="https://console.mistral.ai",
        docs_url="https://docs.mistral.ai/",
        free_tier=_FREE_MISTRAL,
    ),
    "zai": ProviderSpec(
        name="zai",
        base_url="https://api.z.ai/api/paas/v4",
        api_key_env="ZAI_API_KEY",
        default_model="glm-4.7-flash",
        signup_url="https://z.ai",
        docs_url="https://docs.z.ai/guides/overview/pricing",
        free_tier=_FREE_ZAI,
    ),
    "groq": ProviderSpec(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        default_model="openai/gpt-oss-20b",
        signup_url="https://console.groq.com/keys",
        docs_url="https://console.groq.com/docs/rate-limits",
        free_tier=_FREE_GROQ,
    ),
    "nvidia": ProviderSpec(
        name="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key_env="NVIDIA_API_KEY",
        default_model="meta/llama-3.3-70b-instruct",
        signup_url="https://build.nvidia.com",
        docs_url="https://docs.api.nvidia.com/nim/reference/llm-apis",
        free_tier=_FREE_NVIDIA,
        supports_json_schema=False,
    ),
    "cerebras": ProviderSpec(
        name="cerebras",
        base_url="https://api.cerebras.ai/v1",
        api_key_env="CEREBRAS_API_KEY",
        default_model="gpt-oss-120b",
        signup_url="https://cloud.cerebras.ai",
        docs_url="https://inference-docs.cerebras.ai/support/rate-limits",
        free_tier=_FREE_CEREBRAS,
        supports_json_schema=False,
    ),
    # ------------------------------------------------- roteador (grátis+pago)
    "openrouter": ProviderSpec(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        default_model="z-ai/glm-4.5-air:free",
        signup_url="https://openrouter.ai/settings/keys",
        docs_url="https://openrouter.ai/docs/features/structured-outputs",
        free_tier=_FREE_OPENROUTER,
        extra_headers=_OPENROUTER_HEADERS,
    ),
    # ------------------------------------------------------------------ pago
    "openai": ProviderSpec(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-5.4-nano",
        signup_url="https://platform.openai.com/api-keys",
        docs_url="https://developers.openai.com/api/docs/pricing",
        free_tier=_FREE_OPENAI,
    ),
    "anthropic": ProviderSpec(
        name="anthropic",
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        default_model="claude-haiku-4-5",
        signup_url="https://console.anthropic.com/settings/keys",
        docs_url="https://docs.anthropic.com/",
        free_tier=_FREE_ANTHROPIC,
        supports_json_schema=False,
    ),
}


def get_spec(name: str) -> ProviderSpec:
    key = name.strip().lower()
    if key not in SPECS:
        raise KeyError(
            f"provedor de LLM desconhecido: '{name}'. Disponíveis: {', '.join(sorted(SPECS))}"
        )
    return SPECS[key]


def list_specs() -> list[ProviderSpec]:
    return [SPECS[k] for k in sorted(SPECS)]
