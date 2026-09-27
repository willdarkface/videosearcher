"""Classificação de imagem por modelo de visão.

O que sai daqui é o que torna o acervo buscável em linguagem humana: uma frase
descritiva e um conjunto de palavras-chave, gravados por clipe.

Provedor é configurável porque a disponibilidade muda: modelo de visão entra e
sai de tier gratuito com frequência. O padrão é `mistral/pixtral-12b-latest`,
que foi verificado funcionando com chave de tier gratuito — ao contrário de
vários modelos de texto da mesma conta, que devolvem 429.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

log = logging.getLogger("vsworker.vlm")


@dataclass(frozen=True)
class ProvedorVLM:
    nome: str
    base_url: str
    api_key_env: str
    modelo_padrao: str


PROVEDORES: dict[str, ProvedorVLM] = {
    # Verificado funcionando em conta de tier gratuito.
    "mistral": ProvedorVLM(
        "mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "pixtral-12b-latest"
    ),
    # GLM-4.6V-Flash é gratuito na Z.ai.
    "zai": ProvedorVLM(
        "zai", "https://api.z.ai/api/paas/v4", "ZAI_API_KEY", "glm-4.6v-flash"
    ),
    "groq": ProvedorVLM(
        "groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY",
        "meta-llama/llama-4-scout-17b-16e-instruct",
    ),
    "openrouter": ProvedorVLM(
        "openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
        "qwen/qwen2.5-vl-72b-instruct",
    ),
}


class VLMError(RuntimeError):
    pass


@dataclass
class Classificacao:
    caption: str
    palavras: list[str] = field(default_factory=list)
    modelo: str = ""
    sensibilidade: str = "none"

    @property
    def texto_busca(self) -> str:
        return " ".join([self.caption, *self.palavras]).strip()


SYSTEM = """Você indexa acervo de vídeo para um catálogo de busca. Recebe um \
quadro extraído de um clipe e descreve O QUE SE VÊ, para que alguém consiga \
encontrar este clipe depois buscando por palavras.

Devolva JSON com exatamente estes campos:

{"caption": "...", "keywords": ["...", "..."], "sensitivity": "none"}

Regras:
- `caption`: UMA frase em inglês, no máximo 20 palavras, descrevendo o conteúdo \
visível. Descreva o que a imagem mostra, não o que ela significa. \
Bom: "soldiers in winter coats walking through snow beside a military truck". \
Ruim: "an image depicting the hardship of war".
- `keywords`: 6 a 12 termos em inglês, cada um com 1 ou 2 palavras. Inclua \
sujeito, ação, ambiente, época aparente e enquadramento. Termos que alguém \
digitaria numa busca. Não repita palavras da caption sem necessidade.
- `sensitivity`: "graphic" se há corpo, ferimento ou morte explícita; \
"sensitive" se há violência ou sofrimento sem ser explícito; "none" no resto.
- Se o quadro estiver vazio, preto, borrado ou for uma cartela de transição, \
devolva caption "blank or transition frame" e keywords [].

Responda só o JSON, sem texto em volta."""


def _resolver(provedor: str | None, modelo: str | None) -> tuple[ProvedorVLM, str, str]:
    """Escolhe provedor e modelo, e devolve a chave. Se o provedor pedido não
    tem chave, cai para o primeiro que tiver — melhor classificar com o segundo
    melhor modelo do que não classificar."""
    ordem = [provedor] if provedor else []
    ordem += [n for n in ("mistral", "zai", "groq", "openrouter") if n != provedor]

    for nome in ordem:
        spec = PROVEDORES.get(nome or "")
        if spec is None:
            continue
        chave = os.getenv(spec.api_key_env, "").strip()
        if chave:
            return spec, (modelo or spec.modelo_padrao), chave

    disponiveis = ", ".join(p.api_key_env for p in PROVEDORES.values())
    raise VLMError(f"nenhuma chave de VLM configurada. Defina uma de: {disponiveis}")


def classificar(
    keyframe: Path,
    *,
    provedor: str | None = None,
    modelo: str | None = None,
    timeout: float = 120.0,
) -> Classificacao:
    """Descreve o keyframe e extrai palavras-chave."""
    spec, modelo_final, chave = _resolver(provedor, modelo)
    imagem = base64.b64encode(keyframe.read_bytes()).decode()

    payload = {
        "model": modelo_final,
        "max_tokens": 400,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Index this frame."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{imagem}"},
                    },
                ],
            },
        ],
    }

    try:
        resposta = httpx.post(
            f"{spec.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {chave}"},
            json=payload,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise VLMError(f"{spec.nome}: erro de rede ({exc})") from exc

    if resposta.status_code != 200:
        raise VLMError(
            f"{spec.nome}/{modelo_final}: HTTP {resposta.status_code} "
            f"{resposta.text[:200]}"
        )

    try:
        bruto = resposta.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise VLMError(f"{spec.nome}: resposta em formato inesperado") from exc

    return _interpretar(bruto, f"{spec.nome}/{modelo_final}")


def _interpretar(bruto: str, modelo: str) -> Classificacao:
    """Extrai o JSON mesmo quando o modelo embrulha em bloco de código ou
    acrescenta texto em volta — acontece bastante com modelo de visão."""
    dados = _json_de(bruto)
    if dados is None:
        # Último recurso: usar a resposta crua como caption é melhor que perder
        # a classificação inteira por um problema de formatação.
        limpo = " ".join(bruto.split())[:300]
        log.warning("resposta do VLM não era JSON, usando como caption: %r", limpo[:80])
        return Classificacao(caption=limpo, modelo=modelo)

    caption = str(dados.get("caption") or "").strip()
    palavras = []
    for termo in dados.get("keywords") or []:
        if isinstance(termo, str) and (t := termo.strip().lower()) and t not in palavras:
            palavras.append(t)

    sensibilidade = str(dados.get("sensitivity") or "none").strip().lower()
    if sensibilidade not in {"none", "sensitive", "graphic"}:
        sensibilidade = "none"

    return Classificacao(
        caption=caption,
        palavras=palavras[:15],
        modelo=modelo,
        sensibilidade=sensibilidade,
    )


def _json_de(texto: str) -> dict | None:
    limpo = texto.strip()
    if limpo.startswith("```"):
        limpo = re.sub(r"^```[a-zA-Z]*\s*", "", limpo)
        limpo = re.sub(r"\s*```$", "", limpo)
    try:
        dados = json.loads(limpo)
    except json.JSONDecodeError:
        inicio, fim = limpo.find("{"), limpo.rfind("}")
        if inicio < 0 or fim <= inicio:
            return None
        try:
            dados = json.loads(limpo[inicio : fim + 1])
        except json.JSONDecodeError:
            return None
    return dados if isinstance(dados, dict) else None


def quadro_inutil(classificacao: Classificacao) -> bool:
    """Reconhece o quadro que o próprio modelo declarou vazio.

    Complementa a checagem de dHash da ingestão: o hash pega tela chapada, e o
    modelo pega quadro borrado, desfocado ou de transição, que tem variação de
    pixel mas nenhum conteúdo aproveitável.
    """
    texto = classificacao.caption.lower()
    marcas = ("blank or transition", "blank frame", "black frame", "solid color",
              "no discernible", "nothing visible", "blurry transition")
    return not texto or any(m in texto for m in marcas)
