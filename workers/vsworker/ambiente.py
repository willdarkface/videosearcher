"""Carregamento de `.env` para uso em linha de comando.

Em container as variáveis vêm do compose e nada disso é necessário. Mas rodar o
worker pela CLI é caso de uso de primeira classe — é como se testa e como se
ingere item pontual — e obrigar `export` de seis variáveis a cada vez é atrito
sem motivo.

Procura o `.env` subindo a partir do diretório atual, então funciona rodando de
qualquer subpasta do repositório.
"""

from __future__ import annotations

import os
from pathlib import Path


def carregar_env(nome: str = ".env", niveis: int = 4) -> Path | None:
    """Carrega o primeiro `.env` encontrado subindo a árvore de diretórios.

    Variável já definida no ambiente **vence** o arquivo: em produção o compose
    manda, e um `.env` esquecido no disco não pode sobrescrever isso.
    """
    atual = Path.cwd().resolve()
    for _ in range(niveis + 1):
        caminho = atual / nome
        if caminho.is_file():
            _aplicar(caminho)
            return caminho
        if atual.parent == atual:
            break
        atual = atual.parent
    return None


def _aplicar(caminho: Path) -> None:
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        limpa = linha.strip()
        if not limpa or limpa.startswith("#") or "=" not in limpa:
            continue
        chave, _, valor = limpa.partition("=")
        chave = chave.strip()
        valor = valor.strip().strip("'\"")
        if chave and chave not in os.environ:
            os.environ[chave] = valor
