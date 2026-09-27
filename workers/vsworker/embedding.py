"""Embedding de imagem e texto no mesmo espaço vetorial.

É a peça que resolve o problema de relevância. Sem ela, o ranqueamento sabe
duração, resolução, licença e aspecto — mas não sabe **do que a imagem é**, e
foi assim que um filme sobre o motim do Bounty virou candidato para um bloco
sobre Waterloo.

Escolha do runtime: `fastembed`, que roda ONNX em CPU. O caminho óbvio seria
transformers + torch, mas só o wheel do torch tem 529 MB, e o worker de
classificação já é o serviço mais pesado do stack. O ONNX entrega o mesmo
embedding em CPU sem arrastar isso.

Escolha do modelo: `jinaai/jina-clip-v1`, 768 dimensões — casa com a coluna
`vector(768)` do schema. Tem encoder de imagem E de texto no mesmo espaço, que
é o requisito: sem isso não existe busca de texto para imagem.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from pathlib import Path

log = logging.getLogger("vsworker.embedding")

MODELO_PADRAO = "jinaai/jina-clip-v1"
DIMENSOES = 768


class EmbeddingError(RuntimeError):
    pass


class Embedder:
    """Carrega os modelos uma vez e reaproveita.

    Carregamento leva segundos e ocupa memória; instanciar por clipe seria o
    erro clássico que faz um worker de 4 minutos virar um de 4 horas.
    """

    def __init__(self, modelo: str = MODELO_PADRAO) -> None:
        self.modelo = modelo
        self._imagem = None
        self._texto = None

    # ---- carregamento tardio: o worker de fila sobe rápido e só paga o
    # custo do modelo quando a primeira mensagem chega ----

    @property
    def imagem(self):
        if self._imagem is None:
            from fastembed import ImageEmbedding

            log.info("carregando encoder de imagem %s", self.modelo)
            self._imagem = ImageEmbedding(model_name=self.modelo)
        return self._imagem

    @property
    def texto(self):
        if self._texto is None:
            from fastembed import TextEmbedding

            log.info("carregando encoder de texto %s", self.modelo)
            self._texto = TextEmbedding(model_name=self.modelo)
        return self._texto

    # ---- uso ----

    def de_imagens(self, caminhos: Sequence[Path]) -> list[list[float]]:
        if not caminhos:
            return []
        vetores = [v.tolist() for v in self.imagem.embed([str(c) for c in caminhos])]
        self._conferir(vetores)
        return vetores

    def de_textos(self, textos: Sequence[str]) -> list[list[float]]:
        limpos = [t.strip() for t in textos if t and t.strip()]
        if not limpos:
            return []
        vetores = [v.tolist() for v in self.texto.embed(limpos)]
        self._conferir(vetores)
        return vetores

    def de_imagem(self, caminho: Path) -> list[float]:
        vetores = self.de_imagens([caminho])
        if not vetores:
            raise EmbeddingError(f"embedding vazio para {caminho}")
        return vetores[0]

    def de_texto(self, texto: str) -> list[float]:
        vetores = self.de_textos([texto])
        if not vetores:
            raise EmbeddingError("embedding vazio para texto vazio")
        return vetores[0]

    def _conferir(self, vetores: Iterable[list[float]]) -> None:
        """A dimensão precisa casar com a coluna do banco. Falhar aqui, com
        mensagem clara, é muito melhor que o Postgres recusar o INSERT depois de
        o worker já ter processado o lote inteiro."""
        for vetor in vetores:
            if len(vetor) != DIMENSOES:
                raise EmbeddingError(
                    f"modelo {self.modelo} devolveu {len(vetor)} dimensões, "
                    f"mas o schema espera {DIMENSOES}. Trocar de modelo exige "
                    f"migração da coluna `embeddings.vetor` — vetor de modelos "
                    f"diferentes não é comparável."
                )
            return  # conferir o primeiro basta: o modelo é consistente


def para_literal_pgvector(vetor: Sequence[float]) -> str:
    """Formata no literal que o pgvector aceita: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{v:.6f}" for v in vetor) + "]"
