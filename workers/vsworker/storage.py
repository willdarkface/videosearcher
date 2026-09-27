"""Armazenamento de objetos.

O código nunca fala com caminho absoluto: fala com **chave de objeto**. É isso
que faz o passo 2 (trocar volume por S3 ou R2) ser uma troca de implementação e
não uma migração de dados.

`clipes.objeto` no banco guarda exatamente a chave que aparece aqui.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol


class ObjectStore(Protocol):
    def put(self, chave: str, origem: Path) -> str: ...
    def caminho_local(self, chave: str) -> Path: ...
    def existe(self, chave: str) -> bool: ...
    def remover(self, chave: str) -> None: ...
    def bytes_de(self, chave: str) -> int: ...


class DiscoLocal:
    """Implementação em disco, para o volume compartilhado do compose.

    A chave virou caminho relativo dentro da raiz. Nenhum `..` é aceito, para
    uma chave malformada não conseguir escrever fora do acervo.
    """

    def __init__(self, raiz: Path) -> None:
        self.raiz = Path(raiz)
        self.raiz.mkdir(parents=True, exist_ok=True)

    def _resolver(self, chave: str) -> Path:
        limpa = chave.strip().lstrip("/")
        if not limpa or ".." in Path(limpa).parts:
            raise ValueError(f"chave de objeto inválida: {chave!r}")
        return self.raiz / limpa

    def put(self, chave: str, origem: Path) -> str:
        destino = self._resolver(chave)
        destino.parent.mkdir(parents=True, exist_ok=True)
        if origem.resolve() != destino.resolve():
            shutil.move(str(origem), str(destino))
        return chave

    def caminho_local(self, chave: str) -> Path:
        return self._resolver(chave)

    def existe(self, chave: str) -> bool:
        return self._resolver(chave).exists()

    def remover(self, chave: str) -> None:
        self._resolver(chave).unlink(missing_ok=True)

    def bytes_de(self, chave: str) -> int:
        caminho = self._resolver(chave)
        return caminho.stat().st_size if caminho.exists() else 0


def chave_de_clipe(provider: str, provider_id: str, indice: int, extensao: str) -> str:
    """Chave estável e previsível, particionada por provedor.

    Particionar por provedor mantém o diretório navegável e facilita expirar ou
    migrar um provedor inteiro sem tocar nos outros.
    """
    seguro = "".join(c if c.isalnum() or c in "-_" else "_" for c in provider_id)[:80]
    return f"clipes/{provider}/{seguro}/{indice:04d}{extensao}"


def chave_de_keyframe(chave_clipe: str) -> str:
    return chave_clipe.rsplit(".", 1)[0] + ".jpg"
