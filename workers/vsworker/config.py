"""Configuração dos workers, lida do ambiente."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(chave: str, padrao: str = "") -> str:
    return os.getenv(chave, padrao).strip()


def _int(chave: str, padrao: int) -> int:
    try:
        return int(_env(chave) or padrao)
    except ValueError:
        return padrao


def _float(chave: str, padrao: float) -> float:
    try:
        return float(_env(chave) or padrao)
    except ValueError:
        return padrao


@dataclass(frozen=True)
class Config:
    dsn: str
    nats_url: str
    acervo_dir: Path
    duracao_corte_s: float
    duracao_minima_s: float
    altura_alvo: int
    fps_alvo: int
    limiar_cena: float
    max_clipes_por_fonte: int
    modelo_vlm: str
    modelo_embedding: str
    zai_api_key: str

    @classmethod
    def do_ambiente(cls) -> Config:
        dsn = _env("DATABASE_URL") or (
            f"postgresql://{_env('POSTGRES_USER', 'vs')}:"
            f"{_env('POSTGRES_PASSWORD', 'vs')}@"
            f"{_env('POSTGRES_HOST', 'localhost')}:"
            f"{_env('POSTGRES_PORT', '5432')}/"
            f"{_env('POSTGRES_DB', 'videosearcher')}"
        )
        return cls(
            dsn=dsn,
            nats_url=_env("NATS_URL", "nats://localhost:4222"),
            acervo_dir=Path(_env("ACERVO_DIR", "./acervo")),
            duracao_corte_s=_float("DURACAO_CORTE_S", 6.0),
            duracao_minima_s=_float("DURACAO_MINIMA_S", 3.0),
            altura_alvo=_int("ALTURA_ALVO", 1080),
            fps_alvo=_int("FPS_ALVO", 30),
            limiar_cena=_float("LIMIAR_CENA", 0.30),
            # Teto por fonte: um filme de 2 horas renderia 1200 clipes e
            # entupiria a fila de classificação com material de um só assunto.
            max_clipes_por_fonte=_int("MAX_CLIPES_POR_FONTE", 400),
            # Vazio = deixa o vlm.py escolher pelo provedor com chave presente.
            modelo_vlm=_env("MODELO_VLM"),
            # 768 dimensões, casa com a coluna vector(768) do schema.
            modelo_embedding=_env("MODELO_EMBEDDING", "jinaai/jina-clip-v1"),
            zai_api_key=_env("ZAI_API_KEY"),
        )
