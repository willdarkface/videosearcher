"""Cache em disco para respostas de LLM.

Briefing é caro em tempo e em cota, e é reprocessado muito durante o ajuste do
prompt. A chave inclui o prompt e o modelo, então mudar o prompt invalida o
cache naturalmente — sem risco de continuar servindo resposta velha.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path(".cache/llm")


class RespostaCache:
    def __init__(self, directory: Path | None = None, *, ativo: bool = True) -> None:
        self.directory = directory or DEFAULT_DIR
        self.ativo = ativo
        self.acertos = 0
        self.faltas = 0

    @staticmethod
    def chave(*partes: str) -> str:
        h = hashlib.sha256()
        for parte in partes:
            h.update(parte.encode("utf-8"))
            h.update(b"\x00")
        return h.hexdigest()[:32]

    def _caminho(self, chave: str) -> Path:
        return self.directory / f"{chave}.json"

    def obter(self, chave: str) -> Any | None:
        if not self.ativo:
            return None
        caminho = self._caminho(chave)
        if not caminho.exists():
            self.faltas += 1
            return None
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self.faltas += 1
            return None
        self.acertos += 1
        return dados.get("payload")

    def gravar(self, chave: str, payload: Any, meta: dict[str, Any] | None = None) -> None:
        if not self.ativo:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._caminho(chave).write_text(
                json.dumps({"meta": meta or {}, "payload": payload}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass  # cache é best-effort: nunca deve derrubar o pipeline

    @property
    def resumo(self) -> str:
        total = self.acertos + self.faltas
        if not self.ativo:
            return "cache desligado"
        if total == 0:
            return "cache não consultado"
        return f"{self.acertos}/{total} do cache ({self.acertos / total:.0%})"
