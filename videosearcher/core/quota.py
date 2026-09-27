"""Controle de cota e rate limit por provedor.

Usado tanto pelos provedores de mídia quanto pela corrente de LLM: quando um
provedor estoura o limite, o pipeline degrada para o próximo em vez de falhar.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_STATE = Path(".cache/quota.json")


@dataclass
class Window:
    """Janela deslizante simples de timestamps de requisição."""

    seconds: float
    limit: int
    hits: list[float] = field(default_factory=list)

    def _prune(self, now: float) -> None:
        cutoff = now - self.seconds
        self.hits = [t for t in self.hits if t >= cutoff]

    def allow(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        self._prune(now)
        return len(self.hits) < self.limit

    def record(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self._prune(now)
        self.hits.append(now)

    def retry_after(self, now: float | None = None) -> float:
        now = now if now is not None else time.time()
        self._prune(now)
        if len(self.hits) < self.limit:
            return 0.0
        return max(0.0, (self.hits[0] + self.seconds) - now)


class QuotaTracker:
    """Rastreia requisições por provedor, com persistência em disco.

    A persistência importa porque o limite do Pexels é por hora e o do Pixabay
    é por minuto: reiniciar o processo não deveria zerar a contagem.
    """

    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = state_path or DEFAULT_STATE
        self._windows: dict[str, list[Window]] = {}
        self._load()

    # ---- configuração ----

    def configure(
        self,
        provider: str,
        *,
        per_hour: int | None = None,
        per_minute: int | None = None,
        per_day: int | None = None,
    ) -> None:
        windows: list[Window] = []
        existing = {w.seconds: w.hits for w in self._windows.get(provider, [])}
        if per_minute:
            windows.append(Window(60.0, per_minute, list(existing.get(60.0, []))))
        if per_hour:
            windows.append(Window(3600.0, per_hour, list(existing.get(3600.0, []))))
        if per_day:
            windows.append(Window(86400.0, per_day, list(existing.get(86400.0, []))))
        self._windows[provider] = windows

    # ---- uso ----

    def allow(self, provider: str) -> bool:
        return all(w.allow() for w in self._windows.get(provider, []))

    def record(self, provider: str) -> None:
        for w in self._windows.get(provider, []):
            w.record()
        self._save()

    def retry_after(self, provider: str) -> float:
        windows = self._windows.get(provider, [])
        return max((w.retry_after() for w in windows), default=0.0)

    def snapshot(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for provider, windows in self._windows.items():
            out[provider] = {
                f"last_{int(w.seconds)}s": len([t for t in w.hits if t >= time.time() - w.seconds])
                for w in windows
            }
        return out

    # ---- persistência ----

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for provider, windows in data.items():
            self._windows[provider] = [
                Window(float(w["seconds"]), int(w["limit"]), [float(t) for t in w.get("hits", [])])
                for w in windows
            ]

    def _save(self) -> None:
        payload = {
            provider: [
                {"seconds": w.seconds, "limit": w.limit, "hits": w.hits} for w in windows
            ]
            for provider, windows in self._windows.items()
        }
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass  # cota é best-effort: nunca deve derrubar o pipeline
