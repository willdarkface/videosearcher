"""Carregamento dos packs de canal (`channels/*.yaml`).

Um canal é um arquivo YAML. Criar canal novo = copiar um arquivo. Nenhuma regra
de nicho vive no código.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .models import Intent, Look, MediaType, Sensitivity

DEFAULT_CHANNELS_DIR = Path("channels")


# ---------------------------------------------------------------------------
# Schema do pack de canal
# ---------------------------------------------------------------------------


class LLMLink(BaseModel):
    """Um elo da corrente de fallback de LLM."""

    provider: str
    model: str
    tier: str = "free"
    api_key_env: str | None = None  # sobrescreve o padrão do provedor


class LLMConfig(BaseModel):
    chain: list[LLMLink] = Field(default_factory=list)
    batch_size: int = 20
    cache_prompt: bool = True
    temperature: float = 0.2
    max_output_tokens: int = 8000
    on_rate_limit: str = "next_in_chain"
    on_quota_exhausted: str = "next_in_chain"
    timeout_s: float = 120.0


class ProvedoresConfig(BaseModel):
    prioridade: list[str] = Field(default_factory=list)
    pesos: dict[str, float] = Field(default_factory=dict)

    def peso(self, provider: str) -> float:
        return self.pesos.get(provider, 1.0)


class EsteticaConfig(BaseModel):
    look_padrao: Look = Look.ANY
    aceita_4x3: bool = True
    grao_permitido: bool = True


class BriefingConfig(BaseModel):
    vocabulario: str = ""
    intent_padrao: Intent = Intent.LITERAL
    media_padrao: list[MediaType] = Field(
        default_factory=lambda: [MediaType.VIDEO, MediaType.PHOTO]
    )
    # Idioma do slug, que vira o nome do arquivo entregue. As queries de busca
    # são sempre em inglês, independente disto.
    idioma_slug: str = "pt-BR"


class MidiaConfig(BaseModel):
    """Regras de compatibilidade entre o asset e a duração do bloco.

    O bloco tem duração variável e o sistema se adapta a ela — não o contrário.
    A regra central: vídeo precisa **cobrir** o bloco (durar o mesmo ou mais),
    porque esticar vídeo degrada e repetir em loop aparece. Foto não tem essa
    restrição: com pan/zoom ela cobre qualquer duração, e por isso é o fallback
    universal quando nenhum vídeo é longo o bastante.
    """

    video_deve_cobrir_bloco: bool = True
    tolerancia_cobertura_s: float = 0.0
    fallback_para_imagem: bool = True

    # Folga relativa a partir da qual o vídeo é RECUSADO.
    # 1.3 = aceita até 30% mais longo que o bloco. Cobrir o bloco não basta:
    # um filme de 2 horas cobre qualquer coisa e não serve para nada, porque
    # sem detecção de cena ninguém sabe qual trecho usar.
    # Um bloco de 6,0s aceita de 6,0s até 7,8s.
    # Suba este valor só quando o corte por cena estiver ativo no canal.
    folga_relativa_rejeicao: float = 1.3

    # Folga relativa em que a nota de encaixe chega ao piso. Acompanha o teto
    # de rejeição: com teto de 30%, a nota tem que discriminar dentro dessa
    # faixa estreita, senão todo candidato aprovado empata.
    folga_relativa_maxima: float = 0.3

    # Penalidade quando o bloco pede estética de época (bw_archival, painting,
    # sepia) e o asset é material moderno de banco de b-roll.
    penalidade_look_incompativel: float = 0.55

    # Re-rank semântico: compara a miniatura do candidato com o texto do
    # briefing, no mesmo espaço vetorial. É o que impede entregar céu estrelado
    # para um bloco sobre rifle — caso real, medido.
    usar_rerank_semantico: bool = True
    # Abaixo deste valor o candidato é RECUSADO. Calibrado com medição:
    # relevante ficou entre 0,16 e 0,28, irrelevante entre 0,01 e 0,02.
    similaridade_minima: float = 0.08
    modelo_semantico: str = "jinaai/jina-clip-v1"

    # Alvo de proporção de vídeo na entrega. 0.2 = 20% dos blocos com vídeo e
    # 80% com imagem. É decisão global do vídeo, não de cada bloco: primeiro
    # cada bloco descobre o melhor vídeo E a melhor imagem, depois o orçamento
    # de vídeo é distribuído para os blocos que mais ganham com movimento.
    # `null` desliga o alvo e volta ao comportamento de sempre preferir vídeo.
    proporcao_video: float | None = 0.2

    # Peso de cada `motion` na disputa pelo orçamento de vídeo: bloco de ação
    # aproveita movimento muito mais que bloco de documento.
    peso_motion_video: dict[str, float] = Field(
        default_factory=lambda: {"fast": 1.6, "any": 1.0, "slow": 0.7, "still": 0.35}
    )

    # Foto
    imagem_aspecto: str = "16:9"
    imagem_tolerancia_aspecto: float = 0.12  # desvio relativo aceito sem crop
    permitir_crop_para_aspecto: bool = True

    @property
    def aspecto_alvo(self) -> float:
        try:
            w, h = self.imagem_aspecto.split(":")
            return float(w) / float(h)
        except (ValueError, ZeroDivisionError):
            return 16 / 9


class PoliticaConfig(BaseModel):
    sensitivity_maxima: Sensitivity = Sensitivity.SENSITIVE
    licencas_proibidas: list[str] = Field(default_factory=list)
    exige_sem_atribuicao: bool = False

    # Recusa asset cuja licença não foi comprovada pelo metadado da fonte.
    # Padrão ligado: canal monetizado não pode apostar em "provavelmente é
    # domínio público". Ver videosearcher/core/licenca.py.
    exigir_licenca_verificada: bool = True


class EntregaConfig(BaseModel):
    duracao_bloco: tuple[float, float] = (4.0, 10.0)
    duracao_alvo: float | None = None
    gap_maximo_s: float = 1.5
    resolucao_minima: int = 720
    alternativas_por_bloco: int = 2

    # Divide cues longas em frases antes de agrupar, para que o corte caia na
    # fronteira de ideia e não na fronteira arbitrária da legenda.
    dividir_por_frase: bool = True
    duracao_minima_unidade_s: float = 0.6

    @property
    def min_duracao(self) -> float:
        return float(self.duracao_bloco[0])

    @property
    def max_duracao(self) -> float:
        return float(self.duracao_bloco[1])

    @property
    def alvo(self) -> float:
        if self.duracao_alvo is not None:
            return float(self.duracao_alvo)
        return (self.min_duracao + self.max_duracao) / 2


class ChannelConfig(BaseModel):
    """Pack de canal completo, já com `extends` resolvido."""

    nome: str
    slug: str = ""
    idioma_legenda: str = "pt-BR"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    provedores: ProvedoresConfig = Field(default_factory=ProvedoresConfig)
    estetica: EsteticaConfig = Field(default_factory=EsteticaConfig)
    briefing: BriefingConfig = Field(default_factory=BriefingConfig)
    midia: MidiaConfig = Field(default_factory=MidiaConfig)
    politica: PoliticaConfig = Field(default_factory=PoliticaConfig)
    entrega: EntregaConfig = Field(default_factory=EntregaConfig)


# ---------------------------------------------------------------------------
# Carregamento
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def channels_dir(explicit: Path | None = None) -> Path:
    if explicit:
        return explicit
    env = os.getenv("VIDEOSEARCHER_CHANNELS_DIR")
    if env:
        return Path(env)
    return DEFAULT_CHANNELS_DIR


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"pack de canal não encontrado: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TypeError(f"{path} deveria conter um mapeamento YAML no topo")
    return data


def _resolve(slug: str, directory: Path, seen: set[str] | None = None) -> dict[str, Any]:
    seen = seen or set()
    if slug in seen:
        raise ValueError(f"herança circular de canal envolvendo '{slug}'")
    seen.add(slug)

    raw = _read_yaml(directory / f"{slug}.yaml")
    parent_slug = raw.pop("extends", None)
    if parent_slug:
        parent = _resolve(str(parent_slug), directory, seen)
        raw = _deep_merge(parent, raw)
    return raw


def load_channel(slug: str, directory: Path | None = None) -> ChannelConfig:
    """Carrega um canal por slug, resolvendo `extends` recursivamente."""
    directory = channels_dir(directory)
    data = _resolve(slug, directory)
    data.setdefault("nome", slug)
    data["slug"] = slug
    return ChannelConfig.model_validate(data)


def list_channels(directory: Path | None = None) -> list[str]:
    """Slugs disponíveis, ignorando os que começam com `_` (bases de herança)."""
    directory = channels_dir(directory)
    if not directory.exists():
        return []
    return sorted(
        p.stem for p in directory.glob("*.yaml") if not p.stem.startswith("_")
    )
